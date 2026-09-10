"""
TraderReqHandler 单元测试

覆盖 Trader 进程的 Socket 请求处理器：网关连接/订阅、下单撤单、
数据查询（账户/订单/成交/持仓/行情/合约）、任务调度、暂停恢复、
告警配置、公共数据初始化。全部基于 mock Trader，不经过真实 IPC。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from qtrader.models.object import (
    AccountData,
    ContractData,
    Exchange,
    OrderData,
    OrderStatus,
    PositionData,
    TickData,
    TradeData,
)
from qtrader.trader.req import TraderReqHandler


def make_order(order_id: str, status: OrderStatus = OrderStatus.PENDING) -> OrderData:
    return OrderData(
        symbol="SHFE.rb2505",
        account_id="test_account_001",
        order_id=order_id,
        direction="BUY",
        offset="OPEN",
        volume=1,
        price=3500.0,
        status=status,
    )


def make_trade(trade_id: str) -> TradeData:
    return TradeData(
        symbol="SHFE.rb2505",
        account_id="test_account_001",
        order_id="order_001",
        trade_id=trade_id,
        direction="BUY",
        offset="OPEN",
        volume=1,
        price=3500.0,
    )


@pytest.fixture
def mock_trader() -> MagicMock:
    t = MagicMock()
    t.account_id = "test_account_001"
    return t


@pytest.fixture
def engine(mock_trader) -> MagicMock:
    """初始化好的交易引擎（含各类数据）"""
    e = MagicMock()
    e.connect = AsyncMock(return_value=True)
    e.disconnect = AsyncMock(return_value=True)
    e.account = AccountData(account_id="test_account_001", balance=100000.0)
    e.orders = {"order_001": make_order("order_001"), "order_002": make_order("order_002")}
    e.trades = {"trade_001": make_trade("trade_001")}
    e.positions = {
        "SHFE.rb2505": PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=2)
    }
    e.quotes = {"SHFE.rb2505": TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)}
    mock_trader.trading_engine = e
    return e


@pytest.fixture
def handler(mock_trader) -> TraderReqHandler:
    return TraderReqHandler(mock_trader)


def use_active_order(engine: MagicMock) -> None:
    """将 order_001 置为未完成（PENDING），order_002 置为已完成"""
    engine.orders = {
        "order_001": make_order("order_001", OrderStatus.PENDING),
        "order_002": make_order("order_002", OrderStatus.FINISHED),
    }


@pytest.mark.unit
class TestGatewayHandlers:
    """网关连接与订阅"""

    @pytest.mark.asyncio
    async def test_connect_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert not await handler._req_connect({})

    @pytest.mark.asyncio
    async def test_connect(self, engine, handler):
        assert await handler._req_connect({}) is True
        engine.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert not await handler._req_disconnect({})

    @pytest.mark.asyncio
    async def test_disconnect(self, engine, handler):
        assert await handler._req_disconnect({}) is True
        engine.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subscribe(self, engine, handler):
        assert await handler._req_subscribe({"symbol": "SHFE.rb2505"}) is True
        engine.subscribe_symbol.assert_called_once_with("SHFE.rb2505")

    @pytest.mark.asyncio
    async def test_unsubscribe_always_ok(self, handler):
        assert await handler._req_unsubscribe({"symbol": "SHFE.rb2505"}) is True


@pytest.mark.unit
class TestOrderHandlers:
    """下单与撤单"""

    @pytest.mark.asyncio
    async def test_order_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_order({}) is None

    @pytest.mark.asyncio
    async def test_order_success(self, engine, handler):
        engine.insert_order = Mock(return_value=make_order("order_100"))

        result = await handler._req_order(
            {
                "symbol": "SHFE.rb2505",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": 1,
                "price": 3500.0,
            }
        )

        assert result == "order_100"
        engine.insert_order.assert_called_once_with(
            symbol="SHFE.rb2505", direction="BUY", offset="OPEN", volume=1, price=3500.0
        )

    @pytest.mark.asyncio
    async def test_order_engine_returns_none(self, engine, handler):
        engine.insert_order = Mock(return_value=None)
        assert (
            await handler._req_order(
                {"symbol": "SHFE.rb2505", "direction": "BUY", "offset": "OPEN", "volume": 1}
            )
            is None
        )

    @pytest.mark.asyncio
    async def test_order_invalid_direction(self, engine, handler):
        # 无效参数直接抛出，由 SocketServer 包装为错误响应回传 Manager
        with pytest.raises(ValueError, match="BAD"):
            await handler._req_order(
                {"symbol": "x", "direction": "BAD", "offset": "OPEN", "volume": 1}
            )

    @pytest.mark.asyncio
    async def test_cancel_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_cancel({"order_id": "order_001"}) is False

    @pytest.mark.asyncio
    async def test_cancel_success(self, engine, handler):
        engine.cancel_order = Mock(return_value=True)
        assert await handler._req_cancel({"order_id": "order_001"}) is True

    @pytest.mark.asyncio
    async def test_cancel_failure(self, engine, handler):
        engine.cancel_order = Mock(return_value=False)
        assert await handler._req_cancel({"order_id": "order_001"}) is False

    @pytest.mark.asyncio
    async def test_cancel_exception(self, engine, handler):
        # 异常上抛（SocketServer 回传真实原因），不再吞为 False
        engine.cancel_order = Mock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await handler._req_cancel({"order_id": "order_001"})


@pytest.mark.unit
class TestDataQueryHandlers:
    """数据查询"""

    @pytest.mark.asyncio
    async def test_get_account(self, engine, handler):
        result = await handler._req_get_account({})
        assert result["account_id"] == "test_account_001"
        assert result["balance"] == 100000.0

    @pytest.mark.asyncio
    async def test_get_account_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_get_account({}) is None

    @pytest.mark.asyncio
    async def test_get_order_found(self, engine, handler):
        result = await handler._req_get_order({"order_id": "order_001"})
        assert result["order_id"] == "order_001"

    @pytest.mark.asyncio
    async def test_get_order_missing(self, engine, handler):
        assert await handler._req_get_order({}) is None
        assert await handler._req_get_order({"order_id": "nope"}) is None

    @pytest.mark.asyncio
    async def test_get_orders(self, engine, handler):
        result = await handler._req_get_orders({})
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_active_orders_filters_pending(self, engine, handler):
        use_active_order(engine)
        result = await handler._req_get_active_orders({})
        assert [o["order_id"] for o in result] == ["order_001"]

    @pytest.mark.asyncio
    async def test_get_trade_found(self, engine, handler):
        result = await handler._req_get_trade({"trade_id": "trade_001"})
        assert result["trade_id"] == "trade_001"

    @pytest.mark.asyncio
    async def test_get_trade_missing(self, engine, handler):
        assert await handler._req_get_trade({}) is None

    @pytest.mark.asyncio
    async def test_get_trades(self, engine, handler):
        assert len(await handler._req_get_trades({})) == 1

    @pytest.mark.asyncio
    async def test_get_positions(self, engine, handler):
        result = await handler._req_get_positions({})
        assert result[0]["symbol"] == "SHFE.rb2505"

    @pytest.mark.asyncio
    async def test_get_quotes(self, engine, handler):
        result = await handler._req_get_quotes({})
        assert result[0]["symbol"] == "SHFE.rb2505"

    @pytest.mark.asyncio
    async def test_get_account_details_structure(self, engine, handler):
        use_active_order(engine)
        engine.account = None

        result = await handler._req_get_account_details({})

        assert result["account"] is None
        assert result["positions"][0]["symbol"] == "SHFE.rb2505"
        assert [o["order_id"] for o in result["orders"]] == ["order_001"]
        assert len(result["trades"]) == 1
        assert len(result["quotes"]) == 1

    @pytest.mark.asyncio
    async def test_query_handlers_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_get_orders({}) == []
        assert await handler._req_get_trades({}) == []
        assert await handler._req_get_positions({}) == []
        assert await handler._req_get_quotes({}) == []
        assert await handler._req_get_account_details({}) == {
            "account": None,
            "positions": [],
            "orders": [],
            "trades": [],
            "quotes": [],
        }

    @pytest.mark.asyncio
    async def test_get_contracts_appends_update_date(self, engine, handler):
        engine.gateway.get_contracts.return_value = {
            "rb2505": ContractData(symbol="rb2505", exchange=Exchange.SHFE, name="螺纹钢")
        }

        result = await handler._req_get_contracts({})

        assert len(result) == 1
        assert result[0]["symbol"] == "rb2505"
        assert "update_date" in result[0]

    @pytest.mark.asyncio
    async def test_get_contracts_no_gateway(self, mock_trader, handler):
        mock_trader.trading_engine.gateway = None
        assert await handler._req_get_contracts({}) == []


@pytest.mark.unit
class TestJobHandlers:
    """任务调度请求"""

    @pytest.mark.asyncio
    async def test_get_jobs(self, mock_trader, handler):
        mock_trader.trading_engine = MagicMock()
        job = Mock()
        job.model_dump.return_value = {"job_id": "job_001"}
        mock_trader.task_scheduler.get_jobs.return_value = {"job_001": job}

        assert await handler._req_get_jobs({}) == [{"job_id": "job_001"}]

    @pytest.mark.asyncio
    async def test_get_jobs_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_get_jobs({}) == []

    @pytest.mark.asyncio
    async def test_trigger_job(self, mock_trader, handler):
        mock_trader.task_scheduler.trigger_job.return_value = True
        assert await handler._req_trigger_job({"job_id": "job_001"}) is True

    @pytest.mark.asyncio
    async def test_trigger_job_no_scheduler(self, mock_trader, handler):
        mock_trader.task_scheduler = None
        assert await handler._req_trigger_job({"job_id": "job_001"}) is False

    @pytest.mark.asyncio
    async def test_toggle_job(self, mock_trader, handler):
        mock_trader.task_scheduler.update_job_status.return_value = True
        assert await handler._req_toggle_job({"job_id": "job_001", "enabled": False}) is True
        mock_trader.task_scheduler.update_job_status.assert_called_once_with("job_001", False)

    @pytest.mark.asyncio
    async def test_toggle_job_missing_fields(self, mock_trader, handler):
        assert await handler._req_toggle_job({"job_id": "job_001"}) is False

    @pytest.mark.asyncio
    async def test_pause_job(self, mock_trader, handler):
        mock_trader.task_scheduler.operate_job.return_value = True
        assert await handler._req_pause_job({"job_id": "job_001"}) is True
        mock_trader.task_scheduler.operate_job.assert_called_once_with("job_001", "pause")

    @pytest.mark.asyncio
    async def test_resume_job(self, mock_trader, handler):
        mock_trader.task_scheduler.operate_job.return_value = True
        assert await handler._req_resume_job({"job_id": "job_001"}) is True
        mock_trader.task_scheduler.operate_job.assert_called_once_with("job_001", "resume")


@pytest.mark.unit
class TestTradingControlHandlers:
    """交易控制与告警配置"""

    @pytest.mark.asyncio
    async def test_pause_trading(self, engine, handler):
        assert await handler._req_pause_trading({}) is True
        assert engine.paused is True

    @pytest.mark.asyncio
    async def test_resume_trading(self, engine, handler):
        assert await handler._req_resume_trading({}) is True
        assert engine.paused is False

    @pytest.mark.asyncio
    async def test_reload_risk_config(self, engine, handler):
        assert await handler._req_reload_risk_config({}) == {"success": True}
        engine.reload_risk_control_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload_risk_config_no_engine(self, mock_trader, handler):
        mock_trader.trading_engine = None
        assert await handler._req_reload_risk_config({}) == {"success": False}

    @pytest.mark.asyncio
    async def test_alert_config_roundtrip(self, mock_trader, handler):
        alert = mock_trader.account_config.alert
        alert.notification.enabled = False
        alert.notification.dnd_start = 23
        alert.notification.dnd_end = 8
        alert.exception.enabled = True
        alert.exception.dnd_start = 0
        alert.exception.dnd_end = 0

        result = await handler._req_get_alert_config({})

        assert result == {
            "notification": {"enabled": False, "dnd_start": 23, "dnd_end": 8},
            "exception": {"enabled": True, "dnd_start": 0, "dnd_end": 0},
        }

    @pytest.mark.asyncio
    async def test_update_alert_config(self, mock_trader, handler):
        alert = mock_trader.account_config.alert

        await handler._req_update_alert_config(
            {"notification": {"enabled": True, "dnd_start": 22, "dnd_end": 7}}
        )

        assert alert.notification.enabled is True
        assert alert.notification.dnd_start == 22
        assert alert.notification.dnd_end == 7

    @pytest.mark.asyncio
    async def test_update_alert_wechat_deprecated_alias(self, mock_trader, handler):
        alert = mock_trader.account_config.alert

        result = await handler._req_update_alert_wechat({"alert_wechat": True})

        assert alert.notification.enabled is True
        assert result == {"alert_wechat": True}

    @pytest.mark.asyncio
    async def test_refresh_contracts(self, engine, handler):
        engine.refresh_contracts.return_value = True
        assert (await handler._req_refresh_contracts({}))["success"] is True

    @pytest.mark.asyncio
    async def test_refresh_contracts_failed(self, engine, handler):
        engine.refresh_contracts.return_value = False
        result = await handler._req_refresh_contracts({})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_export_positions(self, mock_trader, handler):
        mock_trader.job_manager.post_market_export = AsyncMock()
        result = await handler._req_export_positions({})
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_export_positions_no_job_manager(self, mock_trader, handler):
        mock_trader.job_manager = None
        result = await handler._req_export_positions({})
        assert result["success"] is False


@pytest.mark.unit
class TestInitPublicData:
    """Manager 公共数据（合约）推送"""

    @pytest.mark.asyncio
    async def test_empty_contracts(self, mock_trader, handler):
        mock_trader._init_data_future = None
        result = await handler._req_init_public_data({"contracts": []})

        assert result == {"success": True, "message": "无合约数据", "count": 0}
        assert mock_trader._public_data_initialized is True

    @pytest.mark.asyncio
    async def test_loads_contracts_and_resolves_future(self, engine, handler):
        future = asyncio.Future()
        mock_future = future  # 真实 Future 验证唤醒逻辑
        engine.gateway.load_contracts_from_init_data.return_value = 3
        handler.trader._init_data_future = mock_future

        result = await handler._req_init_public_data({"contracts": [{"symbol": "rb2505"}]})

        assert result == {"success": True, "message": "合约数据已加载", "count": 3}
        assert handler.trader._public_data_initialized is True
        assert future.done() is True and future.result() is True

    @pytest.mark.asyncio
    async def test_no_gateway(self, mock_trader, handler):
        engine = MagicMock()
        engine.gateway = None
        mock_trader.trading_engine = engine

        result = await handler._req_init_public_data({"contracts": [{"symbol": "rb2505"}]})

        assert result["success"] is False
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_load_exception(self, engine, handler):
        engine.gateway.load_contracts_from_init_data.side_effect = RuntimeError("boom")

        result = await handler._req_init_public_data({"contracts": [{"symbol": "rb2505"}]})

        assert result["success"] is False
