"""CPU 密集任务的真线程执行工具。

gevent worker 会把 threading.Thread 补丁为 greenlet：zip/7z/rar 解压、
PIL 封面生成等 C 层计算不释放事件循环，会卡住同 worker 的全部请求。
gevent.get_hub().threadpool 是官方提供的真实 OS 线程池，专用于此类工作。
"""

try:
    import gevent
except ImportError:  # 部分 Windows 开发环境未装 gevent（生产镜像必有）
    gevent = None

import threading

_fallback_pool = None
_fallback_lock = threading.Lock()


def _fallback_apply(fn):
    """无 gevent 时的降级路径：未打补丁环境下普通线程池即真实线程。"""
    global _fallback_pool
    if _fallback_pool is None:
        from concurrent.futures import ThreadPoolExecutor
        with _fallback_lock:
            if _fallback_pool is None:
                _fallback_pool = ThreadPoolExecutor(
                    max_workers=4, thread_name_prefix='cpu-bound')
    return _fallback_pool.submit(fn).result()


def run_cpu_bound(fn, *args, app=None, **kwargs):
    """在真实 OS 线程中执行 fn 并阻塞等待结果。

    - 调用方 greenlet 阻塞期间停泊在 hub 上，事件循环继续服务其他请求
    - 真实线程看不到调用方 greenlet 的 Flask 上下文栈：app 为 None 且
      当前存在 app context 时捕获传入，线程内自建 app context。
      若 fn 将经 TaskManager 池 worker 间接调用（提交后上下文已丢），
      必须在提交现场捕获 app 并显式传参
    - fn 内禁止触碰 gevent 补丁后的锁/事件（跨真实线程使用有死锁风险）；
      TaskManager 的进度字段写入已设计为无锁
    """
    if app is None:
        from flask import current_app, has_app_context
        if has_app_context():
            app = current_app._get_current_object()

    def _inner():
        if app is not None:
            with app.app_context():
                return fn(*args, **kwargs)
        return fn(*args, **kwargs)

    if gevent is not None:
        return gevent.get_hub().threadpool.apply(_inner)
    return _fallback_apply(_inner)
