"""
ManagerJobManager 单元测试

覆盖 Trader 健康检查、网关连接检查、日志清理、告警创建与批量重启守卫。
全部基于 mock TradingManager，不触碰真实进程与数据库。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qtrader.manager.job_mgr import ManagerJobManager


def make_proxy(running: bool = True, connected: bool = True, manual_stop: bool = False):
    proxy = SimpleNamespace(
        is_running=lambda: running,
        manual_stop=manual_stop,
        gateway=SimpleNamespace(connected=connected),
    )
    return proxy


@pytest.fixture
def tm() -> SimpleNamespace:
    """mock TradingManager"""
    t = SimpleNamespace(
        traders={},
        account_configs_map={},
        alarm_service=None,
        app_config=None,
    )
    return t


@pytest.fixture
def job(tm) -> ManagerJobManager:
    return ManagerJobManager(tm)


@pytest.mark.unit
class TestTraderHealthCheck:
    """Trader 进程健康检查"""

    def test_no_alarm_service_skips(self, tm, job):
        tm.alarm_service = None
        job.trader_health_check()  # 不应抛错

    def test_dead_trader_triggers_alarm(self, tm, job):
        alarm = type("A", (), {"notify_alarm": staticmethod(lambda **kw: None)})()
        alarm.notify_alarm = lambda **kw: None
        import unittest.mock as m

        alarm = m.MagicMock()
        tm.alarm_service = alarm
        tm.traders = {"DQ": make_proxy(running=False)}
        tm.account_configs_map = {"DQ": SimpleNamespace(enabled=True)}

        job.trader_health_check()

        alarm.notify_alarm.assert_called_once()
        kwargs = alarm.notify_alarm.call_args.kwargs
        assert kwargs["account_id"] == "DQ"
        assert kwargs["source"] == "HEALTH_CHECK"

    def test_manual_stop_no_alarm(self, tm, job):
        from unittest.mock import MagicMock

        alarm = MagicMock()
        tm.alarm_service = alarm
        tm.traders = {"DQ": make_proxy(running=False, manual_stop=True)}
        tm.account_configs_map = {"DQ": SimpleNamespace(enabled=True)}

        job.trader_health_check()

        alarm.notify_alarm.assert_not_called()

    def test_running_trader_no_alarm(self, tm, job):
        from unittest.mock import MagicMock

        alarm = MagicMock()
        tm.alarm_service = alarm
        tm.traders = {"DQ": make_proxy(running=True)}
        tm.account_configs_map = {"DQ": SimpleNamespace(enabled=True)}

        job.trader_health_check()

        alarm.notify_alarm.assert_not_called()

    def test_disabled_account_skipped(self, tm, job):
        from unittest.mock import MagicMock

        alarm = MagicMock()
        tm.alarm_service = alarm
        tm.traders = {"DQ": make_proxy(running=False)}
        tm.account_configs_map = {"DQ": SimpleNamespace(enabled=False)}

        job.trader_health_check()

        alarm.notify_alarm.assert_not_called()


@pytest.mark.unit
class TestGatewayConnectionCheck:
    """网关连接状态检查"""

    def test_disconnected_listed(self, tm, job):
        tm.traders = {
            "DQ": make_proxy(connected=False),
            "GW": make_proxy(connected=True),
        }
        tm.account_configs_map = {
            "DQ": SimpleNamespace(enabled=True),
            "GW": SimpleNamespace(enabled=True),
        }

        assert job._check_gateway_connection() == ["DQ"]

    def test_disabled_account_not_checked(self, tm, job):
        tm.traders = {"DQ": make_proxy(connected=False)}
        tm.account_configs_map = {"DQ": SimpleNamespace(enabled=False)}

        assert job._check_gateway_connection() == []


@pytest.mark.unit
class TestCleanupLogs:
    """日志文件清理（按文件名中的日期判断）"""

    def test_deletes_old_logs_keeps_recent(self, job, tmp_path, monkeypatch):
        from datetime import datetime, timedelta

        monkeypatch.chdir(tmp_path)
        log_dir = tmp_path / "data" / "logs"
        log_dir.mkdir(parents=True)
        old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        recent_date = datetime.now().strftime("%Y-%m-%d")
        old_file = log_dir / f"trader-DQ_app_{old_date}.log"
        old_file.write_text("x")
        recent_file = log_dir / f"manager_app_{recent_date}.log"
        recent_file.write_text("x")
        no_date_file = log_dir / "no_date.log"
        no_date_file.write_text("x")

        job.cleanup_logs()

        assert not old_file.exists()
        assert recent_file.exists()
        assert no_date_file.exists()  # 无日期文件只告警不删

    def test_missing_dir_noop(self, job, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        job.cleanup_logs()  # 目录不存在，不应抛错


@pytest.mark.unit
class TestCreateAlarm:
    """告警创建（委托给 AlarmService）"""

    def test_notification_type(self, tm, job):
        from unittest.mock import MagicMock

        from qtrader.models.object import AlarmType

        alarm = MagicMock()
        tm.alarm_service = alarm

        job._create_alarm("DQ", "SRC", "标题", "详情", "notification")

        alarm.create_alarm.assert_called_once()
        assert alarm.create_alarm.call_args.kwargs["alarm_type"] == AlarmType.NOTIFICATION

    def test_exception_type_default(self, tm, job):
        from unittest.mock import MagicMock

        from qtrader.models.object import AlarmType

        alarm = MagicMock()
        tm.alarm_service = alarm

        job._create_alarm("DQ", "SRC", "标题", "详情")

        assert alarm.create_alarm.call_args.kwargs["alarm_type"] == AlarmType.EXCEPTION

    def test_no_alarm_service_skips(self, tm, job):
        tm.alarm_service = None
        job._create_alarm("DQ", "SRC", "标题", "详情")  # 不应抛错


@pytest.mark.unit
class TestRestartAllTraders:
    """批量重启"""

    async def test_no_traders_noop(self, tm, job):
        """无 Trader 时直接完成，不抛错"""
        await job.restart_all_traders()

    async def test_disabled_account_skips_restart(self, tm, job):
        """禁用账户不触发重启"""
        disabled = SimpleNamespace(enabled=False)
        proxy = SimpleNamespace()
        tm.traders = {"OFF": proxy}
        tm.account_configs_map = {"OFF": disabled}

        restart = AsyncMock(return_value=True)
        tm.restart_trader = restart

        await job.restart_all_traders()

        restart.assert_not_awaited()

    async def test_enabled_account_restarts(self, tm, job):
        """启用账户触发重启并计数"""
        enabled = SimpleNamespace(enabled=True)
        tm.traders = {"DQ": SimpleNamespace()}
        tm.account_configs_map = {"DQ": enabled}

        restart = AsyncMock(return_value=True)
        tm.restart_trader = restart

        await job.restart_all_traders()

        restart.assert_awaited_once_with("DQ")
