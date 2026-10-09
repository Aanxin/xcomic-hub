"""抓取 API 测试。"""

from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import ScrapeTask
from app.sources.base_source import BaseSource, GalleryListResult
from app.sources.source_registry import get_registry, _reset_registry

GALLERY_URL = 'https://fake.com/g/1/'


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'
    domains = ('fake.com',)

    def search(self, keyword, page=1):
        return GalleryListResult()

    def latest(self, page=1):
        return GalleryListResult()

    def gallery_details(self, url):
        return {'title': 'Fake Gallery'}

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


def test_scrape_submit(client, fake_source, mock_tm):
    resp = client.post('/api/v1/sources/scrape', json={'url': GALLERY_URL})
    assert resp.status_code == 200

    data = resp.get_json()['data']
    assert data['task_id']
    task = ScrapeTask.query.get(data['task_id'])
    assert task is not None
    assert task.status == 'pending'
    mock_tm.submit.assert_not_called(), '派发权在调度器，API 提交只入队'


def test_scrape_missing_url(client, fake_source, mock_tm):
    resp = client.post('/api/v1/sources/scrape', json={})
    assert resp.status_code == 400
    mock_tm.submit.assert_not_called()


def test_scrape_unknown_url(client, fake_source, mock_tm):
    resp = client.post('/api/v1/sources/scrape', json={'url': 'https://unknown.com/g/1/'})
    assert resp.status_code == 400
    mock_tm.submit.assert_not_called()


def test_scrape_conflict_when_running(client, fake_source, mock_tm):
    t = ScrapeTask(id='t1', source='fake', url=GALLERY_URL, status='running')
    db.session.add(t)
    db.session.commit()

    resp = client.post('/api/v1/sources/scrape', json={'url': GALLERY_URL})
    assert resp.status_code == 409
    mock_tm.submit.assert_not_called()
