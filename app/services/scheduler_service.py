import os
import shutil
import threading
import time as _time
from datetime import datetime, timedelta

from app import db, create_app
from app.models import DownloadTask
from app.services.download_service import DownloadService


class SchedulerService:
    def __init__(self):
        self.scheduler_thread = None
        self.monitor_thread = None
        self.chunk_cleanup_thread = None
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_worker, daemon=True)
        self.scheduler_thread.start()
        self.monitor_thread = threading.Thread(target=self._download_monitor, daemon=True)
        self.monitor_thread.start()
        self.chunk_cleanup_thread = threading.Thread(target=self._chunk_cleanup_worker, daemon=True)
        self.chunk_cleanup_thread.start()

    def stop(self):
        self.running = False

    def _scheduler_worker(self):
        _time.sleep(5)
        while self.running:
            try:
                app = create_app()
                with app.app_context():
                    active = db.session.execute(db.text(
                        "SELECT COUNT(*) FROM download_tasks WHERE queue='downloading' AND status IN ('scraping','saving_nfo','adding_torrent','matching')"
                    )).scalar()
                    print(f'[调度器] 检查: 采集中/添加种子/匹配中={active}')
                    if active > 0:
                        pass
                    else:
                        next_task = DownloadTask.query.filter(
                            DownloadTask.queue == 'waiting',
                            DownloadTask.status == 'pending'
                        ).order_by(DownloadTask.queue_position.asc(), DownloadTask.created_at.asc()).first()
                        waiting_count = DownloadTask.query.filter_by(queue='waiting', status='pending').count()
                        print(f'[调度器] 等待队列={waiting_count}, 下一个任务={next_task.id if next_task else "无"}')
                        if next_task:
                            if next_task.url:
                                new_status = 'scraping'
                                new_message = '正在采集页面信息...'
                            else:
                                new_status = 'saving_nfo'
                                new_message = '正在处理种子文件...'
                            result = db.session.execute(db.text(
                                "UPDATE download_tasks SET queue='downloading', status=:status, message=:msg, updated_at=:now "
                                "WHERE id=:id AND queue='waiting' AND status='pending'"
                            ), {'status': new_status, 'msg': new_message, 'now': datetime.utcnow(), 'id': next_task.id})
                            db.session.commit()
                            if result.rowcount > 0:
                                print(f'[调度器] 任务 {next_task.id} 已加入下载队列, status={new_status}')
                                thread = threading.Thread(
                                    target=DownloadService.run_add_task,
                                    args=(next_task.id,),
                                    daemon=True,
                                )
                                thread.start()
                            else:
                                print(f'[调度器] 任务 {next_task.id} CAS失败，已被其他进程处理')
            except Exception as e:
                print(f'[调度器] 检查失败: {e}')
                import traceback
                traceback.print_exc()
            now = _time.time()
            sleep_until = (int(now / 60) + 1) * 60
            sleep_secs = sleep_until - now
            print(f'[调度器] 下次检查: {sleep_secs:.0f}秒后')
            _time.sleep(sleep_secs)

    def _download_monitor(self):
        while self.running:
            _time.sleep(60)
            try:
                app = create_app()
                with app.app_context():
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
                app = create_app()
                with app.app_context():
                    self._cleanup_stale_chunks()
            except Exception as e:
                print(f'[分片清理] 清理失败: {e}')
                import traceback
                traceback.print_exc()
            _time.sleep(600)

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
