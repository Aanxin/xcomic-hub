"""图片代理域名白名单测试（SSRF 防护）。"""

import pytest

from app.sources.image_proxy import is_allowed_image_url


@pytest.mark.parametrize('url', [
    # Nhentai 系
    'https://i.nhentai.net/galleries/123/1.jpg',
    'https://i5.nhentai.net/galleries/123/1.jpg',
    'https://t.nhentai.net/galleries/123/cover.jpg',
    # E-Hentai 系
    'https://e-hentai.org/g/123/abc/',
    'https://exhentai.org/g/123/abc/',
    'https://ehgt.org/ab/cd/thumb.webp',
    'https://ul.ehgt.org/ab/cd/thumb.webp',
    'https://abc.hath.network/xyz/fullimage.jpg',
    'http://i.nhentai.net/galleries/123/1.jpg',
])
def test_allowed_urls(url):
    assert is_allowed_image_url(url) is True


@pytest.mark.parametrize('url', [
    # 完全无关域名
    'https://evil.com/1.jpg',
    'http://127.0.0.1/img.jpg',
    'http://169.254.169.254/latest/meta-data',
    # 伪装子域 / 后缀欺骗
    'https://e-hentai.org.evil.com/1.jpg',
    'https://fake-hentai.org/1.jpg',
    'https://evilehgt.org/a.jpg',
    'https://evil.hath.network.attacker.com/1.jpg',
    # userinfo 混淆
    'https://e-hentai.org@evil.com/1.jpg',
    'https://evil.com#@e-hentai.org/1.jpg',
    # scheme 混用
    'ftp://i.nhentai.net/1.jpg',
    'file:///etc/passwd',
    'javascript:alert(1)',
    # 非法输入
    '',
    'not a url',
    'https://',  # 无 host
])
def test_denied_urls(url):
    assert is_allowed_image_url(url) is False
