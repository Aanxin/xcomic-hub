"""后台线程基础设施测试：调度锁选主 + CPU 密集任务真线程执行。"""

import threading

import pytest

from app.services.scheduler_service import SchedulerService
from app.utils.threading_utils import run_cpu_bound


class TestLeaderLock:
    def setup_method(self):
        self._holders = []

    def teardown_method(self):
        for s in self._holders:
            s.release_leader_lock()

    def test_only_one_process_wins(self):
        s1, s2 = SchedulerService(), SchedulerService()
        self._holders = [s1]
        try:
            assert s1._acquire_leader_lock() is True, '无竞争时应获得锁'
            assert s2._acquire_leader_lock() is False, '第二个进程应抢锁失败'
        finally:
            s1.release_leader_lock()
        assert s2._acquire_leader_lock() is True, '释放后应可重新竞争'
        self._holders = [s2]

    def test_acquire_is_reentrant_safe_release(self):
        s = SchedulerService()
        self._holders = [s]
        assert s._acquire_leader_lock() is True
        s.release_leader_lock()
        s.release_leader_lock()  # 幂等
        assert s._lock_file is None


class TestRunCpuBound:
    def test_runs_on_real_thread_and_returns_value(self):
        caller = threading.current_thread()
        seen = {}

        def probe():
            seen['thread'] = threading.current_thread()
            return 42

        assert run_cpu_bound(probe) == 42
        assert seen['thread'] is not caller, '应在真实 OS 线程中执行'

    def test_app_context_available_inside(self, app):
        from app.models import Setting

        def probe():
            # 无 app context 时 Setting 查询会抛 RuntimeError
            Setting.get('site_name', 'x')
            return 'ok'

        assert run_cpu_bound(probe) == 'ok'

    def test_exception_propagates(self):
        def boom():
            raise ValueError('cpu task failed')

        with pytest.raises(ValueError, match='cpu task failed'):
            run_cpu_bound(boom)

    def test_base_exception_propagates(self):
        """TaskCancelled 继承 BaseException，跨线程池后仍需可传播。"""
        from app.services.task_manager import TaskCancelled

        def cancelled():
            raise TaskCancelled()

        with pytest.raises(TaskCancelled):
            run_cpu_bound(cancelled)
