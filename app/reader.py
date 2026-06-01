import os
import zipfile
import shutil
import io
import tempfile
from config import COMICS_DIR, COVERS_DIR, PAGES_DIR, IMAGE_EXTENSIONS, ARCHIVE_EXTENSIONS

THUMBNAIL_SIZE = (300, 420)

SUPPORTED_ARCHIVE_EXTENSIONS = {'cbz', 'zip', 'cb7', '7z', 'cbr', 'rar'}


def _get_setting(key, default=''):
    from app.models import Setting
    return Setting.get(key, default)


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
        return

    dirs = []
    for name in os.listdir(PAGES_DIR):
        path = os.path.join(PAGES_DIR, name)
        if os.path.isdir(path):
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

    if freed > 0:
        from app.utils.file_utils import format_size
        print(f'[缓存] 页面缓存超过上限 {max_cache_mb}MB，已自动清理 {format_size(freed)}')


def get_comic_pages(comic_id, filename):
    if not filename:
        return []

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    comic_path = os.path.join(COMICS_DIR, filename)

    if not os.path.exists(comic_path):
        return []

    _check_and_auto_clean_cache()

    if ext in ('zip', 'cbz'):
        return _extract_zip_pages(comic_id, comic_path)

    if ext in ('7z', 'cb7'):
        return _extract_7z_pages(comic_id, comic_path)

    if ext in ('rar', 'cbr'):
        return _extract_rar_pages(comic_id, comic_path)

    if ext in IMAGE_EXTENSIONS:
        return [filename]

    return []


def _extract_zip_pages(comic_id, comic_path):
    extract_dir = os.path.join(PAGES_DIR, str(comic_id))

    if os.path.exists(extract_dir):
        pages = _get_sorted_images(extract_dir)
        if pages:
            return pages

    os.makedirs(extract_dir, exist_ok=True)

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

            image_files.sort(key=lambda x: x.filename)

            for idx, info in enumerate(image_files):
                original_name = os.path.basename(info.filename)
                _, file_ext = os.path.splitext(original_name)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(extract_dir, safe_name)
                with zf.open(info) as src, open(dest, 'wb') as dst:
                    shutil.copyfileobj(src, dst)

        return _get_sorted_images(extract_dir)
    except (zipfile.BadZipFile, OSError) as e:
        print(f'[阅读] ZIP解压失败 {comic_path}: {e}')
        return []


def _extract_7z_pages(comic_id, comic_path):
    import py7zr

    extract_dir = os.path.join(PAGES_DIR, str(comic_id))

    if os.path.exists(extract_dir):
        pages = _get_sorted_images(extract_dir)
        if pages:
            return pages

    os.makedirs(extract_dir, exist_ok=True)

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

            image_files.sort()

            for idx, src in enumerate(image_files):
                _, file_ext = os.path.splitext(src)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(extract_dir, safe_name)
                shutil.copy2(src, dest)

        return _get_sorted_images(extract_dir)
    except Exception as e:
        print(f'[阅读] 7z解压失败 {comic_path}: {e}')
        import traceback
        traceback.print_exc()
        return []


def _extract_rar_pages(comic_id, comic_path):
    import rarfile

    extract_dir = os.path.join(PAGES_DIR, str(comic_id))

    if os.path.exists(extract_dir):
        pages = _get_sorted_images(extract_dir)
        if pages:
            return pages

    os.makedirs(extract_dir, exist_ok=True)

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

            image_files.sort()

            for idx, src in enumerate(image_files):
                _, file_ext = os.path.splitext(src)
                safe_name = f"{idx + 1:04d}{file_ext}"
                dest = os.path.join(extract_dir, safe_name)
                shutil.copy2(src, dest)

        return _get_sorted_images(extract_dir)
    except Exception as e:
        print(f'[阅读] RAR解压失败 {comic_path}: {e}')
        import traceback
        traceback.print_exc()
        return []


def _get_sorted_images(directory):
    images = []
    for f in os.listdir(directory):
        ext = f.rsplit('.', 1)[-1].lower() if '.' in f else ''
        if ext in IMAGE_EXTENSIONS:
            images.append(f)
    images.sort()
    return images


def get_page_dir(comic_id, page_filename):
    if '..' in page_filename or page_filename.startswith('/') or page_filename.startswith('\\'):
        return None

    page_dir = os.path.join(PAGES_DIR, str(comic_id))
    path = os.path.join(page_dir, page_filename)
    if os.path.exists(path):
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
    extract_dir = os.path.join(PAGES_DIR, str(comic_id))
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir, ignore_errors=True)


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