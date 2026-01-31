"""测试数据模型

包含所有业务数据模型的单元测试
"""
import pytest
from datetime import datetime
from decimal import Decimal

from src.models.object import (
    AccountData,
    PositionData,
    OrderData,
    TradeData,
    TickData,
    BarData,
    ContractData,
    OrderRequest,
    CancelRequest,
    SubscribeRequest,
    Exchange,
    Direction,
    Offset,
    OrderStatus,
)


class TestAccountModel:
    """测试账户数据模型"""

    def test_account_creation(self):
        """测试创建账户数据"""
        account = AccountData(
            account_id="test_account",
            balance=Decimal("100000.0"),
            available=Decimal("95000.0"),
            frozen=Decimal("5000.0"),
        )
        assert account.account_id == "test_account"
        assert account.balance == Decimal("100000.0")
        assert account.available == Decimal("95000.0")

    def test_account_repr(self):
        """测试账户数据字符串表示"""
        account = AccountData(
            account_id="test", balance=Decimal("1000.0"), available=Decimal("1000.0")
        )
        repr_str = repr(account)
        assert "test" in repr_str

    def test_account_margin_property(self):
        """测试账户保证金计算"""
        account = AccountData(
            account_id="test",
            balance=Decimal("100000.0"),
            available=Decimal("95000.0"),
            margin=Decimal("5000.0"),
        )
        assert account.margin == Decimal("5000.0")


class TestPositionModel:
    """测试持仓数据模型"""

    def test_position_creation(self):
        """测试创建持仓数据"""
        position = PositionData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            pos=10,
            pos_long=10,
            pos_short=0,
            pos_long_yd=5,
            pos_short_yd=0,
            pos_long_td=5,
            pos_short_td=0,
            open_price_long=Decimal("3500.0"),
            open_price_short=Decimal("0.0"),
            float_profit_long=Decimal("100.0"),
            float_profit_short=Decimal("0.0"),
            hold_profit_long=Decimal("50.0"),
            hold_profit_short=Decimal("0.0"),
            margin_long=Decimal("10000.0"),
            margin_short=Decimal("0.0"),
        )
        assert position.symbol == "SHFE.rb2505"
        assert position.pos == 10
        assert position.pos_long == 10

    def test_position_net_position(self):
        """测试持仓净头寸（pos 需要显式提供）"""
        position = PositionData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            pos=7,  # net position
            pos_long=10,
            pos_short=3,
        )
        assert position.pos == 7
        assert position.pos_long == 10
        assert position.pos_short == 3


class TestOrderModel:
    """测试订单数据模型"""

    def test_order_creation(self):
        """测试创建订单数据"""
        order = OrderData(
            order_id="order_001",
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            price=Decimal("3500.0"),
            account_id="test_account",
        )
        assert order.order_id == "order_001"
        assert order.volume == 5
        assert order.status == OrderStatus.SUBMITTING

    def test_order_volume_left(self):
        """测试订单剩余数量计算"""
        order = OrderData(
            order_id="order_001",
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=10,
            traded=3,
            price=Decimal("3500.0"),
            account_id="test_account",
        )
        assert order.volume_left == 7

    def test_order_all_traded(self):
        """测试订单全部成交"""
        order = OrderData(
            order_id="order_002",
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=10,
            traded=10,
            price=Decimal("3500.0"),
            account_id="test_account",
            status=OrderStatus.ALLTRADED,
        )
        assert order.volume_left == 0
        assert order.status == OrderStatus.ALLTRADED

    def test_order_status_transitions(self):
        """测试订单状态流转"""
        order = OrderData(
            order_id="order_003",
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=10,
            price=Decimal("3500.0"),
            account_id="test_account",
        )
        assert order.status == OrderStatus.SUBMITTING
        # 状态可以更新
        order.status = OrderStatus.NOTTRADED
        assert order.status == OrderStatus.NOTTRADED
        order.status = OrderStatus.PARTTRADED
        assert order.status == OrderStatus.PARTTRADED


class TestTradeModel:
    """测试成交数据模型"""

    def test_trade_creation(self):
        """测试创建成交数据"""
        trade = TradeData(
            trade_id="trade_001",
            order_id="order_001",
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            price=Decimal("3500.0"),
            volume=5,
            account_id="test_account",
        )
        assert trade.trade_id == "trade_001"
        assert trade.volume == 5
        assert trade.price == Decimal("3500.0")

    def test_trade_with_datetime(self):
        """测试成交数据包含时间"""
        now = datetime.now()
        trade = TradeData(
            trade_id="trade_002",
            order_id="order_002",
            symbol="SHFE.ag2505",
            exchange=Exchange.SHFE,
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            price=Decimal("4500.0"),
            volume=3,
            trade_time=now,
            account_id="test_account",
        )
        assert trade.trade_id == "trade_002"
        assert trade.trade_time == now


class TestTickData:
    """测试行情数据模型"""

    def test_tick_creation(self):
        """测试创建 tick 数据"""
        tick = TickData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            last_price=Decimal("3500.0"),
            bid_price_1=Decimal("3499.0"),
            ask_price_1=Decimal("3501.0"),
            volume=1000,
            open_interest=5000,
            datetime=datetime.now(),
        )
        assert tick.symbol == "SHFE.rb2505"
        assert tick.last_price == Decimal("3500.0")
        assert tick.volume == 1000


class TestBarData:
    """测试 K 线数据模型"""

    def test_bar_creation(self):
        """测试创建 K 线数据"""
        now = datetime.now()
        bar = BarData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            datetime=now,
            interval="1m",
            open_price=Decimal("3480.0"),
            high_price=Decimal("3520.0"),
            low_price=Decimal("3475.0"),
            close_price=Decimal("3510.0"),
            volume=5000,
        )
        assert bar.symbol == "SHFE.rb2505"
        assert bar.high_price >= bar.low_price
        assert bar.volume == 5000


class TestContractData:
    """测试合约数据模型"""

    def test_contract_creation(self):
        """测试创建合约数据"""
        contract = ContractData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            name="螺纹钢2505",
            multiple=10,
            pricetick=Decimal("1.0"),
        )
        assert contract.symbol == "SHFE.rb2505"
        assert contract.multiple == 10
        assert contract.pricetick == Decimal("1.0")


class TestOrderRequest:
    """测试下单请求数据模型"""

    def test_order_request_creation(self):
        """测试创建下单请求"""
        req = OrderRequest(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            price=Decimal("3500.0"),
        )
        assert req.symbol == "SHFE.rb2505"
        assert req.direction == Direction.BUY
        assert req.volume == 5

    def test_order_request_market_price(self):
        """测试市价单请求（价格为 None）"""
        req = OrderRequest(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            price=None,
        )
        assert req.price is None


class TestCancelRequest:
    """测试撤单请求数据模型"""

    def test_cancel_request_creation(self):
        """测试创建撤单请求"""
        req = CancelRequest(order_id="order_001")
        assert req.order_id == "order_001"


class TestSubscribeRequest:
    """测试订阅请求数据模型"""

    def test_subscribe_request_creation(self):
        """测试创建订阅请求"""
        req = SubscribeRequest(symbols=["SHFE.rb2505"])
        assert "SHFE.rb2505" in req.symbols

    def test_subscribe_request_multiple_symbols(self):
        """测试订阅多个合约"""
        req = SubscribeRequest(
            symbols=["SHFE.rb2505", "SHFE.ag2505", "DCE.m2505"]
        )
        assert len(req.symbols) == 3
        assert "SHFE.rb2505" in req.symbols


class TestEnums:
    """测试枚举类型"""

    def test_exchange_values(self):
        """测试交易所枚举值"""
        assert Exchange.SHFE.value == "SHFE"
        assert Exchange.DCE.value == "DCE"
        assert Exchange.CZCE.value == "CZCE"
        assert Exchange.CFFEX.value == "CFFEX"
        assert Exchange.INE.value == "INE"

    def test_direction_values(self):
        """测试方向枚举值"""
        assert Direction.BUY.value == "BUY"
        assert Direction.SELL.value == "SELL"

    def test_offset_values(self):
        """测试开平枚举值"""
        assert Offset.OPEN.value == "OPEN"
        assert Offset.CLOSE.value == "CLOSE"
        assert Offset.CLOSETODAY.value == "CLOSETODAY"

    def test_order_status_values(self):
        """测试订单状态枚举值"""
        assert OrderStatus.SUBMITTING.value == "SUBMITTING"
        assert OrderStatus.NOTTRADED.value == "NOTTRADED"
        assert OrderStatus.PARTTRADED.value == "PARTTRADED"
        assert OrderStatus.ALLTRADED.value == "ALLTRADED"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
        assert OrderStatus.REJECTED.value == "REJECTED"

    def test_enum_from_string(self):
        """测试从字符串创建枚举"""
        assert Exchange("SHFE") == Exchange.SHFE
        assert Direction("BUY") == Direction.BUY
        assert Offset("OPEN") == Offset.OPEN
        assert OrderStatus("ALLTRADED") == OrderStatus.ALLTRADED

    def test_enum_invalid_value(self):
        """测试无效枚举值"""
        with pytest.raises(ValueError):
            Exchange("INVALID")
        with pytest.raises(ValueError):
            Direction("INVALID")
