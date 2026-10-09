"""E-Hentai 源画廊详情与图片 URL 测试（离线 fixture）。"""

from app.sources import ehentai_source
from app.sources.ehentai_source import EhentaiSource


def _make_gallery_page(gid=100000, token='abcde0', viewer_count=20, page_links=0, start=0):
    links = '\n'.join(
        f'<a href="https://e-hentai.org/s/{token}{(start + i):02x}/{gid}-{start + i + 1}">page {start + i + 1}</a>'
        for i in range(viewer_count)
    )
    pagination = ''
    for p in range(1, page_links + 1):
        pagination += f'<a href="https://e-hentai.org/g/{gid}/{token}/?p={p}">{p + 1}</a>'
    return f'''
    <html><body>
    <h1 id="gn">Test Gallery Title</h1>
    <div id="gdt">{links}</div>
    {pagination}
    </body></html>
    '''


def _make_viewer_page(img_url):
    return f'''
    <html><body>
    <img id="img" src="{img_url}" style="...">
    </body></html>
    '''


def test_collect_viewer_urls_single_page(monkeypatch):
    html = _make_gallery_page(viewer_count=20)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    src = EhentaiSource()
    urls = src._collect_viewer_urls('https://e-hentai.org/g/100000/abcde0/')
    assert len(urls) == 20
    assert urls[0] == 'https://e-hentai.org/s/abcde000/100000-1'
    assert urls[19] == 'https://e-hentai.org/s/abcde013/100000-20'


def test_collect_viewer_urls_multi_page(monkeypatch):
    """含 ?p=1 链接时应请求第二页并合并收集。"""
    page0 = _make_gallery_page(viewer_count=20, page_links=1)
    page1 = _make_gallery_page(viewer_count=5, start=20)  # 第二页是第21-25个查看页
    requested = []

    def fake_urlopen(url, timeout=15):
        requested.append(url)
        return page1 if '?p=1' in url else page0

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    src = EhentaiSource()
    urls = src._collect_viewer_urls('https://e-hentai.org/g/100000/abcde0/')

    assert len(requested) == 2
    assert requested[1] == 'https://e-hentai.org/g/100000/abcde0/?p=1'
    assert len(urls) == 25


def test_page_image_urls_parses_img_tag(monkeypatch):
    gallery_html = _make_gallery_page(viewer_count=3)
    viewer_html = _make_viewer_page('https://x.hath.network/abc/fullimage.jpg')
    sleeps = []

    def fake_urlopen(url, timeout=15):
        return viewer_html if '/s/' in url else gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: sleeps.append(s))

    pages = EhentaiSource().page_image_urls('https://e-hentai.org/g/100000/abcde0/')
    assert [p.url for p in pages] == ['https://x.hath.network/abc/fullimage.jpg'] * 3
    # 第 2、3 个查看页之间应有间隔
    assert sleeps == [1.5, 1.5]


def test_page_image_urls_retries_failed_viewer_then_raises(monkeypatch):
    """查看页请求失败时补试一轮，仍失败应抛错而非静默少页。"""
    import pytest

    gallery_html = _make_gallery_page(viewer_count=2)
    calls = {'n': 0}

    def fake_urlopen(url, timeout=15):
        if '/s/' in url:
            if '100000-2' in url:
                calls['n'] += 1
                raise Exception('timeout')
            return _make_viewer_page('https://x.hath.network/abc/1.jpg')
        return gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: None)

    with pytest.raises(ValueError, match='画廊不完整'):
        EhentaiSource().page_image_urls('https://e-hentai.org/g/100000/abcde0/')
    assert calls['n'] == 2, '失败查看页应恰好补试一轮'


def test_page_image_urls_failed_viewer_recovers_on_retry(monkeypatch):
    """查看页首轮失败、补试成功时应正常返回全部页。"""
    gallery_html = _make_gallery_page(viewer_count=2)
    calls = {'n': 0}

    def fake_urlopen(url, timeout=15):
        if '/s/' in url:
            if '100000-2' in url:
                calls['n'] += 1
                if calls['n'] == 1:
                    raise Exception('timeout')
                return _make_viewer_page('https://x.hath.network/abc/2.jpg')
            return _make_viewer_page('https://x.hath.network/abc/1.jpg')
        return gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: None)

    pages = EhentaiSource().page_image_urls('https://e-hentai.org/g/100000/abcde0/')
    assert [p.url for p in pages] == [
        'https://x.hath.network/abc/1.jpg',
        'https://x.hath.network/abc/2.jpg',
    ]


def test_page_image_urls_viewer_without_img_raises(monkeypatch):
    """查看页无图片（错误页）时补试后抛错，不再静默跳过。"""
    import pytest

    gallery_html = _make_gallery_page(viewer_count=1)

    def fake_urlopen(url, timeout=15):
        if '/s/' in url:
            return '<html><body>error page</body></html>'
        return gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: None)

    with pytest.raises(ValueError, match='画廊不完整'):
        EhentaiSource().page_image_urls('https://e-hentai.org/g/100000/abcde0/')


def test_page_image_urls_quota_image_raises_quota_error(monkeypatch):
    """查看页返回 509 配额占位图时应抛 QuotaError 而非当作正文下载。"""
    import pytest

    from app.sources.base_source import QuotaError

    gallery_html = _make_gallery_page(viewer_count=1)

    def fake_urlopen(url, timeout=15):
        if '/s/' in url:
            return _make_viewer_page('https://ehgt.org/m/509.png')
        return gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr(ehentai_source, '_sleep', lambda s: None)

    with pytest.raises(QuotaError):
        EhentaiSource().page_image_urls('https://e-hentai.org/g/100000/abcde0/')


def test_gallery_details_delegates_to_scraper(monkeypatch):
    calls = {}

    def fake_scrape(self, html_content, source_url=''):
        calls['url'] = source_url
        return {'title': 'Test Gallery Title', 'source_url': source_url}

    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: _make_gallery_page()
    )
    monkeypatch.setattr(
        'app.scrapers.ehentai_scraper.EhentaiScraper.scrape', fake_scrape
    )

    details = EhentaiSource().gallery_details('https://e-hentai.org/g/100000/abcde0/')
    assert details['title'] == 'Test Gallery Title'
    assert calls['url'] == 'https://e-hentai.org/g/100000/abcde0/'


def test_collect_viewer_urls_removed_gallery(monkeypatch):
    """画廊已被移除时应抛出明确的 ValueError 而非静默返回空列表。"""
    removed_html = '''
    <html><head><title>Gallery Not Available - E-Hentai Galleries</title></head>
    <body>This gallery has been <strong>removed</strong>...</body></html>
    '''
    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy',
                        lambda url, timeout=15: removed_html)

    import pytest
    src = EhentaiSource()
    with pytest.raises(ValueError, match='画廊不存在或已被移除'):
        src._collect_viewer_urls('https://e-hentai.org/g/4175370/b717e3566e/')
