"""浏览页测试。"""


def test_browse_page_renders(client):
    resp = client.get('/browse')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'sourceSelectView' in html, '应包含源选择视图'
    assert 'browseView' in html, '应包含浏览视图'
    assert 'searchInput' in html, '应包含搜索框'
    assert 'galleryGrid' in html, '应包含卡片网格挂载点'
    assert 'languageSelect' in html, '应包含语言选择器'


def test_browse_source_dropdown_removed(client):
    """右上角源下拉框已移除，改为源选择页进入。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'id="sourceSelect"' not in html, '不应再有源下拉框'
    assert 'id="backToSourcesBtn"' in html, '应包含返回源选择按钮'


def test_browse_enter_source_before_load(client):
    """初始不加载画廊列表，点击源卡片后才进入浏览并加载。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'enterBrowse' in html, '应通过 enterBrowse 进入源浏览'
    assert 'sourceGrid' in html, '应包含源卡片网格挂载点'


def test_browse_category_tabs(client):
    """浏览视图应包含大类切换标签栏（首页/订阅/热门/排行）。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'id="categoryTabs"' in html, '应包含大类标签栏'
    assert 'switchCategory' in html, '应有大类切换函数'
    assert 'currentCategory' in html, '应维护当前大类状态'


def test_browse_category_in_latest_request(client):
    """非搜索请求应携带当前大类参数。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'category=${encodeURIComponent(currentCategory)}' in html


def test_browse_watched_empty_hint(client):
    """订阅大类无结果时应提示需配置 Cookie。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert '订阅列表为空' in html


def test_browse_toplist_period_selector(client):
    """排行大类应提供时间范围选择（过去一天在最前且为默认，有史以来在最后）。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'id="periodSelect"' in html, '应包含时间范围选择器'
    labels = ['过去一天', '过去一月', '过去一年', '有史以来']
    for label in labels:
        assert label in html
    # 顺序由近到远，默认过去一天（value="all" 带文本以避开语言下拉的"全部语言"选项）
    assert html.index('value="day"') < html.index('value="month"') < html.index('value="year"') < html.index('value="all">有史以来')
    assert '<option value="day" selected>' in html
    assert "currentPeriod = 'day'" in html, '默认时间范围应为过去一天'


def test_browse_card_in_library_badge(client):
    """卡片应按 in_library 标注在封面右上角显示绿勾。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'c.in_library' in html, '应按 in_library 条件渲染徽章'
    assert 'top-0 end-0' in html, '勾应显示在封面右上角'


def test_browse_sort_selector(client):
    """nhentai 源应提供热度时间范围选择（今天/星期/一直以来），默认今天。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'id="sortSelect"' in html, '应包含排序选择器'
    for label in ('今天', '星期', '一直以来'):
        assert label in html
    assert '<option value="today" selected>' in html, '默认排序应为今天'
    assert "SORTABLE_SOURCES = ['nhentai']" in html, '排序选择器仅对支持的源显示'
    assert 'sort=${encodeURIComponent(currentSort)}' in html, '搜索请求应携带 sort 参数'
    assert 'periodParam}${sortParam}${cursorParam}' in html, '浏览（latest）请求也应携带 sort 参数'


def test_browse_task_panel_removed(client):
    """任务面板已移除，统一到下载页查看。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'taskPanel' not in html
    assert 'scrape/tasks' not in html, '不应再轮询抓取任务列表 API'
    assert '已加入下载列表' in html, '提交抓取后应提示跳转下载页'
    assert '下载任务' not in html, '不应再显示下载任务区块'
    assert '下载列表</a> 页查看' not in html, '不应再显示跳转下载列表的提示'


def test_browse_language_defaults_chinese(client):
    """语言选择器默认应为中文。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'value="chinese" selected>中文' in html
    assert "localStorage.getItem('browse_language') || 'chinese'" in html


def test_browse_uses_event_delegation(client):
    """卡片点击应使用事件委托（data-gallery-url），而非内联 onclick。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'data-gallery-url' in html
    assert "browseOpenGallery(" not in html


def test_browse_modal_singleton(client):
    """Modal 应单例复用，避免 backdrop 叠加导致点击失效。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'getOrCreateInstance' in html
    assert 'new bootstrap.Modal' not in html


def test_browse_renders_grouped_tags(client):
    """详情弹窗应渲染分组标签。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'grouped_tags' in html
    assert 'data-tag-search' in html


def test_browse_tag_search_uses_raw_name(client):
    """点击 tag 搜索应使用原始名（data-tag-search 取 raw_category:raw_tags），
    显示仍为翻译名——中文翻译名传给源站搜索搜不到结果。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    # 分组标签：搜索词 = 原始分类:原始标签，显示 = 翻译名
    assert 'data-tag-search="${esc(g.raw_category)}:${esc(g.raw_tags[i])}"' in html
    assert '${esc(t)}' in html, '显示文案仍用翻译名'
    # 无分类标签：搜索词 = 原始标签
    assert 'd.raw_uncat_tags' in html


def test_browse_tag_click_uses_exact_search(client):
    """tag 点击搜索应置 exactTag=true 并在请求带 &exact_tag=1
    （后端转源站精确 tag 语法，对齐站点 /tag/ 路由）；
    手动回车/清除/切大类/返回源列表须重置为普通关键词搜索。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert 'currentExactTag' in html
    # tag 点击置 true；搜索请求 URL 追加 exact_tag=1
    assert 'currentExactTag = true' in html
    assert "'&exact_tag=1'" in html
    # 手动搜索/清除/切大类/返回源列表均重置 false
    assert html.count('currentExactTag = false') >= 4


def test_browse_language_disabled_for_fixed_lists(client):
    """popular/toplist 浏览列表站点忽略语言参数（实测卡数不变），
    语言下拉应禁用并提示；有关键词（搜索）时恢复可用。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert "['popular', 'toplist'].includes(currentCategory)" in html
    assert 'languageSelect' in html and '.disabled' in html
    assert "!!currentKeyword" in html


def test_browse_sort_disabled_for_all_language(client):
    """nhentai 浏览"全部语言"时走站点首页固定列表（实测 sort 参数被忽略），
    热度排序下拉应禁用；搜索时恢复。"""
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    assert "currentLanguage !== 'all'" in html
    assert 'sortSelect' in html and '.disabled' in html


def test_browse_modal_outside_main(client):
    """弹窗必须是 body 直接子级（modals block），不能嵌在 main 内。

    main 有 z-index:1 层叠上下文（base.html body > * 规则），
    弹窗嵌套在内会被 Bootstrap backdrop(z-index:1050) 盖住，按钮无法点击。
    """
    resp = client.get('/browse')
    html = resp.get_data(as_text=True)
    main_end = html.find('</main>')
    modal_pos = html.find('id="galleryModal"')
    assert main_end != -1
    assert modal_pos != -1
    assert modal_pos > main_end, '弹窗应在 </main> 之后（modals block），而非 main 内部'


def test_nav_contains_browse_entry(client):
    resp = client.get('/')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '/browse' in html, '导航应包含浏览入口'
