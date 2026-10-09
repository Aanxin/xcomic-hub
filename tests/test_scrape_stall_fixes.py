"""EH 下载卡死/不再下载修复的回归测试。

覆盖：
1. fetch_image 总传输预算（慢速滴流节点不再无限拖住单页）
2. urlopen_with_proxy 非 2xx 按瞬时错误重试
3. _update_task 终态守卫（取消/看门狗裁决不被复活，协程协作退出）
4. 调度器看门狗终止无进展任务（解除串行队列阻塞）
5. E-Hentai 解析阶段进度回调（大画廊解析不再零进度假死）
6. 换节点重试消息上报（重试链可见 + updated_at 保新鲜）
7. exhentai 查看页链接收集
"""

import pytest

from app import db
from app.models import ScrapeTask
from app.services.image_scrape_service import ImageScrapeService
from app.services.scheduler_service import SchedulerService
from app.services.task_manager import TaskCancelled
from app.sources import ehentai_source, image_proxy
from app.sources.ehentai_source import EhentaiSource


# ---------- 1. fetch_image 总传输预算 ----------

class StreamResp:
    def __init__(self, chunks, content_type='image/jpeg', status=200):
        self._chunks = chunks
        self.headers = {'Content-Type': content_type}
        self.status_code = status
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size=None):
        yield from self._chunks

    def close(self):
        self.closed = True


def _patch_fetch_response(monkeypatch, resp):
    monkeypatch.setattr(image_proxy, '_fetch_response',
                        lambda url, timeout=15, stream=False: resp)


def test_fetch_image_streams_and_joins_chunks(monkeypatch):
    """正常流式读取：分块返回并拼接为完整内容。"""
    _patch_fetch_response(monkeypatch, StreamResp([b'abc', b'def']))
    content, ctype = image_proxy.fetch_image('https://x.hath.network/1.jpg')
    assert content == b'abcdef'
    assert ctype == 'image/jpeg'


def test_fetch_image_total_budget_cuts_trickle(monkeypatch):
    """慢速滴流：相邻读间隙不超时但总预算耗尽，必须抛 Timeout 切断。"""
    _patch_fetch_response(monkeypatch, StreamResp([b'a' * 1024, b'b' * 1024]))
    import requests
    with pytest.raises(requests.Timeout):
        # 负预算 = 截止时刻已过，首个数据块后即应切断
        image_proxy.fetch_image('https://x.hath.network/1.jpg', max_read_seconds=-1)


# ---------- 2. urlopen_with_proxy 非 2xx 重试 ----------

class PageResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
        self.headers = {}


def test_urlopen_retries_http_error_then_recovers(monkeypatch):
    """非 2xx 应按瞬时错误重试：503 两次后 200 应成功返回。"""
    import app.utils.proxy_utils as pu

    statuses = [503, 503, 200]

    class FakeSession:
        def get(self, url, timeout=15, **kwargs):
            return PageResp('ok', status=statuses.pop(0))

    monkeypatch.setattr(pu, 'get_thread_session', lambda: FakeSession())
    monkeypatch.setattr(pu, 'get_cookie_for_url', lambda url: '')
    monkeypatch.setattr(pu, 'get_proxy_handler', lambda url=None: None)
    monkeypatch.setattr('time.sleep', lambda s: None)

    assert pu.urlopen_with_proxy('https://e-hentai.org/') == 'ok'


def test_urlopen_http_error_exhausted_raises(monkeypatch):
    """非 2xx 持续失败时耗尽重试后抛 HTTPError（而非返回错误页 HTML）。"""
    import requests

    import app.utils.proxy_utils as pu

    class FakeSession:
        def get(self, url, timeout=15, **kwargs):
            return PageResp('rate limited', status=429)

    monkeypatch.setattr(pu, 'get_thread_session', lambda: FakeSession())
    monkeypatch.setattr(pu, 'get_cookie_for_url', lambda url: '')
    monkeypatch.setattr(pu, 'get_proxy_handler', lambda url=None: None)
    monkeypatch.setattr('time.sleep', lambda s: None)

    with pytest.raises(requests.HTTPError):
        pu.urlopen_with_proxy('https://e-hentai.org/')


# ---------- 3. _update_task 终态守卫 / 协作取消 ----------

def _make_scrape_task(status='running', **kwargs):
    defaults = dict(id='st1', source='ehentai',
                    url='https://e-hentai.org/g/1/abc/', status=status)
    defaults.update(kwargs)
    t = ScrapeTask(**defaults)
    db.session.add(t)
    db.session.commit()
    return t


def test_update_task_rejected_after_terminal(app):
    """任务已终态后 _update_task 必须抛 TaskCancelled（不复活已取消任务）。"""
    _make_scrape_task(status='failed', message='已手动取消')
    with pytest.raises(TaskCancelled):
        ImageScrapeService._update_task('st1', progress=1)
    with pytest.raises(TaskCancelled):
        ImageScrapeService._update_task('st1', status='running')


def test_note_skipped_without_task(app):
    """task_id 为空时 _note 应静默跳过（单元直调场景）。"""
    ImageScrapeService._note(None, '不应抛错')


# ---------- 4. 调度器看门狗 ----------

def test_watchdog_fails_stale_running_task(app):
    """running 且超阈值无更新（updated_at 过旧）→ 标记失败并说明可续传。"""
    from datetime import datetime, timedelta

    stale = _make_scrape_task(id='stale', status='running')
    stale.updated_at = datetime.utcnow() - timedelta(seconds=SchedulerService.STALE_SCRAPE_SECONDS + 60)
    fresh = _make_scrape_task(id='fresh', status='running')  # 刚更新
    pending = _make_scrape_task(id='pend', status='pending')
    db.session.commit()

    scheduler = SchedulerService()
    n = scheduler._fail_stale_scrapes()

    assert n == 1
    assert ScrapeTask.query.get('stale').status == 'failed'
    assert '续传' in ScrapeTask.query.get('stale').message
    assert ScrapeTask.query.get('fresh').status == 'running', '活跃任务不得误杀'
    assert ScrapeTask.query.get('pend').status == 'pending', 'pending 由派发逻辑管理'


def test_watchdog_keeps_quiet_when_nothing_stale(app):
    _make_scrape_task(status='running')
    assert SchedulerService()._fail_stale_scrapes() == 0
    assert ScrapeTask.query.get('st1').status == 'running'


# ---------- 5. E-Hentai 解析进度回调 ----------

def _gallery_html(viewer_count=3, domain='e-hentai.org'):
    links = '\n'.join(
        f'<a href="https://{domain}/s/aa{i:02x}/100-{i + 1}">p{i + 1}</a>'
        for i in range(viewer_count)
    )
    return f'<html><body><div id="gdt">{links}</div></body></html>'


def _viewer_html(img_no):
    return (f'<html><body><img id="img" src="https://x.hath.network/{img_no}.jpg">'
            f"<script>function nl(key){{}}</script></body></html>")


def test_ehentai_page_image_urls_reports_progress(monkeypatch):
    """解析阶段应逐页回调进度：收集期 total=0，解析期 (done, N) 递增。"""
    reports = []

    def fake_urlopen(url, timeout=15):
        return _viewer_html(1) if '/s/' in url else _gallery_html()

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: None)

    pages = EhentaiSource().page_image_urls(
        'https://e-hentai.org/g/100/abc/', progress_cb=lambda d, t: reports.append((d, t)))

    assert len(pages) == 3
    collect_reports = [r for r in reports if r[1] == 0]
    resolve_reports = [r for r in reports if r[1] == 3]
    assert collect_reports == [(3, 0)], '收集期应以 total=0 上报已收集数'
    assert resolve_reports == [(0, 3), (1, 3), (2, 3), (3, 3)], \
        f'解析期应从 0/N 逐页递增至 N/N: {resolve_reports}'


def test_ehentai_collects_exhentai_viewer_links(monkeypatch):
    """exhentai 画廊的查看页链接域名同为 exhentai.org，应可收集。"""
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: _gallery_html(domain='exhentai.org'))
    urls = EhentaiSource()._collect_viewer_urls('https://exhentai.org/g/100/abc/')
    assert len(urls) == 3
    assert urls[0] == 'https://exhentai.org/s/aa00/100-1'


# ---------- 6. 换节点重试消息上报 ----------

class _ReloadSource:
    """最小 reload 源桩：reload 返回新 URL。"""

    def reload_image(self, page):
        from app.sources.base_source import PageImage
        return PageImage(url=page.url + '?node=2',
                         viewer_url=page.viewer_url, nl_key='new')


def test_reload_retry_notes_task_message(app, monkeypatch):
    """换节点重试时应更新任务消息（进度条冻结期间用户可见 + 看门狗依据）。"""
    from app.sources.base_source import PageImage

    _make_scrape_task(status='running', progress=0, total=1)
    monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

    calls = {'n': 0}

    def fake_download(url, dest, task_id=None, page_no=None):
        calls['n'] += 1
        if calls['n'] <= 1:
            raise Exception('node dead')

    monkeypatch.setattr(ImageScrapeService, '_download_with_retry', staticmethod(fake_download))

    page = PageImage(url='https://bad.hath.network/1.jpg',
                     viewer_url='https://e-hentai.org/s/k/1-1', nl_key='k')
    ImageScrapeService._download_page_with_reload(
        _ReloadSource(), page, dest_path=None, task_id='st1', page_no=7)

    task = ScrapeTask.query.get('st1')
    assert task.message and '第 7 页' in task.message
    assert '换节点重试 1/3' in task.message


def test_run_scrape_stops_after_external_cancel(app, monkeypatch):
    """下载中任务被外部取消（DB 标记终态）后：协程在下个上报点抛
    TaskCancelled 退出，不得复活任务、不得入库。"""
    from app.sources.base_source import BaseSource, GalleryListResult, PageImage
    from app.sources.source_registry import get_registry, _reset_registry

    class CancelSource(BaseSource):
        source_id = 'cancelsrc'
        name = '取消源'
        domains = ('cancel.com',)

        def search(self, keyword, page=1):
            return GalleryListResult()

        def latest(self, page=1):
            return GalleryListResult()

        def gallery_details(self, url):
            return {'title': 'Cancel Me'}

        def page_image_urls(self, url, progress_cb=None):
            return [PageImage(url=f'https://cdn.cancel.com/{i}.jpg') for i in range(1, 4)]

    _reset_registry()
    get_registry().register(CancelSource())
    try:
        task_id = ImageScrapeService.start_scrape('https://cancel.com/g/1/')
        monkeypatch.setattr('app.services.image_scrape_service._sleep', lambda s: None)

        orig_download = ImageScrapeService._download_image

        def download_then_cancel(url, dest):
            orig_download(url, dest)
            # 第 1 页落盘后模拟外部取消（DELETE API / 看门狗都是直接改 DB 行）
            row = ScrapeTask.query.get(task_id)
            row.status = 'failed'
            row.message = '已手动取消；重新发起同一画廊可续传'
            db.session.commit()

        monkeypatch.setattr(ImageScrapeService, '_download_image', staticmethod(download_then_cancel))

        def fake_fetch(url, **kwargs):
            import io

            from PIL import Image
            buf = io.BytesIO()
            Image.new('RGB', (4, 4)).save(buf, format='JPEG')
            return buf.getvalue(), 'image/jpeg'

        monkeypatch.setattr('app.services.image_scrape_service.fetch_image', fake_fetch)

        with pytest.raises(TaskCancelled):
            ImageScrapeService._run_scrape(task_id, 'https://cancel.com/g/1/')

        task = ScrapeTask.query.get(task_id)
        assert task.status == 'failed', '取消裁决不得被运行中的协程覆盖'
        assert '已手动取消' in task.message
        from app.models import Comic
        assert Comic.query.count() == 0, '取消后不得入库'
    finally:
        _reset_registry()
