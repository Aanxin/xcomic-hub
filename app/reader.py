import os
import re
import time
import uuid
import zipfile
import shutil
import io
import tempfile
from config import COMICS_DIR, COVERS_DIR, PAGES_DIR, IMAGE_EXTENSIONS, ARCHIVE_EXTENSIONS

THUMBNAIL_SIZE = (300, 420)

SUPPORTED_ARCHIVE_EXTENSIONS = {'cbz', 'zip', 'cb7', '7z', 'cbr', 'rar'}

# 解压完成标记：随暂存目录一并 rename 进最终目录，存在即代表缓存完整。
# 用于把「解压中途的部分文件」与「完整缓存」区分开，修复轮询/并发读
# 拿到半成品页列表（页数不够）的问题。
READY_MARKER = '.ready'

# 跨进程解压锁的过期时间：超过视为上次进程崩溃的残留锁，允许重新解压。
EXTRACT_LOCK_STALE_SECONDS = 1800


def _natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def _task_id(comic_id):
    return f'extract:{comic_id}'


def _final_dir(comic_id):
    return os.path.join(PAGES_DIR, str(comic_id))


def _lock_path(comic_id):
    return os.path.join(PAGES_DIR, f'{comic_id}.lock')


def _new_staging_dir(comic_id):
    """每任务唯一暂存目录：多 worker 并发解压同一本时互不干扰，先晋升者胜。"""
    return os.path.join(PAGES_DIR, f'{comic_id}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}')


def _try_acquire_extract_lock(comic_id):
    """跨进程解压锁（O_CREAT|O_EXCL 原子创建）。

    gunicorn 多 worker 各持独立 task_manager，进程内任务去重对其他 worker
    不可见；不加锁时同一本漫画会被每个 worker 重复解压一遍。
    锁文件超过 EXTRACT_LOCK_STALE_SECONDS 视为崩溃残留，重置后重新获取。
    """
    path = _lock_path(comic_id)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - os.path.getmtime(path) > EXTRACT_LOCK_STALE_SECONDS:
                os.remove(path)
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return True
        except OSError:
            pass
        return False
    except OSError:
        return False


def _release_extract_lock(comic_id):
    try:
        os.remove(_lock_path(comic_id))
    except OSError:
        pass


def _promote(staging, final):
    """staging → final 原子晋升（.ready 标记随目录带入最终目录）。

    - final 不存在：一步 rename 完成
    - final 已存在且带 .ready：其他 worker 先完成（或旧版完整缓存），丢弃本地 staging
    - final 存在但无标记：旧版残留的半成品目录，替换之
    """
    with open(os.path.join(staging, READY_MARKER), 'w') as f:
        f.write(str(int(time.time())))
    try:
        os.rename(staging, final)
        return
    except OSError:
        pass
    if os.path.exists(os.path.join(final, READY_MARKER)):
        shutil.rmtree(staging, ignore_errors=True)
        return
    tmp_old = f'{final}.old-{uuid.uuid4().hex[:8]}'
    try:
        os.rename(final, tmp_old)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return
    try:
        os.rename(staging, final)
    finally:
        shutil.rmtree(tmp_old, ignore_errors=True)


def _map_status(status):
    """TaskStatus -> 旧版对外 status 字符串(保持 API 兼容)。"""
    from app.services.task_manager import TaskStatus
    return {
        TaskStatus.PENDING: 'extracting',
        TaskStatus.RUNNING: 'extracting',
        TaskStatus.COMPLETED: 'ready',
        TaskStatus.FAILED: 'error',
        TaskStatus.CANCELLED: 'error',
    }.get(status, 'extracting')


def get_extraction_status(comic_id):
    """返回解压状态 dict。无任务时返回 None。

    COMPLETED 但缓存已被清理（LRU 淘汰）视为无任务，让调用方重新触发解压，
    避免返回「ready 但无页面」的矛盾状态。
    """
    from app.services.task_manager import task_manager, TaskStatus
    info = task_manager.get_task(_task_id(comic_id))
    if not info:
        return None
    if info.status == TaskStatus.COMPLETED and not _get_cached_pages(comic_id):
        return None
    result = {
        'status': _map_status(info.status),
        'progress': info.progress,
        'total': info.total,
        'message': info.message or info.error or '',
    }
    if info.status == TaskStatus.COMPLETED:
        pages = _get_cached_pages(comic_id)
        if pages:
            result['pages'] = len(pages)
    return result


def cancel_extraction(comic_id):
    """取消解压任务。返回是否找到了任务。"""
    from app.services.task_manager import task_manager
    return task_manager.cancel(_task_id(comic_id))


def _get_cached_pages(comic_id):
    """完整缓存页列表；无 .ready 标记（解压中/历史半成品）返回 None。"""
    final = _final_dir(comic_id)
    if os.path.exists(os.path.join(final, READY_MARKER)):
        pages = _get_sorted_images(final)
        if pages:
            return pages
    return None


def _get_setting(key, default=''):
    from app.models import Setting
    return Setting.get(key, default)


def _sweep_stale_staging_dirs():
    """清理崩溃残留的暂存目录（{id}.tmp-*）与晋升替换目录（{id}.old-*）。

    年龄阈值与解压锁 TTL 一致：正在解压的暂存目录必然更年轻，不会被误删。
    """
    now = time.time()
    try:
        names = os.listdir(PAGES_DIR)
    except OSError:
        return
    for name in names:
        if '.tmp-' not in name and '.old-' not in name:
            continue
        path = os.path.join(PAGES_DIR, name)
        try:
            if os.path.isdir(path) and now - os.path.getmtime(path) > EXTRACT_LOCK_STALE_SECONDS:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _check_and_auto_clean_cache():
    try:
        max_cache_mb = int(_get_setting('max_cache_size', '0'))
    except (ValueError, TypeError):
        return
    if max_cache_mb <= 0:
        return

    max_cache_bytes = max_cache_mb * 1024 * 1024
    if not os.path.exists(PAGES_DIR):
        return

    from app.utils.file_utils import get_dir_size
    current_size = get_dir_size(PAGES_DIR)
    if current_size <= max_cache_bytes:
        _sweep_stale_staging_dirs()
        return

    dirs = []
    for name in os.listdir(PAGES_DIR):
        path = os.path.join(PAGES_DIR, name)
        if os.path.isdir(path):
            if not name.isdigit():
                # 只把「最终缓存目录」（纯数字名）纳入 LRU 淘汰；
                # 暂存/替换目录由 _sweep_stale_staging_dirs 按年龄清理
                continue
            try:
                mtime = os.path.getmtime(path)
                size = get_dir_size(path)
                dirs.append((mtime, path, size))
            except OSError:
                pass

    dirs.sort(key=lambda x: x[0])

    freed = 0
    target = current_size - max_cache_bytes
    for _mtime, path, size in dirs:
        if freed >= target:
            break
        try:
            shutil.rmtree(path, ignore_errors=True)
            freed += size
        except OSError:
            pass

    _sweep_stale_staging_dirs()

    if freed > 0:
        from app.utils.file_utils import format_size
        print(f'[缓存] 页面缓存超过上限 {max_cache_mb}MB，已自动清理 {format_size(freed)}')


def get_comic_pages(comic_id, filename):
    """同步获取漫画页面。命中完整缓存（.ready 标记）立即返回，否则返回空列表（不阻塞）。

    若需触发异步解压，请使用 `start_extraction_async`。
    """
    if not filename:
        return []

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    comic_path = os.path.join(COMICS_DIR, filename)

    if not os.path.exists(comic_path):
        return []

    if ext in IMAGE_EXTENSIONS:
        return [filename]

    if ext not in SUPPORTED_ARCHIVE_EXTENSIONS:
        return []

    return _get_cached_pages(comic_id) or []


def start_extraction_async(comic_id, filename):
    """启动后台解压。返回当前状态 dict(API 兼容)。

    - 已就绪（缓存命中）：返回 {'status': 'ready', 'pages': [...]}
    - 本进程正在解压：返回 {'status': 'extracting', 'progress': N, 'total': T}
    - 其他进程正在解压（跨进程锁）：返回 {'status': 'extracting', ...}
    - 启动新任务：返回 {'status': 'extracting', 'progress': 0, 'total': 0}
    """
    from app.services.task_manager import task_manager, TaskType, TaskStatus
    if not filename:
        return {'status': 'error', 'message': '文件名为空'}

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    comic_path = os.path.join(COMICS_DIR, filename)

    if not os.path.exists(comic_path):
        return {'status': 'error', 'message': '文件不存在'}

    if ext in IMAGE_EXTENSIONS:
        return {'status': 'ready', 'pages': [filename]}

    if ext not in SUPPORTED_ARCHIVE_EXTENSIONS:
        return {'status': 'error', 'message': '不支持的文件格式'}

    cached = _get_cached_pages(comic_id)
    if cached:
        # 缓存命中直接返回。注意：不再取消任务记录——带 .ready 标记的缓存
        # 与运行中的解压任务不可能同时存在（解压写暂存目录，晋升才落最终目录）。
        return {'status': 'ready', 'pages': cached}

    # 复用进行中的任务,避免重复解压
    existing = task_manager.get_task(_task_id(comic_id))
    if existing and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        return get_extraction_status(comic_id) or {'status': 'extracting', 'progress': 0, 'total': 0}

    # 跨进程锁：gunicorn 多 worker 各持独立 task_manager，进程内去重
    # 看不到其他 worker 的任务；不抢到锁就只回报 extracting，不重复解压。
    if not _try_acquire_extract_lock(comic_id):
        return {'status': 'extracting', 'progress': 0, 'total': 0, 'message': '正在解压…'}

    # 解压是 C 层 CPU 密集工作，gevent 下 greenlet 内不让出会阻塞整个
    # worker 事件循环：委托真实 OS 线程执行。app 必须在提交现场捕获——
    # 池 worker 里上下文已不可见（解压路径查询 Setting 的缓存上限需要）
    from app.utils.threading_utils import run_cpu_bound
    from flask import current_app
    try:
        app_obj = current_app._get_current_object()
    except RuntimeError:
        app_obj = None

    def _run_extraction_threadsafe(comic_id=comic_id, comic_path=comic_path, ext=ext):
        return run_cpu_bound(_run_extraction, comic_id, comic_path, ext, app=app_obj)

    task_manager.submit(
        TaskType.EXTRACTION,
        _task_id(comic_id),
        _run_extraction_threadsafe,
    )
    task_manager.update_progress(_task_id(comic_id), progress=0, total=0, message='准备解压...')
    return get_extraction_status(comic_id) or {'status': 'extracting', 'progress': 0, 'total': 0}


def _run_extraction(comic_id, comic_path, ext):
    """实际解压函数。通过 task_manager 的 progress_callback 协作式取消。

    异常会被 TaskManager._runner 捕获并标记 FAILED/CANCELLED,无需此处兜底。
    暂存目录由各解压函数自行清理（成功晋升 / 失败删除），最终目录只会在
    晋升时被完整替换，取消/失败不再触碰。
    """
    from app.services.task_manager import task_manager, TaskCancelled
    _check_and_auto_clean_cache()
    cb = task_manager.make_progress_callback(_task_id(comic_id))

    try:
        if ext in ('zip', 'cbz'):
            pages = _extract_zip_pages(comic_id, comic_path, progress_callback=cb)
        elif ext in ('7z', 'cb7'):
            pages = _extract_7z_pages(comic_id, comic_path, progress_callback=cb)
        elif ext in ('rar', 'cbr'):
            pages = _extract_rar_pages(comic_id, comic_path, progress_callback=cb)
        else:
            raise ValueError('不支持的文件格式')
    finally:
        # 无论成败都释放跨进程锁；进程崩溃残留由 TTL 兜底
        _release_extract_lock(comic_id)

    if not pages:
        raise RuntimeError('解压失败或压缩包为空')


def _extract_zip_pages(comic_id, comic_path, progress_callback=None):
    final = _final_dir(comic_id)

    # 命中完整缓存（带 .ready 标记）直接复用
    if os.path.exists(os.path.join(final, READY_MARKER)):
        pages = _get_sorted_images(final)
        if pages:
            return pages

    # 先解压到暂存目录，完成后原子晋升：解压中途的部分文件绝不会出现在
    # 最终目录，轮询/并发读不会拿到半成品页列表。
    staging = _new_staging_dir(comic_id)
    os.makedirs(staging, exist_ok=True)

    try:
        with zipfile.ZipFile(comic_path, 'r') as zf:
            image_files = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                file_ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                if file_ext in IMAGE_EXTENSIONS:
                    if name.startswith('__MACOSX') or name.startswith('.'):
                        continue
                    image_files.append(info)

            image_files.sort(key=lambda x: _natural_key(x.filename))
            total = len(image_files)
            if progress_callback and total:
                progress_callback(0, total)

            for idx, info in enumerate(image_files):
                original_name = os.path.basename(info.filename)
                _, file_ext = os.path.splitext(original_name)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(staging, safe_name)
                with zf.open(info) as src, open(dest, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                if progress_callback:
                    progress_callback(idx + 1, total)

        _promote(staging, final)
        pages = _get_sorted_images(final)
        if not pages:
            raise RuntimeError('压缩包内没有可用图片')
        return pages
    except (zipfile.BadZipFile, OSError) as e:
        raise RuntimeError(f'ZIP解压失败 {comic_path}: {e}') from e
    finally:
        # 成功路径 staging 已被 rename 走，此处为 no-op；失败/取消路径清掉残留
        shutil.rmtree(staging, ignore_errors=True)


def _extract_7z_pages(comic_id, comic_path, progress_callback=None):
    import py7zr

    final = _final_dir(comic_id)

    if os.path.exists(os.path.join(final, READY_MARKER)):
        pages = _get_sorted_images(final)
        if pages:
            return pages

    staging = _new_staging_dir(comic_id)
    os.makedirs(staging, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with py7zr.SevenZipFile(comic_path, 'r') as szf:
                szf.extract(path=tmpdir)

            image_files = []
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.startswith('.') or f.startswith('__MACOSX'):
                        continue
                    file_ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
                    if file_ext in IMAGE_EXTENSIONS:
                        image_files.append(os.path.join(root, f))

            image_files.sort(key=_natural_key)
            total = len(image_files)
            if progress_callback and total:
                progress_callback(0, total)

            for idx, src in enumerate(image_files):
                _, file_ext = os.path.splitext(src)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(staging, safe_name)
                shutil.copy2(src, dest)
                if progress_callback:
                    progress_callback(idx + 1, total)

        _promote(staging, final)
        pages = _get_sorted_images(final)
        if not pages:
            raise RuntimeError('压缩包内没有可用图片')
        return pages
    except Exception as e:
        raise RuntimeError(f'7z解压失败 {comic_path}: {e}') from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _extract_rar_pages(comic_id, comic_path, progress_callback=None):
    import rarfile

    final = _final_dir(comic_id)

    if os.path.exists(os.path.join(final, READY_MARKER)):
        pages = _get_sorted_images(final)
        if pages:
            return pages

    staging = _new_staging_dir(comic_id)
    os.makedirs(staging, exist_ok=True)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            with rarfile.RarFile(comic_path, 'r') as rf:
                rf.extractall(path=tmpdir)

            image_files = []
            for root, dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.startswith('.') or f.startswith('__MACOSX'):
                        continue
                    file_ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
                    if file_ext in IMAGE_EXTENSIONS:
                        image_files.append(os.path.join(root, f))

            image_files.sort(key=_natural_key)
            total = len(image_files)
            if progress_callback and total:
                progress_callback(0, total)

            for idx, src in enumerate(image_files):
                _, file_ext = os.path.splitext(src)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(staging, safe_name)
                shutil.copy2(src, dest)
                if progress_callback:
                    progress_callback(idx + 1, total)

        _promote(staging, final)
        pages = _get_sorted_images(final)
        if not pages:
            raise RuntimeError('压缩包内没有可用图片')
        return pages
    except Exception as e:
        raise RuntimeError(f'RAR解压失败 {comic_path}: {e}') from e
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _get_sorted_images(directory):
    images = []
    for f in os.listdir(directory):
        ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
        if ext in IMAGE_EXTENSIONS:
            images.append(f)
    images.sort(key=_natural_key)
    return images


def get_page_dir(comic_id, page_filename):
    if '..' in page_filename or page_filename.startswith('/') or page_filename.startswith('\\'):
        return None

    page_dir = _final_dir(comic_id)
    path = os.path.join(page_dir, page_filename)
    if os.path.exists(path):
        # LRU 标记：服务页面时刷新目录 mtime，缓存自动清理按 mtime 从旧到新
        # 删除 → 正在阅读的漫画缓存最后才可能被淘汰（修复阅读中图片 404）。
        try:
            os.utime(page_dir, None)
        except OSError:
            pass
        return page_dir

    comic_path = os.path.join(COMICS_DIR, page_filename)
    norm_comic = os.path.normpath(comic_path)
    if not norm_comic.startswith(os.path.normpath(COMICS_DIR)):
        return None
    if os.path.exists(norm_comic):
        return os.path.dirname(norm_comic)

    return None


def is_readable(filename):
    if not filename:
        return False
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in SUPPORTED_ARCHIVE_EXTENSIONS or ext in IMAGE_EXTENSIONS


def cleanup_pages(comic_id):
    """清理该漫画全部页面缓存（最终目录 / 暂存目录 / 替换残留 / 解压锁）。"""
    shutil.rmtree(_final_dir(comic_id), ignore_errors=True)
    try:
        for name in os.listdir(PAGES_DIR):
            if name.startswith(f'{comic_id}.tmp-') or name.startswith(f'{comic_id}.old-'):
                shutil.rmtree(os.path.join(PAGES_DIR, name), ignore_errors=True)
    except OSError:
        pass
    try:
        os.remove(_lock_path(comic_id))
    except OSError:
        pass


def _save_cover_thumbnail(img, cover_width):
    try:
        from PIL import Image
    except ImportError:
        return None

    thumbnail_size = (cover_width, int(cover_width * 1.4))

    img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    cover_name = f"{os.urandom(8).hex()}.jpg"
    cover_path = os.path.join(COVERS_DIR, cover_name)
    quality = int(_get_setting('cover_quality', '85'))
    img.save(cover_path, 'JPEG', quality=quality)
    return cover_name


def _find_first_image_in_archive(archive_path, ext_type):
    if ext_type in ('zip', 'cbz'):
        zf = zipfile.ZipFile(archive_path, 'r')
        try:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name.startswith('__MACOSX') or name.startswith('.'):
                    continue
                file_ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                if file_ext in IMAGE_EXTENSIONS:
                    return (name, zf)
        except Exception:
            pass
        zf.close()
        return None

    elif ext_type in ('7z', 'cb7'):
        import py7zr
        szf = py7zr.SevenZipFile(archive_path, 'r')
        try:
            names = szf.getnames()
            for name in names:
                if name.startswith('__MACOSX') or name.startswith('.'):
                    continue
                file_ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                if file_ext in IMAGE_EXTENSIONS:
                    return (name, szf)
        except Exception:
            pass
        szf.close()
        return None

    elif ext_type in ('rar', 'cbr'):
        import rarfile
        rf = rarfile.RarFile(archive_path, 'r')
        try:
            for info in rf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if name.startswith('__MACOSX') or name.startswith('.'):
                    continue
                file_ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                if file_ext in IMAGE_EXTENSIONS:
                    return (name, rf)
        except Exception:
            pass
        rf.close()
        return None

    return None


def generate_cover_from_archive(comic_path, cover_width=300):
    try:
        from PIL import Image
    except ImportError:
        return None

    ext = comic_path.rsplit('.', 1)[-1].lower()
    if ext not in ('cbz', 'zip', 'cb7', '7z', 'cbr', 'rar'):
        return None

    try:
        result = _find_first_image_in_archive(comic_path, ext)
        if result is None:
            return None

        first_name, archive = result

        if ext in ('zip', 'cbz'):
            with archive.open(first_name) as img_file:
                img_data = img_file.read()
                img = Image.open(io.BytesIO(img_data))
                return _save_cover_thumbnail(img, cover_width)

        elif ext in ('7z', 'cb7'):
            with tempfile.TemporaryDirectory() as tmpdir:
                archive.reset()
                archive.extract(path=tmpdir, targets=[first_name])
                extracted_path = os.path.join(tmpdir, first_name)
                if os.path.exists(extracted_path):
                    img = Image.open(extracted_path)
                    return _save_cover_thumbnail(img, cover_width)
            return None

        elif ext in ('rar', 'cbr'):
            with tempfile.TemporaryDirectory() as tmpdir:
                archive.extract(first_name, path=tmpdir)
                extracted_path = os.path.join(tmpdir, first_name)
                if os.path.exists(extracted_path):
                    img = Image.open(extracted_path)
                    return _save_cover_thumbnail(img, cover_width)
            return None

    except Exception as e:
        print(f'[封面] 从压缩包生成封面失败 {comic_path}: {e}')
        import traceback
        traceback.print_exc()
        return None


def generate_cover_from_image(comic_path, cover_width=300):
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(comic_path)
        return _save_cover_thumbnail(img, cover_width)
    except Exception as e:
        print(f'[封面] 从图片生成封面失败 {comic_path}: {e}')
        return None


def regenerate_comic_cover_by_id(comic_id):
    """按 id 重新生成封面，供真实线程执行（run_cpu_bound）。

    ORM 对象绑定 greenlet 本地会话不可跨线程共享，线程内重新加载。
    """
    from app.models import Comic

    comic = Comic.query.get(comic_id)
    if comic is None:
        return None
    return regenerate_comic_cover(comic)


def regenerate_comic_cover(comic):
    from app import db

    if not comic.filename:
        return None

    comic_path = os.path.join(COMICS_DIR, comic.filename)
    if not os.path.exists(comic_path):
        return None

    ext = comic.filename.rsplit('.', 1)[-1].lower() if '.' in comic.filename else ''
    cover_width = int(_get_setting('cover_width', '300'))

    new_cover = None
    if ext in SUPPORTED_ARCHIVE_EXTENSIONS:
        new_cover = generate_cover_from_archive(comic_path, cover_width)
    elif ext in IMAGE_EXTENSIONS:
        new_cover = generate_cover_from_image(comic_path, cover_width)

    if not new_cover:
        return None

    if comic.cover:
        old_cover_path = os.path.join(COVERS_DIR, comic.cover)
        if os.path.exists(old_cover_path):
            os.remove(old_cover_path)
            old_cover_dir = os.path.dirname(old_cover_path)
            if old_cover_dir and old_cover_dir != COVERS_DIR and os.path.isdir(old_cover_dir) and not os.listdir(old_cover_dir):
                os.rmdir(old_cover_dir)

    cover_subdir = os.path.dirname(comic.filename) if comic.filename else ''
    if cover_subdir:
        new_cover_rel = os.path.join(cover_subdir, new_cover).replace('\\', '/')
        old_cover_path = os.path.join(COVERS_DIR, new_cover)
        new_cover_dir = os.path.join(COVERS_DIR, cover_subdir)
        os.makedirs(new_cover_dir, exist_ok=True)
        new_cover_path = os.path.join(new_cover_dir, new_cover)
        if os.path.exists(old_cover_path) and not os.path.exists(new_cover_path):
            shutil.move(old_cover_path, new_cover_path)
        new_cover = new_cover_rel

    comic.cover = new_cover
    db.session.commit()

    return new_cover
