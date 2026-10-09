"""阅读解压 worker 线程 app context 测试。

TaskManager worker 无 Flask 上下文，而解压路径会查询 Setting（缓存上限），
worker 内必须自建 app context，否则任务以 RuntimeError 失败、阅读页永远转圈。
"""

import os
import time
import zipfile

from app import db
from app.models import Comic
from app.reader import _get_cached_pages, start_extraction_async
from app.services.task_manager import task_manager, TaskStatus
from config import COMICS_DIR, PAGES_DIR


def _make_zip_comic(make_comic, name='readtest.zip', num_images=2):
    path = os.path.join(COMICS_DIR, name)
    os.makedirs(COMICS_DIR, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as zf:
        for i in range(num_images):
            zf.writestr(f'{i + 1:04d}.jpg', b'fake-jpeg-bytes')
    return make_comic(filename=name, file_size=os.path.getsize(path))


def _wait_terminal(task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        info = task_manager.get_task(task_id)
        if info and info.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return info
        time.sleep(0.02)
    return task_manager.get_task(task_id)


def test_extraction_worker_has_app_context(app, make_comic):
    comic = _make_zip_comic(make_comic)

    result = start_extraction_async(comic.id, comic.filename)
    assert result['status'] != 'ready', '首次请求不应命中缓存'

    info = _wait_terminal(f'extract:{comic.id}')
    assert info is not None
    assert info.status == TaskStatus.COMPLETED, f'解压任务失败: {info.error}'

    pages = _get_cached_pages(comic.id)
    assert pages and len(pages) == 2


def test_extraction_cached_no_resubmit(app, make_comic):
    comic = _make_zip_comic(make_comic, 'readtest2.zip')

    start_extraction_async(comic.id, comic.filename)
    info = _wait_terminal(f'extract:{comic.id}')
    assert info.status == TaskStatus.COMPLETED

    # 二次请求应缓存命中直接 ready，不重启任务
    result = start_extraction_async(comic.id, comic.filename)
    assert result['status'] == 'ready'
    assert len(result['pages']) == 2
