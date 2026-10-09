"""TaskManager SCRAPE 任务类型测试。"""

import time

from app.services.task_manager import TaskManager, TaskType, TaskStatus


def test_scrape_task_type_exists():
    assert TaskType.SCRAPE.value == 'scrape'
    assert TaskType.SCRAPE in TaskManager._POOL_CONFIG
    assert TaskManager._POOL_CONFIG[TaskType.SCRAPE] == 1  # 全局串行：一次一个下载


def test_scrape_task_executes():
    mgr = TaskManager()
    try:
        results = []
        info = mgr.submit(TaskType.SCRAPE, 'scrape:t1', lambda: results.append('ok'))
        deadline = time.time() + 5
        while info.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED) and time.time() < deadline:
            time.sleep(0.02)
        assert info.status == TaskStatus.COMPLETED
        assert results == ['ok']
    finally:
        mgr.shutdown()


def test_scrape_task_dedup_same_id():
    mgr = TaskManager()
    try:
        calls = []

        def slow_fn():
            calls.append(1)
            time.sleep(0.3)
            return 'done'

        first = mgr.submit(TaskType.SCRAPE, 'scrape:t2', slow_fn)
        second = mgr.submit(TaskType.SCRAPE, 'scrape:t2', slow_fn)
        assert second is first, '同 task_id 应复用已有任务'
        time.sleep(0.6)
        assert calls == [1], '同 id 任务不应重复执行'
    finally:
        mgr.shutdown()


def test_scrape_task_cancel_pending():
    mgr = TaskManager()
    try:
        started = []

        def blocker():
            started.append(1)
            time.sleep(0.5)

        # 占满 SCRAPE 池(2)后第三个任务处于 PENDING
        mgr.submit(TaskType.SCRAPE, 'scrape:a', blocker)
        mgr.submit(TaskType.SCRAPE, 'scrape:b', blocker)
        info = mgr.submit(TaskType.SCRAPE, 'scrape:c', blocker)

        assert mgr.cancel('scrape:c') is True
        assert info.status == TaskStatus.CANCELLED
    finally:
        mgr.shutdown()
