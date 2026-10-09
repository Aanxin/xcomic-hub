"""解压缓存完整性与并发安全测试。

回归背景：解压曾直接把图片逐个写进最终缓存目录，进行中/崩溃残留的
部分文件被 get_comic_pages 当作完整缓存返回 → 客户端轮询拿到半成品
页列表（页数不够）；且 start_extraction_async 缓存命中分支会取消正在
运行的任务并清空最终目录 → 正在阅读的页全部 404（图片加载不出来）。

修复：staging 暂存目录 + .ready 标记原子晋升 + 跨进程解压锁 +
LRU 目录 mtime 保护。
"""

import os
import shutil
import time
import zipfile

import pytest

from app.models import Setting
from app.reader import (
    READY_MARKER,
    _check_and_auto_clean_cache,
    _final_dir,
    _get_cached_pages,
    _lock_path,
    _new_staging_dir,
    _release_extract_lock,
    _try_acquire_extract_lock,
    cleanup_pages,
    get_comic_pages,
    get_page_dir,
    start_extraction_async,
)
from app.services.task_manager import task_manager, TaskStatus
from config import COMICS_DIR, PAGES_DIR


def _make_zip_comic(make_comic, name, num_images=3):
    path = os.path.join(COMICS_DIR, name)
    os.makedirs(COMICS_DIR, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as zf:
        for i in range(num_images):
            zf.writestr(f'{i + 1:04d}.jpg', b'fake-jpeg-bytes')
    return make_comic(filename=name, file_size=os.path.getsize(path))


@pytest.fixture(autouse=True)
def _wipe_pages_dir(app):
    """PAGES_DIR 是会话级临时目录而 comic id 每测重置，先清空避免用例间串扰。"""
    for name in os.listdir(PAGES_DIR):
        p = os.path.join(PAGES_DIR, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.remove(p)
            except OSError:
                pass
    yield


def _wait_terminal(task_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = task_manager.get_task(task_id)
        if info and info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return info
        time.sleep(0.02)
    return task_manager.get_task(task_id)


def test_partial_final_dir_without_marker_is_not_cache(app, make_comic):
    """无 .ready 标记的目录（解压中/历史半成品）不得被当作完整缓存。"""
    comic = _make_zip_comic(make_comic, 'stage1.zip')
    final = _final_dir(comic.id)
    os.makedirs(final, exist_ok=True)
    with open(os.path.join(final, '0001.jpg'), 'wb') as f:
        f.write(b'partial')

    assert _get_cached_pages(comic.id) is None
    assert get_comic_pages(comic.id, comic.filename) == []


def test_extraction_writes_marker_and_completes(app, make_comic):
    comic = _make_zip_comic(make_comic, 'stage2.zip', num_images=4)
    result = start_extraction_async(comic.id, comic.filename)
    assert result['status'] in ('extracting', 'ready')
    info = _wait_terminal(f'extract:{comic.id}')
    assert info.status == TaskStatus.COMPLETED, info.error

    final = _final_dir(comic.id)
    assert os.path.exists(os.path.join(final, READY_MARKER))
    pages = _get_cached_pages(comic.id)
    assert pages and len(pages) == 4
    # 无暂存残留
    leftovers = [n for n in os.listdir(PAGES_DIR) if n.startswith(f'{comic.id}.tmp-')]
    assert leftovers == []
    # 锁已释放
    assert not os.path.exists(_lock_path(comic.id))


def test_legacy_partial_dir_replaced_by_extraction(app, make_comic):
    """旧版残留的无标记半成品目录应被重新解压的结果完整替换。"""
    comic = _make_zip_comic(make_comic, 'stage3.zip', num_images=5)
    final = _final_dir(comic.id)
    os.makedirs(final, exist_ok=True)
    with open(os.path.join(final, '0001.jpg'), 'wb') as f:
        f.write(b'legacy-partial')

    start_extraction_async(comic.id, comic.filename)
    info = _wait_terminal(f'extract:{comic.id}')
    assert info.status == TaskStatus.COMPLETED, info.error

    pages = _get_cached_pages(comic.id)
    assert pages and len(pages) == 5


def test_running_task_not_cancelled_by_second_request(app, make_comic):
    """任务运行期间的第二次请求不得取消任务（回归：曾取消并清空最终目录）。"""
    comic = _make_zip_comic(make_comic, 'stage4.zip', num_images=50)

    first = start_extraction_async(comic.id, comic.filename)
    assert first['status'] in ('extracting', 'ready')

    second = start_extraction_async(comic.id, comic.filename)
    assert second['status'] in ('extracting', 'ready')

    info = _wait_terminal(f'extract:{comic.id}')
    assert info.status == TaskStatus.COMPLETED, info.error
    pages = _get_cached_pages(comic.id)
    assert pages and len(pages) == 50


def test_extract_lock_mutual_exclusion(app, make_comic):
    comic = _make_zip_comic(make_comic, 'stage5.zip')
    assert _try_acquire_extract_lock(comic.id) is True
    # 未释放前二次获取失败（模拟其他 worker）
    assert _try_acquire_extract_lock(comic.id) is False
    _release_extract_lock(comic.id)
    assert _try_acquire_extract_lock(comic.id) is True
    _release_extract_lock(comic.id)


def test_extract_lock_stale_reset(app, make_comic):
    """超龄锁视为崩溃残留，应被重置后重新获取。"""
    comic = _make_zip_comic(make_comic, 'stage6.zip')
    lock = _lock_path(comic.id)
    with open(lock, 'w') as f:
        f.write('')
    stale = time.time() - 4000
    os.utime(lock, (stale, stale))
    assert _try_acquire_extract_lock(comic.id) is True
    _release_extract_lock(comic.id)


def test_auto_clean_only_touches_final_dirs(app, make_comic):
    """LRU 自动清理只删数字命名的最终缓存目录；暂存/锁文件不受影响。"""
    # 清掉其他用例遗留的缓存，构造受控状态
    for name in os.listdir(PAGES_DIR):
        p = os.path.join(PAGES_DIR, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)

    old_dir = os.path.join(PAGES_DIR, '9001')
    new_dir = os.path.join(PAGES_DIR, '9002')
    staging = os.path.join(PAGES_DIR, '9002.tmp-123-abc')
    lock = os.path.join(PAGES_DIR, '9002.lock')
    for d, age, size in ((old_dir, 5000, 600), (new_dir, 100, 100), (staging, 0, 600)):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, '0001.jpg'), 'wb') as f:
            f.write(b'x' * size * 1024)
        t = time.time() - age
        os.utime(d, (t, t))
    with open(lock, 'w') as f:
        f.write('')

    Setting.set('max_cache_size', '1')
    try:
        _check_and_auto_clean_cache()

        assert not os.path.exists(old_dir), '旧缓存应被清理'
        assert os.path.exists(new_dir), '新缓存应保留'
        assert os.path.exists(staging), '暂存目录不应被 LRU 清理'
        assert os.path.exists(lock), '锁文件不应被清理'
    finally:
        Setting.set('max_cache_size', '0')


def test_serve_touches_final_dir_mtime(app, make_comic):
    """get_page_dir 命中页面时应刷新目录 mtime（LRU 保护正在读的漫画）。"""
    comic = _make_zip_comic(make_comic, 'stage7.zip', num_images=2)
    final = _final_dir(comic.id)
    os.makedirs(final, exist_ok=True)
    page = os.path.join(final, '0001.jpg')
    with open(page, 'wb') as f:
        f.write(b'img')
    old = time.time() - 5000
    os.utime(final, (old, old))

    d = get_page_dir(comic.id, '0001.jpg')
    assert d == final
    assert os.path.getmtime(final) > old


def test_cleanup_pages_removes_all_artifacts(app, make_comic):
    comic = _make_zip_comic(make_comic, 'stage8.zip')
    final = _final_dir(comic.id)
    os.makedirs(final, exist_ok=True)
    staging = _new_staging_dir(comic.id)
    os.makedirs(staging, exist_ok=True)
    with open(_lock_path(comic.id), 'w') as f:
        f.write('')

    cleanup_pages(comic.id)

    assert not os.path.exists(final)
    assert not os.path.exists(staging)
    assert not os.path.exists(_lock_path(comic.id))
