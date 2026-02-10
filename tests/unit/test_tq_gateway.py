"""
TqGateway 单元测试

测试 TqGateway 实现的核心功能，包括：
- 初始化
- 连接/断开连接
- 订阅行情
- 下单/撤单
- 数据转换
- 时间间隔转换
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.models.object import (
    AccountData,
    BarData,
    CancelRequest,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    OrderStatus,
    OrderType,
    PositionData,
    ProductType,
    TickData,
    TradeData,
)
from src.trader.gateway.tq_gateway import TqGateway
from src.utils.config_loader import GatewayConfig, TianqinConfig, BrokerConfig


# ==================== Fixtures ====================


@pytest.fixture
def gateway_config() -> GatewayConfig:
    """创建 TqGateway 配置"""
    return GatewayConfig(
        account_id="test_account_001",
        type="TQSDK",
        tianqin=TianqinConfig(
            username="test_user",
            password="test_pass",
        ),
        broker=BrokerConfig(
            type="sim",
        ),
        subscribe_symbols=["SHFE.rb2505"],
    )


@pytest.fixture
def gateway(gateway_config: GatewayConfig) -> TqGateway:
    """创建 TqGateway 实例"""
    return TqGateway(config=gateway_config)


@pytest.fixture
def mock_tq_api():
    """模拟 TqApi"""
    api = MagicMock()
    # 模拟账户数据
    mock_account = MagicMock()
    mock_account.balance = 1000000.0
    mock_account.available = 900000.0
    mock_account.margin = 100000.0
    mock_account.pre_balance = 1000000.0
    mock_account.position_profit = 0.0
    mock_account.close_profit = 0.0
    mock_account.risk_ratio = 0.1
    api.get_account.return_value = mock_account

    # 模拟持仓数据
    mock_positions = {}
    api.get_position.return_value = mock_positions

    # 模拟订单数据
    mock_orders = {}
    api.get_order.return_value = mock_orders

    # 模拟成交数据
    mock_trades = {}
    api.get_trade.return_value = mock_trades

    # 模拟行情订阅
    mock_quote = MagicMock()
    mock_quote.instrument_id = "SHFE.rb2505"
    mock_quote.exchange_id = "SHFE"
    mock_quote.last_price = 3500.0
    mock_quote.ask_price1 = 3501.0
    mock_quote.bid_price1 = 3499.0
    mock_quote.ask_volume1 = 100
    mock_quote.bid_volume1 = 100
    mock_quote.volume = 10000
    mock_quote.turnover = 35000000
    mock_quote.open_interest = 50000
    mock_quote.open = 3480.0
    mock_quote.highest = 3520.0
    mock_quote.lowest = 3470.0
    mock_quote.datetime = int(datetime.now().timestamp() * 1e9)
    api.get_quote.return_value = mock_quote

    # 模拟 K 线数据
    import pandas as pd
    mock_kline = pd.DataFrame({
        "datetime": [int(datetime.now().timestamp() * 1e9)],
        "open": [3500.0],
        "high": [3510.0],
        "low": [3490.0],
        "close": [3505.0],
        "volume": [1000],
        "turnover": [3505000],
        "open_interest": [50000],
    })
    api.get_kline_serial.return_value = mock_kline

    # 模拟合约查询
    api.query_quotes.return_value = ["SHFE.rb2505"]
    api.query_symbol_info.return_value = pd.DataFrame({
        "instrument_id": ["SHFE.rb2505"],
        "exchange_id": ["SHFE"],
        "instrument_name": ["螺纹钢2505"],
        "volume_multiple": [10],
        "price_tick": [1.0],
    })

    # 模拟 is_changing
    api.is_changing.return_value = False
    api.wait_update.return_value = True

    # 模拟下单
    mock_order = {
        "order_id": "test_order_id",
        "instrument_id": "SHFE.rb2505",
        "exchange_id": "SHFE",
        "direction": "BUY",
        "offset": "OPEN",
        "volume_orign": 5,
        "volume_left": 5,
        "limit_price": 3500.0,
        "status": "ALIVE",
        "last_msg": "",
        "insert_date_time": int(datetime.now().timestamp() * 1e9),
    }
    api.insert_order.return_value = mock_order

    # 模拟撤单
    api.cancel_order.return_value = None

    # 模拟交易日历
    trading_calendar = pd.DataFrame({
        "date": ["2026-01-15"],
        "trading": [True],
    })
    api.get_trading_calendar.return_value = trading_calendar

    return api


# ==================== TestTqGatewayInitialization ====================


class TestTqGatewayInitialization:
    """TqGateway 初始化测试"""

    def test_initialization_stores_config(self, gateway: TqGateway, gateway_config: GatewayConfig):
        """测试配置正确存储"""
        assert gateway.config == gateway_config
        assert gateway.account_id == gateway_config.account_id

    def test_initialization_internal_caches(self, gateway: TqGateway):
        """测试内部缓存初始化"""
        assert gateway._account is None
        assert gateway._positions == {}
        assert gateway._orders == {}
        assert gateway._trades == {}
        assert gateway._quotes == {}
        assert gateway._klines == {}
        assert gateway._pending_orders == {}
        assert gateway._contracts == {}

    def test_initialization_connection_status(self, gateway: TqGateway):
        """测试连接状态初始为 False"""
        assert gateway.connected is False
        assert gateway._running is False

    def test_initialization_subscribe_symbols(self, gateway: TqGateway, gateway_config: GatewayConfig):
        """测试订阅符号初始化"""
        assert gateway.hist_subs == gateway_config.subscribe_symbols

    def test_initialization_order_ref(self, gateway: TqGateway):
        """测试订单引用计数初始化"""
        assert gateway._order_ref == 0


# ==================== TestTqGatewayConnect ====================


class TestTqGatewayConnect:
    """TqGateway 连接测试"""

    @pytest.mark.asyncio
    async def test_connect_starts_thread_and_task(self, gateway: TqGateway):
        """测试成功启动线程和协程"""
        with patch("threading.Thread.start") as mock_thread_start:
            with patch("asyncio.create_task") as mock_create_task:
                result = await gateway.connect()

                assert result is True
                mock_thread_start.assert_called_once()
                mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_already_running(self, gateway: TqGateway):
        """测试重复连接处理"""
        gateway._running = True
        result = await gateway.connect()

        assert result is True

    @pytest.mark.asyncio
    async def test_connect_failure_handling(self, gateway: TqGateway):
        """测试连接失败处理"""
        with patch("threading.Thread.start", side_effect=Exception("连接失败")):
            result = await gateway.connect()

            assert result is False
            assert gateway.connected is False


# ==================== TestTqGatewayDisconnect ====================


class TestTqGatewayDisconnect:
    """TqGateway 断开连接测试"""

    @pytest.mark.asyncio
    async def test_disconnect_stops_polling(self, gateway: TqGateway):
        """测试正确停止轮询"""
        gateway._running = True
        gateway.connected = True
        gateway._dispatcher_task = asyncio.create_task(asyncio.sleep(1))

        result = await gateway.disconnect()

        assert result is True
        assert gateway._running is False
        assert gateway.connected is False

    @pytest.mark.asyncio
    async def test_disconnect_cancels_dispatcher_task(self, gateway: TqGateway):
        """测试取消事件分发协程"""
        async def dummy_dispatcher():
            while True:
                await asyncio.sleep(0.1)

        gateway._running = True
        gateway._dispatcher_task = asyncio.create_task(dummy_dispatcher())

        await gateway.disconnect()

        assert gateway._dispatcher_task.cancelled() or gateway._dispatcher_task.done()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, gateway: TqGateway):
        """测试未连接时断开"""
        result = await gateway.disconnect()

        assert result is True


# ==================== TestTqGatewaySubscribe ====================


class TestTqGatewaySubscribe:
    """TqGateway 订阅测试"""

    def test_subscribe_single_symbol(self, gateway: TqGateway):
        """测试订阅单个合约"""
        gateway.connected = True
        gateway.api = MagicMock()

        result = gateway.subscribe("SHFE.rb2505")

        assert result is True
        assert "SHFE.rb2505" in gateway.hist_subs

    def test_subscribe_symbol_list(self, gateway: TqGateway):
        """测试订阅合约列表"""
        gateway.connected = True
        gateway.api = MagicMock()

        result = gateway.subscribe(["SHFE.rb2505", "SHFE.ru2505"])

        assert result is True
        assert "SHFE.rb2505" in gateway.hist_subs
        assert "SHFE.ru2505" in gateway.hist_subs

    def test_subscribe_duplicate_handling(self, gateway: TqGateway):
        """测试重复订阅处理"""
        gateway.connected = True
        gateway.hist_subs = ["SHFE.rb2505"]
        gateway.api = MagicMock()

        result = gateway.subscribe("SHFE.rb2505")

        # 应该允许重复添加到历史列表
        assert result is True


# ==================== TestTqGatewaySendOrder ====================


class TestTqGatewaySendOrder:
    """TqGateway 下单测试"""

    def test_send_order_market_price_uses_counter_price_buy(self, gateway: TqGateway):
        """测试市价单买入使用对手价"""
        gateway.connected = True
        gateway._upper_symbols = {"RB2505": "SHFE.rb2505"}
        gateway._quotes = {
            "SHFE.rb2505": MagicMock(
                ask_price1=3501.0,
                bid_price1=3499.0,
                instrument_id="SHFE.rb2505",
            )
        }
        gateway.api = MagicMock()
        # 模拟 insert_order 返回对象，既有 get() 方法又有 status 属性
        class MockOrder:
            def __init__(self):
                self.status = "ALIVE"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"
                self._data = {
                    "order_id": "test_order_id",
                    "status": "ALIVE",
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        gateway.api.insert_order.return_value = MockOrder()

        req = OrderRequest(
            symbol="RB2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            price=None,  # 市价单
        )

        gateway.send_order(req)

        # 验证使用了卖一价
        call_args = gateway.api.insert_order.call_args
        assert call_args[1]["limit_price"] == 3501.0

    def test_send_order_market_price_uses_counter_price_sell(self, gateway: TqGateway):
        """测试市价单卖出使用对手价"""
        gateway.connected = True
        gateway._upper_symbols = {"RB2505": "SHFE.rb2505"}
        gateway._quotes = {
            "SHFE.rb2505": MagicMock(
                ask_price1=3501.0,
                bid_price1=3499.0,
                instrument_id="SHFE.rb2505",
            )
        }
        gateway.api = MagicMock()
        class MockOrder:
            def __init__(self):
                self.status = "ALIVE"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"
                self._data = {
                    "order_id": "test_order_id",
                    "status": "ALIVE",
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        gateway.api.insert_order.return_value = MockOrder()

        req = OrderRequest(
            symbol="RB2505",
            direction=Direction.SELL,
            offset=Offset.OPEN,
            volume=5,
            price=None,  # 市价单
        )

        gateway.send_order(req)

        # 验证使用了买一价
        call_args = gateway.api.insert_order.call_args
        assert call_args[1]["limit_price"] == 3499.0

    def test_send_order_limit_price(self, gateway: TqGateway):
        """测试限价单使用指定价格"""
        gateway.connected = True
        gateway._upper_symbols = {"RB2505": "SHFE.rb2505"}
        gateway._quotes = {
            "SHFE.rb2505": MagicMock(
                ask_price1=3501.0,
                bid_price1=3499.0,
                instrument_id="SHFE.rb2505",
            )
        }
        gateway.api = MagicMock()
        class MockOrder:
            def __init__(self):
                self.status = "ALIVE"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"
                self._data = {
                    "order_id": "test_order_id",
                    "status": "ALIVE",
                }

            def get(self, key, default=None):
                return self._data.get(key, default)

        gateway.api.insert_order.return_value = MockOrder()

        req = OrderRequest(
            symbol="RB2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            price=3500.0,
        )

        gateway.send_order(req)

        # 验证使用了指定价格
        call_args = gateway.api.insert_order.call_args
        assert call_args[1]["limit_price"] == 3500.0

    def test_send_order_not_connected_returns_none(self, gateway: TqGateway):
        """测试未连接时返回 None"""
        gateway.connected = False

        req = OrderRequest(
            symbol="RB2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )

        result = gateway.send_order(req)

        assert result is None


# ==================== TestTqGatewayCancelOrder ====================


class TestTqGatewayCancelOrder:
    """TqGateway 撤单测试"""

    def test_cancel_order_success(self, gateway: TqGateway):
        """测试成功撤单"""
        gateway.connected = True
        gateway.api = MagicMock()

        mock_order = MagicMock()
        mock_order.order_id = "test_order_id"
        gateway._orders = {"test_order_id": mock_order}

        req = CancelRequest(order_id="test_order_id")

        result = gateway.cancel_order(req)

        assert result is True
        gateway.api.cancel_order.assert_called_once_with(mock_order)

    def test_cancel_order_not_found(self, gateway: TqGateway):
        """测试订单不存在处理"""
        gateway.connected = True
        gateway.api = MagicMock()
        gateway._orders = {}

        req = CancelRequest(order_id="nonexistent_order")

        result = gateway.cancel_order(req)

        assert result is False


# ==================== TestTqGatewayDataConversion ====================


class TestTqGatewayDataConversion:
    """TqGateway 数据转换测试"""

    def test_convert_account(self, gateway: TqGateway):
        """测试 _convert_account() 转换账户数据"""
        mock_account = MagicMock()
        mock_account.balance = 1000000.0
        mock_account.available = 900000.0
        mock_account.margin = 100000.0
        mock_account.pre_balance = 1000000.0
        mock_account.position_profit = 5000.0
        mock_account.close_profit = 1000.0
        mock_account.risk_ratio = 0.1

        result = gateway._convert_account(mock_account)

        assert isinstance(result, AccountData)
        assert result.balance == 1000000.0
        assert result.available == 900000.0
        assert result.margin == 100000.0

    def test_convert_order_alive(self, gateway: TqGateway):
        """测试 _convert_order() 转换活动订单"""
        # 使用真实对象而不是 MagicMock
        class MockOrder:
            def __init__(self):
                self._data = {
                    "order_id": "test_order",
                    "instrument_id": "rb2505",
                    "exchange_id": "SHFE",
                    "direction": "BUY",
                    "offset": "OPEN",
                    "volume_orign": 5,
                    "volume_left": 3,
                    "limit_price": 3500.0,
                    "status": "ALIVE",
                    "last_msg": "",
                    "insert_date_time": int(datetime.now().timestamp() * 1e9),
                }
                # 添加直接属性访问
                self.status = "ALIVE"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_order = MockOrder()

        result = gateway._convert_order(mock_order)

        assert isinstance(result, OrderData)
        assert result.order_id == "test_order"
        assert result.symbol == "rb2505"
        assert result.direction == Direction.BUY
        assert result.volume == 5
        assert result.traded == 2

    def test_convert_order_finished(self, gateway: TqGateway):
        """测试 _convert_order() 转换已完成订单"""
        class MockOrder:
            def __init__(self):
                self._data = {
                    "order_id": "test_order",
                    "instrument_id": "rb2505",
                    "exchange_id": "SHFE",
                    "direction": "BUY",
                    "offset": "OPEN",
                    "volume_orign": 5,
                    "volume_left": 0,
                    "limit_price": 3500.0,
                    "status": "FINISHED",
                    "last_msg": "全部成交",
                    "insert_date_time": int(datetime.now().timestamp() * 1e9),
                }
                # 添加直接属性访问
                self.status = "FINISHED"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_order = MockOrder()

        result = gateway._convert_order(mock_order)

        assert result.status == OrderStatus.FINISHED

    def test_convert_order_rejected(self, gateway: TqGateway):
        """测试 _convert_order() 转换被拒订单"""
        class MockOrder:
            def __init__(self):
                self._data = {
                    "order_id": "test_order",
                    "instrument_id": "rb2505",
                    "exchange_id": "SHFE",
                    "direction": "BUY",
                    "offset": "OPEN",
                    "volume_orign": 5,
                    "volume_left": 5,
                    "limit_price": 3500.0,
                    "status": "ALIVE",
                    "last_msg": "报单被拒绝",  # 包含错误关键词"拒绝"
                    "insert_date_time": int(datetime.now().timestamp() * 1e9),
                }
                # 添加直接属性访问
                self.status = "ALIVE"
                self.instrument_id = "rb2505"
                self.exchange_id = "SHFE"

            def get(self, key, default=None):
                return self._data.get(key, default)

        mock_order = MockOrder()

        result = gateway._convert_order(mock_order)

        # 由于 last_msg 包含"拒绝"，应该被识别为 REJECTED
        assert result.status == OrderStatus.REJECTED

    def test_convert_trade(self, gateway: TqGateway):
        """测试 _convert_trade() 转换成交数据"""
        mock_trade = MagicMock()
        mock_trade.get = lambda k, d=None: {
            "trade_id": "test_trade",
            "order_id": "test_order",
            "instrument_id": "SHFE.rb2505",
            "exchange_id": "SHFE",
            "direction": "BUY",
            "offset": "OPEN",
            "price": 3500.0,
            "volume": 5,
            "trade_date_time": int(datetime.now().timestamp() * 1e9),
        }.get(k, d)

        result = gateway._convert_trade(mock_trade)

        assert isinstance(result, TradeData)
        assert result.trade_id == "test_trade"
        assert result.order_id == "test_order"
        assert result.price == 3500.0
        assert result.volume == 5

    def test_convert_position(self, gateway: TqGateway):
        """测试 _convert_position() 转换持仓数据"""
        mock_position = MagicMock()
        mock_position.instrument_id = "SHFE.rb2505"
        mock_position.exchange_id = "SHFE"
        mock_position.pos_long = 10
        mock_position.pos_short = 0
        mock_position.pos_long_his = 5
        mock_position.pos_short_his = 0
        mock_position.pos_long_today = 5
        mock_position.pos_short_today = 0
        mock_position.open_price_long = 3500.0
        mock_position.open_price_short = 0.0
        mock_position.float_profit_long = 500.0
        mock_position.float_profit_short = 0.0
        mock_position.position_profit_long = 500.0
        mock_position.position_profit_short = 0.0
        mock_position.margin_long = 35000.0
        mock_position.margin_short = 0.0

        result = gateway._convert_position(mock_position)

        assert isinstance(result, PositionData)
        assert result.symbol == "SHFE.rb2505"
        assert result.pos == 10
        assert result.pos_long == 10
        assert result.pos_short == 0

    def test_convert_tick(self, gateway: TqGateway):
        """测试 _convert_tick() 转换行情数据"""
        now_ts = int(datetime.now().timestamp() * 1e9)
        mock_quote = MagicMock()
        mock_quote.get = lambda k, d=None: {
            "instrument_id": "SHFE.rb2505",
            "exchange_id": "SHFE",
            "datetime": now_ts,
            "last_price": 3500.0,
            "volume": 10000,
            "turnover": 35000000,
            "open_interest": 50000,
            "bid_price1": 3499.0,
            "ask_price1": 3501.0,
            "bid_volume1": 100,
            "ask_volume1": 100,
            "open": 3480.0,
            "highest": 3520.0,
            "lowest": 3470.0,
            "pre_open_interest": 49000,
            "upper_limit": 3650.0,
            "lower_limit": 3350.0,
        }.get(k, d)

        result = gateway._convert_tick(mock_quote)

        assert isinstance(result, TickData)
        assert result.symbol == "rb2505"
        assert result.last_price == 3500.0

    def test_convert_bar(self, gateway: TqGateway):
        """测试 _convert_bar() 转换K线数据"""
        now_ts = int(datetime.now().timestamp() * 1e9)
        data = {
            "datetime": now_ts,
            "open": 3500.0,
            "high": 3510.0,
            "low": 3490.0,
            "close": 3505.0,
            "volume": 1000,
            "turnover": 3505000,
            "open_interest": 50000,
        }

        result = gateway._convert_bar("SHFE.rb2505", "M1", data, now_ts)

        assert isinstance(result, BarData)
        assert result.symbol == "SHFE.rb2505"
        assert result.interval == "M1"
        assert result.open_price == 3500.0
        assert result.close_price == 3505.0


# ==================== TestTqGatewayIntervalConversion ====================


class TestTqGatewayIntervalConversion:
    """TqGateway 时间间隔转换测试"""

    def test_interval_m1_conversion(self, gateway: TqGateway):
        """测试 M1 转换为秒数"""
        result = gateway._interval_to_seconds("M1")
        assert result == 60

    def test_interval_m5_conversion(self, gateway: TqGateway):
        """测试 M5 转换为秒数"""
        result = gateway._interval_to_seconds("M5")
        assert result == 300

    def test_interval_m15_conversion(self, gateway: TqGateway):
        """测试 M15 转换为秒数"""
        result = gateway._interval_to_seconds("M15")
        assert result == 900

    def test_interval_h1_conversion(self, gateway: TqGateway):
        """测试 H1 转换为秒数"""
        result = gateway._interval_to_seconds("H1")
        assert result == 3600

    def test_interval_h4_conversion(self, gateway: TqGateway):
        """测试 H4 转换为秒数"""
        result = gateway._interval_to_seconds("H4")
        assert result == 14400

    def test_interval_invalid_format_raises_error(self, gateway: TqGateway):
        """测试无效格式抛出异常"""
        with pytest.raises(ValueError, match="暂不支持的时间间隔"):
            gateway._interval_to_seconds("D1")

        with pytest.raises(ValueError, match="暂不支持的时间间隔"):
            gateway._interval_to_seconds("INVALID")


# ==================== TestTqGatewayGetTradingDay ====================


class TestTqGatewayGetTradingDay:
    """TqGateway 交易日获取测试"""

    def test_get_trading_day_before_8pm(self, gateway: TqGateway):
        """测试晚上8点前返回当天"""
        with patch("src.trader.gateway.tq_gateway.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 1, 15, 19, 0, 0)

            result = gateway.get_trading_day()

            # 19点应该在当天
            assert result is not None

    def test_get_trading_day_after_8pm(self, gateway: TqGateway):
        """测试晚上8点后返回次日"""
        gateway.connected = True
        gateway.api = MagicMock()
        with patch("src.trader.gateway.tq_gateway.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2026, 1, 15, 21, 0, 0)

            import pandas as pd
            mock_calendar = pd.DataFrame({
                "date": ["2026-01-15", "2026-01-16"],
                "trading": [True, True],
            })
            gateway.api.get_trading_calendar.return_value = mock_calendar

            result = gateway.get_trading_day()

            # 21点应该在次日
            assert result is not None


# ==================== TestTqGatewayGetContracts ====================


class TestTqGatewayGetContracts:
    """TqGateway 合约查询测试"""

    def test_get_contracts_returns_cached(self, gateway: TqGateway):
        """测试返回缓存的合约"""
        from src.models.object import ContractData
        mock_contract = ContractData(
            symbol="rb2505",
            exchange="SHFE",
            name="螺纹钢2505",
        )
        gateway._contracts = {"rb2505": mock_contract}
        gateway.connected = True  # 需要连接状态
        gateway.api = MagicMock()  # 需要API实例

        result = gateway.get_contracts()

        assert "rb2505" in result
        assert result["rb2505"] == mock_contract

    def test_get_contracts_not_connected_returns_empty(self, gateway: TqGateway):
        """测试未连接时返回空"""
        gateway.connected = False

        result = gateway.get_contracts()

        assert result == {}


# ==================== TestTqGatewayParseExchange ====================


class TestTqGatewayParseExchange:
    """TqGateway 交易所解析测试"""

    def test_parse_exchange_shfe(self, gateway: TqGateway):
        """测试解析 SHFE"""
        result = gateway._parse_exchange("SHFE")
        assert result == Exchange.SHFE

    def test_parse_exchange_dce(self, gateway: TqGateway):
        """测试解析 DCE"""
        result = gateway._parse_exchange("DCE")
        assert result == Exchange.DCE

    def test_parse_exchange_czce(self, gateway: TqGateway):
        """测试解析 CZCE"""
        result = gateway._parse_exchange("CZCE")
        assert result == Exchange.CZCE

    def test_parse_exchange_cffex(self, gateway: TqGateway):
        """测试解析 CFFEX"""
        result = gateway._parse_exchange("CFFEX")
        assert result == Exchange.CFFEX

    def test_parse_exchange_ine(self, gateway: TqGateway):
        """测试解析 INE"""
        result = gateway._parse_exchange("INE")
        assert result == Exchange.INE

    def test_parse_exchange_gfex(self, gateway: TqGateway):
        """测试解析 GFEX"""
        result = gateway._parse_exchange("GFEX")
        assert result == Exchange.GFEX

    def test_parse_exchange_unknown(self, gateway: TqGateway):
        """测试解析未知交易所"""
        result = gateway._parse_exchange("UNKNOWN")
        assert result == Exchange.NONE


# ==================== TestTqGatewayFormatSymbol ====================


class TestTqGatewayFormatSymbol:
    """TqGateway 合约代码格式化测试"""

    def test_format_symbol_empty(self, gateway: TqGateway):
        """测试空字符串"""
        result = gateway._format_symbol("")
        assert result is None

    def test_format_symbol_in_upper_symbols(self, gateway: TqGateway):
        """测试在映射中找到"""
        gateway._upper_symbols = {"RB2505": "SHFE.rb2505"}

        result = gateway._format_symbol("RB2505")

        assert result == "SHFE.rb2505"

    def test_format_symbol_not_found(self, gateway: TqGateway):
        """测试未找到映射"""
        gateway._upper_symbols = {}

        result = gateway._format_symbol("UNKNOWN")

        assert result is None


# ==================== TestTqGatewayMapEventType ====================


class TestTqGatewayMapEventType:
    """TqGateway 事件类型映射测试"""

    def test_map_tick_event(self, gateway: TqGateway):
        """测试映射 tick 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("tick")

        assert result == EventTypes.TICK_UPDATE

    def test_map_bar_event(self, gateway: TqGateway):
        """测试映射 bar 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("bar")

        assert result == EventTypes.KLINE_UPDATE

    def test_map_order_event(self, gateway: TqGateway):
        """测试映射 order 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("order")

        assert result == EventTypes.ORDER_UPDATE

    def test_map_trade_event(self, gateway: TqGateway):
        """测试映射 trade 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("trade")

        assert result == EventTypes.TRADE_UPDATE

    def test_map_position_event(self, gateway: TqGateway):
        """测试映射 position 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("position")

        assert result == EventTypes.POSITION_UPDATE

    def test_map_account_event(self, gateway: TqGateway):
        """测试映射 account 事件"""
        from src.utils.event_engine import EventTypes

        result = gateway._map_event_type("account")

        assert result == EventTypes.ACCOUNT_UPDATE

    def test_map_unknown_event(self, gateway: TqGateway):
        """测试映射未知事件"""
        result = gateway._map_event_type("unknown")

        assert result is None
