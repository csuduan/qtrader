import pytest
from datetime import datetime

from src.models.object import (
    Direction,
    PosDirection,
    Offset,
    OrderStatus,
    ProductType,
    Exchange,
    Interval,
    OrderType,
    OrderData,
    TradeData,
    TickData,
    BarData
)


@pytest.mark.unit
class TestEnums:
    """枚举类型测试"""
    
    def test_direction_enum(self):
        """测试买卖方向枚举"""
        assert Direction.BUY == "BUY"
        assert Direction.SELL == "SELL"
        assert len(Direction) == 2
    
    def test_direction_enum_values(self):
        """测试方向枚举值"""
        values = [d.value for d in Direction]
        assert "BUY" in values
        assert "SELL" in values
    
    def test_pos_direction_enum(self):
        """测试持仓方向枚举"""
        assert PosDirection.LONG == "LONG"
        assert PosDirection.SHORT == "SHORT"
        assert PosDirection.NET == "NET"
        assert len(PosDirection) == 3
    
    def test_offset_enum(self):
        """测试开平类型枚举"""
        assert Offset.OPEN == "OPEN"
        assert Offset.CLOSE == "CLOSE"
        assert Offset.CLOSETODAY == "CLOSETODAY"
        assert Offset.CLOSEYESTERDAY == "CLOSEYESTERDAY"
        assert len(Offset) == 5
    
    def test_order_status_enum(self):
        """测试订单状态枚举"""
        assert OrderStatus.SUBMITTING == "SUBMITTING"
        assert OrderStatus.NOTTRADED == "NOTTRADED"
        assert OrderStatus.PARTTRADED == "PARTTRADED"
        assert OrderStatus.ALLTRADED == "ALLTRADED"
        assert OrderStatus.CANCELLED == "CANCELLED"
        assert OrderStatus.REJECTED == "REJECTED"
        assert len(OrderStatus) == 6
    
    def test_product_type_enum(self):
        """测试产品类型枚举"""
        assert ProductType.FUTURES == "FUTURES"
        assert ProductType.OPTION == "OPTION"
        assert ProductType.SPOT == "SPOT"
        assert len(ProductType) == 5
    
    def test_exchange_enum(self):
        """测试交易所枚举"""
        assert Exchange.SHFE == "SHFE"
        assert Exchange.DCE == "DCE"
        assert Exchange.CZCE == "CZCE"
        assert Exchange.CFFEX == "CFFEX"
        assert Exchange.GFEX == "GFEX"
        assert Exchange.INE == "INE"
        assert Exchange.SSE == "SSE"
        assert Exchange.SZSE == "SZSE"
        assert Exchange.NONE == ""
        assert len(Exchange) >= 9
    
    def test_interval_enum(self):
        """测试K线周期枚举"""
        assert Interval.MINUTE == "1m"
        assert Interval.HOUR == "1h"
        assert Interval.DAILY == "d"
        assert len(Interval) >= 3
    
    def test_interval_custom(self):
        """测试自定义周期枚举"""
        # Interval是一个枚举，不支持任意字符串
        # 只能使用预定义的值
        assert Interval.TICK == "tick"
        assert Interval.MINUTE == "1m"
        assert Interval.HOUR == "1h"
    
    def test_order_type_enum(self):
        """测试订单类型枚举"""
        assert OrderType.LIMIT == "LIMIT"
        assert OrderType.MARKET == "MARKET"
        assert OrderType.FOK == "FOK"
        assert OrderType.FAK == "FAK"
        assert len(OrderType) == 4


@pytest.mark.unit
class TestTickData:
    """Tick数据模型测试"""
    
    def test_tick_data_creation(self):
        """测试Tick数据创建"""
        from datetime import datetime
        
        tick = TickData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            last_price=3500.0,
            volume=100,
            turnover=350000.0,
            open_interest=1000,
            bid_price1=3499.0,
            ask_price1=3501.0,
            bid_volume1=10,
            ask_volume1=10,
            open_price=3500.0,
            high_price=3510.0,
            low_price=3490.0,
            pre_close=3495.0,
            limit_up=3644.5,
            limit_down=3345.5
        )
        
        assert tick.symbol == "rb2505"
        assert tick.exchange == Exchange.SHFE
        assert tick.last_price == 3500.0
        assert tick.volume == 100
    
    def test_tick_data_std_symbol(self):
        """测试Tick标准合约代码"""
        tick = TickData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            last_price=3500.0,
            volume=0,
            turnover=0.0,
            open_interest=0,
            bid_price1=0.0,
            ask_price1=0.0,
            bid_volume1=0,
            ask_volume1=0,
            open_price=0.0,
            high_price=0.0,
            low_price=0.0,
            pre_close=0.0,
            limit_up=0.0,
            limit_down=0.0
        )
        
        # TickData的std_symbol是 symbol.exchange
        assert tick.std_symbol == "rb2505.SHFE"
    
    def test_tick_data_with_optional_fields(self):
        """测试Tick数据带可选字段"""
        from datetime import datetime
        
        tick = TickData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            last_price=3500.0,
            volume=0,
            turnover=0.0,
            open_interest=0,
            bid_price1=3499.0,
            ask_price1=3501.0,
            bid_volume1=10,
            ask_volume1=10,
            open_price=0.0,
            high_price=0.0,
            low_price=0.0,
            pre_close=0.0,
            limit_up=0.0,
            limit_down=0.0
        )
        
        assert tick.bid_price1 == 3499.0
        assert tick.ask_price1 == 3501.0
        assert tick.bid_volume1 == 10
        assert tick.ask_volume1 == 10


@pytest.mark.unit
class TestBarData:
    """Bar数据模型测试"""
    
    def test_bar_data_creation(self):
        """测试Bar数据创建"""
        from datetime import datetime
        
        bar = BarData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            interval=Interval.MINUTE,
            open_price=3500.0,
            high_price=3510.0,
            low_price=3490.0,
            close_price=3505.0,
            volume=1000.0,
            turnover=3505000.0,
            open_interest=5000.0
        )
        
        assert bar.symbol == "rb2505"
        assert bar.open_price == 3500.0
        assert bar.high_price == 3510.0
        assert bar.low_price == 3490.0
        assert bar.close_price == 3505.0
    
    def test_bar_data_std_symbol(self):
        """测试Bar标准合约代码"""
        from datetime import datetime
        
        bar = BarData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            interval=Interval.MINUTE,
            open_price=3500.0,
            high_price=3510.0,
            low_price=3490.0,
            close_price=3505.0,
            volume=1000.0,
            turnover=0.0,
            open_interest=0.0
        )
        
        # BarData的std_symbol属性是 symbol.exchange
        assert bar.std_symbol == "rb2505.SHFE"
    
    def test_bar_data_without_extras(self):
        """测试Bar数据不使用额外字段"""
        from datetime import datetime
        
        bar = BarData(
            symbol="rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime(2024, 1, 1, 9, 30, 0),
            interval=Interval.MINUTE,
            open_price=3500.0,
            high_price=3510.0,
            low_price=3490.0,
            close_price=3505.0,
            volume=1000,
            turnover=0.0,
            open_interest=0
        )
        
        assert bar.extras == {}


@pytest.mark.unit
class TestDataValidation:
    """数据验证测试"""
    
    def test_order_data_valid(self):
        """测试订单数据有效性"""
        order = OrderData(
            order_id="test_order",
            symbol="rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=10,
            price=3500.0,
            account_id="test_account",
            gateway_order_id="",
            trading_day="",
            insert_time=datetime(2024, 1, 1, 9, 30, 0),
            update_time=datetime(2024, 1, 1, 9, 30, 0)
        )
        
        assert order.order_id == "test_order"
        assert order.volume == 10
    
    def test_trade_data_valid(self):
        """测试成交数据有效性"""
        trade = TradeData(
            trade_id="test_trade",
            order_id="test_order",
            symbol="rb2505",
            exchange=Exchange.SHFE,
            direction=Direction.BUY,
            offset=Offset.OPEN,
            price=3500.0,
            volume=5,
            account_id="test_account",
            trading_day="",
            trade_time=datetime(2024, 1, 1, 9, 30, 0),
            commission=0.0
        )
        
        assert trade.trade_id == "test_trade"
        assert trade.price == 3500.0


@pytest.mark.unit
class TestEnumComparison:
    """枚举比较测试"""
    
    def test_direction_comparison(self):
        """测试方向枚举比较"""
        assert Direction.BUY == Direction.BUY
        assert Direction.BUY != Direction.SELL
    
    def test_order_status_comparison(self):
        """测试订单状态枚举比较"""
        status = OrderStatus.ALLTRADED
        assert status == OrderStatus.ALLTRADED
        assert status != OrderStatus.PARTTRADED
    
    def test_string_to_enum_conversion(self):
        """测试字符串转枚举"""
        direction = Direction("BUY")
        assert direction == Direction.BUY
        
        offset = Offset("OPEN")
        assert offset == Offset.OPEN
    
    def test_enum_value_extraction(self):
        """测试枚举值提取"""
        assert Direction.BUY.value == "BUY"
        assert OrderStatus.CANCELLED.value == "CANCELLED"
    
    def test_iteration_over_enums(self):
        """测试枚举迭代"""
        directions = list(Direction)
        assert len(directions) == 2
        assert Direction.BUY in directions
        assert Direction.SELL in directions
    
    def test_enum_name(self):
        """测试枚举名称"""
        assert Direction.BUY.name == "BUY"
        assert OrderStatus.SUBMITTING.name == "SUBMITTING"
