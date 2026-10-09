"""抓取流水线：从漫画源下载整本图片 → 打包 ZIP → 入库。"""

import hashlib
import os
import shutil
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import db
from app.models import Comic, ScrapeTask
from app.services.file_operation_service import FileOperationService
from app.services.nfo_service import NfoService
from app.services.task_manager import task_manager, TaskCancelled, TaskType
from app.sources.base_source import PageImage, QuotaError
from app.sources.image_proxy import fetch_image
from app.sources.source_registry import get_registry
from app.utils.file_utils import safe_filename
from config import COMICS_DIR, DOWNLOAD_DIR

# 单图下载重试次数与退避基数
IMAGE_RETRY = 3
# 超时单独放宽：图片源慢/不稳定，timeout 时给更多次机会
IMAGE_TIMEOUT_RETRY = 5
RETRY_BACKOFF = 0.5
# 单图传输总预算（秒）：读间隙超时拦不住慢速滴流节点，总预算兜底
IMAGE_TRANSFER_BUDGET = 120

# E-Hentai 串行下载间隔（秒），nhentai 并发数
EHENTAI_INTERVAL = 1.0
NHENTAI_CONCURRENCY = 3
# 坏节点换源重载次数（E-Hentai ?nl=，每轮 reload 请求新节点）
IMAGE_RELOAD_RETRY = 3

# 任务终态：进入终态后 _update_task 拒绝再写入（看门狗/手动取消的裁决生效）
TERMINAL_STATUSES = ('done', 'failed')

# 首扫结束后对失败页的整本补试轮数；全部页失败视为整体性故障，补试无意义
PAGE_RETRY_ROUNDS = 2
PAGE_RETRY_ROUND_INTERVAL = 3.0
# 失败页号在任务 message 中最多列出的数量
MAX_FAILED_PAGE_LIST = 20

_sleep = time.sleep


class ScrapePartialError(Exception):
    """补试后仍有失败页：任务失败，但保留已下载文件供同一画廊续传。"""

    def __init__(self, failed, total):
        page_nos = sorted(i + 1 for i in failed)
        listing = ','.join(str(n) for n in page_nos[:MAX_FAILED_PAGE_LIST])
        if len(page_nos) > MAX_FAILED_PAGE_LIST:
            listing += f' 等 {len(page_nos)} 页'
        msg = (f'第 {listing} 页下载失败'
               f'（已保留 {total - len(failed)}/{total} 页，重新发起同一画廊可续传）')
        last_error = next(iter(failed.values()), '')
        if last_error:
            msg += f' 最后错误: {last_error}'
        super().__init__(msg)


class ImageScrapeService:

    @staticmethod
    def _temp_dir_for(url):
        """临时目录按画廊 URL 哈希命名：同一画廊重发自动复用已下载页（续传）。"""
        digest = hashlib.md5(url.encode('utf-8')).hexdigest()[:16]
        return os.path.join(DOWNLOAD_DIR, 'scrape', digest)

    @staticmethod
    def start_scrape(url):
        """创建任务记录并提交线程池，返回 task_id。"""
        source = get_registry().sources()
        source = next((s for s in source if s.can_handle(url)), None)
        if source is None:
            raise ValueError('无法识别的画廊地址')

        task_id = uuid.uuid4().hex[:32]
        task = ScrapeTask(
            id=task_id,
            source=source.source_id,
            url=url,
            status='pending',
        )
        db.session.add(task)
        db.session.commit()

        # 全局串行队列：一律只入队（pending），由唯一持调度锁的 leader
        # 统一派发——TaskManager 池是进程内的，4 个 gunicorn worker 各有
        # 一份，仅靠池并发数无法跨进程串行
        return task_id

    @staticmethod
    def submit_task(task_id, url, app):
        """把已创建的 ScrapeTask 提交到抓取池（调度器与即时提交共用入口）。"""
        task_manager.submit(
            TaskType.SCRAPE,
            f'scrape:{task_id}',
            ImageScrapeService._run_in_app_context, app, task_id, url,
        )

    @staticmethod
    def _run_in_app_context(app, task_id, url):
        with app.app_context():
            ImageScrapeService._run_scrape(task_id, url)

    @staticmethod
    def _update_task(task_id, force=False, **fields):
        """更新任务字段，立即提交。

        必须用短事务：若节流延迟提交，暂存的脏状态会在下一次 query 的
        autoflush 时发出 UPDATE 并保持写事务打开，直到数页之后才提交——
        期间其他进程的任何写入（如发起新抓取的 INSERT）都会
        database is locked。WAL 下单页一次小提交开销极低。

        终态守卫：任务已被看门狗/手动取消标记终态时抛 TaskCancelled
        （BaseException，穿透业务层 except Exception），让仍在运行的
        抓取协程在下一个进度上报点协作退出，也不会把已终止任务复活。
        """
        task = ScrapeTask.query.get(task_id)
        if task is None:
            return None
        if task.status in TERMINAL_STATUSES:
            raise TaskCancelled(f'任务已终止（{task.status}），停止后续写入')
        for key, val in fields.items():
            setattr(task, key, val)
        db.session.commit()
        return task

    @staticmethod
    def _note(task_id, message):
        """仅更新任务消息：长重试链保持 updated_at 新鲜（看门狗依据），
        并让用户看到当前卡在哪一页的重试上。

        进度消息是尽力而为的附属信息，DB 瞬时异常（锁竞争等）静默跳过，
        不影响下载主流程；TaskCancelled 为 BaseException，仍正常穿透
        （协作取消语义不受影响）。"""
        if task_id:
            try:
                ImageScrapeService._update_task(task_id, message=message[:512])
            except TaskCancelled:
                raise
            except Exception:
                pass

    @staticmethod
    def _run_scrape(task_id, url):
        """流水线主体。调用方需提供 app context。任何异常统一标记任务失败。"""
        temp_dir = ImageScrapeService._temp_dir_for(url)
        completed = False
        try:
            source = next((s for s in get_registry().sources() if s.can_handle(url)), None)
            if source is None:
                raise ValueError('无法识别的画廊地址')

            ImageScrapeService._update_task(
                task_id, force=True, status='running', message='获取画廊信息...')

            # 1. 元数据 + 查重
            details = source.gallery_details(url)
            ImageScrapeService._update_task(
                task_id, force=True, title=(details.get('title') or '')[:512])
            existing = Comic.query.filter_by(source_url=url).first()
            if existing is not None:
                ImageScrapeService._update_task(
                    task_id, status='done', message='已在库中', comic_id=existing.id
                )
                completed = True
                return

            # 2. 全部图片 URL（大画廊解析需数分钟，逐页上报进度避免
            #    长时间零进展被误判卡死，也让看门狗有新鲜 updated_at）
            def _resolve_progress(done, total_cnt):
                if total_cnt:
                    ImageScrapeService._update_task(
                        task_id, progress=done, total=total_cnt,
                        message=f'解析图片地址 {done}/{total_cnt}')
                else:
                    ImageScrapeService._update_task(
                        task_id, message=f'收集画廊页面链接 {done} 页')

            image_urls = source.page_image_urls(url, progress_cb=_resolve_progress)
            if not image_urls:
                raise ValueError('未能解析到任何图片')
            ImageScrapeService._update_task(
                task_id, force=True, total=len(image_urls), progress=0)

            # 3. 下载：失败页容错收集 + 统一补试（单页失败不再炸掉整本）
            os.makedirs(temp_dir, exist_ok=True)
            pages = [p if isinstance(p, PageImage) else PageImage(url=p) for p in image_urls]
            failed = ImageScrapeService._download_all(source, pages, temp_dir, task_id)
            failed = ImageScrapeService._retry_failed_pages(
                source, pages, temp_dir, failed, task_id)
            if failed:
                raise ScrapePartialError(failed, len(pages))

            # 4. 打包 ZIP
            title = details.get('title') or 'untitled'
            zip_name = safe_filename(f'{title}.zip') or f'{task_id}.zip'
            zip_path = os.path.join(temp_dir, zip_name)
            ImageScrapeService._pack_zip(temp_dir, zip_path)

            # 5. 入库
            comic = ImageScrapeService._import_comic(details, url, zip_path, zip_name)

            # 6. 完成
            ImageScrapeService._update_task(
                task_id, status='done', message='入库完成',
                progress=len(image_urls), total=len(image_urls), comic_id=comic.id,
            )
            completed = True
        except QuotaError:
            db.session.rollback()
            ImageScrapeService._update_task(
                task_id, force=True, status='failed',
                message='带宽配额限制（509/1004），请稍后再试或配置站点 Cookie',
            )
        except ScrapePartialError as e:
            # 失败保留临时目录，重新发起同一画廊时续传
            db.session.rollback()
            ImageScrapeService._update_task(
                task_id, force=True, status='failed', message=str(e)[:512]
            )
        except Exception as e:
            db.session.rollback()
            ImageScrapeService._update_task(
                task_id, force=True, status='failed', message=str(e)[:500]
            )
        finally:
            if completed:
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _skip_existing(dest_path):
        """续传：目标文件已存在且非空则跳过下载。"""
        return os.path.exists(dest_path) and os.path.getsize(dest_path) > 0

    @staticmethod
    def _download_all(source, pages, temp_dir, task_id):
        """按源策略下载全部图片，序号命名；进度实时上报。

        返回失败页索引 -> 错误信息。E-Hentai（支持换节点）串行 + 间隔，
        nhentai 并发；worker 只做下载，进度由主流程统一上报。
        """
        total = len(pages)
        failed = {}
        done = 0

        def _mark_ok():
            nonlocal done
            done += 1
            ImageScrapeService._update_task(
                task_id, progress=done, total=total, message=f'下载中 {done}/{total}')

        if getattr(source, 'reload_image', None):
            # 支持坏节点换源的源（E-Hentai H@H）：串行 + 间隔 + 换节点重载
            for i, page in enumerate(pages):
                dest = os.path.join(temp_dir, f'{i + 1:04d}.jpg')
                try:
                    if ImageScrapeService._skip_existing(dest):
                        _mark_ok()
                    else:
                        ImageScrapeService._download_page_with_reload(
                            source, page, dest, task_id=task_id, page_no=i + 1)
                        _mark_ok()
                except QuotaError:
                    raise
                except Exception as e:
                    failed[i] = str(e)
                if i + 1 < total:
                    _sleep(EHENTAI_INTERVAL)
        else:
            from flask import current_app
            app = current_app._get_current_object()

            def worker(pair):
                i, page = pair
                dest = os.path.join(temp_dir, f'{i + 1:04d}.jpg')
                # app context 是线程本地的，worker 需自建（fetch_image 内 Setting 查询）
                with app.app_context():
                    if ImageScrapeService._skip_existing(dest):
                        return
                    # 不传 task_id/page_no：worker 线程内 _note 写库会与主线程
                    # _mark_ok 并发使用同一 DB（测试内存库 StaticPool 单连接
                    # 直接竞态报 InterfaceError；文件库则有无谓锁竞争）。
                    # 进度与保活由主线程 _mark_ok 统一上报；慢链路重试消息
                    # 保活只在 EH 串行主线程路径（_download_page_with_reload）
                    ImageScrapeService._download_with_retry(page.url, dest)

            with ThreadPoolExecutor(max_workers=NHENTAI_CONCURRENCY) as pool:
                futures = {
                    pool.submit(worker, (i, page)): i
                    for i, page in enumerate(pages)
                }
                # as_completed：哪页先下完就先上报，进度逐页实时
                for fut in as_completed(futures):
                    try:
                        fut.result()
                        _mark_ok()
                    except QuotaError:
                        raise
                    except Exception as e:
                        failed[futures[fut]] = str(e)
        return failed

    @staticmethod
    def _retry_failed_pages(source, pages, temp_dir, failed, task_id):
        """对首扫失败页统一补试若干轮（换节点重载仍可用）。

        全部页都失败视为整体性故障（网络/配额中断），补试无意义直接返回。
        """
        total = len(pages)
        for _round in range(PAGE_RETRY_ROUNDS):
            if not failed or len(failed) >= total:
                break
            _sleep(PAGE_RETRY_ROUND_INTERVAL)
            still = {}
            for i in list(failed):
                dest = os.path.join(temp_dir, f'{i + 1:04d}.jpg')
                try:
                    ImageScrapeService._download_page_with_reload(
                        source, pages[i], dest, task_id=task_id, page_no=i + 1)
                except QuotaError:
                    raise
                except Exception as e:
                    still[i] = str(e)
            failed = still
            ImageScrapeService._update_task(task_id, progress=total - len(failed), total=total)
        return failed

    @staticmethod
    def _download_page_with_reload(source, page, dest_path, task_id=None, page_no=None):
        """下载单页：原 URL 重试耗尽后，源支持换节点时 reload 重试。

        E-Hentai 图片 URL 绑定固定 H@H 节点，节点不可达时同一 URL 重试
        只会打同一节点；?nl= 重载让站点返回另一节点的图片 URL。
        重试全程通过 _note 上报消息：单页重试链可达数分钟，静默重试
        会让进度条长时间冻结（被误判卡死），也失去换节点可见性。
        """
        reload_fn = getattr(source, 'reload_image', None)
        try:
            ImageScrapeService._download_with_retry(
                page.url, dest_path, task_id=task_id, page_no=page_no)
            return
        except Exception:
            if reload_fn is None or not page.nl_key or not page.viewer_url:
                raise

        last_err = None
        for n in range(IMAGE_RELOAD_RETRY):
            ImageScrapeService._note(
                task_id, f'第 {page_no} 页节点异常，换节点重试 {n + 1}/{IMAGE_RELOAD_RETRY}')
            _sleep(RETRY_BACKOFF)
            try:
                page = reload_fn(page)
            except QuotaError:
                raise
            except Exception as e:
                last_err = e
                continue
            try:
                ImageScrapeService._download_with_retry(
                    page.url, dest_path, task_id=task_id, page_no=page_no)
                return
            except Exception as e:
                last_err = e
        raise last_err or Exception('换节点重载失败')

    @staticmethod
    def _download_with_retry(url, dest_path, task_id=None, page_no=None):
        """下载单图，失败自动重试；timeout 使用更宽的次数与退避。"""
        import requests as _requests

        attempt = 0
        while True:
            attempt += 1
            try:
                ImageScrapeService._download_image(url, dest_path)
                return
            except _requests.Timeout:
                # 超时往往由源站瞬时抖动导致，多给几次机会
                if attempt >= IMAGE_TIMEOUT_RETRY:
                    raise
                if page_no:
                    ImageScrapeService._note(
                        task_id, f'第 {page_no} 页超时，重试 {attempt}/{IMAGE_TIMEOUT_RETRY}')
                _sleep(RETRY_BACKOFF * (2 ** attempt))
            except Exception:
                if attempt >= IMAGE_RETRY:
                    raise
                if page_no:
                    ImageScrapeService._note(
                        task_id, f'第 {page_no} 页下载失败，重试 {attempt}/{IMAGE_RETRY}')
                _sleep(RETRY_BACKOFF * (2 ** (attempt - 1)))

    @staticmethod
    def _download_image(url, dest_path):
        """下载单张图片到目标路径（受 IMAGE_TRANSFER_BUDGET 总预算约束）。"""
        content, _ = fetch_image(url, max_read_seconds=IMAGE_TRANSFER_BUDGET)
        if not content:
            raise ValueError(f'图片内容为空: {url}')
        with open(dest_path, 'wb') as f:
            f.write(content)

    @staticmethod
    def _pack_zip(temp_dir, zip_path):
        """把临时目录内的图片打包为 ZIP。"""
        files = sorted(
            f for f in os.listdir(temp_dir)
            if os.path.isfile(os.path.join(temp_dir, f))
        )
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for name in files:
                zf.write(os.path.join(temp_dir, name), arcname=name)

    @staticmethod
    def _import_comic(details, url, zip_path, zip_name):
        """复制到漫画库目录并创建 Comic + NFO + 封面。"""
        dst_path, rel_filename, dst_size, _ = FileOperationService().copy_to_comics_dir(
            zip_path, zip_name
        )

        comic = Comic(
            title=details.get('title', ''),
            title_jp=details.get('title_jp', ''),
            author=details.get('author', ''),
            category=details.get('category', ''),
            language=details.get('language', ''),
            date=details.get('date', ''),
            plot=details.get('plot', ''),
            rating=details.get('rating', 0.0) or 0.0,
            tags=details.get('tags', ''),
            uploader=details.get('uploader', ''),
            page_count=details.get('page_count', 0) or 0,
            source_url=url,
            filename=rel_filename,
            file_size=dst_size,
        )
        db.session.add(comic)
        db.session.commit()

        NfoService.save_comic_nfo(comic)
        db.session.commit()

        # PIL 封面生成是 CPU 密集工作，委托真实线程避免阻塞事件循环
        from app.reader import regenerate_comic_cover_by_id
        from app.utils.threading_utils import run_cpu_bound
        run_cpu_bound(regenerate_comic_cover_by_id, comic.id)
        return comic

    @staticmethod
    def recover_interrupted():
        """启动恢复：将 pending/running 的抓取任务标记为失败。

        仅在本进程首次调用时执行（真·启动恢复）。
        create_app() 会被调度器 worker / 抓取线程反复调用，
        若不加以限制，会把正在运行的任务误判为中断。
        """
        if getattr(ImageScrapeService, '_recovery_done', False):
            return 0
        ImageScrapeService._recovery_done = True

        tasks = ScrapeTask.query.filter(ScrapeTask.status.in_(['pending', 'running'])).all()
        for task in tasks:
            task.status = 'failed'
            task.message = '服务重启中断，请重新发起抓取'
        if tasks:
            db.session.commit()
        return len(tasks)
