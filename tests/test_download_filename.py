"""下载接口文件名截断测试。

超长 title 的漫画下载时，Content-Disposition 中的文件名必须截断
（客户端文件系统单文件名限制：ext4 255 字节 / Windows 默认 260 字符路径），
否则浏览器保存失败。
"""

import os
import zipfile
from urllib.parse import unquote

from app import db
from app.models import Comic
from config import COMICS_DIR

LONG_TITLE = (
    '[Kitsuneya (Leafy)] Lolicon Sensei ga Hoka no Seito ni Te o Dasanai You ni '
    'Nandemo Iu Koto o Kiite kureru Youjo Shun & Rumi no Hon _ '
    '为防止萝莉控老师对其他学生肆意伸出魔爪 愿意对老师言听计从的幼女瞬与瑠美的本子 '
    '(Blue Archive) [Chinese] [欶澜汉化组] [Digital]'
)


def _make_long_title_comic():
    """超长 title 漫画 + 磁盘 ZIP 产物。"""
    path = os.path.join(COMICS_DIR, 'long_dl_test.zip')
    os.makedirs(COMICS_DIR, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('0001.jpg', b'fake-jpeg')
    comic = Comic(title=LONG_TITLE, filename='long_dl_test.zip',
                  file_size=os.path.getsize(path))
    db.session.add(comic)
    db.session.commit()
    return comic


def _download_name(resp):
    """从 Content-Disposition 提取下载名：优先 RFC 5987 filename*，回退 filename=。"""
    cd = resp.headers.get('Content-Disposition', '')
    fallback = None
    for part in cd.split(';'):
        part = part.strip()
        if part.startswith("filename*=UTF-8''"):
            return unquote(part.split("''", 1)[1])
        if part.startswith('filename='):
            fallback = part[len('filename='):].strip('"')
    return fallback


def test_download_truncates_long_filename(app):
    """/comic/<id>/download：超长 title 截断到 240 字节内且保留扩展名。"""
    comic = _make_long_title_comic()
    resp = app.test_client().get(f'/comic/{comic.id}/download')
    assert resp.status_code == 200

    name = _download_name(resp)
    assert name, '应包含 filename* 编码'
    assert len(name.encode('utf-8')) <= 240, f'下载名 {len(name.encode("utf-8"))} 字节未截断'
    assert name.endswith('.zip'), '截断不应丢扩展名'


def test_api_download_truncates_long_filename(app):
    """/api/v1/comics/<id>/download：同上。"""
    comic = _make_long_title_comic()
    resp = app.test_client().get(f'/api/v1/comics/{comic.id}/download')
    assert resp.status_code == 200

    name = _download_name(resp)
    assert name, '应包含 filename* 编码'
    assert len(name.encode('utf-8')) <= 240
    assert name.endswith('.zip')


def test_download_short_title_untouched(app):
    """正常长度 title 下载名应原样（不截断不加料）。"""
    path = os.path.join(COMICS_DIR, 'short_dl_test.zip')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('0001.jpg', b'fake-jpeg')
    comic = Comic(title='普通标题', filename='short_dl_test.zip',
                  file_size=os.path.getsize(path))
    db.session.add(comic)
    db.session.commit()

    resp = app.test_client().get(f'/comic/{comic.id}/download')
    name = _download_name(resp)
    assert name == '普通标题.zip'


def test_download_title_with_illegal_chars(app):
    """title 含非法字符（/ 等）时应清理而不是 500。"""
    path = os.path.join(COMICS_DIR, 'illegal_dl_test.zip')
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('0001.jpg', b'fake-jpeg')
    comic = Comic(title='a/b:c*d?', filename='illegal_dl_test.zip',
                  file_size=os.path.getsize(path))
    db.session.add(comic)
    db.session.commit()

    resp = app.test_client().get(f'/comic/{comic.id}/download')
    assert resp.status_code == 200
    name = _download_name(resp)
    assert '/' not in name and '\\' not in name
    assert name.endswith('.zip')
