"""统一后台任务管理器。

将散落的裸 threading.Thread 收口到分类型的 ThreadPoolExecutor 中:
- 池化限并发,防止狂点开导致线程爆炸
- 任务去重:同 task_id 复用,避免重复执行
- 协作式取消:运行中任务通过 cancel_flag + progress_callback 检查
- 异常可追溯:Future.exception() 不再被吞
- 状态统一查询:解压/上传合并/下载任务进度走同一接口
"""

from __future__ import annotations

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class TaskType(str, Enum):
    EXTRACTION = 'extraction'
    UPLOAD_ASSEMBLY = 'upload_assembly'
    DOWNLOAD_TASK = 'download_task'
    SCRAPE = 'scrape'


class TaskStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


class TaskCancelled(BaseException):
    """协作式取消抛出的异常。

    继承 BaseException 而非 Exception,避免被业务代码的 `except Exception` 误捕
    (例如 _extract_7z_pages / _extract_rar_pages 中的兜底 except)。
    """


@dataclass
class TaskInfo:
    task_id: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    total: int = 0
    message: str = ''
    result: Any = None
    error: Optional[str] = None
    started_at: float = 0.0
    finished_at: Optional[float] = None
    cancel_flag: threading.Event = field(default_factory=threading.Event)


class TaskManager:
    """后台任务管理器(线程安全单例)。

    不同任务类型用独立线程池,避免相互阻塞(例如解压慢不会卡住上传合并)。
    """

    # 各任务类型的并发上限
    # SCRAPE 固定 1：下载任务全局串行（一次一个），后续任务在池内 FIFO 排队
    _POOL_CONFIG = {
        TaskType.EXTRACTION: 2,
        TaskType.UPLOAD_ASSEMBLY: 2,
        TaskType.DOWNLOAD_TASK: 3,
        TaskType.SCRAPE: 1,
    }

    # 已完成任务的保留时长,超过后自动清理
    CLEANUP_AGE_SECONDS = 3600

    def __init__(self):
        self._pools: dict[TaskType, ThreadPoolExecutor] = {
            t: ThreadPoolExecutor(max_workers=n, thread_name_prefix=t.value)
            for t, n in self._POOL_CONFIG.items()
        }
        self._tasks: dict[str, TaskInfo] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.RLock()

    def submit(self, task_type: TaskType, task_id: str,
               fn: Callable, *args, **kwargs) -> TaskInfo:
        """提交任务。

        - 同 task_id 仍在 pending/running 时复用,不重复提交
        - 已完成任务会被新提交覆盖(重新执行)
        """
        with self._lock:
            existing = self._tasks.get(task_id)
            if existing and existing.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                # 复用前确认任务真的还活着(未被 cancel 撤下却卡在 PENDING)
                fut = self._futures.get(task_id)
                if fut and fut.done():
                    # Future 已结束但 status 未更新(被 cancel 撤下):覆盖重建
                    pass
                else:
                    return existing

            info = TaskInfo(task_id=task_id, task_type=task_type, status=TaskStatus.PENDING)
            self._tasks[task_id] = info
            fut = self._pools[task_type].submit(self._runner, info, fn, args, kwargs)
            self._futures[task_id] = fut
            return info

    def _runner(self, info: TaskInfo, fn, args, kwargs):
        info.status = TaskStatus.RUNNING
        info.started_at = time.time()
        try:
            result = fn(*args, **kwargs)
            if info.cancel_flag.is_set():
                info.status = TaskStatus.CANCELLED
            else:
                info.result = result
                info.status = TaskStatus.COMPLETED
        except TaskCancelled:
            info.status = TaskStatus.CANCELLED
        except Exception as e:
            # 先写 error 再切 status,避免读侧看到 FAILED 但 error=None 的瞬时态
            info.error = str(e)
            info.status = TaskStatus.FAILED
            print(f'[TaskManager] 任务 {info.task_id} 失败: {e}')
            traceback.print_exc()
        finally:
            info.finished_at = time.time()
        return info.result

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        with self._lock:
            return self._tasks.get(task_id)

    def update_progress(self, task_id: str,
                        progress: int = -1, total: int = -1,
                        message: str = '') -> None:
        """更新任务进度。若任务已被请求取消，则抛 TaskCancelled。

        进度字段为无锁写入：CPU 型任务（解压/封面）的进度回调来自
        真实 OS 线程，不能触碰 gevent 补丁后的锁；CPython 下属性赋值
        原子，读侧（状态轮询）容忍瞬时旧值。
        """
        info = self._tasks.get(task_id)
        if not info:
            return
        if info.cancel_flag.is_set():
            raise TaskCancelled()
        if progress >= 0:
            info.progress = progress
        if total >= 0:
            info.total = total
        if message:
            info.message = message

    def make_progress_callback(self, task_id: str) -> Callable[[int, int], None]:
        """生成 progress_callback 闭包:更新状态 + 检查取消。

        用于对接既有解压函数的 progress_callback(p, t) 签名。
        """
        def cb(progress: int, total: int) -> None:
            self.update_progress(task_id, progress=progress, total=total)
        return cb

    def cancel(self, task_id: str) -> bool:
        """请求取消任务。

        - 未启动(PENDING):Future.cancel() 撤下,并标记 CANCELLED 让后续 submit 可重建
        - 运行中(RUNNING):设置 cancel_flag,任务在下一次 progress_callback 时退出
        - 已完成:无副作用(幂等)
        """
        with self._lock:
            info = self._tasks.get(task_id)
            fut = self._futures.get(task_id)
            if not info:
                return False
            info.cancel_flag.set()
            if fut and not fut.done():
                if fut.cancel():
                    # 成功撤下未启动的任务:立即标记终态,避免卡在 PENDING
                    info.status = TaskStatus.CANCELLED
                    info.finished_at = time.time()
            return True

    def cleanup(self) -> None:
        """清理已完成且超期的任务记录,避免字典无限增长。"""
        now = time.time()
        with self._lock:
            stale = [
                tid for tid, info in self._tasks.items()
                if info.finished_at and now - info.finished_at > self.CLEANUP_AGE_SECONDS
            ]
            for tid in stale:
                self._tasks.pop(tid, None)
                self._futures.pop(tid, None)

    def shutdown(self) -> None:
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)


# 全局单例
task_manager = TaskManager()
