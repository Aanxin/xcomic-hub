"""ScrapeTask 模型测试。"""

from datetime import datetime

from app import db
from app.models import ScrapeTask


def test_scrape_task_create_defaults(app):
    task = ScrapeTask(
        id='abc123',
        source='ehentai',
        url='https://e-hentai.org/g/123/abc/',
    )
    db.session.add(task)
    db.session.commit()

    saved = ScrapeTask.query.get('abc123')
    assert saved is not None
    assert saved.source == 'ehentai'
    assert saved.url == 'https://e-hentai.org/g/123/abc/'
    assert saved.title == ''
    assert saved.status == 'pending'
    assert saved.message == ''
    assert saved.progress == 0
    assert saved.total == 0
    assert saved.comic_id is None
    assert isinstance(saved.created_at, datetime)
    assert isinstance(saved.updated_at, datetime)


def test_scrape_task_to_dict(app):
    task = ScrapeTask(
        id='task1',
        source='nhentai',
        url='https://nhentai.net/g/1/',
        title='Test Title',
        status='running',
        message='下载中',
        progress=5,
        total=20,
        comic_id=42,
    )
    db.session.add(task)
    db.session.commit()

    d = ScrapeTask.query.get('task1').to_dict()
    assert d['id'] == 'task1'
    assert d['source'] == 'nhentai'
    assert d['url'] == 'https://nhentai.net/g/1/'
    assert d['title'] == 'Test Title'
    assert d['status'] == 'running'
    assert d['message'] == '下载中'
    assert d['progress'] == 5
    assert d['total'] == 20
    assert d['comic_id'] == 42
    assert 'created_at' in d
    assert 'updated_at' in d
