"""下载列表页（纯列表，无输入区）测试。"""


def test_download_page_renders(client):
    resp = client.get('/download')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'downloadList' in html, '应包含列表挂载点'


def test_download_page_no_input_tabs(client):
    """三个输入 tab 应全部移除。"""
    resp = client.get('/download')
    html = resp.get_data(as_text=True)
    assert 'url_input' not in html
    assert 'torrent_file_input' not in html
    assert 'nfo_textarea' not in html
    assert 'url-tab' not in html          # tab 按钮已删
    assert 'torrent-tab' not in html
    assert 'nfo-tab' not in html


def test_download_page_polls_unified_api(client):
    """应轮询统一下载列表 API 并用事件委托删除。"""
    resp = client.get('/download')
    html = resp.get_data(as_text=True)
    assert '/api/v1/downloads/tasks' in html
    assert 'data-task-type' in html and 'data-task-id' in html


def test_download_page_type_badge(client):
    """列表应区分 scrape/download 两种任务类型。"""
    resp = client.get('/download')
    html = resp.get_data(as_text=True)
    assert 'scrape' in html
    assert 'download' in html
    assert '图片抓取' in html
    assert '种子下载' in html
