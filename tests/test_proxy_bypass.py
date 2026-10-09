"""代理域名旁路测试：命中后缀直连，未命中走代理。"""

import pytest

from app.utils.proxy_utils import get_proxy_handler


@pytest.fixture
def proxy_settings(monkeypatch):
    """代理开启 + 默认旁路列表（hath.network），可按需覆盖字段。"""
    from app.models import Setting

    values = {
        'proxy_enabled': '1',
        'proxy_type': 'http',
        'proxy_host': '192.168.31.51',
        'proxy_port': '7890',
        'proxy_user': '',
        'proxy_pass': '',
        'proxy_bypass': 'hath.network',
    }

    def fake_get(key, default=''):
        return values.get(key, default)

    monkeypatch.setattr(Setting, 'get', fake_get)
    return values


def test_bypass_hath_network_subdomain(proxy_settings):
    """H@H 节点（任意子域+非标准端口）命中默认旁路，直连。"""
    assert get_proxy_handler('https://jpsddrp.buytigtpqwrm.hath.network:21443/h/x/006.webp') is None


def test_bypass_hath_network_bare_host(proxy_settings):
    assert get_proxy_handler('https://hath.network/a.jpg') is None


def test_main_site_still_proxied(proxy_settings):
    """主站不在旁路列表，仍走代理。"""
    handler = get_proxy_handler('https://e-hentai.org/g/4175370/b717e3566e/')
    assert handler == {'http': 'http://192.168.31.51:7890', 'https': 'http://192.168.31.51:7890'}


def test_bypass_custom_list(proxy_settings):
    proxy_settings['proxy_bypass'] = 'foo.com, bar.org'
    assert get_proxy_handler('https://cdn.foo.com/a.jpg') is None
    assert get_proxy_handler('https://x.bar.org/a.jpg') is None
    assert get_proxy_handler('https://e-hentai.org/') is not None


def test_bypass_empty_disables(proxy_settings):
    """旁路列表留空 = 全部走代理。"""
    proxy_settings['proxy_bypass'] = ''
    assert get_proxy_handler('https://abc.hath.network:21443/x.jpg') is not None


def test_bypass_no_url_keeps_old_behavior(proxy_settings):
    """不传 url 时保持旧行为（一律走代理），兼容既有调用。"""
    assert get_proxy_handler() is not None


def test_bypass_suffix_not_spoofable(proxy_settings):
    """后缀匹配不能被前缀伪装域名绕过。"""
    assert get_proxy_handler('https://hath.network.evil.com/a.jpg') is not None
    assert get_proxy_handler('https://fakehath.network/a.jpg') is not None


def test_proxy_disabled_always_direct(proxy_settings, monkeypatch):
    from app.models import Setting
    monkeypatch.setattr(Setting, 'get', lambda key, default='': '0' if key == 'proxy_enabled' else default)
    assert get_proxy_handler('https://e-hentai.org/') is None
    assert get_proxy_handler('https://abc.hath.network/x.jpg') is None


def test_bypass_default_when_setting_absent(monkeypatch):
    """未配置 proxy_bypass 时使用默认 hath.network。"""
    from app.models import Setting
    monkeypatch.setattr(Setting, 'get', lambda key, default='': {
        'proxy_enabled': '1', 'proxy_host': '127.0.0.1', 'proxy_port': '7890',
    }.get(key, default))
    assert get_proxy_handler('https://abc.hath.network/x.jpg') is None
    assert get_proxy_handler('https://e-hentai.org/') is not None
