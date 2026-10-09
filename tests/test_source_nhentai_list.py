"""Nhentai 源列表/搜索解析测试（SvelteKit SSR HTML fixture）。"""

from app.sources.nhentai_source import NhentaiSource


def _make_list_html(num_galleries=2, with_next=False):
    """构造 SvelteKit SSR 渲染的画廊列表 HTML。"""
    cards = ''
    for i in range(1, num_galleries + 1):
        gid = 670000 + i
        media_id = 4100000 + i
        title = f'Gallery {i} [Digital]'
        cards += f'''
        <div class="gallery lang-gb">
          <a href="/g/{gid}/" class="cover" style="padding: 0 0 141.2% 0">
            <img loading="lazy" alt="{title}" class="lazyload"
                 src="https://t1.nhentai.net/galleries/{media_id}/thumb.webp"
                 onload="this.__e=event" onerror="this.__e=event"/>
            <div class="caption">{title}</div>
          </a>
        </div>
        '''
    next_btn = ''
    if with_next:
        # 2026-10 改版后结构：class="next" + aria-label，href 的 & 转义为 &amp;
        next_btn = ('<a href="/?sort=date&amp;page=2" class="next svelte-1c1j7oq" '
                    'aria-label="Next page"><i class="fa fa-chevron-right"></i></a>')
    else:
        next_btn = ('<a href="/?sort=date&amp;page=1" class="previous svelte-1c1j7oq" '
                    'aria-label="Previous page"><i class="fa fa-chevron-left"></i></a>')
    return f'''
    <html><body>
    <div id="content">
      <div class="container index-container">
        {cards}
      </div>
    </div>
    {next_btn}
    </body></html>
    '''


def test_parse_search_cards(monkeypatch):
    html = _make_list_html(2)
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )

    src = NhentaiSource()
    result = src.search('keyword', page=1)

    assert len(result.items) == 2
    card = result.items[0]
    assert card.url == 'https://nhentai.net/g/670001/'
    assert card.title == 'Gallery 1 [Digital]'
    assert card.cover_url == 'https://t1.nhentai.net/galleries/4100001/thumb.webp'
    assert result.items[1].url == 'https://nhentai.net/g/670002/'


def test_parse_has_next_when_button_exists(monkeypatch):
    from app.sources.nhentai_source import NhentaiSource

    html = _make_list_html(2, with_next=True)
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    result = NhentaiSource().search('kw')
    assert result.has_next is True


def test_search_url_and_latest_url(monkeypatch):
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)

    src = NhentaiSource()
    src.search('big breasts', page=3, sort=None)
    src.latest(page=2)

    assert urls_seen[0] == 'https://nhentai.net/search/?q=big+breasts&page=3'
    assert urls_seen[1] == 'https://nhentai.net/?page=2'


def test_empty_result_no_exception(monkeypatch):
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy',
        lambda url, timeout=15: '<html><body>no results</body></html>'
    )
    result = NhentaiSource().search('nothing')
    assert result.items == []
    assert result.has_next is False


def test_full_page_without_next_button_is_last(monkeypatch):
    """末页判定完全按翻页按钮：无 next 按钮时即使满页（25 卡）也是末页。
    （旧的数量兜底会在末页恰好满页时误报有下一页，已移除。）"""
    html = _make_list_html(25, with_next=False)
    monkeypatch.setattr(
        'app.sources.nhentai_source.urlopen_with_proxy', lambda url, timeout=15: html
    )
    result = NhentaiSource().latest()
    assert len(result.items) == 25
    assert result.has_next is False


def test_latest_with_language_filter(monkeypatch):
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)

    NhentaiSource().latest(page=2, language='chinese')
    assert urls_seen[0] == 'https://nhentai.net/language/chinese/?page=2'


def test_search_with_language_filter(monkeypatch):
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)

    NhentaiSource().search('kw', page=1, language='chinese', sort=None)
    assert urls_seen[0] == 'https://nhentai.net/search/?q=language%3Achinese+kw&page=1'


def test_latest_without_language_keeps_plain_url(monkeypatch):
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)

    NhentaiSource().latest(page=4, language=None)
    assert urls_seen[0] == 'https://nhentai.net/?page=4'


# ---------- 搜索排序（时间范围：今天/星期/一直以来） ----------

def test_search_sort_default_today(monkeypatch):
    """排序=today 必须显式传 popular-today：站点默认排序已是 date（最新上传，
    2026-10 实测），省略参数会显示最新列表而非今日热门。"""
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)
    NhentaiSource().search('kw', page=1, language='chinese', sort='today')
    assert urls_seen[0] == 'https://nhentai.net/search/?q=language%3Achinese+kw&page=1&sort=popular-today'


def test_search_sort_week_all(monkeypatch):
    """排序：星期（popular-week）/ 一直以来（popular）。"""
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)
    src = NhentaiSource()
    src.search('kw', language='chinese', sort='week')
    src.search('kw', language='chinese', sort='all')
    assert urls_seen[0] == 'https://nhentai.net/search/?q=language%3Achinese+kw&page=1&sort=popular-week'
    assert urls_seen[1] == 'https://nhentai.net/search/?q=language%3Achinese+kw&page=1&sort=popular'


def test_search_sort_none_omits_param(monkeypatch):
    """显式 sort=None 时不加 sort 参数（站点自身默认 date 排序）。"""
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)
    NhentaiSource().search('kw', language='chinese', sort=None)
    assert 'sort=' not in urls_seen[0]


def test_latest_sort_passthrough(monkeypatch):
    """latest（语言浏览页）也支持 sort 透传。"""
    urls_seen = []

    def fake_urlopen(url, timeout=15):
        urls_seen.append(url)
        return _make_list_html(0)

    monkeypatch.setattr('app.sources.nhentai_source.urlopen_with_proxy', fake_urlopen)
    src = NhentaiSource()
    src.latest(language='chinese', sort='week')
    src.latest(language='chinese')
    assert urls_seen[0] == 'https://nhentai.net/language/chinese/?page=1&sort=popular-week'
    assert 'sort=' not in urls_seen[1]
