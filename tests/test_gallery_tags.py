"""画廊详情标签分组测试。"""

import pytest

from app.sources.base_source import BaseSource, GalleryListResult
from app.sources.source_registry import get_registry, _reset_registry


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'
    domains = ('fake.com',)

    def search(self, keyword, page=1, language=None):
        return GalleryListResult()

    def latest(self, page=1, language=None):
        return GalleryListResult()

    def gallery_details(self, url):
        return {
            'title': 'T',
            'tags': 'female:glasses, male:muscle, full color, language:chinese',
        }

    def page_image_urls(self, url):
        return []


@pytest.fixture()
def fake_source(app):
    _reset_registry()
    get_registry().register(FakeSource())
    yield
    _reset_registry()


def _set_mapping(app, text):
    from app.models import Setting
    from app import db
    Setting.set('tag_mapping', text)
    db.session.commit()


def test_gallery_details_grouped_tags(app, fake_source):
    from app.services.source_browse_service import SourceBrowseService
    _set_mapping(app, '')  # 无映射：分组原样返回

    details = SourceBrowseService.gallery_details('https://fake.com/g/1/')
    grouped = details['grouped_tags']
    by_raw = {g['raw_category']: g['raw_tags'] for g in grouped}
    assert by_raw.get('female') == ['glasses']
    assert by_raw.get('male') == ['muscle']
    assert by_raw.get('language') == ['chinese']
    # 无分类标签进 uncat（原始名保留，供点击搜索）
    assert details['uncat_tags'] == ['full color']
    assert details['raw_uncat_tags'] == ['full color']


def test_gallery_details_maps_chinese(app, fake_source):
    from app.services.source_browse_service import SourceBrowseService
    _set_mapping(app, 'female=女性\nglasses=眼镜\nfull color=全彩')

    details = SourceBrowseService.gallery_details('https://fake.com/g/1/')
    grouped = details['grouped_tags']
    cats = {g['category']: g['tags'] for g in grouped}
    assert cats.get('女性') == ['眼镜']
    assert '全彩' in details['uncat_tags']
    # 翻译后原始名仍保留（点击搜索用原始名，中文翻译名源站搜不到）
    assert details['raw_uncat_tags'] == ['full color']
    female = next(g for g in grouped if g['raw_category'] == 'female')
    assert female['raw_tags'] == ['glasses']
    assert female['tags'] == ['眼镜']


def test_gallery_details_empty_tags(app, fake_source, monkeypatch):
    from app.services.source_browse_service import SourceBrowseService

    monkeypatch.setattr(
        FakeSource, 'gallery_details',
        lambda self, url: {'title': 'T'},
    )

    details = SourceBrowseService.gallery_details('https://fake.com/g/1/')
    assert details['grouped_tags'] == []
    assert details['uncat_tags'] == []
    assert details['raw_uncat_tags'] == []
