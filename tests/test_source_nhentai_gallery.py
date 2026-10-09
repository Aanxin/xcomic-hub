"""Nhentai 源画廊详情与图片 URL 测试（离线 fixture）。"""

import json

from app.sources.nhentai_source import NhentaiSource


def _make_gallery_html(media_id='9876', pages=None):
    pages = pages or [
        {'t': 'j', 'w': 1200, 'h': 1800},
        {'t': 'j', 'w': 1200, 'h': 1800},
        {'t': 'p', 'w': 1200, 'h': 1800},
    ]
    payload = json.dumps({
        'id': 5,
        'media_id': media_id,
        'title': {'english': 'Test Gallery', 'japanese': '', 'pretty': 'Test Gallery'},
        'images': {'pages': pages},
        'num_pages': len(pages),
        'tags': [],
    })
    escaped = payload.replace('\\', '\\\\').replace('"', '\\"')
    return f'''
    <html><body>
    <h1 class="title"><span class="pretty">Test Gallery</span></h1>
    <section id="tags"></section>
    <script>
      window.gallery_info = JSON.parse("{escaped}");
    </script>
    </body></html>
    '''


def test_page_image_urls_from_gallery_info(monkeypatch):
    html = _make_gallery_html('9876')
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )

    urls = NhentaiSource().page_image_urls('https://nhentai.net/g/5/')
    assert urls == [
        'https://i.nhentai.net/galleries/9876/1.jpg',
        'https://i.nhentai.net/galleries/9876/2.jpg',
        'https://i.nhentai.net/galleries/9876/3.png',
    ]


def test_page_image_urls_empty_when_no_json(monkeypatch):
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy',
        lambda url, timeout=15: '<html><body>blocked</body></html>'
    )
    assert NhentaiSource().page_image_urls('https://nhentai.net/g/5/') == []


def test_gallery_details_delegates_to_scraper(monkeypatch):
    html = _make_gallery_html()
    calls = {}

    def fake_scrape(self, html_content, source_url=''):
        calls['html'] = html_content
        calls['url'] = source_url
        return {'title': 'Test Gallery', 'source_url': source_url}

    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    monkeypatch.setattr(
        'app.scrapers.nhentai_scraper.NhentaiScraper.scrape', fake_scrape
    )

    details = NhentaiSource().gallery_details('https://nhentai.net/g/5/')
    assert details['title'] == 'Test Gallery'
    assert details['source_url'] == 'https://nhentai.net/g/5/'
    assert 'gallery_info' in calls['html']
