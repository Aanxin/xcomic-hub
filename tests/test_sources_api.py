"""浏览 API 蓝图测试（假源注入，不打网络）。"""

import pytest

from app.sources.base_source import BaseSource, GalleryCard, GalleryListResult
from app.sources.source_registry import get_registry, _reset_registry


class FakeSource(BaseSource):
    source_id = 'fake'
    name = '假源'
    domains = ('fake.com',)

    def __init__(self):
        self.calls = []

    def search(self, keyword, page=1, language=None, cursor=None, sort=None, exact_tag=False):
        self.calls.append(('search', keyword, page, language, cursor, sort, exact_tag))
        return GalleryListResult(
            items=[GalleryCard(url=f'https://fake.com/g/{keyword}/', title=f'结果:{keyword}')],
            has_next=page < 3,
        )

    def latest(self, page=1, language=None, cursor=None, sort=None):
        self.calls.append(('latest', page, language, cursor, sort))
        return GalleryListResult(
            items=[GalleryCard(url=f'https://fake.com/g/{page}/', title=f'最新{page}')],
            has_next=page < 3,
        )

    def gallery_details(self, url):
        return {'title': 'Fake Gallery', 'source_url': url, 'page_count': 10}

    def page_image_urls(self, url):
        return ['https://i.nhentai.net/galleries/1/1.jpg']


@pytest.fixture()
def fake_source(app):
    _reset_registry()
    fs = FakeSource()
    get_registry().register(fs)
    yield fs
    _reset_registry()


def test_list_sources(client, fake_source):
    resp = client.get('/api/v1/sources')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['code'] == 0
    assert {'id': 'fake', 'name': '假源',
            'categories': [{'id': 'home', 'name': '首页'}]} in data['data']


class FakeCategorizedSource(FakeSource):
    """支持多大类（home/popular）的假源，用于大类透传测试。"""
    source_id = 'fakecat'
    name = '分类假源'

    def categories(self):
        return [{'id': 'home', 'name': '首页'}, {'id': 'popular', 'name': '热门'}]

    def browse(self, category='home', page=1, language=None, cursor=None, period='all', sort=None):
        self.calls.append(('browse', category, page, language, cursor, period))
        return GalleryListResult(
            items=[GalleryCard(url=f'https://fake.com/{category}/{page}/', title=f'大类{category}')],
            has_next=False,
        )


@pytest.fixture()
def categorized_source(app):
    _reset_registry()
    fs = FakeCategorizedSource()
    get_registry().register(fs)
    yield fs
    _reset_registry()


def test_latest_category_default_home(client, fake_source):
    """不传 category 时默认 home，经 browse 路由到 latest。"""
    resp = client.get('/api/v1/sources/fake/latest')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 1, 'chinese', None, None)]


def test_latest_sort_passthrough(client, fake_source):
    """sort 查询参数应透传给源的 latest()（热度时间范围，浏览链路）。"""
    resp = client.get('/api/v1/sources/fake/latest?sort=week')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 1, 'chinese', None, 'week')]


def test_latest_category_passthrough(client, categorized_source):
    """category 查询参数应透传给源的 browse()。"""
    resp = client.get('/api/v1/sources/fakecat/latest?category=popular&page=2')
    assert resp.status_code == 200
    assert categorized_source.calls == [('browse', 'popular', 2, 'chinese', None, 'all')]
    assert resp.get_json()['data']['items'][0]['title'] == '大类popular'


def test_latest_period_passthrough(client, categorized_source):
    """period 查询参数应透传给源的 browse()（排行榜时间范围）。"""
    resp = client.get('/api/v1/sources/fakecat/latest?category=popular&period=month')
    assert resp.status_code == 200
    assert categorized_source.calls == [('browse', 'popular', 1, 'chinese', None, 'month')]


def test_latest_unsupported_category(client, fake_source):
    """源不支持的大类应返回 400。"""
    resp = client.get('/api/v1/sources/fake/latest?category=toplist')
    assert resp.status_code == 400
    assert '大类' in resp.get_json()['message']


def test_latest(client, fake_source):
    resp = client.get('/api/v1/sources/fake/latest?page=2')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['items'][0]['title'] == '最新2'
    assert data['has_next'] is True


def test_latest_defaults_to_chinese(client, fake_source):
    """默认应传递 language=chinese 筛选。"""
    resp = client.get('/api/v1/sources/fake/latest')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 1, 'chinese', None, None)]


def test_latest_language_all_disables_filter(client, fake_source):
    resp = client.get('/api/v1/sources/fake/latest?language=all')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 1, None, None, None)]


def test_latest_explicit_language(client, fake_source):
    resp = client.get('/api/v1/sources/fake/latest?language=japanese')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 1, 'japanese', None, None)]


def test_latest_cursor_passthrough(client, fake_source):
    """cursor 查询参数应透传给源（E-Hentai 游标分页）。"""
    resp = client.get('/api/v1/sources/fake/latest?page=2&cursor=4147836')
    assert resp.status_code == 200
    assert fake_source.calls == [('latest', 2, 'chinese', '4147836', None)]


def test_latest_returns_next_cursor_default_empty(client, fake_source):
    """响应应包含 next_cursor 字段，默认为空串（数字页码分页源）。"""
    resp = client.get('/api/v1/sources/fake/latest')
    assert resp.status_code == 200
    assert resp.get_json()['data']['next_cursor'] == ''


def test_search(client, fake_source):
    resp = client.get('/api/v1/sources/fake/search?keyword=abc&page=1')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['items'][0]['url'] == 'https://fake.com/g/abc/'
    assert data['has_next'] is True


# ---------- 库内标注（in_library） ----------

def test_latest_annotates_in_library(client, fake_source, app):
    """列表项应标注 in_library：库中已有 source_url 匹配的漫画为 True。"""
    from app import db
    from app.models import Comic

    db.session.add(Comic(title='已入库', author='', file_size=0, rating=0.0,
                         source_url='https://fake.com/g/1/'))
    db.session.commit()

    resp = client.get('/api/v1/sources/fake/latest?page=1')
    assert resp.status_code == 200
    item = resp.get_json()['data']['items'][0]
    assert item['url'] == 'https://fake.com/g/1/'
    assert item['in_library'] is True


def test_latest_in_library_false_when_absent(client, fake_source, app):
    """库中无匹配漫画时 in_library 为 False。"""
    resp = client.get('/api/v1/sources/fake/latest?page=1')
    assert resp.status_code == 200
    assert resp.get_json()['data']['items'][0]['in_library'] is False


def test_search_annotates_in_library(client, fake_source, app):
    """搜索结果同样标注 in_library。"""
    from app import db
    from app.models import Comic

    db.session.add(Comic(title='已入库', author='', file_size=0, rating=0.0,
                         source_url='https://fake.com/g/abc/'))
    db.session.commit()

    resp = client.get('/api/v1/sources/fake/search?keyword=abc')
    assert resp.status_code == 200
    assert resp.get_json()['data']['items'][0]['in_library'] is True


def test_search_defaults_to_chinese(client, fake_source):
    resp = client.get('/api/v1/sources/fake/search?keyword=abc')
    assert resp.status_code == 200
    assert fake_source.calls == [('search', 'abc', 1, 'chinese', None, None, False)]


def test_search_language_all_disables_filter(client, fake_source):
    resp = client.get('/api/v1/sources/fake/search?keyword=abc&language=all')
    assert resp.status_code == 200
    assert fake_source.calls == [('search', 'abc', 1, None, None, None, False)]


def test_search_cursor_passthrough(client, fake_source):
    resp = client.get('/api/v1/sources/fake/search?keyword=abc&page=3&cursor=42')
    assert resp.status_code == 200
    assert fake_source.calls == [('search', 'abc', 3, 'chinese', '42', None, False)]


def test_search_sort_passthrough(client, fake_source):
    """sort 查询参数应透传给源的 search()（热度时间范围）。"""
    resp = client.get('/api/v1/sources/fake/search?keyword=abc&sort=week')
    assert resp.status_code == 200
    assert fake_source.calls == [('search', 'abc', 1, 'chinese', None, 'week', False)]


def test_search_exact_tag_passthrough(client, fake_source):
    """exact_tag=1（tag 点击搜索）应透传给源，缺省为 False（普通关键词）。"""
    resp = client.get('/api/v1/sources/fake/search?keyword=female:glasses&exact_tag=1')
    assert resp.status_code == 200
    assert fake_source.calls[-1] == ('search', 'female:glasses', 1, 'chinese', None, None, True)

    resp = client.get('/api/v1/sources/fake/search?keyword=female:glasses')
    assert resp.status_code == 200
    assert fake_source.calls[-1][-1] is False


def test_search_missing_keyword(client, fake_source):
    resp = client.get('/api/v1/sources/fake/search')
    assert resp.status_code == 400


def test_latest_unknown_source(client, fake_source):
    resp = client.get('/api/v1/sources/nonexistent/latest')
    assert resp.status_code == 404


def test_gallery_details(client, fake_source):
    resp = client.get('/api/v1/sources/gallery?url=https://fake.com/g/1/')
    assert resp.status_code == 200
    data = resp.get_json()['data']
    assert data['title'] == 'Fake Gallery'
    assert data['page_count'] == 10


def test_gallery_details_missing_url(client, fake_source):
    resp = client.get('/api/v1/sources/gallery')
    assert resp.status_code == 400
