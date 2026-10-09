"""SettingsService 统一设置读写测试。"""

import pytest

from app.models import Setting
from app.services.settings_service import SettingsService


def test_get_all_masks_secrets(app):
    Setting.set('proxy_pass', 'secret123')
    Setting.set('qb_pass', '')

    data = SettingsService.get_all()

    assert data['proxy_pass'] == '******'
    assert data['qb_pass'] == ''
    assert data['proxy_bypass'] == 'hath.network', '未配置时应返回声明式默认值'


def test_validate_range_and_type(app):
    assert SettingsService.validate({'per_page': '50'}) is None
    assert '每页显示数量' in SettingsService.validate({'per_page': '0'})
    assert '1-100' in SettingsService.validate({'per_page': '101'})
    assert '整数' in SettingsService.validate({'per_page': 'abc'})
    assert '数值' in SettingsService.validate({'upload_interval': 'x'})

    assert SettingsService.validate({'max_cache_size': '-1'}) is not None
    assert SettingsService.validate({'max_cache_size': '0'}) is None


def test_validate_ignores_unknown_and_secret_fields(app):
    assert SettingsService.validate({'unknown_key': 'whatever'}) is None
    assert SettingsService.validate({'proxy_pass': 'anything'}) is None


def test_save_skips_mask_and_unknown(app):
    Setting.set('proxy_pass', 'real-password')

    SettingsService.save({
        'proxy_pass': '******',
        'qb_user': 'bob',
        'unknown_key': 'x',
    })

    assert Setting.get('proxy_pass') == 'real-password', '掩码不应覆盖真实值'
    assert Setting.get('qb_user') == 'bob'
    assert Setting.query.filter_by(key='unknown_key').first() is None


def test_save_normalizes_numeric_types(app):
    SettingsService.save({'per_page': 24, 'upload_interval': '2'})

    assert Setting.get('per_page') == '24'
    assert Setting.get('upload_interval') == '2.0'


def test_load_all_defaults(app):
    vals = SettingsService.load_all()
    assert vals['site_name'] == 'xcomic'
    assert vals['qb_port'] == '8080'
