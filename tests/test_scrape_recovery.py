"""recover_interrupted 只应在进程启动时执行一次的测试。"""

from app import db
from app.models import ScrapeTask
from app.services.image_scrape_service import ImageScrapeService


def _make_task(status='running'):
    task = ScrapeTask(id='t_rec_1', source='nhentai', url='https://nhentai.net/g/1/', status=status)
    db.session.add(task)
    db.session.commit()
    return task


def test_recover_marks_running_task_failed(app):
    """首次调用：running 任务标记失败（真·启动恢复）。"""
    ImageScrapeService._recovery_done = False  # 重置进程标记
    task = _make_task('running')
    ImageScrapeService.recover_interrupted()
    assert task.status == 'failed'
    assert '中断' in task.message


def test_recover_runs_only_once_per_process(app):
    """同一进程内再次调用（调度器 worker 的 create_app）不应误杀新任务。"""
    ImageScrapeService._recovery_done = False
    ImageScrapeService.recover_interrupted()  # 首次：启动恢复

    task = _make_task('running')  # 之后出现的新运行中任务
    ImageScrapeService.recover_interrupted()  # 调度器 worker 触发的重复调用
    db.session.refresh(task)
    assert task.status == 'running', '重复调用不应把运行中的任务标记失败'
