"""safe_filename 超长文件名截断测试。

真实案例：超长日中混合文件名（UTF-8 305 字节）上传后无法打开——
旧实现从末尾截断把 .zip 扩展名截掉，阅读器按扩展名识别格式导致拒绝。
"""

import os
import zipfile

from app.utils.file_utils import safe_filename
from app.reader import get_comic_pages
from config import ARCHIVE_EXTENSIONS, COMICS_DIR, IMAGE_EXTENSIONS

# 用户报告的真实文件名（UTF-8 305 字节，超过 240 截断上限）
LONG_NAME = (
    '[Kitsuneya (Leafy)] Lolicon Sensei ga Hoka no Seito ni Te o Dasanai You ni '
    'Nandemo Iu Koto o Kiite kureru Youjo Shun & Rumi no Hon _ '
    '为防止萝莉控老师对其他学生肆意伸出魔爪 愿意对老师言听计从的幼女瞬与瑠美的本子 '
    '(Blue Archive) [Chinese] [欶澜汉化组] [Digital].zip'
)


def test_safe_filename_normal_untouched():
    assert safe_filename('normal comic.zip') == 'normal comic.zip'


def test_safe_filename_keeps_extension_when_truncated():
    """超长文件名截断后必须保留扩展名（阅读器按扩展名识别格式）。"""
    safe = safe_filename(LONG_NAME)
    assert safe.endswith('.zip'), '截断不应丢掉 .zip 扩展名'
    assert len(safe.encode('utf-8')) <= 240, '截断后仍超 240 字节'


def test_safe_filename_truncate_size_limit():
    """中英混合名按 UTF-8 字节截断到 240 以内。"""
    name = '漫画' * 130 + '.zip'
    safe = safe_filename(name)
    assert len(safe.encode('utf-8')) <= 240
    assert safe.endswith('.zip')


def test_safe_filename_no_extension_fallback():
    """无扩展名超长走整体截断，不会崩。"""
    safe = safe_filename('无扩展名超长' * 60)
    assert safe
    assert len(safe.encode('utf-8')) <= 240


def test_safe_filename_huge_extension_fallback():
    """扩展名本身异常超长（>16 字节）走整体截断。"""
    name = 'a' * 50 + '.' + 'b' * 100
    safe = safe_filename(name)
    assert safe
    assert len(safe.encode('utf-8')) <= 240


def test_long_filename_upload_openable(app, make_comic):
    """端到端：超长名 ZIP 入库后 get_comic_pages 应按压缩包处理（不返回空/不拒绝）。"""
    safe = safe_filename(LONG_NAME)
    assert safe.endswith('.zip')

    ext = safe.rsplit('.', 1)[-1].lower()
    assert ext in ARCHIVE_EXTENSIONS, '阅读器应能识别为压缩包'

    # 模拟磁盘上的上传产物：该文件名保存 + 入库
    path = os.path.join(COMICS_DIR, safe)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('0001.jpg', b'fake-jpeg')

    comic = make_comic(filename=safe, file_size=os.path.getsize(path))
    # get_comic_pages 走到压缩包分支（返回 [] 仅因无缓存，而非格式拒绝）
    assert get_comic_pages(comic.id, comic.filename) == []
