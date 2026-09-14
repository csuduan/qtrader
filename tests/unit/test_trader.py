"""
Trader 交易执行器单元测试

覆盖当前 API 的核心行为：初始化状态、事件处理器注册、
账户/订单/成交/持仓/行情推送、Tick 批量推送、批量持久化、停止清理。
不启动真实 Socket 与交易引擎。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.models.object import AccountData, OrderData, PositionData, TickData, TradeData
from qtrader.trader.trader import Trader
from qtrader.utils.async_event_engine import EventTypes


@pytest.fixture
def trader_config() -> MagicMock:
    config = MagicMock()
    config.account_id = "test_account_001"
    return config


@pytest.fixture
def trader(trader_config) -> Trader:
    return Trader(trader_config)


@pytest.fixture
def socket_server() -> AsyncMock:
    server = AsyncMock()
    return server


def make_account() -> AccountData:
    return AccountData(account_id="test_account_001", balance=100000.0, available=95000.0)


@pytest.mark.unit
class TestTraderInit:
    """初始化状态"""

    def test_init_basic_attributes(self, trader):
        assert trader.account_id == "test_account_001"
        assert trader._running is False

    def test_init_components_none(self, trader):
        assert trader.trading_engine is None
        assert trader.strategy_manager is None
        assert trader.job_manager is None
        assert trader.switchPos_manager is None
        assert trader.task_scheduler is None
        assert trader.socket_server is None

    def test_init_batch_state(self, trader):
        assert trader._cached_account is None
        assert trader._pending_positions == {}
        assert trader._pending_ticks == []
        assert trader._persist_interval == 30.0
        assert trader._tick_push_interval == 1.0

    def test_get_task_scheduler(self, trader):
        assert trader.get_task_scheduler() is None
        trader.task_scheduler = Mock()
        assert trader.get_task_scheduler() is trader.task_scheduler


@pytest.mark.unit
class TestRegisterEventHandlers:
    """事件处理器注册"""

    def test_registers_all_push_events(self, trader):
        event_engine = MagicMock()
        with patch("qtrader.trader.trader.ctx") as mock_ctx:
            mock_ctx.get_event_engine.return_value = event_engine
            trader._register_event_handlers()

        registered_types = {call.args[0] for call in event_engine.register.call_args_list}
        assert registered_types == {
            EventTypes.ACCOUNT_UPDATE,
            EventTypes.ACCOUNT_READY,
            EventTypes.ORDER_UPDATE,
            EventTypes.TRADE_UPDATE,
            EventTypes.POSITION_UPDATE,
            EventTypes.TICK_UPDATE,
        }


@pytest.mark.unit
class TestEventPushHandlers:
    """事件推送处理器（Trader → Manager）"""

    @pytest.mark.asyncio
    async def test_on_account_update_caches_and_pushes(self, trader, socket_server):
        trader.socket_server = socket_server
        account = make_account()

        await trader._on_account_update(account)

        assert trader._cached_account["balance"] == 100000.0
        socket_server.send_push.assert_awaited_once()
        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "account"
        assert payload["account_id"] == "test_account_001"

    @pytest.mark.asyncio
    async def test_on_account_ready_notifies(self, trader, socket_server):
        trader.socket_server = socket_server

        await trader._on_account_ready({})

        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "trader_ready"
        assert payload["account_id"] == "test_account_001"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_on_order_update_persists_and_pushes(self, trader, socket_server):
        trader.socket_server = socket_server
        order = OrderData(
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            order_id="order_001",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=3500.0,
        )

        with patch.object(trader._order_dao, "save") as mock_persist:
            await trader._on_order_update(order)

        mock_persist.assert_called_once_with(trader.account_id, order)
        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "order"
        assert payload["order_id"] == "order_001"

    @pytest.mark.asyncio
    async def test_on_trade_update_persists_and_pushes(self, trader, socket_server):
        trader.socket_server = socket_server
        trade = TradeData(
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            order_id="order_001",
            trade_id="trade_001",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=3500.0,
        )

        with patch.object(trader._trade_dao, "save") as mock_persist:
            await trader._on_trade_update(trade)

        mock_persist.assert_called_once_with(trader.account_id, trade)
        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "trade"
        assert payload["trade_id"] == "trade_001"

    @pytest.mark.asyncio
    async def test_on_position_update_strips_source_and_pushes(self, trader, socket_server):
        trader.socket_server = socket_server
        pos = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=2)
        pos_dict = pos.model_dump()
        pos_dict["_source"] = "internal"

        await trader._on_position_update(pos_dict)

        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "position"
        assert "_source" not in payload
        assert trader._pending_positions["SHFE.rb2505"]["pos_long_td"] == 2

    @pytest.mark.asyncio
    async def test_on_tick_update_only_caches(self, trader, socket_server):
        trader.socket_server = socket_server
        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)

        await trader._on_tick_update(tick)

        assert len(trader._pending_ticks) == 1
        socket_server.send_push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_account_update_swallows_errors(self, trader):
        trader.socket_server = AsyncMock()
        trader.socket_server.send_push.side_effect = RuntimeError("boom")

        await trader._on_account_update(make_account())  # 不应抛出


@pytest.mark.unit
class TestTickPushLoop:
    """Tick 批量推送"""

    @pytest.mark.asyncio
    async def test_batches_pending_ticks(self, trader, socket_server):
        trader.socket_server = socket_server
        trader._running = True
        trader._tick_push_interval = 0.01
        trader.trading_engine = Mock(account=make_account())
        trader._pending_ticks.append({"symbol": "SHFE.rb2505", "last_price": 3500.0})
        trader._pending_ticks.append({"symbol": "SHFE.hc2505", "last_price": 3300.0})

        task = asyncio.create_task(trader._tick_push_loop())
        for _ in range(50):
            await asyncio.sleep(0.01)
            if socket_server.send_push.await_count:
                break
        trader._running = False
        task.cancel()
        await task  # 循环内部捕获 CancelledError 后正常退出

        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "tick_batch"
        assert len(payload["ticks"]) == 2
        assert payload["account"]["account_id"] == "test_account_001"
        assert trader._pending_ticks == []

    @pytest.mark.asyncio
    async def test_no_ticks_no_push(self, trader, socket_server):
        trader.socket_server = socket_server
        trader._running = True
        trader._tick_push_interval = 0.01

        task = asyncio.create_task(trader._tick_push_loop())
        await asyncio.sleep(0.05)
        trader._running = False
        task.cancel()
        await task  # 循环内部捕获 CancelledError 后正常退出

        socket_server.send_push.assert_not_awaited()


@pytest.mark.unit
class TestCacheAndPersist:
    """缓存与批量持久化"""

    def test_cache_account_data(self, trader):
        trader._cache_account_data(make_account())
        assert trader._cached_account["available"] == 95000.0

    def test_cache_position_data_keyed_by_symbol(self, trader):
        pos = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1)
        trader._cache_position_data(pos.model_dump())
        assert "SHFE.rb2505" in trader._pending_positions

    @pytest.mark.asyncio
    async def test_batch_persist_clears_cache_on_success(self, trader):
        trader._cached_account = {"balance": 1.0}
        trader._pending_positions = {"SHFE.rb2505": {"pos_long_td": 1}}

        with patch.object(trader, "_do_batch_persist", return_value=True):
            await trader._batch_persist()

        assert trader._cached_account is None
        assert trader._pending_positions == {}

    @pytest.mark.asyncio
    async def test_batch_persist_keeps_cache_on_failure(self, trader):
        trader._cached_account = {"balance": 1.0}

        with patch.object(trader, "_do_batch_persist", return_value=False):
            await trader._batch_persist()

        assert trader._cached_account == {"balance": 1.0}

    @pytest.mark.asyncio
    async def test_batch_persist_skips_when_empty(self, trader):
        with patch.object(trader, "_do_batch_persist") as mock_persist:
            await trader._batch_persist()

        mock_persist.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_batch_persist_no_db(self, trader):
        with patch("qtrader.utils.async_database.get_async_session", return_value=None):
            assert await trader._do_batch_persist({"balance": 1.0}, {}) is False

    @pytest.mark.asyncio
    async def test_do_batch_persist_success(self, trader):
        session = MagicMock()
        db = MagicMock()
        db.get_session.return_value.__aenter__.return_value = session
        db.get_session.return_value.__aexit__.return_value = False

        with (
            patch("qtrader.utils.async_database.get_async_session", db.get_session),
            patch.object(trader._account_dao, "save_dict") as mock_save_account,
            patch.object(trader._position_dao, "save_dict") as mock_save_position,
        ):
            result = await trader._do_batch_persist(
                {"balance": 1.0}, {"SHFE.rb2505": {"pos_long_td": 1}}
            )

        assert result is True
        mock_save_account.assert_awaited_once_with(session, trader.account_id, {"balance": 1.0})
        mock_save_position.assert_awaited_once_with(
            session, trader.account_id, "SHFE.rb2505", {"pos_long_td": 1}
        )

    @pytest.mark.asyncio
    async def test_do_batch_persist_exception_returns_false(self, trader):
        with patch(
            "qtrader.utils.async_database.get_async_session",
            side_effect=RuntimeError("db down"),
        ):
            assert await trader._do_batch_persist({"balance": 1.0}, {}) is False


@pytest.mark.unit
class TestTraderStop:
    """停止清理"""

    @pytest.mark.asyncio
    async def test_stop_cleans_up_components_and_files(self, trader, socket_server, tmp_path):
        socket_path = tmp_path / "qtrader_test_account_001.sock"
        socket_path.write_text("")
        pid_file = tmp_path / "qtrader_test_account_001.pid"
        pid_file.write_text("12345")

        trader.socket_server = socket_server
        trader._socket_path = str(socket_path)
        trader._tick_push_task = asyncio.create_task(asyncio.sleep(10))
        trader._persist_task = asyncio.create_task(asyncio.sleep(10))
        engine = MagicMock()
        engine.close = AsyncMock()
        trader.trading_engine = engine

        await trader.stop()

        assert trader._running is False
        engine.risk_control.flush_counters.assert_called_once()
        engine.close.assert_awaited_once()
        socket_server.stop.assert_awaited_once()
        assert trader._tick_push_task.cancelled()
        assert trader._persist_task.cancelled()
        assert not socket_path.exists()
        assert not pid_file.exists()

    @pytest.mark.asyncio
    async def test_stop_flushes_pending_ticks(self, trader, socket_server):
        trader.socket_server = socket_server
        trader._socket_path = None
        trader._pending_ticks.append({"symbol": "SHFE.rb2505", "last_price": 3500.0})

        await trader.stop()

        msg_type, payload = socket_server.send_push.call_args[0]
        assert msg_type == "tick_batch"
        assert len(payload["ticks"]) == 1
        assert trader._pending_ticks == []
