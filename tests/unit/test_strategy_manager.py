"""
StrategyManager 单元测试

覆盖当前 API 的核心行为：事件注册与分发（tick/bar/order/trade）、
策略启停、订阅、结算、下单映射（order_strategy_map）、撤单校验、
策略持仓查询与保存、CSV 参数加载。不加载真实策略类与数据库。
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from qtrader.models.object import (
    BarData,
    Direction,
    Offset,
    OrderData,
    OrderStatus,
    PositionData,
    TickData,
    TradeData,
)
from qtrader.trader.order_cmd import OrderCmd
from qtrader.trader.strategy_manager import StrategyManager, load_csv_file, load_strategy_params
from qtrader.utils.async_event_engine import EventTypes
from qtrader.utils.config_loader import StrategyConfig


def make_config(symbol: str = "SHFE.rb2505", **overrides) -> StrategyConfig:
    config = StrategyConfig(enabled=True, type="rsi_strategy", symbol=symbol, bar="M1")
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def make_strategy(
    strategy_id: str = "rsi_001", symbol: str = "SHFE.rb2505", enabled: bool = True
) -> MagicMock:
    s = MagicMock()
    s.strategy_id = strategy_id
    s.symbol = symbol
    s.enabled = enabled
    s.enable = Mock(return_value=True)
    s.on_tick = AsyncMock()
    s.on_bar = AsyncMock()
    s.on_order = AsyncMock()
    s.on_trade = AsyncMock()
    s.get_position.return_value = None
    s.get_all_positions.return_value = {}
    s.bar_subscriptions = [f"{symbol}-M1"]
    return s


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
def engine() -> MagicMock:
    e = MagicMock()
    e.account_id = "test_account_001"
    e.trading_day = "2026-09-03"
    order = Mock()
    order.order_id = "order_100"
    e.insert_order = Mock(return_value=order)
    e.cancel_order = Mock(return_value=True)
    e.get_kline.return_value = None
    return e


@pytest.fixture
def manager(engine) -> StrategyManager:
    return StrategyManager({}, engine)


@pytest.mark.unit
class TestInit:
    """初始化"""

    def test_init_state(self, manager):
        assert manager.strategies_configs == {}
        assert manager.strategies == {}
        assert manager.order_strategy_map == {}
        assert manager.subscribed_symbols == set()
        assert manager.trading_engine is not None

    def test_register_events(self, manager):
        event_engine = MagicMock()
        manager.event_engine = event_engine
        manager._register_events()

        registered = {call.args[0] for call in event_engine.register.call_args_list}
        assert registered == {
            EventTypes.TICK_UPDATE,
            EventTypes.KLINE_UPDATE,
            EventTypes.ORDER_UPDATE,
            EventTypes.TRADE_UPDATE,
        }

    def test_register_events_no_engine_skipped(self, manager):
        manager.event_engine = None
        manager._register_events()  # 仅告警，不抛错


@pytest.mark.unit
class TestEventDispatch:
    """事件分发"""

    @pytest.mark.asyncio
    async def test_on_tick_dispatches_to_matching_strategy(self, manager):
        strategy = make_strategy()
        other = make_strategy("rsi_002", symbol="SHFE.hc2505")
        manager.strategies = {"rsi_001": strategy, "rsi_002": other}
        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)

        await manager._on_tick(tick)

        strategy.on_tick.assert_awaited_once_with(tick)
        other.on_tick.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_tick_disabled_strategy_skipped(self, manager):
        strategy = make_strategy(enabled=False)
        manager.strategies = {"rsi_001": strategy}
        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)

        await manager._on_tick(tick)

        strategy.on_tick.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_tick_updates_existing_position(self, manager):
        strategy = make_strategy()
        position = MagicMock()
        strategy.get_position.return_value = position
        manager.strategies = {"rsi_001": strategy}
        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)

        await manager._on_tick(tick)

        position.update_position.assert_called_once_with(tick)

    @pytest.mark.asyncio
    async def test_on_tick_swallows_strategy_errors(self, manager):
        strategy = make_strategy()
        strategy.on_tick.side_effect = RuntimeError("boom")
        manager.strategies = {"rsi_001": strategy}
        tick = TickData.model_construct(symbol="SHFE.rb2505", last_price=3500.0)

        await manager._on_tick(tick)  # 不应抛出

    @pytest.mark.asyncio
    async def test_on_bar_dispatches_by_symbol(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}
        bar = BarData.model_construct(symbol="SHFE.rb2505", interval="M1")

        await manager._on_bar(bar)

        strategy.on_bar.assert_awaited_once_with(bar)

    @pytest.mark.asyncio
    async def test_on_order_routed_by_map(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}
        manager.order_strategy_map["order_001"] = "rsi_001"

        await manager._on_order(make_order("order_001"))

        strategy.on_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_on_order_unmapped_skipped(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}

        await manager._on_order(make_order("order_unknown"))

        strategy.on_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_order_terminal_status_cleans_map(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}
        manager.order_strategy_map["order_001"] = "rsi_001"
        manager.order_strategy_map["order_002"] = "rsi_001"

        await manager._on_order(make_order("order_001", OrderStatus.FINISHED))
        await manager._on_order(make_order("order_002", OrderStatus.PENDING))

        assert "order_001" not in manager.order_strategy_map
        assert "order_002" in manager.order_strategy_map

    @pytest.mark.asyncio
    async def test_on_trade_routed_by_map(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}
        manager.order_strategy_map["order_001"] = "rsi_001"

        await manager._on_trade(make_trade("trade_001"))

        strategy.on_trade.assert_awaited_once()


@pytest.mark.unit
class TestStrategyControl:
    """策略启停与订阅"""

    def test_enable_disable_strategy(self, manager):
        strategy = make_strategy()
        manager.strategies = {"rsi_001": strategy}

        assert manager.enable_strategy("rsi_001") is True
        strategy.enable.assert_called_once_with()

        assert manager.disable_strategy("rsi_001") is True
        strategy.enable.assert_called_with(False)

    def test_enable_unknown_strategy(self, manager):
        assert manager.enable_strategy("nope") is False
        assert manager.disable_strategy("nope") is False

    def test_subscribe_symbol_with_interval(self, manager, engine):
        assert manager.subscribe_symbol("SHFE.rb2505", "M1") is True
        engine.subscribe_symbol.assert_called_once_with("SHFE.rb2505")
        engine.subscribe_bars.assert_called_once_with("SHFE.rb2505", "M1")

    def test_subscribe_symbol_without_interval(self, manager, engine):
        manager.subscribe_symbol("SHFE.rb2505", "")
        engine.subscribe_symbol.assert_called_once()
        engine.subscribe_bars.assert_not_called()

    def test_subscribe_symbol_no_engine(self, engine):
        manager = StrategyManager({}, None)
        assert manager.subscribe_symbol("SHFE.rb2505", "M1") is False


@pytest.mark.unit
class TestTrading:
    """交易接口与订单映射"""

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, manager, engine):
        manager.order_strategy_map["order_100"] = "rsi_001"
        assert await manager.cancel_order("rsi_001", "order_100") is True

    @pytest.mark.asyncio
    async def test_cancel_order_wrong_strategy(self, manager, engine):
        manager.order_strategy_map["order_100"] = "rsi_002"
        assert await manager.cancel_order("rsi_001", "order_100") is False
        engine.cancel_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_order_exception(self, manager, engine):
        engine.cancel_order.side_effect = RuntimeError("boom")
        assert await manager.cancel_order("rsi_001", "order_x") is False

    @pytest.mark.asyncio
    async def test_send_order_cmd(self, manager, engine):
        cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=1)
        await manager.send_order_cmd("rsi_001", cmd)
        engine.insert_order_cmd.assert_called_once_with(cmd)

    @pytest.mark.asyncio
    async def test_send_order_cmd_swallows_errors(self, manager, engine):
        engine.insert_order_cmd.side_effect = RuntimeError("boom")
        cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=1)
        await manager.send_order_cmd("rsi_001", cmd)  # 不应抛出

    @pytest.mark.asyncio
    async def test_cancel_order_cmd(self, manager, engine):
        engine.cancel_order_cmd = AsyncMock()
        cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=1)
        await manager.cancel_order_cmd("rsi_001", cmd)
        engine.cancel_order_cmd.assert_awaited_once_with(cmd.cmd_id)


@pytest.mark.unit
class TestSettlePositions:
    """持仓结算"""

    def test_settle_long_position(self, manager):
        strategy = make_strategy()
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            pos_long_td=3,
            pos_long_yd=2,
            hold_price_long=3500.0,
        )
        pos.last_price = 3600.0
        strategy.get_all_positions.return_value = {"SHFE.rb2505": pos}
        manager.strategies = {"rsi_001": strategy}

        manager.settle_positions()

        assert pos.pos_long_yd == 5  # 今仓转为昨仓
        assert pos.pos_long_td == 0
        assert pos.hold_price_long == 3600.0  # 以最新价重置成本

    def test_settle_short_position(self, manager):
        strategy = make_strategy()
        pos = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            pos_short_td=2,
            hold_price_short=3500.0,
        )
        pos.last_price = 3450.0
        strategy.get_all_positions.return_value = {"SHFE.rb2505": pos}
        manager.strategies = {"rsi_001": strategy}

        manager.settle_positions()

        assert pos.pos_short_yd == 2
        assert pos.pos_short_td == 0
        assert pos.hold_price_short == 3450.0


@pytest.mark.unit
class TestStrategyPositions:
    """策略持仓查询与保存"""

    def test_get_strategy_position(self, manager):
        strategy = make_strategy()
        expected = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1)
        strategy.get_position.return_value = expected
        manager.strategies = {"rsi_001": strategy}

        assert manager.get_strategy_position("rsi_001", "SHFE.rb2505") is expected
        strategy.get_position.assert_called_once_with("SHFE.rb2505")

    def test_get_strategy_position_unknown(self, manager):
        assert manager.get_strategy_position("nope", "SHFE.rb2505") is None

    def test_get_all_strategy_positions(self, manager):
        strategy = make_strategy()
        pos = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1)
        strategy.get_all_positions.return_value = {"SHFE.rb2505": pos}
        manager.strategies = {"rsi_001": strategy}

        result = manager.get_all_strategy_positions("rsi_001")

        assert result["SHFE.rb2505"]["symbol"] == "SHFE.rb2505"

    def test_get_all_strategy_positions_unknown(self, manager):
        assert manager.get_all_strategy_positions("nope") == {}

    def test_save_strategy_position_adds_account_id(self, manager):
        pos = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1)

        with patch.object(manager, "_position_service") as mock_service:
            mock_service.save_position.return_value = True
            assert manager.save_strategy_position(pos) is True

        assert pos.extras["account_id"] == "test_account_001"

    def test_get_position_from_engine(self, manager, engine):
        pos = PositionData(symbol="SHFE.rb2505", exchange="SHFE", pos_long_td=1)
        engine.positions = {"SHFE.rb2505": pos}

        assert manager.get_position("SHFE.rb2505") is pos

    def test_get_position_none_when_empty(self, manager, engine):
        engine.positions = {}
        assert manager.get_position("SHFE.rb2505") is None


@pytest.mark.unit
class TestParamLoading:
    """CSV 参数加载"""

    def test_load_csv_file(self, tmp_path):
        csv_path = tmp_path / "params.csv"
        csv_path.write_text(
            "strategy_id,k1,k2\n" "rsi_001,10,20\n" "rsi_002,30,\n" ",99,99\n",
            encoding="utf-8",
        )

        with patch("qtrader.trader.strategy_manager._csv_cache", {}):
            result = load_csv_file(str(csv_path))

        assert result["rsi_001"]["k1"] == "10"
        assert "rsi_002" in result
        assert len(result) == 2  # 空 strategy_id 行被忽略

    def test_load_csv_file_missing(self):
        with patch("qtrader.trader.strategy_manager._csv_cache", {}):
            assert load_csv_file("/nonexistent/x.csv") == {}

    def test_load_strategy_params_merges_csv(self, tmp_path):
        config = make_config()
        config.params_file = "params_20260903.csv"
        app_config = MagicMock()
        app_config.paths.params = str(tmp_path)
        (tmp_path / "params_20260903.csv").write_text(
            "strategy_id,rsi_period\nrsi_001,14\n", encoding="utf-8"
        )

        with (
            patch("qtrader.trader.strategy_manager._csv_cache", {}),
            patch("qtrader.trader.strategy_manager.get_config_loader") as mock_loader,
        ):
            mock_loader.return_value._load_app_config.return_value = app_config
            params = load_strategy_params(config, "rsi_001")

        assert params["rsi_period"] == "14"
        assert config.params["rsi_period"] == "14"

    def test_load_strategy_params_no_file(self):
        config = make_config()
        config.params_file = None
        assert load_strategy_params(config, "rsi_001") == {}

    def test_load_strategy_params_no_row(self, tmp_path):
        config = make_config()
        config.params_file = "params.csv"
        app_config = MagicMock()
        app_config.paths.params = str(tmp_path)
        (tmp_path / "params.csv").write_text("strategy_id,rsi_period\nother,14\n", encoding="utf-8")

        with (
            patch("qtrader.trader.strategy_manager._csv_cache", {}),
            patch("qtrader.trader.strategy_manager.get_config_loader") as mock_loader,
        ):
            mock_loader.return_value._load_app_config.return_value = app_config
            assert load_strategy_params(config, "rsi_001") == {}
