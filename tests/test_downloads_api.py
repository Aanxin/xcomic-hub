"""统一下载列表 API 测试：合并 ScrapeTask + DownloadTask。"""

import pytest

from app import db
from app.models import DownloadTask, ScrapeTask


def _add_scrape(status='running', progress=5, total=10, title='抓取A'):
    t = ScrapeTask(id='sc1', source='nhentai', url='https://nhentai.net/g/1/',
                   title=title, status=status, progress=progress, total=total)
    db.session.add(t)
    db.session.commit()
    return t


def _add_download(status='downloading', qb=78.2, title='种子B'):
    t = DownloadTask(id='dl1', url='https://e-hentai.org/g/1/abc/',
                     title=title, status=status, qb_progress=qb,
                     queue='downloading', qb_state='downloading')
    db.session.add(t)
    db.session.commit()
    return t


def test_tasks_merges_both_types(client):
    """列表应同时返回 scrape 与 download 两类任务，含统一字段。"""
    _add_scrape()
    _add_download()

    resp = client.get('/api/v1/downloads/tasks')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    items = data['items']
    assert len(items) == 2

    by_type = {i['type']: i for i in items}
    assert by_type['scrape']['progress_pct'] == 50.0
    assert by_type['scrape']['title'] == '抓取A'
    assert by_type['download']['progress_pct'] == 78.2
    assert by_type['download']['title'] == '种子B'


def test_tasks_active_before_finished(client):
    """进行中任务排在完成/失败任务之前。"""
    from datetime import datetime, timedelta

    old = datetime.utcnow() - timedelta(hours=1)
    done_scrape = _add_scrape(status='done', title='已完成抓取')
    done_scrape.created_at = old
    active_dl = _add_download(status='downloading', title='进行中种子')
    active_dl.created_at = datetime.utcnow()
    db.session.commit()

    resp = client.get('/api/v1/downloads/tasks')
    items = resp.get_json()['data']['items']
    assert items[0]['title'] == '进行中种子'
    assert items[-1]['title'] == '已完成抓取'


def test_tasks_scrape_progress_zero_when_no_total(client):
    """total=0 的抓取任务进度为 0 而非除零错误。"""
    _add_scrape(status='pending', progress=0, total=0, title='待解析')
    resp = client.get('/api/v1/downloads/tasks')
    items = resp.get_json()['data']['items']
    assert items[0]['progress_pct'] == 0.0


def test_tasks_empty(client):
    resp = client.get('/api/v1/downloads/tasks')
    assert resp.status_code == 200
    assert resp.get_json()['data']['items'] == []


# ---------- 统一删除 ----------

def test_delete_scrape_task(client):
    _add_scrape(status='done', title='抓取记录')
    resp = client.delete('/api/v1/downloads/tasks/scrape/sc1')
    assert resp.status_code == 200
    assert ScrapeTask.query.get('sc1') is None


def test_delete_running_scrape_cancels(client):
    """运行中的抓取任务：取消（标记终态）而非拒绝，解除队列阻塞。

    卡死任务此前无法删除只能重启服务；现在标记 failed 后，运行中的
    抓取协程会在下一个进度上报点被终态守卫协作终止。
    """
    _add_scrape(status='running')
    resp = client.delete('/api/v1/downloads/tasks/scrape/sc1')
    assert resp.get_json()['code'] == 0
    task = ScrapeTask.query.get('sc1')
    assert task is not None, '取消后保留记录（终态守卫依赖 DB 行传递取消信号）'
    assert task.status == 'failed'
    assert '取消' in task.message


def test_delete_pending_scrape_cancels(client):
    """等待中的抓取任务：同样取消，调度器不再派发已终态任务。"""
    _add_scrape(status='pending')
    resp = client.delete('/api/v1/downloads/tasks/scrape/sc1')
    assert resp.get_json()['code'] == 0
    assert ScrapeTask.query.get('sc1').status == 'failed'


def test_delete_download_task(client, monkeypatch):
    _add_download(status='done', title='种子记录')

    deleted = []
    monkeypatch.setattr(
        'app.services.download_service.DownloadService.delete_task',
        lambda task: deleted.append(task.id),
    )
    resp = client.delete('/api/v1/downloads/tasks/download/dl1')
    assert resp.status_code == 200
    assert deleted == ['dl1']


def test_delete_unknown_type_rejected(client):
    resp = client.delete('/api/v1/downloads/tasks/other/xx')
    assert resp.get_json()['code'] != 0


def test_delete_not_found(client):
    assert client.delete('/api/v1/downloads/tasks/scrape/nope').get_json()['code'] != 0
    assert client.delete('/api/v1/downloads/tasks/download/nope').get_json()['code'] != 0


# ---------- 废弃 API 已删除 ----------

def test_legacy_input_routes_removed(client):
    """三个输入入口与旧进度接口应已删除（404 或 405=仅剩其他方法）。"""
    assert client.post('/api/v1/downloads/start', json={'url': 'https://x.com/'}).status_code in (404, 405)
    assert client.post('/api/v1/downloads/torrent').status_code in (404, 405)
    assert client.post('/api/v1/downloads/nfo', json={}).status_code in (404, 405)
    assert client.get('/api/v1/downloads/progress').status_code in (404, 405)


def test_legacy_scrape_tasks_route_removed(client):
    assert client.get('/api/v1/sources/scrape/tasks').status_code == 404


def test_tasks_title_falls_back_to_comic_title(client):
    """任务无标题（历史任务）时应回退显示已入库漫画的标题。"""
    from app.models import Comic

    comic = Comic(title='已入库的漫画', filename='x.cbz')
    db.session.add(comic)
    db.session.commit()

    t = ScrapeTask(id='sc9', source='ehentai', url='https://e-hentai.org/g/9/abc/',
                   title='', status='done', progress=10, total=10,
                   comic_id=comic.id)
    db.session.add(t)
    db.session.commit()

    resp = client.get('/api/v1/downloads/tasks')
    item = next(i for i in resp.get_json()['data']['items'] if i['id'] == 'sc9')
    assert item['title'] == '已入库的漫画', '应显示漫画标题而非 URL'


def test_tasks_title_own_wins_over_comic(client):
    """任务自带标题时优先于漫画标题。"""
    from app.models import Comic

    comic = Comic(title='漫画名', filename='y.cbz')
    db.session.add(comic)
    db.session.commit()

    t = ScrapeTask(id='sc10', source='nhentai', url='https://nhentai.net/g/2/',
                   title='任务标题', status='failed', comic_id=comic.id)
    db.session.add(t)
    db.session.commit()

    resp = client.get('/api/v1/downloads/tasks')
    item = next(i for i in resp.get_json()['data']['items'] if i['id'] == 'sc10')
    assert item['title'] == '任务标题'
