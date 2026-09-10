"""
TradingEngine 单元测试

覆盖当前 API 的核心行为：初始化与网关装配、属性委托（账户/订单/持仓/行情）、
下单链路（连接校验/暂停/风控/事件推送）、撤单、暂停恢复、报单指令管理、
合约代码标准化。使用 mock Gateway，不连接真实交易系统。
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.models.object import (
    AccountData,
    Direction,
    Offset,
    OrderData,
    PositionData,
    TickData,
)
from qtrader.trader.order_cmd import OrderCmd
from qtrader.trader.trading_engine import TradingEngine
from qtrader.utils.async_event_engine import AsyncEventEngine, EventTypes
from qtrader.utils.config_loader import RiskControlConfig


@pytest.fixture
def engine() -> TradingEngine:
    config = MagicMock()
    config.account_id = "DQ"
    config.name = "测试账户"
    config.trading.paused = False
    config.trading.risk_control = None
    config.gateway.type = "TQSDK"
    config.gateway.broker.user_id = "USER001"
    config.gateway.broker.broker_name = "测试期货"
    config.gateway.broker.type = "kq"

    with (
        patch("qtrader.trader.gateway.tq_gateway.TqGateway") as mock_gw_cls,
        patch("qtrader.trader.trading_engine.ctx") as mock_ctx,
        patch.object(TradingEngine, "_load_risk_control_config", return_value=RiskControlConfig()),
    ):
        mock_ctx.get_event_engine.return_value = MagicMock(spec=AsyncEventEngine)
        e = TradingEngine(config)
        e._mock_gateway_cls = mock_gw_cls
        # 网关 mock 默认行为
        mock_gw_cls.return_value.connected = False
        mock_gw_cls.return_value.std_symbol.side_effect = lambda s: s
        mock_gw_cls.return_value.subscribe.return_value = True
    return e


def make_gateway(engine: TradingEngine) -> MagicMock:
    gateway = engine._mock_gateway_cls.return_value
    gateway.connected = True
    gateway.md_connected = True
    gateway.td_connected = True
    return gateway


def make_order_data() -> OrderData:
    return OrderData(
        symbol="rb2505",
        account_id="DQ",
        order_id="order_001",
        direction="BUY",
        offset="OPEN",
        volume=1,
        price=3500.0,
    )


@pytest.mark.unit
class TestInit:
    """初始化"""

    def test_init_state(self, engine):
        assert engine.account_id == "DQ"
        assert engine.paused is False
        assert engine.gateway is not None
        assert engine.event_engine is not None
        assert engine.risk_control is not None

    def test_init_paused_from_config(self):
        config = MagicMock()
        config.account_id = "DQ"
        config.trading.paused = True
        config.trading.risk_control = None
        config.gateway.type = "TQSDK"
        config.gateway.broker = MagicMock()
        with (
            patch("qtrader.trader.gateway.tq_gateway.TqGateway"),
            patch("qtrader.trader.trading_engine.ctx") as mock_ctx,
            patch.object(
                TradingEngine, "_load_risk_control_config", return_value=RiskControlConfig()
            ),
        ):
            mock_ctx.get_event_engine.return_value = MagicMock(spec=AsyncEventEngine)
            e = TradingEngine(config)
        assert e.paused is True


@pytest.mark.unit
class TestPropertiesNoGateway:
    """无网关时的属性兜底"""

    def test_properties_fallback(self, engine):
        engine.gateway = None
        assert engine.connected is False
        assert engine.trades == {}
        assert engine.orders == {}
        assert engine.positions == {}
        assert engine.quotes == {}
        assert engine.account is None
        assert isinstance(engine.trading_day, datetime)
        assert engine.get_position("rb2505") is None
        assert engine.get_kline("rb2505", "M1") is None


@pytest.mark.unit
class TestPropertiesDelegation:
    """属性委托到网关"""

    def test_trades_orders_positions_quotes(self, engine):
        gateway = make_gateway(engine)
        gateway.get_trades.return_value = {"t1": object()}
        gateway.get_orders.return_value = {"o1": object()}
        gateway.get_positions.return_value = {"rb2505": object()}
        gateway.get_quotes.return_value = {"rb2505": object()}

        assert "t1" in engine.trades
        assert "o1" in engine.orders
        assert "rb2505" in engine.positions
        assert "rb2505" in engine.quotes

    def test_account_enriched_with_broker_info(self, engine):
        gateway = make_gateway(engine)
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=100.0)

        account = engine.account

        assert account.user_id == "USER001"
        assert account.broker_name == "测试期货"
        assert account.broker_type == "TQ"  # TQSDK 网关固定为 TQ
        assert account.trade_paused is False
        assert account.md_connected is True
        assert isinstance(account.risk_status, dict)

    def test_account_none_when_gateway_returns_none(self, engine):
        gateway = make_gateway(engine)
        gateway.get_account.return_value = None
        assert engine.account is None

    def test_trading_day_parsed(self, engine):
        gateway = make_gateway(engine)
        gateway.get_trading_day.return_value = "20260903"
        assert engine.trading_day == datetime(2026, 9, 3)

    def test_get_position(self, engine):
        gateway = make_gateway(engine)
        pos = PositionData(symbol="rb2505", exchange="SHFE", pos_long_td=1)
        gateway.get_positions.return_value = {"rb2505": pos}
        assert engine.get_position("rb2505") is pos

    def test_get_contract(self, engine):
        gateway = make_gateway(engine)
        gateway.get_contracts.return_value = {"rb2505": object()}
        assert engine.get_contract("rb2505") is not None
        assert engine.get_contract("nope") is None


@pytest.mark.unit
class TestInsertOrder:
    """下单链路"""

    def test_not_connected_raises(self, engine):
        gateway = make_gateway(engine)
        gateway.connected = False
        with pytest.raises(Exception, match="未连接"):
            engine.insert_order("rb2505", "BUY", "OPEN", 1)

    def test_paused_raises(self, engine):
        make_gateway(engine)
        engine.paused = True
        with pytest.raises(Exception, match="暂停"):
            engine.insert_order("rb2505", "BUY", "OPEN", 1)

    def test_risk_check_fails_raises(self, engine):
        make_gateway(engine)
        with patch.object(engine.risk_control, "check_order", return_value=False):
            with pytest.raises(Exception, match="风控"):
                engine.insert_order("rb2505", "BUY", "OPEN", 10000)

    def test_insert_order_rejected_in_non_trading_session(self, engine):
        """盘中非交易时段（小节休息/午休/闭市）直接报单应被拦截"""
        make_gateway(engine)
        with patch("qtrader.trader.trading_engine.is_symbol_trading_time", return_value=False):
            with pytest.raises(Exception, match="非交易时段"):
                engine.insert_order("SHFE.rb2505", "BUY", "OPEN", 1)
        gateway = engine._mock_gateway_cls.return_value
        gateway.send_order.assert_not_called()

    def test_insert_order_allowed_in_trading_session(self, engine):
        """交易时段正常放行（conftest 默认放开时段守卫）"""
        gateway = make_gateway(engine)
        gateway.send_order.return_value = make_order_data()
        engine.insert_order("rb2505", "BUY", "OPEN", 1)
        gateway.send_order.assert_called_once()

    def test_insert_order_success(self, engine):
        gateway = make_gateway(engine)
        order = make_order_data()
        gateway.send_order.return_value = order
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=1.0)

        result = engine.insert_order("rb2505", "BUY", "OPEN", 2, price=3500.0)

        assert result is order
        assert order.insert_time is not None
        gateway.send_order.assert_called_once()
        req = gateway.send_order.call_args[0][0]
        assert req.symbol == "rb2505"
        assert req.direction == Direction.BUY
        assert req.offset == Offset.OPEN
        assert req.volume == 2
        # 事件推送：账户更新（含风控状态）
        engine.event_engine.put.assert_called()
        assert any(
            call.args[0] == EventTypes.ACCOUNT_UPDATE
            for call in engine.event_engine.put.call_args_list
        )

    def test_insert_order_gateway_returns_none(self, engine):
        gateway = make_gateway(engine)
        gateway.send_order.return_value = None
        assert engine.insert_order("rb2505", "SELL", "CLOSE", 1) is None

    def test_market_order_price_none(self, engine):
        gateway = make_gateway(engine)
        gateway.send_order.return_value = make_order_data()
        gateway.get_account.return_value = None

        engine.insert_order("rb2505", "BUY", "OPEN", 1, price=0)

        req = gateway.send_order.call_args[0][0]
        assert req.price is None  # 市价


@pytest.mark.unit
class TestCancelOrder:
    """撤单"""

    def test_not_connected_fails(self, engine):
        gateway = make_gateway(engine)
        gateway.connected = False
        assert engine.cancel_order("order_001") is False

    def test_risk_check_blocks(self, engine):
        gateway = make_gateway(engine)
        with patch.object(engine.risk_control, "check_cancel", return_value=False):
            assert engine.cancel_order("order_001") is False
        gateway.cancel_order.assert_not_called()

    def test_cancel_success(self, engine):
        gateway = make_gateway(engine)
        gateway.cancel_order.return_value = True
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=1.0)

        assert engine.cancel_order("order_001") is True
        gateway.cancel_order.assert_called_once()

    def test_cancel_gateway_fails(self, engine):
        gateway = make_gateway(engine)
        gateway.cancel_order.return_value = False
        assert engine.cancel_order("order_001") is False


@pytest.mark.unit
class TestPauseResume:
    """暂停与恢复"""

    def test_pause_emits_event(self, engine):
        gateway = make_gateway(engine)
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=1.0)

        engine.pause()

        assert engine.paused is True
        call = engine.event_engine.put.call_args
        assert call.args[0] == EventTypes.ACCOUNT_UPDATE
        assert call.args[1]["trade_paused"] is True

    def test_resume_emits_event(self, engine):
        gateway = make_gateway(engine)
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=1.0)

        engine.resume()

        assert engine.paused is False
        call = engine.event_engine.put.call_args
        assert call.args[1]["trade_paused"] is False


@pytest.mark.unit
class TestOrderCmd:
    """报单指令管理"""

    def make_cmd(self) -> OrderCmd:
        return OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=10,
        )

    def test_insert_order_cmd(self, engine):
        engine._order_cmd_executor = MagicMock()
        cmd = self.make_cmd()

        cmd_id = engine.insert_order_cmd(cmd)

        assert cmd_id == cmd.cmd_id
        assert engine._order_cmds[cmd_id] is cmd
        assert cmd.symbol == "SHFE.rb2505"
        engine._order_cmd_executor.register.assert_called_once_with(cmd)

    def test_get_order_cmd(self, engine):
        cmd = self.make_cmd()
        engine.insert_order_cmd(cmd)

        result = engine.get_order_cmd(cmd.cmd_id)
        assert result["cmd_id"] == cmd.cmd_id
        assert engine.get_order_cmd("ghost") is None

    def test_get_all_order_cmds(self, engine):
        engine.insert_order_cmd(self.make_cmd())
        engine.insert_order_cmd(self.make_cmd())
        assert len(engine.get_all_order_cmds()) == 2

    def test_cleanup_finished_cmds(self, engine):
        executor = MagicMock()
        engine._order_cmd_executor = executor
        cmd = self.make_cmd()
        engine.insert_order_cmd(cmd)
        # 将指令标记为完成（is_finished 由 status 派生）
        from qtrader.trader.order_cmd import OrderCmdStatus

        cmd.status = OrderCmdStatus.FINISHED

        engine.cleanup_finished_order_cmds()

        assert engine._order_cmds == {}
        executor.unregister.assert_called_once_with(cmd.cmd_id)

    @pytest.mark.asyncio
    async def test_finished_cmd_still_queryable_via_executor_run_loop(self, engine):
        """回归：指令在执行器主循环中完成后，get_order_cmd 仍可读终态（switch_mgr 依赖）"""
        from qtrader.trader.order_cmd import OrderCmdStatus
        from qtrader.trader.order_executor import OrderCmdExecutor

        # 用真实执行器，替换其事件引擎避免外部依赖
        event_engine = MagicMock()
        executor = OrderCmdExecutor(event_engine, engine)
        engine._order_cmd_executor = executor

        cmd = self.make_cmd()
        engine.insert_order_cmd(cmd)
        cmd.status = OrderCmdStatus.FINISHED  # 注册后标记完成

        # 手动跑一轮主循环的移除逻辑（不启动任务，直接模拟一轮）
        executor._running = True
        task = asyncio.create_task(executor._run_loop())
        await asyncio.sleep(0.25)  # 至少一轮 0.1s 循环
        executor._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # 已从 pending 移除，但 engine 侧仍可读到终态（供 switch_mgr 更新成交进度）
        assert cmd.cmd_id not in executor._pending_cmds
        result = engine.get_order_cmd(cmd.cmd_id)
        assert result is not None
        assert result["cmd_id"] == cmd.cmd_id

    @pytest.mark.asyncio
    async def test_cancel_order_cmd_no_executor(self, engine):
        engine._order_cmd_executor = None
        assert await engine.cancel_order_cmd("x") is False

    @pytest.mark.asyncio
    async def test_cancel_order_cmd(self, engine):
        executor = MagicMock()
        executor.close.return_value = True
        engine._order_cmd_executor = executor
        assert await engine.cancel_order_cmd("x") is True
        executor.close.assert_called_once_with("x")


@pytest.mark.unit
class TestStdSymbolAndSubscribe:
    """合约标准化与订阅"""

    def test_std_symbol_no_gateway(self, engine):
        engine.gateway = None
        assert engine.std_symbol("SHFE.rb2505") == "SHFE.rb2505"

    def test_std_symbol_delegates(self, engine):
        gateway = make_gateway(engine)
        gateway.std_symbol.side_effect = lambda s: "rb2505"  # side_effect 优先于 return_value
        assert engine.std_symbol("SHFE.rb2505") == "rb2505"

    def test_std_symbol_fallback_when_none(self, engine):
        gateway = make_gateway(engine)
        gateway.std_symbol.return_value = None
        assert engine.std_symbol("UNKNOWN") == "UNKNOWN"

    def test_subscribe_symbol_string(self, engine):
        gateway = make_gateway(engine)
        assert engine.subscribe_symbol("SHFE.rb2505") is True
        gateway.subscribe.assert_called_once_with(["SHFE.rb2505"])

    def test_subscribe_symbol_no_gateway(self, engine):
        engine.gateway = None
        assert engine.subscribe_symbol("SHFE.rb2505") is True

    def test_subscribe_bars(self, engine):
        gateway = make_gateway(engine)
        assert engine.subscribe_bars("SHFE.rb2505", "M1") is True
        gateway.subscribe_bars.assert_called_once_with("SHFE.rb2505", "M1")


@pytest.mark.unit
class TestConnection:
    """连接管理"""

    @pytest.mark.asyncio
    async def test_connect_no_gateway(self, engine):
        engine.gateway = None
        assert await engine.connect() is False

    @pytest.mark.asyncio
    async def test_connect_success(self, engine):
        gateway = make_gateway(engine)

        async def connect_side_effect():
            gateway.connected = True
            return True

        gateway.connect = AsyncMock(side_effect=connect_side_effect)
        assert await engine.connect() is True
        gateway.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect(self, engine):
        gateway = make_gateway(engine)
        gateway.disconnect = AsyncMock(return_value=True)
        assert await engine.disconnect() is True
        gateway.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close(self, engine):
        gateway = make_gateway(engine)
        gateway.close = AsyncMock()
        await engine.close()
        gateway.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_no_gateway(self, engine):
        engine.gateway = None
        assert await engine.disconnect() is False


@pytest.mark.unit
class TestGetStatus:
    """状态查询"""

    def test_get_status(self, engine):
        gateway = make_gateway(engine)
        gateway.get_account.return_value = AccountData(account_id="DQ", balance=1.0)

        status = engine.get_status()

        assert status["connected"] is True
        assert status["paused"] is False
        assert status["daily_orders"] == 0
        assert status["daily_cancels"] == 0
