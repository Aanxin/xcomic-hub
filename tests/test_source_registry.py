"""源注册表测试。"""

import pytest

from app.sources.base_source import BaseSource, GalleryListResult, SourceRegistry


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'

    def search(self, keyword, page=1, language=None, cursor=None, sort=None):
        return GalleryListResult(items=[], has_next=False)

    def latest(self, page=1, language=None, cursor=None, sort=None):
        return GalleryListResult(items=[], has_next=False)

    def gallery_details(self, url):
        return {}

    def page_image_urls(self, url):
        return []


def test_register_and_create():
    registry = SourceRegistry()
    registry.register(FakeSource())

    source = registry.create_source('fake')
    assert isinstance(source, FakeSource)
    assert source.source_id == 'fake'
    assert source.name == '假源'


def test_create_unknown_source_raises():
    registry = SourceRegistry()
    with pytest.raises(ValueError):
        registry.create_source('nonexistent')


def test_list_sources():
    registry = SourceRegistry()
    registry.register(FakeSource())

    sources = registry.list_sources()
    assert {'id': 'fake', 'name': '假源',
            'categories': [{'id': 'home', 'name': '首页'}]} in sources


def test_default_browse_home_routes_to_latest():
    """默认 browse(home) 应路由到 latest，非 home 大类抛 UnsupportedCategory。"""
    import pytest as _pytest
    from app.sources.base_source import UnsupportedCategory

    source = FakeSource()
    result = source.browse('home', page=2)
    assert result.items == []

    with _pytest.raises(UnsupportedCategory):
        source.browse('toplist')


def test_register_replaces_same_id():
    registry = SourceRegistry()
    registry.register(FakeSource())
    registry.register(FakeSource())

    assert len(registry.list_sources()) == 1


def test_gallery_list_result_defaults():
    result = GalleryListResult(items=[])
    assert result.items == []
    assert result.has_next is False
