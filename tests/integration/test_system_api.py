"""
系统控制 API 集成测试

覆盖路由 qtrader.manager.api.routes.system（前缀 /api/system）。
走完整 FastAPI 栈，TradingManager / TraderProxy / 配置加载器全程 mock；
风控参数落库分支用临时 SQLite 承载 SystemParamPo。
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from qtrader.models.object import AccountData
from qtrader.models.po import Base, SystemParamPo

ACCOUNT = "DQ"
BASE = "/api/system"


def make_trader() -> MagicMock:
    """构造各系统操作方法均已配置的 TraderProxy mock"""
    trader = MagicMock()
    trader.get_status = MagicMock(
        return_value={
            "account_id": ACCOUNT,
            "running": True,
            "alive": True,
            "paused": False,
            "pid": 12345,
        }
    )
    trader.connect = AsyncMock(return_value=True)
    trader.disconnect = AsyncMock(return_value=True)
    trader.pause = AsyncMock(return_value=True)
    trader.resume = AsyncMock(return_value=True)
    trader.reload_risk_config = AsyncMock(return_value=True)
    trader.update_alert_wechat = AsyncMock(return_value=True)
    trader.get_alert_config = AsyncMock(return_value={"immediate": True, "threshold": False})
    return trader


def make_account() -> AccountData:
    return AccountData(
        account_id=ACCOUNT,
        balance=100000.0,
        available=50000.0,
        risk_status={"paused": False, "max_daily_orders": 100},
    )


def make_fake_param_db(tmp_path):
    """构造仅包含系统参数表的临时 SQLite 数据库"""
    # 路由经异步会话写入；同步引擎仅供用例读取校验落库结果
    sync_engine = create_engine(f"sqlite:///{tmp_path}/system_params.db")
    Base.metadata.create_all(sync_engine, tables=[SystemParamPo.__table__])
    session_local = sessionmaker(bind=sync_engine, autoflush=False, expire_on_commit=False)

    async_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/system_params.db")

    @asynccontextmanager
    async def get_session():
        async with async_sessionmaker(async_engine, expire_on_commit=False)() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return SimpleNamespace(get_session=get_session), session_local


def make_config_loader(tmp_path=None) -> MagicMock:
    """构造带 alert 配置结构的 config loader mock"""
    alert = SimpleNamespace(
        notification=SimpleNamespace(enabled=True, dnd_start=22, dnd_end=8),
        exception=SimpleNamespace(
            enabled=False,
            dnd_start=23,
            dnd_end=7,
            indicators=[
                SimpleNamespace(
                    name="daily_loss", window=1, threshold=5.0, description="日亏损超阈值"
                )
            ],
        ),
    )
    loader = MagicMock()
    loader.load_config.return_value = SimpleNamespace(alert=alert)
    loader.config_dir = str(tmp_path) if tmp_path else "/nonexistent-config-dir"
    # atomic_write_text 需真实写入以便断言落盘结果
    if tmp_path:
        from qtrader.utils.config_loader import ConfigLoader

        real = ConfigLoader(str(tmp_path))
        loader.atomic_write_text = real.atomic_write_text
    return loader


@pytest.mark.integration
class TestSystemStatus:
    """系统状态 GET /api/system/status"""

    def test_status_without_trader_returns_default(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get(f"{BASE}/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"account_id": ACCOUNT, "paused": False, "running": False}

    def test_status_with_trader(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.get(f"{BASE}/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["running"] is True
        assert body["data"]["pid"] == 12345


@pytest.mark.integration
class TestRiskControlStatus:
    """风控状态 GET /api/system/risk-control"""

    def test_get_risk_status(self, client, mock_trading_manager):
        mock_trading_manager.get_account = AsyncMock(return_value=make_account())

        resp = client.get(f"{BASE}/risk-control", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"paused": False, "max_daily_orders": 100}
        mock_trading_manager.get_account.assert_awaited_once_with(ACCOUNT)


@pytest.mark.integration
class TestRiskControlUpdate:
    """更新风控参数 PUT /api/system/risk-control"""

    def test_update_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.put(f"{BASE}/risk-control", json={"max_daily_orders": 50})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert "不存在" in body["message"]

    def test_update_without_db(self, client, mock_trading_manager):
        """无数据库时写入失败，返回明确错误且不通知 Trader 重载"""
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.put(
            f"{BASE}/risk-control", json={"max_daily_orders": 50, "account_id": ACCOUNT}
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "风控参数写入数据库失败"
        trader.reload_risk_config.assert_not_awaited()

    def test_update_success_persists_params(self, client, mock_trading_manager, tmp_path):
        db, session_local = make_fake_param_db(tmp_path)
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        mock_trading_manager.get_account = AsyncMock(return_value=make_account())

        with patch("qtrader.manager.api.routes.system.require_async_database", return_value=db):
            resp = client.put(
                f"{BASE}/risk-control",
                json={
                    "max_daily_orders": 50,
                    "order_timeout": 30,
                    "account_id": ACCOUNT,
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "风控参数已更新"
        assert body["data"] == {"paused": False, "max_daily_orders": 100}
        trader.reload_risk_config.assert_awaited_once()

        with session_local() as session:
            params = {
                p.param_key: p
                for p in session.query(SystemParamPo).filter(SystemParamPo.account_id == ACCOUNT)
            }
        assert set(params) == {"risk_control.max_daily_orders", "risk_control.order_timeout"}
        assert params["risk_control.max_daily_orders"].param_value == "50"
        assert params["risk_control.max_daily_orders"].param_type == "int"
        assert params["risk_control.max_daily_orders"].group == "risk_control"
        assert params["risk_control.order_timeout"].param_value == "30"

    def test_update_existing_param_updates_not_duplicates(
        self, client, mock_trading_manager, tmp_path
    ):
        """重复写入同一参数走更新分支，不产生重复行"""
        db, session_local = make_fake_param_db(tmp_path)
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        mock_trading_manager.get_account = AsyncMock(return_value=make_account())

        with patch("qtrader.manager.api.routes.system.require_async_database", return_value=db):
            client.put(f"{BASE}/risk-control", json={"max_daily_orders": 50, "account_id": ACCOUNT})
            client.put(f"{BASE}/risk-control", json={"max_daily_orders": 60, "account_id": ACCOUNT})

        with session_local() as session:
            rows = session.query(SystemParamPo).filter(SystemParamPo.account_id == ACCOUNT).all()
        assert len(rows) == 1
        assert rows[0].param_key == "risk_control.max_daily_orders"
        assert rows[0].param_value == "60"


@pytest.mark.integration
class TestAlertWechat:
    """微信告警配置 GET/PUT /api/system/alert-wechat"""

    def test_update_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.put(
            f"{BASE}/alert-wechat", json={"alert_wechat": True, "account_id": ACCOUNT}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "微信告警配置已更新"
        assert body["data"] == {"alert_wechat": True}
        trader.update_alert_wechat.assert_awaited_once_with(True)

    def test_update_failed(self, client, mock_trading_manager):
        trader = make_trader()
        trader.update_alert_wechat = AsyncMock(return_value=False)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.put(f"{BASE}/alert-wechat", json={"alert_wechat": False})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "更新微信告警配置失败"

    def test_update_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.put(
            f"{BASE}/alert-wechat", json={"alert_wechat": True, "account_id": ACCOUNT}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_get_legacy_value_true(self, client, mock_trading_manager):
        trader = make_trader()
        trader.get_alert_config = AsyncMock(return_value={"immediate": True, "threshold": False})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(f"{BASE}/alert-wechat", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"alert_wechat": True}
        assert "已废弃" in body["message"]

    def test_get_legacy_value_false(self, client, mock_trading_manager):
        trader = make_trader()
        trader.get_alert_config = AsyncMock(return_value={"immediate": False, "threshold": False})
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(f"{BASE}/alert-wechat", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        assert resp.json()["data"] == {"alert_wechat": False}

    def test_get_config_unavailable(self, client, mock_trading_manager):
        trader = make_trader()
        trader.get_alert_config = AsyncMock(return_value=None)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get(f"{BASE}/alert-wechat", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "获取告警配置失败"

    def test_get_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get(f"{BASE}/alert-wechat", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestConnectDisconnect:
    """交易系统连接控制 POST /api/system/connect|disconnect|disconnect/gateway"""

    def test_connect_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/connect", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"connected": True}
        assert body["message"] == "连接成功"
        trader.connect.assert_awaited_once()

    def test_connect_failed(self, client, mock_trading_manager):
        trader = make_trader()
        trader.connect = AsyncMock(return_value=False)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/connect", json=ACCOUNT)

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "连接失败"

    def test_connect_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/connect", json=ACCOUNT)

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_disconnect_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/disconnect", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"connected": False}
        assert body["message"] == "已断开连接"
        trader.disconnect.assert_awaited_once()

    def test_disconnect_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/disconnect", json=ACCOUNT)

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_disconnect_gateway_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/disconnect/gateway", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"md_connected": False, "td_connected": False}
        assert body["message"] == "已断开网关连接"

    def test_disconnect_gateway_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/disconnect/gateway", json=ACCOUNT)

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestTraderLifecycle:
    """Trader 进程生命周期 POST /api/system/trader/start|stop、GET /api/system/trader/status"""

    def test_start_success(self, client, mock_trading_manager):
        mock_trading_manager.start_trader = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/trader/start")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"running": True}
        assert body["message"] == "Trader已启动"
        mock_trading_manager.start_trader.assert_awaited_once_with(None)

    def test_start_failed(self, client, mock_trading_manager):
        mock_trading_manager.start_trader = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/trader/start", json=ACCOUNT)

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "Trader启动失败"
        mock_trading_manager.start_trader.assert_awaited_once_with(ACCOUNT)

    def test_stop_success(self, client, mock_trading_manager):
        mock_trading_manager.stop_trader = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/trader/stop", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"running": False}
        assert body["message"] == "Trader已停止"
        mock_trading_manager.stop_trader.assert_awaited_once_with(ACCOUNT)

    def test_stop_failed(self, client, mock_trading_manager):
        mock_trading_manager.stop_trader = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/trader/stop", json=ACCOUNT)

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "Trader停止失败"

    def test_status_without_trader_returns_default(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get(f"{BASE}/trader/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["account_id"] == ACCOUNT
        assert data["running"] is False
        assert data["alive"] is False
        assert data["pid"] is None
        assert data["restart_count"] == 0
        assert data["socket_path"] is None

    def test_status_with_trader(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=make_trader())

        resp = client.get(f"{BASE}/trader/status", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["running"] is True
        assert data["alive"] is True
        assert data["pid"] == 12345


@pytest.mark.integration
class TestPauseResume:
    """交易暂停/恢复 POST /api/system/pause|resume"""

    def test_pause_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/pause", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"paused": True}
        assert body["message"] == "交易已暂停"
        trader.pause.assert_awaited_once()

    def test_pause_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/pause", json=ACCOUNT)

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_resume_success(self, client, mock_trading_manager):
        trader = make_trader()
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.post(f"{BASE}/resume", json=ACCOUNT)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"paused": False}
        assert body["message"] == "交易已恢复"
        trader.resume.assert_awaited_once()

    def test_resume_trader_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post(f"{BASE}/resume", json=ACCOUNT)

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestManagerSchedulerJobs:
    """Manager 定时任务 GET /api/system/scheduler/jobs、operate、toggle"""

    def test_list_jobs(self, client, mock_trading_manager):
        mock_trading_manager.get_manager_scheduler_jobs = MagicMock(
            return_value=[{"job_id": "weekly_report", "enabled": True}]
        )

        resp = client.get(f"{BASE}/scheduler/jobs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] == 1
        assert body["data"]["tasks"][0]["job_id"] == "weekly_report"

    def test_list_jobs_empty(self, client, mock_trading_manager):
        mock_trading_manager.get_manager_scheduler_jobs = MagicMock(return_value=[])

        resp = client.get(f"{BASE}/scheduler/jobs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"tasks": [], "count": 0}

    @pytest.mark.parametrize(
        "action,expected_text",
        [("pause", "任务已暂停"), ("resume", "任务已恢复"), ("trigger", "任务已触发")],
    )
    def test_operate_job(self, client, mock_trading_manager, action, expected_text):
        mock_trading_manager.operate_manager_scheduler_job = MagicMock(return_value=True)

        resp = client.post(f"{BASE}/scheduler/jobs/job1/operate", json={"action": action})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == expected_text
        assert body["data"] == {"job_id": "job1"}
        mock_trading_manager.operate_manager_scheduler_job.assert_called_once_with("job1", action)

    def test_operate_job_failed(self, client, mock_trading_manager):
        mock_trading_manager.operate_manager_scheduler_job = MagicMock(return_value=False)

        resp = client.post(f"{BASE}/scheduler/jobs/job1/operate", json={"action": "pause"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "操作任务失败"

    def test_operate_job_invalid_json_body(self, client, mock_trading_manager):
        resp = client.post(
            f"{BASE}/scheduler/jobs/job1/operate",
            content="{bad json",
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 400
        assert body["message"] == "请求体解析失败"

    def test_toggle_job_enabled(self, client, mock_trading_manager):
        mock_trading_manager.toggle_manager_scheduler_job = MagicMock(return_value=True)

        resp = client.put(f"{BASE}/scheduler/jobs/job1/toggle", json=True)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "任务状态已更新"
        assert body["data"] == {"job_id": "job1", "enabled": True}
        mock_trading_manager.toggle_manager_scheduler_job.assert_called_once_with("job1", True)

    def test_toggle_job_failed(self, client, mock_trading_manager):
        mock_trading_manager.toggle_manager_scheduler_job = MagicMock(return_value=False)

        resp = client.put(f"{BASE}/scheduler/jobs/job1/toggle", json=False)

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "更新任务状态失败"


@pytest.mark.integration
class TestManagerAlertConfig:
    """Manager 全局告警配置 GET/PUT /api/system/manager/alert-config"""

    def test_get_alert_config(self, client):
        loader = make_config_loader()

        with patch("qtrader.manager.api.routes.system.get_config_loader", return_value=loader):
            resp = client.get(f"{BASE}/manager/alert-config")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["notification"] == {"enabled": True, "dnd_start": 22, "dnd_end": 8}
        assert data["exception"]["enabled"] is False
        assert data["exception"]["dnd_start"] == 23
        assert data["exception"]["indicators"] == [
            {
                "name": "daily_loss",
                "window": 1,
                "threshold": 5.0,
                "description": "日亏损超阈值",
            }
        ]

    def test_update_alert_config_writes_yaml(self, client, tmp_path):
        loader = make_config_loader(tmp_path=tmp_path)

        with patch("qtrader.manager.api.routes.system.get_config_loader", return_value=loader):
            resp = client.put(
                f"{BASE}/manager/alert-config",
                json={
                    "notification": {"enabled": False, "dnd_start": 21},
                    "exception": {"enabled": True, "dnd_end": 6},
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "告警配置已更新"
        data = body["data"]
        assert data["notification"]["enabled"] is False
        assert data["notification"]["dnd_start"] == 21
        assert data["exception"]["enabled"] is True
        assert data["exception"]["dnd_end"] == 6
        # indicators 原样保留
        assert data["exception"]["indicators"][0]["name"] == "daily_loss"

        # 配置写入到 loader 指定的临时目录，未触碰真实 config/
        config_file = tmp_path / "config.yaml"
        assert config_file.exists()
        with open(config_file, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["alert"]["notification"] == {
            "enabled": False,
            "dnd_start": 21,
            "dnd_end": 8,
        }
        assert saved["alert"]["exception"]["enabled"] is True
        assert saved["alert"]["exception"]["indicators"][0]["name"] == "daily_loss"
