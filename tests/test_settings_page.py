"""设置页面（web 表单）回归测试。

背景：SettingsService 重构后 render_template(**vals) 与显式 kwarg
重复导致 500——页面渲染此前没有测试覆盖，这里锁住 GET/POST 行为。
"""

from app.models import Setting


def test_settings_page_renders(client):
    resp = client.get('/settings')
    assert resp.status_code == 200
    # 表单关键字段存在（含后加的 proxy_bypass）
    assert b'proxy_bypass' in resp.data
    assert b'proxy_host' in resp.data


def test_settings_post_saves_values(client, app):
    form = {
        'site_name': '测试站名',
        'per_page': '24',
        'max_content_length': '2048',
        'chunk_size': '5',
        'upload_interval': '2',
        'auto_cover': '1',
        'cover_width': '300',
        'cover_quality': '85',
        'proxy_enabled': '0',
        'proxy_bypass': 'hath.network,foo.org',
        'max_cache_size': '10',
    }
    resp = client.post('/settings', data=form, follow_redirects=True)

    assert resp.status_code == 200
    assert Setting.get('site_name') == '测试站名'
    assert Setting.get('per_page') == '24'
    assert Setting.get('upload_interval') == '2.0'
    assert Setting.get('proxy_bypass') == 'hath.network,foo.org'
    assert Setting.get('max_cache_size') == '10'


def test_settings_post_invalid_value_rejected(client, app):
    resp = client.post('/settings', data={'per_page': '0', 'site_name': 'x'},
                       follow_redirects=True)

    assert resp.status_code == 200  # flash 错误后重渲染
    assert Setting.get('per_page', '12') == '12', '非法值不应被保存'
