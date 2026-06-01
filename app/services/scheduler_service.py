import threading
import time as _time

from app import db, create_app
from app.models import DownloadTask
from app.services.download_service import DownloadService


class SchedulerService:
    def __init__(self):
        self.scheduler_thread = None
        self.monitor_thread = None
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.scheduler_thread = threading.Thread(target=self._scheduler_worker, daemon=True)
        self.scheduler_thread.start()
        self.monitor_thread = threading.Thread(target=self._download_monitor, daemon=True)
        self.monitor_thread.start()

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
                            from datetime import datetime
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
