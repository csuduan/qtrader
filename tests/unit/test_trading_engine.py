"""
TradingEngine 单元测试
测试 TradingEngine 类的所有方法和功能
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, Mock, PropertyMock, patch
import pytest

from src.trader.trading_engine import TradingEngine
from src.models.object import (
    Direction,
    Offset,
    OrderData,
    TradeData,
    PositionData,
    AccountData,
    TickData,
    BarData,
    Interval,
    Exchange,
)
from src.utils.event_engine import EventEngine, EventTypes


# ==================== Fixtures ====================


@pytest.fixture
def mock_account_config():
    """创建模拟的账户配置"""
    config = MagicMock()
    config.account_id = "test_account_001"
    config.account_type = "kq"
    config.gateway.type = "TQSDK"
    config.gateway.broker.user_id = "test_user"
    config.trading.paused = False
    config.trading.risk_control = MagicMock(
        max_single_order_volume=10,
        max_daily_order_volume=100,
        max_daily_cancel_volume=50,
    )
    return config


@pytest.fixture
def mock_gateway():
    """模拟Gateway"""
    gateway = MagicMock()
    gateway.connected = False
    gateway.connect = MagicMock(return_value=True)
    gateway.disconnect = MagicMock(return_value=True)
    gateway.send_order = MagicMock(return_value=None)
    gateway.cancel_order = MagicMock(return_value=True)
    gateway.subscribe = MagicMock(return_value=True)
    gateway.get_trades = MagicMock(return_value={})
    gateway.get_account = MagicMock(return_value=None)
    gateway.get_orders = MagicMock(return_value={})
    gateway.get_positions = MagicMock(return_value={})
    gateway.get_quotes = MagicMock(return_value={})
    gateway.register_callbacks = MagicMock()
    return gateway


@pytest.fixture
def mock_event_engine():
    """模拟EventEngine"""
    engine = MagicMock()
    engine.put = MagicMock()
    return engine


@pytest.fixture
def mock_risk_control():
    """模拟RiskControl"""
    rc = MagicMock()
    rc.check_order = MagicMock(return_value=True)
    rc.on_order_inserted = MagicMock()
    rc.get_status = MagicMock(return_value={})
    rc.config = MagicMock()
    rc.daily_order_count = 0
    rc.daily_cancel_count = 0
    return rc


@pytest.fixture
def trading_engine(mock_account_config, mock_risk_control):
    """创建TradingEngine实例"""
    with patch("src.trader.trading_engine.ctx"), \
         patch("src.trader.trading_engine.get_app_context"):
        # Create engine without patching RiskControl
        engine = TradingEngine(mock_account_config)
        # Set risk_control manually
        engine.risk_control = mock_risk_control
        return engine


# ==================== Test Initialization ====================


class TestTradingEngineInit:
    """测试 TradingEngine 初始化"""

    def test_init_with_account_config(self, trading_engine, mock_account_config):
        """测试使用账户配置初始化"""
        assert trading_engine.config == mock_account_config
        assert trading_engine.account_id == "test_account_001"

    def test_init_paused_state_from_config(self, trading_engine):
        """测试从配置获取暂停状态"""
        assert hasattr(trading_engine, "paused")

    def test_init_gateway_initialization(self, trading_engine):
        """测试Gateway初始化"""
        assert trading_engine.gateway is not None

    def test_init_event_engine(self, trading_engine):
        """测试事件引擎"""
        assert trading_engine.event_engine is not None


# ==================== Test Properties ====================


class TestTradingEngineProperties:
    """测试 TradingEngine 属性"""

    def test_connected_property_no_gateway(self, trading_engine):
        """测试无Gateway时连接状态"""
        trading_engine.gateway = None
        assert trading_engine.connected is False

    def test_connected_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时连接状态"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        assert trading_engine.connected is True

    def test_trades_property_no_gateway(self, trading_engine):
        """测试无Gateway时成交数据"""
        trading_engine.gateway = None
        assert trading_engine.trades == {}

    def test_trades_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时成交数据"""
        trading_engine.gateway = mock_gateway
        mock_trade = MagicMock()
        mock_gateway.get_trades.return_value = {"trade_1": mock_trade}
        result = trading_engine.trades
        assert mock_gateway.get_trades.called
        assert "trade_1" in result
        assert result["trade_1"] == mock_trade

    def test_account_property_no_gateway(self, trading_engine):
        """测试无Gateway时账户数据"""
        trading_engine.gateway = None
        assert trading_engine.account is None

    def test_account_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时账户数据"""
        trading_engine.gateway = mock_gateway
        mock_account = MagicMock(spec=AccountData)
        mock_account.model_dump = MagicMock(return_value={"account_id": "test"})
        mock_account.gateway_connected = False
        mock_gateway.get_account.return_value = mock_account

        result = trading_engine.account
        assert result.gateway_connected is False
        assert result.user_id == "test_user"

    def test_orders_property_no_gateway(self, trading_engine):
        """测试无Gateway时订单数据"""
        trading_engine.gateway = None
        assert trading_engine.orders == {}

    def test_orders_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时订单数据"""
        trading_engine.gateway = mock_gateway
        mock_order = MagicMock()
        mock_gateway.get_orders.return_value = {"order_1": mock_order}
        result = trading_engine.orders
        assert mock_gateway.get_orders.called
        assert "order_1" in result
        assert result["order_1"] == mock_order

    def test_positions_property_no_gateway(self, trading_engine):
        """测试无Gateway时持仓数据"""
        trading_engine.gateway = None
        assert trading_engine.positions == {}

    def test_positions_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时持仓数据"""
        trading_engine.gateway = mock_gateway
        mock_position = MagicMock()
        mock_gateway.get_positions.return_value = {"pos_1": mock_position}
        result = trading_engine.positions
        assert mock_gateway.get_positions.called
        assert "pos_1" in result
        assert result["pos_1"] == mock_position

    def test_quotes_property_no_gateway(self, trading_engine):
        """测试无Gateway时行情数据"""
        trading_engine.gateway = None
        assert trading_engine.quotes == {}

    def test_quotes_property_with_gateway(self, trading_engine, mock_gateway):
        """测试有Gateway时行情数据"""
        trading_engine.gateway = mock_gateway
        mock_quote = MagicMock()
        mock_gateway.get_quotes.return_value = {"quote_1": mock_quote}
        result = trading_engine.quotes
        assert mock_gateway.get_quotes.called
        assert "quote_1" in result
        assert result["quote_1"] == mock_quote


# ==================== Test Connect/Disconnect ====================


class TestTradingEngineConnectDisconnect:
    """测试连接和断开"""

    def test_connect_success(self, trading_engine, mock_gateway):
        """测试成功连接"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connect.return_value = True

        result = trading_engine.connect()

        assert result is True
        mock_gateway.connect.assert_called_once()

    def test_connect_no_gateway(self, trading_engine):
        """测试无Gateway时连接"""
        trading_engine.gateway = None

        result = trading_engine.connect()

        assert result is False

    def test_connect_exception(self, trading_engine, mock_gateway):
        """测试连接异常"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connect.side_effect = Exception("Connection error")

        result = trading_engine.connect()

        assert result is False

    def test_disconnect_success(self, trading_engine, mock_gateway):
        """测试成功断开"""
        trading_engine.gateway = mock_gateway
        mock_gateway.disconnect.return_value = True

        result = trading_engine.disconnect()

        assert result is True
        mock_gateway.disconnect.assert_called_once()

    def test_disconnect_no_gateway(self, trading_engine):
        """测试无Gateway时断开"""
        trading_engine.gateway = None

        result = trading_engine.disconnect()

        assert result is False

    def test_disconnect_exception(self, trading_engine, mock_gateway):
        """测试断开异常"""
        trading_engine.gateway = mock_gateway
        mock_gateway.disconnect.side_effect = Exception("Disconnect error")

        result = trading_engine.disconnect()

        assert result is False


# ==================== Test Insert Order ====================


class TestTradingEngineInsertOrder:
    """测试下单"""

    def test_insert_order_success(self, trading_engine, mock_gateway):
        """测试成功下单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        mock_order = MagicMock(spec=OrderData)
        mock_order.order_id = "order_123"
        mock_gateway.send_order.return_value = mock_order
        trading_engine.paused = False

        result = trading_engine.insert_order(
            symbol="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=3500.0
        )

        assert result == "order_123"

    def test_insert_order_market_order(self, trading_engine, mock_gateway):
        """测试市价下单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        mock_order = MagicMock(spec=OrderData)
        mock_order.order_id = "order_123"
        mock_gateway.send_order.return_value = mock_order
        trading_engine.paused = False

        result = trading_engine.insert_order(
            symbol="SHFE.rb2505",
            direction="BUY",
            offset="OPEN",
            volume=1,
            price=0
        )

        assert result == "order_123"

    def test_insert_order_not_connected(self, trading_engine, mock_gateway):
        """测试未连接时下单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = False

        with pytest.raises(Exception, match="交易引擎未连接"):
            trading_engine.insert_order("SHFE.rb2505", "BUY", "OPEN", 1)

    def test_insert_order_paused(self, trading_engine, mock_gateway):
        """测试暂停时下单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        trading_engine.paused = True

        with pytest.raises(Exception, match="交易已暂停"):
            trading_engine.insert_order("SHFE.rb2505", "BUY", "OPEN", 1)

    def test_insert_order_risk_control_failure(self, trading_engine, mock_gateway, mock_risk_control):
        """测试风控检查失败"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        trading_engine.paused = False
        trading_engine.risk_control = mock_risk_control
        mock_risk_control.check_order.return_value = False

        with pytest.raises(Exception, match="风控检查失败"):
            trading_engine.insert_order("SHFE.rb2505", "BUY", "OPEN", 1)

    def test_insert_order_no_gateway(self, trading_engine):
        """测试无Gateway时下单"""
        trading_engine.gateway = None
        trading_engine.paused = False

        with pytest.raises(Exception):
            trading_engine.insert_order("SHFE.rb2505", "BUY", "OPEN", 1)


# ==================== Test Cancel Order ====================


class TestTradingEngineCancelOrder:
    """测试撤单"""

    def test_cancel_order_success(self, trading_engine, mock_gateway):
        """测试成功撤单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        mock_gateway.cancel_order.return_value = True

        result = trading_engine.cancel_order("order_123")

        assert result is True

    def test_cancel_order_not_connected(self, trading_engine, mock_gateway):
        """测试未连接时撤单"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = False

        result = trading_engine.cancel_order("order_123")

        assert result is False

    def test_cancel_order_no_gateway(self, trading_engine):
        """测试无Gateway时撤单"""
        trading_engine.gateway = None

        result = trading_engine.cancel_order("order_123")

        assert result is False


# ==================== Test Pause/Resume ====================


class TestTradingEnginePauseResume:
    """测试暂停和恢复交易"""

    def test_pause(self, trading_engine, mock_event_engine, mock_gateway):
        """测试暂停交易"""
        trading_engine.gateway = mock_gateway
        # Mock get_account to return a proper AccountData-like object
        mock_account = MagicMock()
        mock_account.model_dump = MagicMock(return_value={"account_id": "test"})
        mock_gateway.get_account.return_value = mock_account
        trading_engine.paused = False
        trading_engine.event_engine = mock_event_engine

        trading_engine.pause()

        assert trading_engine.paused is True
        mock_event_engine.put.assert_called()

    def test_pause_with_account_data(self, trading_engine, mock_event_engine, mock_gateway):
        """测试暂停时有账户数据"""
        trading_engine.gateway = mock_gateway
        mock_account = MagicMock()
        mock_account.model_dump = MagicMock(return_value={"account_id": "test"})
        mock_gateway.get_account.return_value = mock_account
        trading_engine.paused = False
        trading_engine.event_engine = mock_event_engine

        trading_engine.pause()

        assert trading_engine.paused is True

    def test_resume(self, trading_engine, mock_event_engine, mock_gateway):
        """测试恢复交易"""
        trading_engine.gateway = mock_gateway
        # Mock get_account to return a proper AccountData-like object
        mock_account = MagicMock()
        mock_account.model_dump = MagicMock(return_value={"account_id": "test"})
        mock_gateway.get_account.return_value = mock_account
        trading_engine.paused = True
        trading_engine.event_engine = mock_event_engine

        trading_engine.resume()

        assert trading_engine.paused is False
        mock_event_engine.put.assert_called()

    def test_resume_with_account_data(self, trading_engine, mock_event_engine, mock_gateway):
        """测试恢复时有账户数据"""
        trading_engine.gateway = mock_gateway
        mock_account = MagicMock()
        mock_account.model_dump = MagicMock(return_value={"account_id": "test"})
        mock_gateway.get_account.return_value = mock_account
        trading_engine.paused = True
        trading_engine.event_engine = mock_event_engine

        trading_engine.resume()

        assert trading_engine.paused is False


# ==================== Test Get Status ====================


class TestTradingEngineGetStatus:
    """测试获取状态"""

    def test_get_status(self, trading_engine):
        """测试获取引擎状态"""
        trading_engine.paused = False

        with patch.object(trading_engine, "gateway", MagicMock(connected=True)):
            status = trading_engine.get_status()

            assert status["connected"] is True
            assert status["paused"] is False

    def test_get_status_no_gateway(self, trading_engine):
        """测试无Gateway时获取状态"""
        # Set gateway to None to test the no-gateway case
        trading_engine.gateway = None
        status = trading_engine.get_status()

        assert status["connected"] is False


# ==================== Test Subscribe Symbol ====================


class TestTradingEngineSubscribeSymbol:
    """测试订阅合约"""

    def test_subscribe_symbol_success(self, trading_engine, mock_gateway):
        """测试成功订阅"""
        trading_engine.gateway = mock_gateway
        mock_gateway.subscribe.return_value = True

        result = trading_engine.subscribe_symbol("SHFE.rb2505")

        assert result is True

    def test_subscribe_symbol_list(self, trading_engine, mock_gateway):
        """测试订阅多个合约"""
        trading_engine.gateway = mock_gateway
        mock_gateway.subscribe.return_value = True

        result = trading_engine.subscribe_symbol(["SHFE.rb2505", "SHFE.rb2506"])

        assert result is True

    def test_subscribe_symbol_empty(self, trading_engine, mock_gateway):
        """测试订阅空列表"""
        trading_engine.gateway = mock_gateway

        result = trading_engine.subscribe_symbol("")

        assert result is False

    def test_subscribe_symbol_no_gateway(self, trading_engine):
        """测试无Gateway时订阅"""
        trading_engine.gateway = None

        result = trading_engine.subscribe_symbol("SHFE.rb2505")

        assert result is False


# ==================== Test Emit Event ====================


class TestTradingEngineEmitEvent:
    """测试推送事件"""

    def test_emit_event(self, trading_engine, mock_event_engine):
        """测试推送事件"""
        trading_engine.event_engine = mock_event_engine

        trading_engine._emit_event("test_event", {"key": "value"})

        mock_event_engine.put.assert_called_once_with("test_event", {"key": "value"})

    def test_emit_event_no_event_engine(self, trading_engine):
        """测试无事件引擎时推送"""
        trading_engine.event_engine = None

        # Should not raise exception
        trading_engine._emit_event("test_event", {"key": "value"})

    def test_emit_event_exception(self, trading_engine):
        """测试推送事件异常"""
        trading_engine.event_engine = MagicMock()
        trading_engine.event_engine.put.side_effect = Exception("Event error")

        # Should not raise exception
        trading_engine._emit_event("test_event", {"key": "value"})


# ==================== Test Gateway Callbacks ====================


class TestTradingEngineGatewayCallbacks:
    """测试Gateway回调"""

    def test_on_tick(self, trading_engine, mock_event_engine):
        """测试tick回调"""
        trading_engine.event_engine = mock_event_engine
        tick = TickData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime.now(),
            last_price=Decimal("3500")
        )

        trading_engine._on_tick(tick)

        mock_event_engine.put.assert_called_once_with(EventTypes.TICK_UPDATE, tick)

    def test_on_bar(self, trading_engine, mock_event_engine):
        """测试bar回调"""
        trading_engine.event_engine = mock_event_engine
        bar = BarData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            interval=Interval.MINUTE,
            datetime=datetime.now(),
            open_price=Decimal("3490"),
            high_price=Decimal("3510"),
            low_price=Decimal("3485"),
            close_price=Decimal("3500"),
            volume=1000
        )

        trading_engine._on_bar(bar)

        mock_event_engine.put.assert_called_once()
        call_args = mock_event_engine.put.call_args
        assert call_args[0][0] == EventTypes.KLINE_UPDATE
        assert "symbol" in call_args[0][1]

    def test_on_order(self, trading_engine, mock_event_engine):
        """测试order回调"""
        trading_engine.event_engine = mock_event_engine
        order = OrderData(
            order_id="order_123",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
            account_id="test_account"
        )

        trading_engine._on_order(order)

        mock_event_engine.put.assert_called_once_with(EventTypes.ORDER_UPDATE, order)

    def test_on_trade(self, trading_engine, mock_event_engine):
        """测试trade回调"""
        trading_engine.event_engine = mock_event_engine
        trade = TradeData(
            trade_id="trade_123",
            order_id="order_123",
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            account_id="test_account"
        )

        trading_engine._on_trade(trade)

        mock_event_engine.put.assert_called_once_with(EventTypes.TRADE_UPDATE, trade)

    def test_on_position(self, trading_engine, mock_event_engine):
        """测试position回调"""
        trading_engine.event_engine = mock_event_engine
        position = PositionData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            pos=1,
            pos_long=0,
            pos_short=1
        )

        trading_engine._on_position(position)

        mock_event_engine.put.assert_called_once_with(EventTypes.POSITION_UPDATE, position)

    def test_on_account(self, trading_engine, mock_event_engine):
        """测试account回调"""
        trading_engine.event_engine = mock_event_engine
        account = AccountData(account_id="test_account")

        trading_engine._on_account(account)

        mock_event_engine.put.assert_called_once_with(EventTypes.ACCOUNT_UPDATE, account)


# ==================== Edge Cases ====================


class TestTradingEngineEdgeCases:
    """测试边界情况"""

    def test_init_gateway_ctp_type(self, mock_account_config):
        """测试CTP类型Gateway初始化"""
        mock_account_config.gateway.type = "CTP"

        with patch("src.trader.trading_engine.ctx"), \
             patch("src.trader.trading_engine.get_app_context"), \
             patch("src.trader.trading_engine.RiskControl", return_value=MagicMock()), \
             patch("src.trader.gateway.ctp_gateway.CtpGateway") as mock_ctp:
            engine = TradingEngine(mock_account_config)

            # CTP Gateway should be created (even if mocked)
            assert mock_ctp.called

    def test_insert_order_returns_none(self, trading_engine, mock_gateway):
        """测试下单返回None"""
        trading_engine.gateway = mock_gateway
        mock_gateway.connected = True
        mock_gateway.send_order.return_value = None
        trading_engine.paused = False

        result = trading_engine.insert_order(
            "SHFE.rb2505", "BUY", "OPEN", 1
        )

        assert result is None
