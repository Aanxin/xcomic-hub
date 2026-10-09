"""图片代理路由测试。"""

import pytest

from app.sources import image_proxy


class FakeResp:
    def __init__(self, content=b'imgbytes', content_type='image/jpeg', status=200):
        self.content = content
        self.headers = {'Content-Type': content_type}
        self.status_code = status
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f'{self.status_code}')

    def iter_content(self, chunk_size=None):
        yield self.content

    def close(self):
        self.closed = True


@pytest.fixture()
def patch_fetch(monkeypatch):
    def _patch(resp=None, exc=None):
        if exc:
            monkeypatch.setattr(image_proxy, '_fetch_response',
                                lambda url, timeout=15, stream=False: (_ for _ in ()).throw(exc))
        else:
            monkeypatch.setattr(image_proxy, '_fetch_response',
                                lambda url, timeout=15, stream=False: resp or FakeResp())
    return _patch


def test_image_proxy_rejects_non_whitelist(client):
    resp = client.get('/api/v1/sources/image?url=https://evil.com/1.jpg')
    assert resp.status_code == 400


def test_image_proxy_rejects_missing_url(client):
    resp = client.get('/api/v1/sources/image')
    assert resp.status_code == 400


def test_image_proxy_streams_image(client, patch_fetch):
    patch_fetch(FakeResp(content=b'abcdef', content_type='image/png'))
    resp = client.get('/api/v1/sources/image?url=https://i.nhentai.net/galleries/1/1.jpg')

    assert resp.status_code == 200
    assert resp.data == b'abcdef'
    assert resp.headers['Content-Type'].startswith('image/png')
    assert resp.headers['Cache-Control'] == 'public, max-age=86400'


def test_image_proxy_upstream_404(client, patch_fetch):
    import requests
    patch_fetch(exc=requests.HTTPError('404'))
    resp = client.get('/api/v1/sources/image?url=https://i.nhentai.net/galleries/1/1.jpg')
    assert resp.status_code == 502


def test_image_proxy_upstream_timeout(client, patch_fetch):
    import requests
    patch_fetch(exc=requests.Timeout('timeout'))
    resp = client.get('/api/v1/sources/image?url=https://i.nhentai.net/galleries/1/1.jpg')
    assert resp.status_code == 504


def test_fetch_image_adds_referer(monkeypatch):
    """E-H 图片应带 e-hentai.org Referer，nhentai 带 nhentai.net。"""
    import requests as requests_mod

    captured = {}

    class FakeSession:
        headers = {}
        cookies = requests_mod.cookies.RequestsCookieJar()
        proxies = None

        def mount(self, prefix, adapter):
            pass

        def get(self, url, timeout=15, **kwargs):
            captured['url'] = url
            captured['referer'] = (kwargs.get('headers') or {}).get('Referer')
            return FakeResp()

    monkeypatch.setattr(requests_mod, 'Session', lambda: FakeSession())
    monkeypatch.setattr(image_proxy, 'get_cookie_for_url', lambda url: '')
    monkeypatch.setattr(image_proxy, 'get_proxy_handler', lambda url=None: None)

    content, ctype = image_proxy.fetch_image('https://abc.hath.network/x/1.jpg')
    assert content == b'imgbytes'
    assert captured['referer'] == 'https://e-hentai.org/'

    image_proxy.fetch_image('https://i.nhentai.net/galleries/1/1.jpg')
    assert captured['referer'] == 'https://nhentai.net/'


def test_proxy_image_disk_cache(client, monkeypatch):
    """同一图片第二次请求应命中磁盘缓存，不再回源。"""
    calls = {'n': 0}

    def counting_fetch(url, timeout=15):
        calls['n'] += 1
        return (b'imgbytes', 'image/jpeg')

    monkeypatch.setattr('app.api.sources.fetch_image', counting_fetch)

    url = 'https://i.nhentai.net/galleries/999/cache-test.jpg'
    r1 = client.get(f'/api/v1/sources/image?url={url}')
    r2 = client.get(f'/api/v1/sources/image?url={url}')

    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.data == b'imgbytes'
    assert r2.mimetype == 'image/jpeg'
    assert calls['n'] == 1, f'第二次请求不应回源（回源 {calls["n"]} 次）'
