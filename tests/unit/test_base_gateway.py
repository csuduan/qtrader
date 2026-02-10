"""
BaseGateway 单元测试
测试 BaseGateway 抽象基类的所有方法和功能
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock
import pytest

from src.trader.gateway.base_gateway import BaseGateway
from src.models.object import (
    Direction,
    Offset,
    OrderData,
    TradeData,
    PositionData,
    AccountData,
    TickData,
    BarData,
    Exchange,
    OrderRequest,
    CancelRequest,
    ContractData,
    Interval,
)


class MockConcreteGateway(BaseGateway):
    gateway_name = "MockGateway"
    exchanges = [Exchange.SHFE, Exchange.DCE]

    def __init__(self):
        super().__init__()

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> bool:
        self.connected = False
        return True

    def subscribe(self, symbol) -> bool:
        return True

    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        order = OrderData(
            order_id=f"order_{id(req)}",
            symbol=req.symbol,
            direction=req.direction,
            offset=req.offset,
            volume=req.volume,
            price=Decimal(str(req.price)) if req.price else Decimal("0"),
            traded=0,
            status="SUBMITTING",
            account_id="test_account",
        )
        return order

    def cancel_order(self, req: CancelRequest) -> bool:
        return True

    def get_account(self) -> Optional[AccountData]:
        return AccountData(
            account_id="test_account",
            balance=Decimal("100000"),
            available=Decimal("95000"),
            frozen=Decimal("5000"),
        )

    def get_positions(self):
        return {"SHFE.rb2505": PositionData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos=1, pos_long=1, pos_short=0
        )}

    def get_orders(self):
        return {"order_123": OrderData(
            order_id="order_123", symbol="SHFE.rb2505", direction=Direction.BUY,
            offset=Offset.OPEN, volume=1, price=Decimal("3500"),
            traded=0, status="ACTIVE", account_id="test_account"
        )}

    def get_trades(self):
        return {"trade_123": TradeData(
            trade_id="trade_123", order_id="order_123", symbol="SHFE.rb2505",
            direction=Direction.BUY, offset=Offset.OPEN, volume=1,
            price=Decimal("3500"), account_id="test_account"
        )}

    def get_contracts(self):
        return {"SHFE.rb2505": ContractData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, name="螺纹钢2505",
            product_class="rb", volume_multiple=10, price_tick=1, min_volume=1
        )}

    def get_quotes(self):
        return {"SHFE.rb2505": TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )}


@pytest.fixture
def mock_gateway():
    return MockConcreteGateway()


class TestBaseGatewayInitialization:
    def test_init_sets_connected_false(self, mock_gateway):
        assert mock_gateway.connected is False

    def test_init_sets_trading_day_none(self, mock_gateway):
        assert mock_gateway.trading_day is None

    def test_init_all_callbacks_none(self, mock_gateway):
        assert mock_gateway.on_tick_callback is None
        assert mock_gateway.on_bar_callback is None
        assert mock_gateway.on_order_callback is None
        assert mock_gateway.on_trade_callback is None
        assert mock_gateway.on_position_callback is None
        assert mock_gateway.on_account_callback is None
        assert mock_gateway.on_contract_callback is None

    def test_gateway_name_attribute(self, mock_gateway):
        assert mock_gateway.gateway_name == "MockGateway"

    def test_exchanges_attribute(self, mock_gateway):
        assert mock_gateway.exchanges == [Exchange.SHFE, Exchange.DCE]


class TestBaseGatewayRegisterCallbacks:
    def test_register_callbacks_all(self, mock_gateway):
        callbacks = {
            "on_tick": MagicMock(), "on_bar": MagicMock(), "on_order": MagicMock(),
            "on_trade": MagicMock(), "on_position": MagicMock(),
            "on_account": MagicMock(), "on_contract": MagicMock()
        }
        mock_gateway.register_callbacks(**callbacks)
        assert mock_gateway.on_tick_callback == callbacks["on_tick"]


class TestBaseGatewayRegisterStrategyCallbacks:
    def test_register_strategy_callbacks_both(self, mock_gateway):
        on_tick = MagicMock()
        on_bar = MagicMock()
        mock_gateway.register_strategy_callbacks(on_tick=on_tick, on_bar=on_bar)
        assert mock_gateway.on_tick_strategy == on_tick
        assert mock_gateway.on_bar_strategy == on_bar


class TestBaseGatewayEmitTick:
    def test_emit_tick_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_tick=callback)
        tick = TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )
        mock_gateway._emit_tick(tick)
        callback.assert_called_once_with(tick)

    def test_emit_tick_with_strategy_callback(self, mock_gateway):
        callback = MagicMock()
        strategy_callback = MagicMock()
        mock_gateway.register_callbacks(on_tick=callback)
        mock_gateway.register_strategy_callbacks(on_tick=strategy_callback, on_bar=strategy_callback)
        tick = TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )
        mock_gateway._emit_tick(tick)
        callback.assert_called_once_with(tick)
        strategy_callback.assert_called_once_with(tick)

    def test_emit_tick_no_callback(self, mock_gateway):
        tick = TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )
        mock_gateway._emit_tick(tick)


class TestBaseGatewayEmitBar:
    def test_emit_bar_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_bar=callback)
        bar = BarData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, interval=Interval.MINUTE,
            datetime=datetime.now(), open_price=Decimal("3490"),
            high_price=Decimal("3510"), low_price=Decimal("3485"),
            close_price=Decimal("3500"), volume=1000
        )
        mock_gateway._emit_bar(bar)
        callback.assert_called_once_with(bar)

    def test_emit_bar_with_strategy_callback(self, mock_gateway):
        callback = MagicMock()
        strategy_callback = MagicMock()
        mock_gateway.register_callbacks(on_bar=callback)
        mock_gateway.register_strategy_callbacks(on_tick=strategy_callback, on_bar=strategy_callback)
        bar = BarData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, interval=Interval.MINUTE,
            datetime=datetime.now(), open_price=Decimal("3490"),
            high_price=Decimal("3510"), low_price=Decimal("3485"),
            close_price=Decimal("3500"), volume=1000
        )
        mock_gateway._emit_bar(bar)
        callback.assert_called_once_with(bar)
        strategy_callback.assert_called_once_with(bar)

    def test_emit_bar_no_callback(self, mock_gateway):
        bar = BarData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, interval=Interval.MINUTE,
            datetime=datetime.now(), open_price=Decimal("3490"),
            high_price=Decimal("3510"), low_price=Decimal("3485"),
            close_price=Decimal("3500"), volume=1000
        )
        mock_gateway._emit_bar(bar)


class TestBaseGatewayEmitOrder:
    def test_emit_order_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_order=callback)
        order = OrderData(
            order_id="order_123", symbol="SHFE.rb2505", direction=Direction.BUY,
            offset=Offset.OPEN, volume=1, price=Decimal("3500"),
            traded=0, status="ACTIVE", account_id="test_account"
        )
        mock_gateway._emit_order(order)
        callback.assert_called_once_with(order)

    def test_emit_order_no_callback(self, mock_gateway):
        order = OrderData(
            order_id="order_123", symbol="SHFE.rb2505", direction=Direction.BUY,
            offset=Offset.OPEN, volume=1, price=Decimal("3500"),
            traded=0, status="ACTIVE", account_id="test_account"
        )
        mock_gateway._emit_order(order)


class TestBaseGatewayEmitTrade:
    def test_emit_trade_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_trade=callback)
        trade = TradeData(
            trade_id="trade_123", order_id="order_123", symbol="SHFE.rb2505",
            direction=Direction.BUY, offset=Offset.OPEN, volume=1,
            price=Decimal("3500"), account_id="test_account"
        )
        mock_gateway._emit_trade(trade)
        callback.assert_called_once_with(trade)

    def test_emit_trade_no_callback(self, mock_gateway):
        trade = TradeData(
            trade_id="trade_123", order_id="order_123", symbol="SHFE.rb2505",
            direction=Direction.BUY, offset=Offset.OPEN, volume=1,
            price=Decimal("3500"), account_id="test_account"
        )
        mock_gateway._emit_trade(trade)


class TestBaseGatewayEmitPosition:
    def test_emit_position_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_position=callback)
        position = PositionData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos=1, pos_long=1, pos_short=0
        )
        mock_gateway._emit_position(position)
        callback.assert_called_once_with(position)

    def test_emit_position_no_callback(self, mock_gateway):
        position = PositionData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos=1, pos_long=1, pos_short=0
        )
        mock_gateway._emit_position(position)


class TestBaseGatewayEmitAccount:
    def test_emit_account_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_account=callback)
        account = AccountData(
            account_id="test_account", balance=Decimal("100000"),
            available=Decimal("95000"), frozen=Decimal("5000")
        )
        mock_gateway._emit_account(account)
        callback.assert_called_once_with(account)

    def test_emit_account_no_callback(self, mock_gateway):
        account = AccountData(
            account_id="test_account", balance=Decimal("100000"),
            available=Decimal("95000"), frozen=Decimal("5000")
        )
        mock_gateway._emit_account(account)


class TestBaseGatewayEmitContract:
    def test_emit_contract_with_callback(self, mock_gateway):
        callback = MagicMock()
        mock_gateway.register_callbacks(on_contract=callback)
        contract = ContractData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, name="螺纹钢2505",
            product_class="rb", volume_multiple=10, price_tick=1, min_volume=1
        )
        mock_gateway._emit_contract(contract)
        callback.assert_called_once_with(contract)

    def test_emit_contract_no_callback(self, mock_gateway):
        contract = ContractData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE, name="螺纹钢2505",
            product_class="rb", volume_multiple=10, price_tick=1, min_volume=1
        )
        mock_gateway._emit_contract(contract)


class TestBaseGatewayAbstractMethods:
    def test_connect_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.connect()
        assert result is True
        assert gateway.connected is True

    def test_disconnect_is_abstract(self):
        gateway = MockConcreteGateway()
        gateway.connect()
        result = gateway.disconnect()
        assert result is True
        assert gateway.connected is False

    def test_subscribe_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.subscribe("SHFE.rb2505")
        assert result is True

    def test_send_order_is_abstract(self):
        gateway = MockConcreteGateway()
        req = OrderRequest(
            symbol="SHFE.rb2505", direction=Direction.BUY,
            offset=Offset.OPEN, volume=1, price=Decimal("3500")
        )
        result = gateway.send_order(req)
        assert result is not None
        assert result.order_id is not None

    def test_cancel_order_is_abstract(self):
        gateway = MockConcreteGateway()
        req = CancelRequest(order_id="order_123")
        result = gateway.cancel_order(req)
        assert result is True

    def test_get_account_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_account()
        assert result is not None
        assert result.account_id == "test_account"

    def test_get_positions_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_positions()
        assert isinstance(result, dict)
        assert "SHFE.rb2505" in result

    def test_get_orders_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_orders()
        assert isinstance(result, dict)
        assert "order_123" in result

    def test_get_trades_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_trades()
        assert isinstance(result, dict)
        assert "trade_123" in result

    def test_get_contracts_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_contracts()
        assert isinstance(result, dict)
        assert "SHFE.rb2505" in result

    def test_get_quotes_is_abstract(self):
        gateway = MockConcreteGateway()
        result = gateway.get_quotes()
        assert isinstance(result, dict)
        assert "SHFE.rb2505" in result


class TestBaseGatewayEdgeCases:
    def test_emit_tick_none_callback_not_crash(self, mock_gateway):
        mock_gateway.on_tick_callback = None
        tick = TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )
        mock_gateway._emit_tick(tick)

    def test_multiple_callback_registrations(self, mock_gateway):
        callback1 = MagicMock()
        callback2 = MagicMock()
        mock_gateway.register_callbacks(on_tick=callback1)
        mock_gateway.register_callbacks(on_tick=callback2)
        assert mock_gateway.on_tick_callback == callback2

    def test_emit_to_callback_that_raises(self, mock_gateway):
        def failing_callback(data):
            raise ValueError("Test error")
        mock_gateway.register_callbacks(on_tick=failing_callback)
        tick = TickData(
            symbol="SHFE.rb2505", exchange=Exchange.SHFE,
            datetime=datetime.now(), last_price=Decimal("3500")
        )
        with pytest.raises(ValueError, match="Test error"):
            mock_gateway._emit_tick(tick)
