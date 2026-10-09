"""抓取历史与续传目录清理测试。"""

import os
import time

from app import db
from app.models import ScrapeTask
from app.services.scheduler_service import SchedulerService


def _make_task(n, status='done'):
    return ScrapeTask(id=f't{n:03d}', source='fake', url=f'https://fake.com/g/{n}/',
                      status=status)


def test_cleanup_scrape_history_keeps_latest_50(app):
    db.session.add_all([_make_task(i) for i in range(55)])
    db.session.commit()

    SchedulerService._cleanup_scrape_history()

    remaining = ScrapeTask.query.filter_by(status='done').all()
    assert len(remaining) == 50
    ids = {t.id for t in remaining}
    assert 't054' in ids, '应保留最新记录'
    assert 't000' not in ids, '应删除最旧记录'


def test_cleanup_scrape_history_keeps_running_tasks(app):
    db.session.add_all([_make_task(i, status='running') for i in range(60)])
    db.session.commit()

    SchedulerService._cleanup_scrape_history()

    assert ScrapeTask.query.filter_by(status='running').count() == 60, '进行中任务不清理'


def test_cleanup_scrape_temp_dirs_by_mtime(app, monkeypatch):
    from config import DOWNLOAD_DIR

    scrape_dir = os.path.join(DOWNLOAD_DIR, 'scrape')
    os.makedirs(scrape_dir, exist_ok=True)
    old_dir = os.path.join(scrape_dir, 'oldhash')
    fresh_dir = os.path.join(scrape_dir, 'freshhash')
    os.makedirs(old_dir, exist_ok=True)
    os.makedirs(fresh_dir, exist_ok=True)
    with open(os.path.join(old_dir, '0001.jpg'), 'wb') as f:
        f.write(b'x')
    with open(os.path.join(fresh_dir, '0001.jpg'), 'wb') as f:
        f.write(b'x')
    aged = time.time() - 8 * 86400
    os.utime(old_dir, (aged, aged))

    SchedulerService._cleanup_scrape_history()

    assert not os.path.exists(old_dir), '超期目录应被清理'
    assert os.path.exists(fresh_dir), '新鲜目录应保留'
