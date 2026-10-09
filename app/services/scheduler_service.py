import os
import shutil
import threading
import time as _time
from datetime import datetime, timedelta

from app import db
from app.models import DownloadTask
from app.services.download_service import DownloadService
from app.services.task_manager import task_manager, TaskType

try:
    import fcntl
except ImportError:  # Windows 无 fcntl
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


class SchedulerService:
    def __init__(self, app=None):
        self.app = app
        self.scheduler_thread = None
        self.monitor_thread = None
        self.chunk_cleanup_thread = None
        self.running = False
        self._lock_file = None

    def start(self):
        if self.running:
            return
        # 多 gunicorn worker 都会执行 create_app：文件锁选主，
        # 仅持锁进程运行调度器，避免 4 份轮询/清理放大 DB 竞争
        if not self._acquire_leader_lock():
            print('[调度器] 其他进程已持有调度锁，本进程跳过后台调度')
            return
        if self.app is None:
            from flask import current_app
            self.app = current_app._get_current_object()
        self.running = True

        # 抓取任务只在 leader 进程运行（调度派发 + TaskManager 池均在本
        # 进程）：新 leader 上任意味着旧 leader 及其协程已死，此处恢复
        # 其中断任务。非 leader 进程不恢复——会把存活 leader 正在跑的
        # 任务误杀。
        try:
            with self.app.app_context():
                from app.services.image_scrape_service import ImageScrapeService
                ImageScrapeService.recover_interrupted()
        except Exception as e:
            print(f'[抓取] 启动恢复失败: {e}')

        self.scheduler_thread = threading.Thread(target=self._scheduler_worker, daemon=True)
        self.scheduler_thread.start()
        self.monitor_thread = threading.Thread(target=self._download_monitor, daemon=True)
        self.monitor_thread.start()
        self.chunk_cleanup_thread = threading.Thread(target=self._chunk_cleanup_worker, daemon=True)
        self.chunk_cleanup_thread.start()

    def _acquire_leader_lock(self):
        """非阻塞抢占调度锁。进程退出时 OS 自动释放，无需显式清理。"""
        from config import DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        lock_path = os.path.join(DATA_DIR, 'scheduler.lock')
        try:
            lock_file = open(lock_path, 'a+b')
        except OSError:
            return False
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            # 两者皆无的平台（罕见）退化为不选主，行为与旧版一致
        except (OSError, IOError, ValueError):
            lock_file.close()
            return False
        self._lock_file = lock_file
        return True

    def release_leader_lock(self):
        """显式释放调度锁（测试/优雅停机用；进程退出自动释放）。"""
        if self._lock_file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except (OSError, IOError, ValueError):
            pass
        self._lock_file.close()
        self._lock_file = None

    def stop(self):
        self.running = False

    # 队列派发检查间隔（秒）：任务结束后最多此延迟内启动下一个
    DISPATCH_INTERVAL = 10
    # 运行中抓取任务的无进展判定阈值（秒）：progress/message 每页都会
    # 提交刷新 updated_at，超过此值无任何更新即判定卡死
    STALE_SCRAPE_SECONDS = 600

    def _scheduler_worker(self):
        _time.sleep(5)
        while self.running:
            try:
                with self.app.app_context():
                    self._fail_stale_scrapes()
                    self._dispatch_next_task()
            except Exception as e:
                print(f'[调度器] 检查失败: {e}')
                import traceback
                traceback.print_exc()
            print(f'[调度器] 下次检查: {self.DISPATCH_INTERVAL}秒后')
            _time.sleep(self.DISPATCH_INTERVAL)

    def _fail_stale_scrapes(self):
        """看门狗：running 的抓取任务超时无进展则标记失败。

        抓取池全局串行（1 槽），一个真卡死的任务会让调度器永远不派发
        后续任务（表现为"不再下载"）。正常任务每页/每次重试都会提交
        progress 或 message 刷新 updated_at；长时间无任何提交即判定卡死，
        终止该任务让队列继续。已下载页保留在续传目录，重发同一画廊
        可续传。仍在运行的抓取协程会在下一个上报点被终态守卫
        （_update_task 抛 TaskCancelled）协作终止。
        """
        from app.models import ScrapeTask

        cutoff = datetime.utcnow() - timedelta(seconds=self.STALE_SCRAPE_SECONDS)
        stale = ScrapeTask.query.filter(
            ScrapeTask.status == 'running',
            ScrapeTask.updated_at < cutoff,
        ).all()
        for t in stale:
            t.status = 'failed'
            t.message = (f'任务超过 {self.STALE_SCRAPE_SECONDS // 60} 分钟无进展，'
                         '已自动终止；重新发起同一画廊可续传')
            print(f'[调度器] 看门狗终止卡死任务: {t.id} ({(t.title or t.url)[:50]})')
        if stale:
            db.session.commit()
        return len(stale)

    def _dispatch_next_task(self):
        """全局串行下载队列：任何时刻只允许一个下载任务在跑。

        活跃定义：running 的抓取任务，或非终态（未 done/error/failed）的种子任务。
        空闲时按创建时间取最老的等待任务（抓取 pending / 种子 waiting）派发。
        """
        from app.models import ScrapeTask

        active_scrape = ScrapeTask.query.filter_by(status='running').count()
        active_download = DownloadTask.query.filter(
            DownloadTask.queue == 'downloading',
            DownloadTask.status.notin_(('done', 'error', 'failed')),
        ).count()
        print(f'[调度器] 活跃: 抓取={active_scrape} 种子={active_download}')
        if active_scrape or active_download:
            return False

        cand_scrape = ScrapeTask.query.filter_by(status='pending') \
            .order_by(ScrapeTask.created_at.asc()).first()
        cand_download = DownloadTask.query.filter_by(queue='waiting', status='pending') \
            .order_by(DownloadTask.queue_position.asc(), DownloadTask.created_at.asc()).first()

        pick_scrape = False
        if cand_scrape and cand_download:
            pick_scrape = (cand_scrape.created_at or datetime.min) <= \
                          (cand_download.created_at or datetime.min)
        elif cand_scrape:
            pick_scrape = True
        elif not cand_download:
            return False

        if pick_scrape:
            from app.services.image_scrape_service import ImageScrapeService
            print(f'[调度器] 派发抓取任务 {cand_scrape.id}')
            ImageScrapeService.submit_task(cand_scrape.id, cand_scrape.url, self.app)
            return True

        # 种子任务：CAS 抢占后提交（防多进程重复派发）
        next_task = cand_download
        if next_task.url:
            new_status, new_message = 'scraping', '正在采集页面信息...'
        else:
            new_status, new_message = 'saving_nfo', '正在处理种子文件...'
        result = db.session.execute(db.text(
            "UPDATE download_tasks SET queue='downloading', status=:status, message=:msg, updated_at=:now "
            "WHERE id=:id AND queue='waiting' AND status='pending'"
        ), {'status': new_status, 'msg': new_message, 'now': datetime.utcnow(), 'id': next_task.id})
        db.session.commit()
        if result.rowcount > 0:
            print(f'[调度器] 派发种子任务 {next_task.id}, status={new_status}')
            task_manager.submit(
                TaskType.DOWNLOAD_TASK,
                f'download:{next_task.id}',
                DownloadService.run_add_task,
                next_task.id,
            )
            return True
        return False

    def _download_monitor(self):
        while self.running:
            _time.sleep(60)
            try:
                with self.app.app_context():
                    active = DownloadTask.query.filter(
                        DownloadTask.status.in_(['downloading', 'matching', 'importing'])
                    ).count()
                    if active > 0:
                        DownloadService.update_download_progress()
            except Exception as e:
                print(f'[下载监控] 更新进度失败: {e}')

    def _chunk_cleanup_worker(self):
        _time.sleep(30)
        while self.running:
            try:
                with self.app.app_context():
                    self._cleanup_stale_chunks()
                    self._cleanup_scrape_history()
                    self._cleanup_image_cache()
                # 顺带清理已完成的 TaskManager 记录,避免 _tasks/_futures 字典无限增长
                task_manager.cleanup()
            except Exception as e:
                print(f'[分片清理] 清理失败: {e}')
                import traceback
                traceback.print_exc()
            _time.sleep(600)

    # 抓取续传目录保留窗口（秒），超期未写入即清理
    SCRAPE_TEMP_MAX_AGE = 7 * 86400

    @classmethod
    def _cleanup_scrape_history(cls):
        """清理抓取历史与续传目录：记录保留最近 50 条，目录超 7 天未写入清理。

        续传目录按画廊 URL 哈希命名，删除历史记录不影响续传能力。
        活跃任务持续写入会使目录 mtime 保持新鲜，不会被误删。
        """
        from app.models import ScrapeTask
        from config import DOWNLOAD_DIR

        finished = ScrapeTask.query.filter(
            ScrapeTask.status.in_(['done', 'failed'])
        ).order_by(ScrapeTask.updated_at.desc()).all()
        if len(finished) > 50:
            for task in finished[50:]:
                db.session.delete(task)
            db.session.commit()
            print(f'[抓取清理] 清理过期抓取记录: {len(finished) - 50} 条')

        scrape_dir = os.path.join(DOWNLOAD_DIR, 'scrape')
        if not os.path.isdir(scrape_dir):
            return
        cutoff = _time.time() - cls.SCRAPE_TEMP_MAX_AGE
        for name in os.listdir(scrape_dir):
            entry = os.path.join(scrape_dir, name)
            if not os.path.isdir(entry):
                continue
            try:
                if os.path.getmtime(entry) < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    print(f'[抓取清理] 清理过期续传目录: {name}')
            except OSError:
                pass

    # 源图片代理缓存保留窗口（秒）
    IMAGE_CACHE_MAX_AGE = 14 * 86400

    @classmethod
    def _cleanup_image_cache(cls):
        """清理源图片代理的过期磁盘缓存。"""
        from config import IMAGE_CACHE_DIR

        if not os.path.isdir(IMAGE_CACHE_DIR):
            return
        cutoff = _time.time() - cls.IMAGE_CACHE_MAX_AGE
        removed = 0
        for name in os.listdir(IMAGE_CACHE_DIR):
            path = os.path.join(IMAGE_CACHE_DIR, name)
            if not os.path.isfile(path):
                continue
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
        if removed:
            print(f'[图片缓存] 清理过期缓存: {removed} 个')

    def _cleanup_stale_chunks(self):
        from config import DATA_DIR
        from app.models import ChunkedUpload

        chunks_dir = os.path.join(DATA_DIR, 'chunks')
        if not os.path.exists(chunks_dir):
            return

        now = datetime.utcnow()
        stale_active = now - timedelta(hours=2)
        stale_finished = now - timedelta(hours=24)

        stale_uploads = ChunkedUpload.query.filter(
            ChunkedUpload.status.in_(['pending', 'uploading', 'paused']),
            ChunkedUpload.updated_at < stale_active
        ).all()

        for cu in stale_uploads:
            chunk_dir = os.path.join(chunks_dir, cu.id)
            if os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
                print(f'[分片清理] 清理中断上传的分片: {cu.id} ({cu.original_filename})')
            cu.status = 'failed'
            cu.error = '上传超时，已自动清理'
            cu.updated_at = now

        db.session.commit()

        finished_uploads = ChunkedUpload.query.filter(
            ChunkedUpload.status.in_(['completed', 'failed', 'cancelled']),
            ChunkedUpload.updated_at < stale_finished
        ).all()

        for cu in finished_uploads:
            chunk_dir = os.path.join(chunks_dir, cu.id)
            if os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir, ignore_errors=True)
            db.session.delete(cu)

        if finished_uploads:
            db.session.commit()
            print(f'[分片清理] 清理过期上传记录: {len(finished_uploads)} 条')

        db_ids = set()
        all_uploads = ChunkedUpload.query.all()
        for cu in all_uploads:
            db_ids.add(cu.id)

        for name in os.listdir(chunks_dir):
            entry_path = os.path.join(chunks_dir, name)
            if not os.path.isdir(entry_path):
                continue
            if name.startswith('_'):
                continue
            if name not in db_ids:
                shutil.rmtree(entry_path, ignore_errors=True)
                print(f'[分片清理] 清理无记录的分片目录: {name}')

        for temp_prefix in ('_nfo_temp', '_cover_temp'):
            temp_dir = os.path.join(chunks_dir, temp_prefix)
            if not os.path.exists(temp_dir):
                continue
            for name in os.listdir(temp_dir):
                entry_path = os.path.join(temp_dir, name)
                if not os.path.isdir(entry_path):
                    continue
                try:
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(entry_path))
                    if now - mtime > timedelta(hours=24):
                        shutil.rmtree(entry_path, ignore_errors=True)
                        print(f'[分片清理] 清理过期临时目录: {temp_prefix}/{name}')
                except OSError:
                    pass
