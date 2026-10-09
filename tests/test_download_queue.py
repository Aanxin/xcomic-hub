"""全局串行下载队列行为测试：一次一个任务，其余按提交顺序排队。"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import DownloadTask, ScrapeTask
from app.services.scheduler_service import SchedulerService
from app.services.image_scrape_service import ImageScrapeService
from app.sources.base_source import BaseSource, GalleryListResult
from app.sources.source_registry import get_registry, _reset_registry

SCRAPE_URL = 'https://fake.com/g/1/'


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'
    domains = ('fake.com',)

    def search(self, keyword, page=1):
        return GalleryListResult()

    def latest(self, page=1):
        return GalleryListResult()

    def gallery_details(self, url):
        return {'title': 'T'}

    def page_image_urls(self, url):
        return []


@pytest.fixture()
def fake_source():
    _reset_registry()
    get_registry().register(FakeSource())
    yield
    _reset_registry()


@pytest.fixture()
def mock_tm():
    tm = MagicMock()
    with patch('app.services.image_scrape_service.task_manager', tm):
        yield tm


def _add_active_download():
    t = DownloadTask(id='dl_active', url='https://e-hentai.org/g/1/abc/',
                     title='种子', status='downloading', qb_progress=30.0,
                     queue='downloading', qb_state='downloading')
    db.session.add(t)
    db.session.commit()
    return t


def _add_waiting_download(created_at=None):
    t = DownloadTask(id='dl_wait', url='https://e-hentai.org/g/2/xyz/',
                     title='等待种子', status='pending', queue='waiting',
                     queue_position=1, created_at=created_at)
    db.session.add(t)
    db.session.commit()
    return t


def test_start_scrape_defers_when_torrent_active(app, fake_source, mock_tm):
    """种子任务下载中：新抓取任务应保持 pending 排队，不立即提交。"""
    _add_active_download()

    task_id = ImageScrapeService.start_scrape(SCRAPE_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'pending'
    mock_tm.submit.assert_not_called(), '派发权在调度器，提交时不得直接入池'


def test_start_scrape_always_enqueues(app, fake_source, mock_tm):
    """无论空闲与否，抓取任务一律入队由调度器派发（跨进程全局串行）。"""
    task_id = ImageScrapeService.start_scrape(SCRAPE_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'pending'
    mock_tm.submit.assert_not_called()


def test_dispatch_skips_when_download_active(app, mock_tm):
    """种子任务下载中：排队的抓取任务不得派发。"""
    _add_active_download()
    db.session.add(ScrapeTask(id='s_wait', source='fake', url=SCRAPE_URL,
                              status='pending', created_at=datetime.utcnow()))
    db.session.commit()

    svc = SchedulerService(app=app)
    assert svc._dispatch_next_task() is False

    task = ScrapeTask.query.get('s_wait')
    assert task.status == 'pending', '一次只允许一个任务'
    mock_tm.submit.assert_not_called()


def test_dispatch_skips_when_scrape_running(app, mock_tm):
    """抓取任务运行中：等待中的种子任务不得派发。"""
    db.session.add(ScrapeTask(id='s_run', source='fake', url=SCRAPE_URL,
                              status='running', created_at=datetime.utcnow()))
    _add_waiting_download()
    db.session.commit()

    svc = SchedulerService(app=app)
    assert svc._dispatch_next_task() is False

    dl = DownloadTask.query.get('dl_wait')
    assert dl.queue == 'waiting' and dl.status == 'pending', '一次只允许一个任务'


def test_dispatch_oldest_scrape_wins_over_newer_torrent(app, mock_tm):
    """空闲时按创建时间取最老任务：更早的抓取优先于更晚的种子。"""
    older = datetime.utcnow() - timedelta(hours=1)
    db.session.add(ScrapeTask(id='s_old', source='fake', url=SCRAPE_URL,
                              status='pending', created_at=older))
    _add_waiting_download(created_at=datetime.utcnow())
    db.session.commit()

    svc = SchedulerService(app=app)
    assert svc._dispatch_next_task() is True

    mock_tm.submit.assert_called_once()
    assert mock_tm.submit.call_args[0][1] == 'scrape:s_old'
    dl = DownloadTask.query.get('dl_wait')
    assert dl.queue == 'waiting', '种子应继续排队'


def test_dispatch_torrent_when_idle(app):
    """空闲且只有等待种子时：CAS 派发种子任务。"""
    _add_waiting_download()
    db.session.commit()

    svc = SchedulerService(app=app)
    with patch('app.services.scheduler_service.task_manager') as tm:
        assert svc._dispatch_next_task() is True
        tm.submit.assert_called_once()
        assert tm.submit.call_args[0][1] == 'download:dl_wait'

    dl = DownloadTask.query.get('dl_wait')
    assert dl.queue == 'downloading'
    assert dl.status == 'scraping'
