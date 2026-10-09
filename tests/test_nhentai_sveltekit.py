"""Nhentai SvelteKit 内嵌 JSON 解析测试。"""

import json

from app.scrapers.nhentai_scraper import NhentaiScraper
from app.sources.nhentai_source import NhentaiSource


def _make_sveltekit_gallery_html():
    """构造 SvelteKit 画廊页：完整 JSON 内嵌在 script 的 body 字段中。"""
    gallery = {
        'id': 675754,
        'media_id': '4137717',
        'title': {
            'english': '[Artist] Test Gallery [Chinese]',
            'japanese': '[アーティスト] テスト [中国翻訳]',
            'pretty': 'Test Gallery',
        },
        'cover': {'path': 'galleries/4137717/cover.webp', 'width': 350, 'height': 498},
        'num_pages': 3,
        'upload_date': 1787752882,
        'pages': [
            {'number': 1, 'path': 'galleries/4137717/1.webp', 'width': 1182, 'height': 1680},
            {'number': 2, 'path': 'galleries/4137717/2.jpg', 'width': 1182, 'height': 1680},
            {'number': 3, 'path': 'galleries/4137717/3.png', 'width': 1182, 'height': 1680},
        ],
        'tags': [
            {'type': 'language', 'name': 'translated', 'count': 100},
            {'type': 'language', 'name': 'chinese', 'count': 200},
            {'type': 'category', 'name': 'manga', 'count': 300},
            {'type': 'tag', 'name': 'anal', 'count': 400},
            {'type': 'artist', 'name': 'takami jiro', 'count': 10},
        ],
    }
    body = json.dumps(gallery)
    outer = json.dumps({'status': 200, 'statusText': 'OK', 'body': body})
    return f'''
    <html><body>
    <h1 class="before svelte-x"><span class="pretty">Test</span></h1>
    <script>{outer}</script>
    </body></html>
    '''


def test_scrape_sveltekit_title_and_meta():
    scraper = NhentaiScraper()
    result = scraper.scrape(_make_sveltekit_gallery_html(), source_url='https://nhentai.net/g/675754/')
    assert result['title'] == '[Artist] Test Gallery [Chinese]'
    assert result['title_jp'] == '[アーティスト] テスト [中国翻訳]'
    assert result['page_count'] == 3


def test_scrape_sveltekit_tags():
    scraper = NhentaiScraper()
    result = scraper.scrape(_make_sveltekit_gallery_html(), source_url='https://nhentai.net/g/675754/')
    tags = result['tags'].split(',')
    assert 'language:chinese' in tags
    assert 'language:translated' in tags
    assert 'category:manga' in tags
    assert 'tag:anal' in tags
    assert 'artist:takami jiro' in tags
    assert result['language'] == 'Chinese'
    assert result['author'] == 'takami jiro'
    assert result['category'] == 'Manga'


def test_page_image_urls_from_sveltekit_pages(monkeypatch):
    html = _make_sveltekit_gallery_html()
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    urls = NhentaiSource().page_image_urls('https://nhentai.net/g/675754/')
    assert urls == [
        'https://i.nhentai.net/galleries/4137717/1.webp',
        'https://i.nhentai.net/galleries/4137717/2.jpg',
        'https://i.nhentai.net/galleries/4137717/3.png',
    ]


def test_scrape_sveltekit_cover(monkeypatch):
    """封面优先取 og:image（完整 URL），无 og 时用 JSON cover.path。"""
    html = _make_sveltekit_gallery_html().replace(
        '<html><body>',
        '<html><head><meta property="og:image" content="https://t2.nhentai.net/galleries/4137717/cover.webp.webp"></head><body>',
    )
    scraper = NhentaiScraper()
    result = scraper.scrape(html, source_url='https://nhentai.net/g/675754/')
    assert result['cover_url'] == 'https://t2.nhentai.net/galleries/4137717/cover.webp.webp'

    # 无 og:image 时 fallback 到 JSON cover.path
    scraper2 = NhentaiScraper()
    result2 = scraper2.scrape(_make_sveltekit_gallery_html(), source_url='https://nhentai.net/g/675754/')
    assert result2['cover_url'] == 'https://t.nhentai.net/galleries/4137717/cover.webp'
