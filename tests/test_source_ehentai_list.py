"""E-Hentai 源列表/搜索解析测试（离线 fixture）。"""


def _make_list_html(num_galleries=2, with_next=False, next_cursor=None):
    rows = ''
    for i in range(num_galleries):
        cls = 'gtr0' if i % 2 == 0 else 'gtr1'
        gid = 100000 + i
        token = f'abcde{i}'
        rows += f'''
        <tr class="{cls}">
          <td class="glnew">1 hour ago</td>
          <td class="glcat">Manga</td>
          <td class="gl3c glname">
            <a href="https://e-hentai.org/g/{gid}/{token}/">
              <div class="glink">Test Title {i} [Digital]</div>
            </a>
            <div class="glsub">Author{i} &nbsp; | &nbsp; 20{i} pages</div>
          </td>
          <td class="gl2c">
            <div class="glthumb">
              <a href="https://e-hentai.org/g/{gid}/{token}/">
                <img src="https://ehgt.org/ab/c{i}/thumb{i}.webp" alt="Test Title {i}">
              </a>
            </div>
          </td>
        </tr>
        '''
    next_arrow = ''
    if with_next:
        next_arrow = '<td><a href="https://e-hentai.org/?page=2">&gt;</a></td>'
    # 新版游标分页块（searchnav + dnext）
    searchnav = ''
    if next_cursor:
        searchnav = f'''
        <div id="searchnav">
          <a id="dprev" href="https://e-hentai.org/?f_search=x&amp;prev=111">Prev</a>
          <a id="dnext" href="https://e-hentai.org/?f_search=x&amp;next={next_cursor}">Next &gt;</a>
        </div>
        '''
    return f'''
    <html><body>
    <table class="itg">
      <tbody>{rows}</tbody>
    </table>
    {searchnav}
    <table class="ptt">
      <tr>
        <td><a href="https://e-hentai.org/?page=0">1</a></td>
        <td><a href="https://e-hentai.org/?page=1">2</a></td>
        {next_arrow}
      </tr>
    </table>
    </body></html>
    '''


def _make_thumbnail_html(num_galleries=3):
    """Thumbnail 列表模式（账号偏好，无 <tr> 表格，div 布局 + gl1t 卡片块）。"""
    cards = ''
    for i in range(num_galleries):
        gid = 4171330 + i
        token = f'1a4516ca7{i}'
        cards += f'''
        <div class="gl1t">
          <a href="https://e-hentai.org/g/{gid}/{token}/"><div class="gl4t glname glink">Thumb Title {i} [Digital]</div></a>
          <div class="gl3t" style="height:251px;width:250px"><a href="https://e-hentai.org/g/{gid}/{token}/"><img style="height:251px;width:250px" alt="Thumb Title {i}" title="Thumb Title {i}" src="https://ehgt.org/w/02/55{i}/6914{i}-jexjy01f.webp" /></a></div>
          <div class="gl6t"><div class="gt" title="female:x">f:x</div></div>
          <div class="gl5t"><div><div class="cs ct1">Misc</div><div id="posted_{gid}">2026-09-05 14:46</div></div><div><div class="ir"></div><div>{20 + i} pages</div></div></div>
        </div>
        '''
    return f'''
    <html><body>
    <div class="itg gld">{cards}</div>
    <div id="searchnav">
      <a id="dprev" href="https://e-hentai.org/?prev=111">Prev</a>
      <a id="dnext" href="https://e-hentai.org/?next=4171657">Next &gt;</a>
    </div>
    </body></html>
    '''


def test_parse_thumbnail_mode(monkeypatch):
    """Thumbnail 列表模式（账号 Cookie 偏好）：应正确解析卡片而非 0/1 张。"""
    html = _make_thumbnail_html(3)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    from app.sources.ehentai_source import EhentaiSource

    result = EhentaiSource().search('kw')
    assert len(result.items) == 3
    first = result.items[0]
    assert first.title == 'Thumb Title 0 [Digital]', '标题应从 gl4t glname glink 解析而非回退 URL'
    assert first.url == 'https://e-hentai.org/g/4171330/1a4516ca70/'
    assert 'ehgt.org' in first.cover_url
    assert first.page_count == 20
    assert result.next_cursor == '4171657'
    assert result.has_next is True


def test_parse_popular_thumbnail_mode(monkeypatch):
    """热门页（/popular）在 Thumbnail 模式下同样可解析。"""
    html = _make_thumbnail_html(2)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    from app.sources.ehentai_source import EhentaiSource

    result = EhentaiSource().browse('popular')
    assert len(result.items) == 2
    assert result.items[0].title == 'Thumb Title 0 [Digital]'


def test_parse_search_cards(monkeypatch):
    html = _make_list_html(2)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )

    result = __import__('app.sources.ehentai_source', fromlist=['EhentaiSource']).EhentaiSource().search('kw')

    assert len(result.items) == 2
    card = result.items[0]
    assert card.url == 'https://e-hentai.org/g/100000/abcde0/'
    assert card.title == 'Test Title 0 [Digital]'
    assert card.cover_url == 'https://ehgt.org/ab/c0/thumb0.webp'
    assert card.page_count == 200
    assert result.items[1].url == 'https://e-hentai.org/g/100001/abcde1/'


def test_has_next_detection(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource

    no_next = _make_list_html(2, with_next=False)
    with_next = _make_list_html(2, with_next=True)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: with_next
    )
    assert EhentaiSource().search('kw').has_next is True

    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: no_next
    )
    assert EhentaiSource().search('kw').has_next is False


def test_search_url_page_offset(monkeypatch):
    """入参 page=1 应请求 ?page=0（E-H 页码从 0 开始）。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().search('big breasts', page=1)
    EhentaiSource().latest(page=3)

    assert 'f_search=big+breasts&page=0' in urls_seen[0]
    assert urls_seen[1] == 'https://e-hentai.org/?page=2'


def test_empty_result_no_exception(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: '<html><body>No hits found</body></html>'
    )
    result = EhentaiSource().search('nothing')
    assert result.items == []
    assert result.has_next is False


def test_latest_with_language_filter(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().latest(page=1, language='chinese')
    assert urls_seen[0] == 'https://e-hentai.org/?f_search=language%3Achinese&page=0'


def test_search_with_language_filter(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().search('big breasts', page=2, language='chinese')
    assert urls_seen[0] == 'https://e-hentai.org/?f_search=language%3Achinese+big+breasts&page=1'


def test_search_exact_tag_quotes_and_dollar(monkeypatch):
    """exact_tag=True（tag 点击）时搜索词应包引号+$，对齐站点 /tag/ 路由的
    精确匹配语义；默认普通搜索保持裸词（实测 f:wolf 裸拼会前缀命中 wolf girl）。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().search('female:wolf', exact_tag=True)
    assert 'f_search=%22female%3Awolf%24%22' in urls_seen[0]

    EhentaiSource().search('female:wolf')
    assert 'f_search=female%3Awolf' in urls_seen[1]


def test_latest_without_language_keeps_plain_url(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().latest(page=3, language=None)
    assert urls_seen[0] == 'https://e-hentai.org/?page=2'


def test_cursor_pagination_dnext(monkeypatch):
    """新版游标分页：dnext 链接存在 → has_next + next_cursor。"""
    from app.sources.ehentai_source import EhentaiSource

    html = _make_list_html(2, next_cursor='4147836')
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )

    result = EhentaiSource().search('kw')
    assert result.has_next is True
    assert result.next_cursor == '4147836'


def test_no_next_page_without_dnext(monkeypatch):
    """无 dnext 且旧 ptt 无箭头 → 无下一页。"""
    from app.sources.ehentai_source import EhentaiSource

    html = _make_list_html(2, with_next=False, next_cursor=None)
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    result = EhentaiSource().search('kw')
    assert result.has_next is False
    assert result.next_cursor == ''


def test_search_with_cursor_uses_next_param(monkeypatch):
    """传入 cursor 时应请求 next= 游标而非 page= 页码。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().search('kw', page=2, cursor='4147836')
    assert 'next=4147836' in urls_seen[0]
    assert 'page=' not in urls_seen[0]

    EhentaiSource().latest(page=2, language='chinese', cursor='123456')
    assert 'next=123456' in urls_seen[1]
    assert 'page=' not in urls_seen[1]


# ---------- 大类切换（首页/订阅/热门/排行） ----------

def test_categories():
    from app.sources.ehentai_source import EhentaiSource
    cats = EhentaiSource().categories()
    assert [c['id'] for c in cats] == ['home', 'watched', 'popular', 'toplist']
    assert [c['name'] for c in cats] == ['首页', '订阅', '热门', '排行']


def test_browse_home_routes_to_latest(monkeypatch):
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().browse('home', page=2, language='chinese')
    assert urls_seen[0] == 'https://e-hentai.org/?f_search=language%3Achinese&page=1'


def test_browse_watched_url(monkeypatch):
    """订阅：/watched 路径 + f_search 语言筛选 + 数字页码。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().browse('watched', page=1, language='chinese')
    assert urls_seen[0] == 'https://e-hentai.org/watched?f_search=language%3Achinese&page=0'


def test_browse_popular_ignores_language_and_pagination(monkeypatch):
    """热门：站点全局单页列表，不支持 f_search 与分页参数。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    EhentaiSource().browse('popular', page=1, language='chinese')
    assert urls_seen[0] == 'https://e-hentai.org/popular'


def _make_toplist_html(num=2, with_next=False):
    """真实 toplist 结构（2026-08 抓取验证）：itg gltc 表格，行首 <p>#N</p> 排名，
    画廊链接与标题为标准 glname/glink 结构。with_next 控制 dnext 翻页链接。"""
    rows = ''
    for i in range(num):
        gid = 596447 + i
        rows += (
            f'<tr><td><p>#{i + 1}</p><p>158,384,466</p></td>'
            f'<td class="gl1c glcat"><div class="cn cta">Western</div></td>'
            f'<td class="gl2c"><img src="https://ehgt.org/w/{gid}.webp" /></td>'
            f'<td class="gl3c glname"><a href="https://e-hentai.org/g/{gid}/3894f02c20/">'
            f'<div class="glink">Title {i}</div><div>345 pages</div></a></td></tr>'
        )
    nav = '<a id="dnext" href="https://e-hentai.org/toplist.php?tl=15&amp;p=1">&gt;</a>' if with_next else ''
    return f'<html><body><table class="itg gltc"><tbody>{rows}</tbody></table>{nav}</body></html>'


def test_browse_toplist_parses_rank(monkeypatch):
    """排行：解析行首 <p>#N</p> 排名与 glink 标题链接；has_next 按页面分页结构判定。"""
    from app.sources.ehentai_source import EhentaiSource
    monkeypatch.setattr(
        'app.sources.ehentai_source.urlopen_with_proxy',
        lambda url, timeout=15: _make_toplist_html(2)
    )

    result = EhentaiSource().browse('toplist')
    assert len(result.items) == 2
    assert result.items[0].url == 'https://e-hentai.org/g/596447/3894f02c20/'
    assert result.items[0].title == 'Title 0'
    assert result.items[0].rank == 1
    assert result.items[1].rank == 2
    assert result.items[0].page_count == 345
    assert result.items[0].cover_url == f'https://ehgt.org/w/596447.webp'
    assert result.has_next is False
    assert result.next_cursor == ''


def test_browse_toplist_pagination(monkeypatch):
    """排行翻页：page=2 请求 &p=1（实测每页 50 条、排名远超 200），
    页面带 dnext 时 has_next=True。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_toplist_html(2, with_next=True)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    result = EhentaiSource().browse('toplist', page=2, period='day')
    assert urls_seen[0] == 'https://e-hentai.org/toplist.php?tl=15&p=1'
    assert result.has_next is True


# ---------- 排行时间范围 ----------

def test_browse_toplist_period_urls(monkeypatch):
    """排行时间范围映射：all→tl=11 / year→12 / month→13 / day→15；默认 all。"""
    from app.sources.ehentai_source import EhentaiSource
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_toplist_html(0)

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    src = EhentaiSource()
    src.browse('toplist')
    src.browse('toplist', period='year')
    src.browse('toplist', period='month')
    src.browse('toplist', period='day')

    assert urls_seen == [
        'https://e-hentai.org/toplist.php?tl=11&p=0',
        'https://e-hentai.org/toplist.php?tl=12&p=0',
        'https://e-hentai.org/toplist.php?tl=13&p=0',
        'https://e-hentai.org/toplist.php?tl=15&p=0',
    ]


def test_browse_toplist_unknown_period():
    """未知时间范围应抛 UnsupportedCategory。"""
    import pytest
    from app.sources.base_source import UnsupportedCategory
    from app.sources.ehentai_source import EhentaiSource

    with pytest.raises(UnsupportedCategory):
        EhentaiSource().browse('toplist', period='century')


def test_browse_unsupported_category():
    """不支持的大类应抛 UnsupportedCategory。"""
    import pytest
    from app.sources.base_source import UnsupportedCategory
    from app.sources.ehentai_source import EhentaiSource

    with pytest.raises(UnsupportedCategory):
        EhentaiSource().browse('whatever')


# ---------- 坏节点换源（?nl= 重载） ----------

_VIEWER_HTML = (
    '<html><body><div id="i3">'
    '<img id="img" src="https://node1.hath.network/h/x/1.webp" onerror="nl(\'40976-496845\')">'
    '</div></body></html>'
)


def test_page_image_urls_returns_page_image(monkeypatch):
    """page_image_urls 应返回带查看页/nl key 上下文的 PageImage（供坏节点重载）。"""
    from app.sources.base_source import PageImage
    from app.sources.ehentai_source import EhentaiSource

    gallery_html = '<a href="https://e-hentai.org/s/6e087c1526/4171806-1">p1</a>'

    def fake_urlopen(url, timeout=15):
        return _VIEWER_HTML if '/s/' in url else gallery_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)
    monkeypatch.setattr('app.sources.ehentai_source._sleep', lambda s: None)

    pages = EhentaiSource().page_image_urls('https://e-hentai.org/g/4171806/d6f48b324c/')
    assert len(pages) == 1
    p = pages[0]
    assert isinstance(p, PageImage)
    assert p.url == 'https://node1.hath.network/h/x/1.webp'
    assert p.viewer_url == 'https://e-hentai.org/s/6e087c1526/4171806-1'
    assert p.nl_key == '40976-496845'


def test_reload_image_requests_nl_param(monkeypatch):
    """reload_image 应请求 查看页?nl=key 并返回新节点图片的 PageImage。"""
    from app.sources.base_source import PageImage
    from app.sources.ehentai_source import EhentaiSource

    urls_seen = []
    new_html = (
        '<img id="img" src="https://node2.hath.network/h/x/1.webp" onerror="nl(\'999-888\')">'
    )

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return new_html

    monkeypatch.setattr('app.sources.ehentai_source.urlopen_with_proxy', fake_urlopen)

    page = PageImage(
        url='https://node1.hath.network/h/x/1.webp',
        viewer_url='https://e-hentai.org/s/6e087c1526/4171806-2',
        nl_key='40976-496845',
    )
    new_page = EhentaiSource().reload_image(page)

    assert urls_seen == ['https://e-hentai.org/s/6e087c1526/4171806-2?nl=40976-496845']
    assert new_page.url == 'https://node2.hath.network/h/x/1.webp'
    assert new_page.nl_key == '999-888'
    assert new_page.viewer_url == page.viewer_url, '重载后查看页不变，可继续再重载'

