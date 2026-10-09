"""抓取流水线测试（假源 + mock 下载）。"""

import os
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from app import db
from app.models import Comic, ScrapeTask
from app.services.image_scrape_service import ImageScrapeService
from app.sources.base_source import BaseSource, GalleryListResult
from app.sources.source_registry import get_registry, _reset_registry

GALLERY_URL = 'https://fake.com/g/1/'
DETAILS = {
    'title': 'Fake Gallery',
    'title_jp': '偽ギャラリー',
    'author': 'Fake Author',
    'category': 'Manga',
    'tags': 'tag1,tag2',
    'rating': 4.5,
    'source_url': GALLERY_URL,
    'page_count': 3,
}
IMAGE_URLS = [
    'https://i.nhentai.net/galleries/1/1.jpg',
    'https://i.nhentai.net/galleries/1/2.jpg',
    'https://i.nhentai.net/galleries/1/3.jpg',
]


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'
    domains = ('fake.com',)

    def search(self, keyword, page=1):
        return GalleryListResult()

    def latest(self, page=1):
        return GalleryListResult()

    def gallery_details(self, url):
        return dict(DETAILS)

    def page_image_urls(self, url, progress_cb=None):
        return list(IMAGE_URLS)


@pytest.fixture()
def fake_source():
    _reset_registry()
    get_registry().register(FakeSource())
    yield
    _reset_registry()


@pytest.fixture()
def fake_fetch(monkeypatch):
    """离线图片下载 stub：返回真实的最小 JPEG（封面生成需要合法图片）。"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color=(200, 100, 50)).save(buf, format='JPEG')
    jpeg_bytes = buf.getvalue()

    def _fetch(url, **kwargs):
        return (jpeg_bytes, 'image/jpeg')

    monkeypatch.setattr('app.services.image_scrape_service.fetch_image', _fetch)


@pytest.fixture()
def mock_tm():
    tm = MagicMock()
    with patch('app.services.image_scrape_service.task_manager', tm):
        yield tm


def _start_and_run(service, url):
    """start_scrape 创建记录后，同步执行流水线主体。"""
    task_id = service.start_scrape(url)
    ImageScrapeService._run_scrape(task_id, url)
    return task_id


def test_start_scrape_creates_and_enqueues(app, fake_source, mock_tm):
    """创建任务后只入队（pending），由调度器统一派发（全局串行）。"""
    task_id = ImageScrapeService.start_scrape(GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task is not None
    assert task.source == 'fake'
    assert task.url == GALLERY_URL
    assert task.status == 'pending'

    mock_tm.submit.assert_not_called(), '派发权在调度器，提交时不得直接入池'


def test_start_scrape_unknown_url_rejected(app, fake_source, mock_tm):
    with pytest.raises(ValueError):
        ImageScrapeService.start_scrape('https://unknown.com/g/1/')
    mock_tm.submit.assert_not_called()


def _jpeg_bytes():
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new('RGB', (4, 4), color=(200, 100, 50)).save(buf, format='JPEG')
    return buf.getvalue()


def test_download_worker_has_app_context(app, fake_source, mock_tm, monkeypatch):
    """并发下载 worker 线程内必须带 app context（fetch_image 内 Setting 查询需要）。"""
    from app.models import Setting

    jpeg = _jpeg_bytes()

    def _fetch(url, **kwargs):
        Setting.get('nonexistent')  # 无 app context 时抛 RuntimeError
        return (jpeg, 'image/jpeg')

    monkeypatch.setattr('app.services.image_scrape_service.fetch_image', _fetch)
    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done'
    assert 'application context' not in (task.message or '')


def test_download_progress_realtime_per_page(app, fake_source, mock_tm, monkeypatch):
    """并发下载进度应按完成顺序逐页实时上报（不等待前面的页）。"""
    import time

    jpeg = _jpeg_bytes()
    state = {'first_page_done': False}
    timeline = []

    def _fetch(url, **kwargs):
        if url.endswith('/1.jpg'):
            time.sleep(0.3)  # 第 1 页慢
            state['first_page_done'] = True
        return (jpeg, 'image/jpeg')

    real_update = ImageScrapeService._update_task

    def spy_update(task_id, **kw):
        if kw.get('progress'):
            timeline.append((kw['progress'], state['first_page_done']))
        return real_update(task_id, **kw)

    monkeypatch.setattr('app.services.image_scrape_service.fetch_image', _fetch)
    monkeypatch.setattr(ImageScrapeService, '_update_task', staticmethod(spy_update))

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done'
    # 后面的页先下载完时就应上报进度，而非等第 1 页完成
    assert any(progress >= 1 and not first_done for progress, first_done in timeline), \
        f'进度未逐页实时上报: {timeline}'


def test_scrape_success(app, fake_source, mock_tm, fake_fetch):
    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done'
    assert task.comic_id is not None
    assert task.progress == 3
    assert task.total == 3
    assert task.title == 'Fake Gallery', '元数据获取后应写入任务标题'

    comic = Comic.query.get(task.comic_id)
    assert comic is not None
    assert comic.title == 'Fake Gallery'
    assert comic.title_jp == '偽ギャラリー'
    assert comic.author == 'Fake Author'
    assert comic.tags == 'tag1,tag2'
    assert comic.page_count == 3
    assert comic.source_url == GALLERY_URL
    assert comic.filename.endswith('.zip')
    assert comic.cover, '封面应已生成'
    assert comic.nfo_file, 'NFO 应已生成'

    # ZIP 内含 3 张按序命名的图片
    from config import COMICS_DIR
    zip_path = os.path.join(COMICS_DIR, comic.filename)
    assert os.path.exists(zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == ['0001.jpg', '0002.jpg', '0003.jpg']
        assert zf.read('0001.jpg').startswith(b'\xff\xd8'), '应为合法 JPEG 字节'

    # 临时目录已清理
    from config import DOWNLOAD_DIR
    assert not os.path.exists(os.path.join(DOWNLOAD_DIR, 'scrape', task_id))


def test_scrape_dedup_existing_comic(app, fake_source, mock_tm):
    existing = Comic(title='Existing', filename='x.cbz', source_url=GALLERY_URL)
    db.session.add(existing)
    db.session.commit()

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done'
    assert task.comic_id == existing.id
    assert Comic.query.count() == 1, '不应新建漫画'


def test_scrape_retry_success(app, fake_source, mock_tm, fake_fetch, monkeypatch):
    attempts = {'n': 0}
    orig = ImageScrapeService._download_image

    def flaky(url, dest):
        if url.endswith('2.jpg'):
            attempts['n'] += 1
            if attempts['n'] < 3:
                raise Exception('boom')
        orig(url, dest)

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(flaky))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done'
    assert attempts['n'] == 3


def test_scrape_retry_exhausted_fails(app, fake_source, mock_tm, monkeypatch):
    def always_fail(url, dest):
        raise Exception('network down')

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(always_fail))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert 'network down' in task.message
    assert Comic.query.count() == 0

    from config import DOWNLOAD_DIR
    assert not os.path.exists(os.path.join(DOWNLOAD_DIR, 'scrape', task_id))


def test_scrape_timeout_retries_more(app, fake_source, mock_tm, fake_fetch, monkeypatch):
    """timeout 应比普通错误获得更多重试次数（IMAGE_TIMEOUT_RETRY）。"""
    import requests as _requests

    attempts = {'n': 0}
    orig = ImageScrapeService._download_image

    def flaky_timeout(url, dest):
        if url.endswith('2.jpg'):
            attempts['n'] += 1
            # 连续 4 次 timeout（超过普通 IMAGE_RETRY=3），第 5 次成功
            if attempts['n'] <= 4:
                raise _requests.Timeout('read timeout')
        orig(url, dest)

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(flaky_timeout))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done', f'超时应自动重试成功: {task.message}'
    assert attempts['n'] == 5


def test_scrape_timeout_retries_exhausted_fails(app, fake_source, mock_tm, monkeypatch):
    """timeout 超过 IMAGE_TIMEOUT_RETRY 次仍失败时任务应标记失败。"""
    import requests as _requests

    def always_timeout(url, dest):
        raise _requests.Timeout('read timeout')

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(always_timeout))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'


def test_scrape_no_image_urls_fails(app, fake_source, mock_tm, monkeypatch):
    monkeypatch.setattr(FakeSource, 'page_image_urls', lambda self, url, progress_cb=None: [])

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert task.message


def test_recover_interrupted(app):
    ImageScrapeService._recovery_done = False  # 模拟进程刚启动
    t1 = ScrapeTask(id='r1', source='fake', url=GALLERY_URL, status='running')
    t2 = ScrapeTask(id='r2', source='fake', url=GALLERY_URL, status='pending')
    t3 = ScrapeTask(id='r3', source='fake', url=GALLERY_URL, status='done')
    db.session.add_all([t1, t2, t3])
    db.session.commit()

    ImageScrapeService.recover_interrupted()

    assert ScrapeTask.query.get('r1').status == 'failed'
    assert '服务重启中断' in ScrapeTask.query.get('r1').message
    assert ScrapeTask.query.get('r2').status == 'failed'
    assert ScrapeTask.query.get('r3').status == 'done'


# ---------- E-Hentai 坏节点换源（?nl= 重载） ----------

RELOAD_GALLERY_URL = 'https://fakereload.com/g/9/'


class FakeReloadSource(BaseSource):
    """带换节点能力的假源：坏节点的 URL 永远失败，重载后返回好节点。"""
    source_id = 'fakereload'
    name = '换节点假源'
    domains = ('fakereload.com',)
    reload_count = 0

    def search(self, keyword, page=1):
        return GalleryListResult()

    def latest(self, page=1):
        return GalleryListResult()

    def gallery_details(self, url):
        d = dict(DETAILS)
        d['source_url'] = url
        return d

    def page_image_urls(self, url, progress_cb=None):
        from app.sources.base_source import PageImage
        return [PageImage(
            url='https://bad-node.hath.network/h/x/1.webp',
            viewer_url='https://fakereload.com/s/aaa/1-1',
            nl_key='40976-496845',
        )]

    def reload_image(self, page):
        FakeReloadSource.reload_count += 1
        return type(page)(
            url=f'https://good-node.hath.network/h/x/1-{FakeReloadSource.reload_count}.webp',
            viewer_url=page.viewer_url,
            nl_key='new',
        )


@pytest.fixture()
def reload_source():
    _reset_registry()
    get_registry().register(FakeReloadSource())
    FakeReloadSource.reload_count = 0
    yield
    _reset_registry()


def test_scrape_reloads_node_after_download_failure(app, reload_source, mock_tm, fake_fetch, monkeypatch):
    """坏节点下载耗尽重试后，应调用源 reload_image 换节点下载成功。"""
    orig = ImageScrapeService._download_image

    def fail_bad_node(url, dest):
        if 'bad-node' in url:
            raise Exception('SSL EOF from dead node')
        orig(url, dest)

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(fail_bad_node))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), RELOAD_GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'done', f'换节点后应成功: {task.message}'
    assert FakeReloadSource.reload_count >= 1, '应至少触发一次换节点'


def test_scrape_reload_exhausted_fails(app, reload_source, mock_tm, monkeypatch):
    """换节点重载次数耗尽后任务应失败，message 带最后错误。"""

    def always_fail(url, dest):
        raise Exception('all nodes dead')

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(always_fail))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), RELOAD_GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert 'all nodes dead' in task.message
    assert FakeReloadSource.reload_count == 3, '应重载 3 次后放弃'


def test_scrape_no_reload_context_fails_directly(app, fake_source, mock_tm, monkeypatch):
    """无重载上下文（纯 URL 页，如 nhentai）失败时不换节点，直接失败。"""
    def always_fail(url, dest):
        raise Exception('plain url dead')

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(always_fail))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert 'plain url dead' in task.message


# ---------- 失败容错 / 续传 / 配额 ----------

def test_scrape_partial_failure_keeps_files_and_lists_pages(app, fake_source, mock_tm, monkeypatch):
    """部分页失败经补试仍失败：任务失败、message 列缺页与续传提示、临时文件保留。"""
    orig = ImageScrapeService._download_image

    def fail_page2(url, dest):
        if url.endswith('2.jpg'):
            raise Exception('node dead')
        orig(url, dest)

    monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(fail_page2))
    monkeypatch.setattr('app.services.image_scrape_service.fetch_image',
                        lambda url, **kwargs: (_jpeg_bytes(), 'image/jpeg'))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert '第 2 页下载失败' in task.message
    assert '已保留 2/3 页' in task.message
    assert '重新发起同一画廊可续传' in task.message
    assert 'node dead' in task.message
    assert Comic.query.count() == 0, '存在缺页时不得入库'

    from config import DOWNLOAD_DIR
    temp_dir = os.path.join(DOWNLOAD_DIR, 'scrape',
                            __import__('hashlib').md5(GALLERY_URL.encode()).hexdigest()[:16])
    assert os.path.exists(temp_dir), '失败后应保留已下载文件供续传'
    assert sorted(os.listdir(temp_dir)) == ['0001.jpg', '0003.jpg']

    # 清理现场，避免影响其他测试的续传判断
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_scrape_resume_skips_existing_files(app, fake_source, mock_tm, fake_fetch, monkeypatch):
    """重发同一画廊时复用哈希临时目录，跳过已存在的页，仅补下缺失页。"""
    import hashlib

    fetched = []

    def counting_fetch(url, **kwargs):
        fetched.append(url)
        return (_jpeg_bytes(), 'image/jpeg')

    monkeypatch.setattr('app.services.image_scrape_service.fetch_image', counting_fetch)
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    from config import DOWNLOAD_DIR
    temp_dir = os.path.join(
        DOWNLOAD_DIR, 'scrape', hashlib.md5(GALLERY_URL.encode()).hexdigest()[:16])
    os.makedirs(temp_dir, exist_ok=True)
    for name in ('0001.jpg', '0003.jpg'):
        with open(os.path.join(temp_dir, name), 'wb') as f:
            f.write(_jpeg_bytes())

    try:
        task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

        task = ScrapeTask.query.get(task_id)
        assert task.status == 'done', task.message
        assert task.progress == 3 and task.total == 3
        assert len(fetched) == 1, f'应只下载缺失的第 2 页: {fetched}'
        assert fetched[0].endswith('2.jpg')
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_scrape_quota_error_clear_message(app, fake_source, mock_tm, monkeypatch):
    """源抛 QuotaError 时任务失败并显示配额提示，而非底层异常文本。"""
    from app.sources.base_source import QuotaError

    monkeypatch.setattr(FakeSource, 'page_image_urls',
                        lambda self, url, progress_cb=None: (_ for _ in ()).throw(QuotaError('509')))
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    task_id = _start_and_run(ImageScrapeService(), GALLERY_URL)

    task = ScrapeTask.query.get(task_id)
    assert task.status == 'failed'
    assert '带宽配额限制' in task.message


def test_update_task_commits_immediately(app, fake_source, mock_tm):
    """回归：进度更新不得携带脏状态（会开长写事务导致并发写 database is locked）。"""
    from app import db

    task_id = ImageScrapeService.start_scrape(GALLERY_URL)

    ImageScrapeService._update_task(task_id, progress=1, total=3)  # 非"每5页"也必须提交
    assert not db.session.dirty, '进度更新必须立即提交，不能跨请求持有写事务'
    assert ScrapeTask.query.get(task_id).progress == 1
