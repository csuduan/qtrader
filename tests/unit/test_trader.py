"""
测试Trader交易执行器

包含所有Trader类方法的单元测试
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch, call
from datetime import datetime
from decimal import Decimal

from src.utils.config_loader import TraderConfig, SocketConfig, PathsConfig
from src.trader.trader import Trader
from src.models.object import (
    AccountData,
    OrderData,
    TradeData,
    PositionData,
    TickData,
    Direction,
    Offset,
    Exchange,
)


# ==================== Fixtures ====================


@pytest.fixture
def mock_trader_config():
    """创建模拟的TraderConfig"""
    config = MagicMock(spec=TraderConfig)
    config.account_id = "test_account_001"
    config.account_type = "kq"
    config.enabled = True
    config.auto_start = False
    config.trading = MagicMock()
    config.trading.paused = False
    config.trading.risk_control = None
    config.paths = PathsConfig(
        switchPos_files="./data/orders",
        logs="./data/logs",
        database="./storage/test_trading.db",
        export="./data/export",
        params="./data/params",
    )
    config.socket = SocketConfig(socket_dir="./data/socks")
    config.scheduler = None
    config.strategies = None
    config.gateway = MagicMock()
    config.gateway.type = "TQSDK"
    config.gateway.broker = MagicMock()
    config.gateway.broker.user_id = "test_user"
    return config


@pytest.fixture
def mock_trading_engine():
    """创建模拟的TradingEngine"""
    engine = MagicMock()
    engine.account_id = "test_account_001"
    engine.connect = MagicMock(return_value=True)
    engine.disconnect = MagicMock()
    engine.insert_order = MagicMock(return_value="order_123")
    engine.cancel_order = MagicMock(return_value=True)
    engine.account = AccountData(
        account_id="test_account_001",
        balance=Decimal("100000.0"),
        available=Decimal("95000.0"),
        frozen=Decimal("5000.0"),
    )
    engine.orders = {}
    engine.trades = {}
    engine.positions = {}
    engine.quotes = {}
    return engine


@pytest.fixture
def mock_strategy_manager():
    """创建模拟的StrategyManager"""
    manager = MagicMock()
    manager.stop_all = MagicMock()
    manager.start_strategy = MagicMock(return_value=True)
    manager.stop_strategy = MagicMock(return_value=True)
    manager.start_all = MagicMock()
    manager.strategies = {}
    return manager


@pytest.fixture
def mock_socket_server():
    """创建模拟的SocketServer"""
    server = AsyncMock()
    server.start = AsyncMock()
    server.stop = AsyncMock()
    server.send_message = AsyncMock()
    server.send_heartbeat = AsyncMock()
    server.register_handlers_from_instance = MagicMock()
    return server


@pytest.fixture
def mock_event_engine():
    """创建模拟的AsyncEventEngine"""
    engine = AsyncMock()
    engine.register = MagicMock()
    return engine


@pytest.fixture
def trader_instance(mock_trader_config):
    """创建Trader实例（不启动）"""
    with patch("src.trader.trader.ctx"), patch("src.trader.trader.get_app_context"):
        trader = Trader(mock_trader_config)
        return trader


@pytest.fixture
def running_trader(trader_instance, mock_trading_engine, mock_strategy_manager, mock_socket_server):
    """创建运行中的Trader实例"""
    trader_instance.trading_engine = mock_trading_engine
    trader_instance.strategy_manager = mock_strategy_manager
    trader_instance.socket_server = mock_socket_server
    trader_instance._running = True
    trader_instance._socket_path = "./data/socks/test.sock"
    return trader_instance


# ==================== Test Initialization ====================


class TestTraderInitialization:
    """测试Trader初始化"""

    def test_init_with_config(self, trader_instance, mock_trader_config):
        """测试使用配置初始化Trader"""
        assert trader_instance.account_config == mock_trader_config
        assert trader_instance.account_id == "test_account_001"
        assert trader_instance.trading_engine is None
        assert trader_instance.switchPos_manager is None
        assert trader_instance.job_manager is None
        assert trader_instance.strategy_manager is None
        assert trader_instance.task_scheduler is None
        assert trader_instance.socket_server is None
        assert trader_instance._running is False

    def test_init_attributes(self, trader_instance):
        """测试初始化属性设置"""
        assert hasattr(trader_instance, "account_config")
        assert hasattr(trader_instance, "account_id")
        assert hasattr(trader_instance, "trading_engine")
        assert hasattr(trader_instance, "strategy_manager")
        assert hasattr(trader_instance, "_running")


# ==================== Test Start Method ====================


class TestTraderStart:
    """测试Trader启动方法"""

    @pytest.mark.asyncio
    async def test_start_initializes_components(
        self, trader_instance, mock_trading_engine, mock_strategy_manager, mock_socket_server, mock_event_engine
    ):
        """测试启动时初始化所有组件"""
        with patch(
            "src.trader.trader.TradingEngine", return_value=mock_trading_engine
        ), patch(
            "src.trader.trader.SwitchPosManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.JobManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.SocketServer", return_value=mock_socket_server
        ), patch(
            "src.trader.trader.get_app_context",
            return_value=MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine)),
        ), patch.object(
            trader_instance, "_init_database", new=AsyncMock()
        ), patch.object(
            trader_instance, "_init_strategy_manager", new=AsyncMock()
        ):
            # 启动并在初始化完成后停止
            start_task = asyncio.create_task(trader_instance.start())
            await asyncio.sleep(0.1)  # 让初始化完成
            trader_instance._running = False  # 停止循环
            await start_task

            assert trader_instance._running is False
            assert trader_instance.trading_engine is not None

    @pytest.mark.asyncio
    async def test_start_without_scheduler(
        self, trader_instance, mock_trading_engine, mock_socket_server, mock_event_engine
    ):
        """测试无调度器配置时启动"""
        trader_instance.account_config.scheduler = None

        with patch(
            "src.trader.trader.TradingEngine", return_value=mock_trading_engine
        ), patch(
            "src.trader.trader.SwitchPosManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.JobManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.SocketServer", return_value=mock_socket_server
        ), patch(
            "src.trader.trader.get_app_context",
            return_value=MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine)),
        ), patch.object(
            trader_instance, "_init_database", new=AsyncMock()
        ), patch.object(
            trader_instance, "_init_strategy_manager", new=AsyncMock()
        ):
            start_task = asyncio.create_task(trader_instance.start())
            await asyncio.sleep(0.1)
            trader_instance._running = False
            await start_task

            assert trader_instance.task_scheduler is None

    @pytest.mark.asyncio
    async def test_start_with_scheduler(
        self, trader_instance, mock_trading_engine, mock_socket_server, mock_event_engine
    ):
        """测试有调度器配置时启动"""
        mock_scheduler_config = MagicMock()
        trader_instance.account_config.scheduler = mock_scheduler_config

        mock_task_scheduler = MagicMock()
        mock_task_scheduler.start = MagicMock()

        with patch(
            "src.trader.trader.TradingEngine", return_value=mock_trading_engine
        ), patch(
            "src.trader.trader.SwitchPosManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.JobManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.TaskScheduler", return_value=mock_task_scheduler
        ), patch(
            "src.trader.trader.SocketServer", return_value=mock_socket_server
        ), patch(
            "src.trader.trader.get_app_context",
            return_value=MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine)),
        ), patch.object(
            trader_instance, "_init_database", new=AsyncMock()
        ), patch.object(
            trader_instance, "_init_strategy_manager", new=AsyncMock()
        ):
            start_task = asyncio.create_task(trader_instance.start())
            await asyncio.sleep(0.1)
            trader_instance._running = False
            await start_task

            assert trader_instance.task_scheduler is not None
            mock_task_scheduler.start.assert_called_once()


# ==================== Test Stop Method ====================


class TestTraderStop:
    """测试Trader停止方法"""

    @pytest.mark.asyncio
    async def test_stop_sets_running_flag(self, running_trader):
        """测试停止时设置运行标志"""
        await running_trader.stop()
        assert running_trader._running is False

    @pytest.mark.asyncio
    async def test_stop_stops_strategy_manager(self, running_trader, mock_strategy_manager):
        """测试停止时停止策略管理器"""
        await running_trader.stop()
        mock_strategy_manager.stop_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_without_strategy_manager(self, trader_instance):
        """测试无策略管理器时停止"""
        trader_instance.strategy_manager = None
        trader_instance._running = True
        trader_instance._socket_path = None
        # 不应该抛出异常
        await trader_instance.stop()
        assert trader_instance._running is False

    @pytest.mark.asyncio
    async def test_stop_stops_task_scheduler(self, running_trader):
        """测试停止时停止任务调度器"""
        mock_scheduler = MagicMock()
        mock_scheduler.shutdown = MagicMock()
        running_trader.task_scheduler = mock_scheduler

        await running_trader.stop()

        mock_scheduler.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_disconnects_trading_engine(self, running_trader, mock_trading_engine):
        """测试停止时断开交易引擎连接"""
        await running_trader.stop()
        mock_trading_engine.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_stops_socket_server(self, running_trader, mock_socket_server):
        """测试停止时停止Socket服务器"""
        await running_trader.stop()
        mock_socket_server.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cleans_pid_and_socket_files(self, running_trader, tmp_path):
        """测试停止时清理PID和Socket文件"""
        socket_dir = tmp_path / "socks"
        socket_dir.mkdir(parents=True, exist_ok=True)
        socket_path = socket_dir / "test.sock"
        pid_path = socket_dir / "qtrader_test_account_001.pid"

        # 创建测试文件
        socket_path.touch()
        pid_path.touch()

        running_trader._socket_path = str(socket_path)

        await running_trader.stop()

        assert not socket_path.exists()
        assert not pid_path.exists()

    @pytest.mark.asyncio
    async def test_stop_handles_file_cleanup_errors(self, running_trader):
        """测试停止时处理文件清理错误"""
        running_trader._socket_path = "/nonexistent/path.sock"
        # 不应该抛出异常
        await running_trader.stop()
        assert running_trader._running is False


# ==================== Test Event Handlers ====================


class TestEventHandlers:
    """测试事件处理器"""

    @pytest.mark.asyncio
    async def test_on_account_update_with_socket(self, trader_instance, mock_socket_server):
        """测试账户更新事件处理器（有Socket）"""
        trader_instance.socket_server = mock_socket_server
        account_data = AccountData(
            account_id="test", balance=Decimal("1000"), available=Decimal("1000")
        )

        await trader_instance._on_account_update(account_data)

        mock_socket_server.send_message.assert_called_once_with("account", account_data.model_dump())

    @pytest.mark.asyncio
    async def test_on_account_update_without_socket(self, trader_instance, caplog):
        """测试账户更新事件处理器（无Socket）"""
        trader_instance.socket_server = None
        account_data = AccountData(
            account_id="test", balance=Decimal("1000"), available=Decimal("1000")
        )

        with patch("src.trader.trader.logger"):
            await trader_instance._on_account_update(account_data)

    @pytest.mark.asyncio
    async def test_on_order_update_with_socket(self, trader_instance, mock_socket_server):
        """测试订单更新事件处理器"""
        trader_instance.socket_server = mock_socket_server
        order_data = OrderData(
            order_id="order_123",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
        )

        await trader_instance._on_order_update(order_data)

        mock_socket_server.send_message.assert_called_once_with("order", order_data.model_dump())

    @pytest.mark.asyncio
    async def test_on_trade_update_with_socket(self, trader_instance, mock_socket_server):
        """测试成交更新事件处理器"""
        trader_instance.socket_server = mock_socket_server
        trade_data = TradeData(
            trade_id="trade_123",
            order_id="order_123",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
        )

        await trader_instance._on_trade_update(trade_data)

        mock_socket_server.send_message.assert_called_once_with("trade", trade_data.model_dump())

    @pytest.mark.asyncio
    async def test_on_position_update_with_socket(self, trader_instance, mock_socket_server):
        """测试持仓更新事件处理器"""
        trader_instance.socket_server = mock_socket_server
        position_data = PositionData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            pos=1,
            pos_long=1,
            pos_short=0,
        )

        await trader_instance._on_position_update(position_data)

        mock_socket_server.send_message.assert_called_once_with("position", position_data.model_dump())

    @pytest.mark.asyncio
    async def test_on_tick_update(self, trader_instance, mock_socket_server):
        """测试行情更新事件处理器（不推送）"""
        trader_instance.socket_server = mock_socket_server
        tick_data = TickData(
            symbol="SHFE.rb2505",
            exchange=Exchange.SHFE,
            datetime=datetime.now(),
            last_price=Decimal("3500"),
        )

        await trader_instance._on_tick_update(tick_data)

        # 行情数据不推送
        mock_socket_server.send_message.assert_not_called()


# ==================== Test Event Registration ====================


class TestEventRegistration:
    """测试事件注册"""

    def test_register_event_handlers(self, trader_instance, mock_event_engine):
        """测试注册事件处理器"""
        with patch(
            "src.trader.trader.get_app_context",
            return_value=MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine)),
        ):
            trader_instance._register_event_handlers()

            # 检查所有事件类型都已注册
            from src.utils.event_engine import EventTypes

            expected_calls = [
                call(EventTypes.ACCOUNT_UPDATE, trader_instance._on_account_update),
                call(EventTypes.ACCOUNT_STATUS, trader_instance._on_account_update),
                call(EventTypes.ORDER_UPDATE, trader_instance._on_order_update),
                call(EventTypes.TRADE_UPDATE, trader_instance._on_trade_update),
                call(EventTypes.POSITION_UPDATE, trader_instance._on_position_update),
                call(EventTypes.TICK_UPDATE, trader_instance._on_tick_update),
            ]

            mock_event_engine.register.assert_has_calls(expected_calls, any_order=True)


# ==================== Test Socket Request Handlers ====================


class TestSocketRequestHandlers:
    """测试Socket请求处理器"""

    @pytest.mark.asyncio
    async def test_req_connect(self, trader_instance):
        """测试连接请求"""
        result = await trader_instance._req_connect({})
        assert result is True

    @pytest.mark.asyncio
    async def test_req_disconnect(self, trader_instance):
        """测试断开连接请求"""
        result = await trader_instance._req_disconnect({})
        assert result is True

    @pytest.mark.asyncio
    async def test_req_subscribe(self, trader_instance):
        """测试订阅请求"""
        result = await trader_instance._req_subscribe({})
        assert result is True

    @pytest.mark.asyncio
    async def test_req_unsubscribe(self, trader_instance):
        """测试取消订阅请求"""
        result = await trader_instance._req_unsubscribe({})
        assert result is True

    @pytest.mark.asyncio
    async def test_req_order_success(self, running_trader, mock_trading_engine):
        """测试下单请求成功"""
        order_data = {
            "symbol": "SHFE.rb2505",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 3500.0,
        }

        result = await running_trader._req_order(order_data)

        assert result == "order_123"
        mock_trading_engine.insert_order.assert_called_once_with(
            symbol="SHFE.rb2505", direction="BUY", offset="OPEN", volume=1, price=3500.0
        )

    @pytest.mark.asyncio
    async def test_req_order_without_price(self, running_trader, mock_trading_engine):
        """测试下单请求（无价格，市价单）"""
        order_data = {
            "symbol": "SHFE.rb2505",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
        }

        result = await running_trader._req_order(order_data)

        assert result == "order_123"
        mock_trading_engine.insert_order.assert_called_once_with(
            symbol="SHFE.rb2505", direction="BUY", offset="OPEN", volume=1, price=0
        )

    @pytest.mark.asyncio
    async def test_req_order_no_trading_engine(self, trader_instance):
        """测试无交易引擎时下单"""
        trader_instance.trading_engine = None

        result = await trader_instance._req_order({"symbol": "SHFE.rb2505"})

        assert result is None

    @pytest.mark.asyncio
    async def test_req_order_exception(self, running_trader, mock_trading_engine):
        """测试下单异常处理"""
        mock_trading_engine.insert_order.side_effect = Exception("Connection error")

        result = await running_trader._req_order(
            {"symbol": "SHFE.rb2505", "direction": "BUY", "offset": "OPEN", "volume": 1}
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_req_cancel_success(self, running_trader, mock_trading_engine):
        """测试撤单请求成功"""
        result = await running_trader._req_cancel({"order_id": "order_123"})

        assert result is True
        mock_trading_engine.cancel_order.assert_called_once_with("order_123")

    @pytest.mark.asyncio
    async def test_req_cancel_failure(self, running_trader, mock_trading_engine):
        """测试撤单请求失败"""
        mock_trading_engine.cancel_order.return_value = False

        result = await running_trader._req_cancel({"order_id": "order_123"})

        assert result is False

    @pytest.mark.asyncio
    async def test_req_cancel_no_trading_engine(self, trader_instance):
        """测试无交易引擎时撤单"""
        trader_instance.trading_engine = None

        result = await trader_instance._req_cancel({"order_id": "order_123"})

        assert result is False

    @pytest.mark.asyncio
    async def test_req_get_account(self, running_trader, mock_trading_engine):
        """测试获取账户信息"""
        result = await running_trader._req_get_account({})

        assert result is not None
        assert result["account_id"] == "test_account_001"
        # balance is a float, not string
        assert result["balance"] == 100000.0

    @pytest.mark.asyncio
    async def test_req_get_account_no_engine(self, trader_instance):
        """测试无交易引擎时获取账户"""
        trader_instance.trading_engine = None

        result = await trader_instance._req_get_account({})

        assert result is None

    @pytest.mark.asyncio
    async def test_req_get_order_existing(self, running_trader):
        """测试获取存在的订单"""
        order = OrderData(
            order_id="order_123",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
        )
        running_trader.trading_engine.orders = {"order_123": order}

        result = await running_trader._req_get_order({"order_id": "order_123"})

        assert result is not None
        assert result["order_id"] == "order_123"

    @pytest.mark.asyncio
    async def test_req_get_order_not_existing(self, running_trader):
        """测试获取不存在的订单"""
        result = await running_trader._req_get_order({"order_id": "order_999"})

        assert result is None

    @pytest.mark.asyncio
    async def test_req_get_orders_empty(self, running_trader):
        """测试获取所有订单（空列表）"""
        result = await running_trader._req_get_orders({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_get_orders_with_data(self, running_trader):
        """测试获取所有订单（有数据）"""
        order1 = OrderData(
            order_id="order_1",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status="ACTIVE",
        )
        order2 = OrderData(
            order_id="order_2",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=1,
            price=Decimal("3500"),
            traded=1,
            status="FILLED",
        )
        running_trader.trading_engine.orders = {"order_1": order1, "order_2": order2}

        result = await running_trader._req_get_orders({})

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_req_get_active_orders(self, running_trader):
        """测试获取活动订单"""
        from src.models.object import OrderStatus

        order_active = OrderData(
            order_id="order_active",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=0,
            status=OrderStatus.NOTTRADED.value,
        )
        order_filled = OrderData(
            order_id="order_filled",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
            traded=1,
            status=OrderStatus.ALLTRADED.value,
        )
        running_trader.trading_engine.orders = {
            "order_active": order_active,
            "order_filled": order_filled,
        }

        result = await running_trader._req_get_active_orders({})

        # Only ACTIVE status orders are returned
        # Change to use SUBMITTING or NOTTRADED which are considered active
        assert len(result) == 1
        assert result[0]["order_id"] == "order_active"

    @pytest.mark.asyncio
    async def test_req_get_trade_existing(self, running_trader):
        """测试获取存在的成交"""
        trade = TradeData(
            trade_id="trade_123",
            order_id="order_123",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
        )
        running_trader.trading_engine.trades = {"trade_123": trade}

        result = await running_trader._req_get_trade({"trade_id": "trade_123"})

        assert result is not None
        assert result["trade_id"] == "trade_123"

    @pytest.mark.asyncio
    async def test_req_get_trade_not_existing(self, running_trader):
        """测试获取不存在的成交"""
        result = await running_trader._req_get_trade({"trade_id": "trade_999"})

        assert result is None

    @pytest.mark.asyncio
    async def test_req_get_trades_empty(self, running_trader):
        """测试获取所有成交（空列表）"""
        result = await running_trader._req_get_trades({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_get_trades_with_data(self, running_trader):
        """测试获取所有成交（有数据）"""
        trade1 = TradeData(
            trade_id="trade_1",
            order_id="order_1",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=Decimal("3500"),
        )
        trade2 = TradeData(
            trade_id="trade_2",
            order_id="order_2",
            symbol="SHFE.rb2505",
            account_id="test_account_001",
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=1,
            price=Decimal("3500"),
        )
        running_trader.trading_engine.trades = {"trade_1": trade1, "trade_2": trade2}

        result = await running_trader._req_get_trades({})

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_req_get_positions_empty(self, running_trader):
        """测试获取所有持仓（空列表）"""
        result = await running_trader._req_get_positions({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_get_positions_with_data(self, running_trader):
        """测试获取所有持仓（有数据）"""
        from src.models.object import Exchange

        position1 = PositionData(symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos=1, pos_long=1, pos_short=0)
        position2 = PositionData(symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos=-1, pos_long=0, pos_short=1)
        running_trader.trading_engine.positions = {
            "SHFE.rb2505_LONG": position1,
            "SHFE.rb2505_SHORT": position2,
        }

        result = await running_trader._req_get_positions({})

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_req_get_quotes_empty(self, running_trader):
        """测试获取所有行情（空列表）"""
        result = await running_trader._req_get_quotes({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_get_quotes_with_data(self, running_trader):
        """测试获取所有行情（有数据）"""
        from src.models.object import Exchange

        quote1 = TickData(symbol="SHFE.rb2505", exchange=Exchange.SHFE, datetime=datetime.now(), last_price=Decimal("3500"))
        quote2 = TickData(symbol="SHFE.rb2505", exchange=Exchange.SHFE, datetime=datetime.now(), last_price=Decimal("3510"))
        running_trader.trading_engine.quotes = {"quote_1": quote1, "quote_2": quote2}

        result = await running_trader._req_get_quotes({})

        assert len(result) == 2


# ==================== Test Strategy Management Handlers ====================


class TestStrategyManagementHandlers:
    """测试策略管理处理器"""

    @pytest.mark.asyncio
    async def test_req_list_strategies_empty(self, running_trader):
        """测试获取策略列表（空）"""
        running_trader.strategy_manager.strategies = {}

        result = await running_trader._req_list_strategies({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_list_strategies_with_data(self, running_trader):
        """测试获取策略列表（有数据）"""
        mock_strategy = MagicMock()
        mock_strategy.strategy_id = "strategy_1"
        mock_strategy.active = True
        mock_strategy.config = {"enabled": True, "type": "rsi", "symbol": "SHFE.rb2505"}

        running_trader.strategy_manager.strategies = {"strategy_1": mock_strategy}

        result = await running_trader._req_list_strategies({})

        assert len(result) == 1
        assert result[0]["strategy_id"] == "strategy_1"
        assert result[0]["active"] is True

    @pytest.mark.asyncio
    async def test_req_list_strategies_no_manager(self, trader_instance):
        """测试无策略管理器时获取列表"""
        trader_instance.strategy_manager = None

        result = await trader_instance._req_list_strategies({})

        assert result == []

    @pytest.mark.asyncio
    async def test_req_get_strategy_existing(self, running_trader):
        """测试获取指定策略（存在）"""
        mock_strategy = MagicMock()
        mock_strategy.strategy_id = "strategy_1"
        mock_strategy.active = True
        mock_strategy.config = {"enabled": True, "type": "rsi"}

        running_trader.strategy_manager.strategies = {"strategy_1": mock_strategy}

        result = await running_trader._req_get_strategy({"strategy_id": "strategy_1"})

        assert result is not None
        assert result["strategy_id"] == "strategy_1"

    @pytest.mark.asyncio
    async def test_req_get_strategy_not_existing(self, running_trader):
        """测试获取指定策略（不存在）"""
        running_trader.strategy_manager.strategies = {}

        result = await running_trader._req_get_strategy({"strategy_id": "strategy_999"})

        assert result is None

    @pytest.mark.asyncio
    async def test_req_start_strategy(self, running_trader, mock_strategy_manager):
        """测试启动策略"""
        result = await running_trader._req_start_strategy({"strategy_id": "strategy_1"})

        assert result is True
        mock_strategy_manager.start_strategy.assert_called_once_with("strategy_1")

    @pytest.mark.asyncio
    async def test_req_start_strategy_no_id(self, running_trader):
        """测试启动策略（无ID）"""
        result = await running_trader._req_start_strategy({})

        assert result is False

    @pytest.mark.asyncio
    async def test_req_stop_strategy(self, running_trader, mock_strategy_manager):
        """测试停止策略"""
        result = await running_trader._req_stop_strategy({"strategy_id": "strategy_1"})

        assert result is True
        mock_strategy_manager.stop_strategy.assert_called_once_with("strategy_1")

    @pytest.mark.asyncio
    async def test_req_start_all_strategies(self, running_trader, mock_strategy_manager):
        """测试启动所有策略"""
        result = await running_trader._req_start_all_strategies({})

        assert result is True
        mock_strategy_manager.start_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_req_stop_all_strategies(self, running_trader, mock_strategy_manager):
        """测试停止所有策略"""
        result = await running_trader._req_stop_all_strategies({})

        assert result is True
        mock_strategy_manager.stop_all.assert_called_once()

    def test_build_strategy_config(self, running_trader):
        """测试构建策略配置"""
        mock_strategy = MagicMock()
        mock_strategy.config = {
            "enabled": True,
            "type": "rsi_strategy",
            "symbol": "SHFE.rb2505",
            "exchange": "SHFE",
            "volume": 1,
            "volume_per_trade": 2,
            "max_position": 5,
            "bar": "M1",
            "params_file": "test.csv",
            "take_profit_pct": 0.02,
            "stop_loss_pct": 0.01,
            "fee_rate": 0.0001,
            "StartTime": "09:30:00",
            "EndTime": "14:50:00",
            "ForceExitTime": "14:55:00",
            "one_trade_per_day": True,
            "rsi_period": 14,
            "rsi_long_threshold": 50,
            "rsi_short_threshold": 80,
            "short_kline_period": 5,
            "long_kline_period": 15,
            "DirThr": 0.7,
            "UsedSignal": True,  # Changed to boolean
        }

        result = running_trader._build_strategy_config(mock_strategy)

        assert result["enabled"] is True
        assert result["strategy_type"] == "rsi_strategy"
        assert result["symbol"] == "SHFE.rb2505"
        assert result["exchange"] == "SHFE"
        assert result["volume_per_trade"] == 2
        assert result["max_position"] == 5
        assert result["bar"] == "M1"
        assert result["take_profit_pct"] == 0.02
        assert result["stop_loss_pct"] == 0.01
        assert result["trade_start_time"] == "09:30:00"
        assert result["trade_end_time"] == "14:50:00"
        assert result["force_exit_time"] == "14:55:00"
        assert result["one_trade_per_day"] is True
        assert result["rsi_period"] == 14
        assert result["dir_threshold"] == 0.7
        assert result["used_signal"] is True


# ==================== Test System Param Handlers ====================


class TestSystemParamHandlers:
    """测试系统参数处理器"""

    @pytest.mark.asyncio
    async def test_req_get_jobs_with_scheduler(self, running_trader):
        """测试获取任务列表（有调度器）"""
        mock_job = MagicMock()
        mock_job.model_dump = MagicMock(return_value={"job_id": "job_1"})

        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs = MagicMock(return_value={"job_1": mock_job})
        running_trader.task_scheduler = mock_scheduler

        result = await running_trader._req_get_jobs({})

        assert len(result) == 1
        assert result[0]["job_id"] == "job_1"

    @pytest.mark.asyncio
    async def test_req_get_jobs_no_scheduler(self, trader_instance):
        """测试获取任务列表（无调度器）"""
        trader_instance.trading_engine = None

        result = await trader_instance._req_get_jobs({})

        assert result == []


# ==================== Test Database Initialization ====================


class TestDatabaseInitialization:
    """测试数据库初始化"""

    @pytest.mark.asyncio
    async def test_init_database_creates_new(self, trader_instance, tmp_path):
        """测试创建新数据库"""
        from src.utils.database import init_database

        db_file = tmp_path / "new_test.db"
        trader_instance.account_config.paths.database = str(db_file)

        with patch("src.utils.database.init_database", wraps=init_database) as mock_init_db, patch(
            "src.trader.trader.get_database", return_value=MagicMock()
        ) as mock_get_db:
            mock_db = MagicMock()
            mock_session = MagicMock()
            mock_init_db.return_value = mock_db
            mock_db.get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db.get_session.return_value.__exit__ = MagicMock(return_value=False)

            await trader_instance._init_database()

            # init_database should be called since file doesn't exist
            assert mock_init_db.called

    @pytest.mark.asyncio
    async def test_init_database_existing(self, trader_instance, tmp_path):
        """测试数据库已存在"""
        db_file = tmp_path / "existing_test.db"
        db_file.touch()  # 创建文件
        trader_instance.account_config.paths.database = str(db_file)

        with patch("src.trader.trader.init_database") as mock_init_db:
            await trader_instance._init_database()
            mock_init_db.assert_called_once()


# ==================== Test Heartbeat Loop ====================


class TestHeartbeatLoop:
    """测试心跳循环"""

    @pytest.mark.asyncio
    async def test_heartbeat_loop_sends_heartbeat(self, trader_instance, mock_socket_server):
        """测试心跳循环发送心跳"""
        trader_instance.socket_server = mock_socket_server
        trader_instance._running = True

        # 运行一次心跳后停止
        heartbeat_task = asyncio.create_task(trader_instance._heartbeat_loop(interval=0.1))
        await asyncio.sleep(0.15)
        trader_instance._running = False
        await heartbeat_task

        mock_socket_server.send_heartbeat.assert_called()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_without_socket(self, trader_instance):
        """测试无Socket时心跳循环"""
        trader_instance.socket_server = None
        trader_instance._running = True

        # 不应该抛出异常
        heartbeat_task = asyncio.create_task(trader_instance._heartbeat_loop(interval=0.1))
        await asyncio.sleep(0.15)
        trader_instance._running = False
        await heartbeat_task

    @pytest.mark.asyncio
    async def test_heartbeat_loop_handles_exception(self, trader_instance, mock_socket_server):
        """测试心跳循环处理异常"""
        trader_instance.socket_server = mock_socket_server
        trader_instance._running = True
        mock_socket_server.send_heartbeat.side_effect = Exception("Connection error")

        # 不应该抛出异常
        heartbeat_task = asyncio.create_task(trader_instance._heartbeat_loop(interval=0.1))
        await asyncio.sleep(0.15)
        trader_instance._running = False

        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass  # 预期的取消异常


# ==================== Test Proxy Callback ====================


class TestProxyCallback:
    """测试代理回调"""

    def test_set_proxy_callback(self, trader_instance):
        """测试设置代理回调"""
        callback = MagicMock()
        trader_instance.set_proxy_callback(callback)

        assert trader_instance._proxy_msg_callback == callback


# ==================== Test Get Task Scheduler ====================


class TestGetTaskScheduler:
    """测试获取任务调度器"""

    def test_get_task_scheduler_with_scheduler(self, trader_instance):
        """测试获取任务调度器（存在）"""
        mock_scheduler = MagicMock()
        trader_instance.task_scheduler = mock_scheduler

        result = trader_instance.get_task_scheduler()

        assert result == mock_scheduler

    def test_get_task_scheduler_without_scheduler(self, trader_instance):
        """测试获取任务调度器（不存在）"""
        trader_instance.task_scheduler = None

        result = trader_instance.get_task_scheduler()

        assert result is None


# ==================== Test Standalone Mode ====================


class TestStandaloneMode:
    """测试独立模式"""

    @pytest.mark.asyncio
    async def test_run_standalone_starts_socket_server(self, trader_instance, mock_socket_server):
        """测试独立模式启动Socket服务器"""
        trader_instance._socket_path = "./test.sock"

        with patch("src.trader.trader.SocketServer", return_value=mock_socket_server):
            await trader_instance._run_standalone()

            mock_socket_server.start.assert_called_once()
            mock_socket_server.register_handlers_from_instance.assert_called_once_with(trader_instance)


# ==================== Edge Cases and Error Handling ====================


class TestEdgeCases:
    """测试边界情况和错误处理"""

    @pytest.mark.asyncio
    async def test_start_with_invalid_enum_values(self, running_trader, mock_trading_engine):
        """测试下单时无效的枚举值"""
        mock_trading_engine.insert_order.side_effect = ValueError("Invalid direction")

        result = await running_trader._req_order(
            {"symbol": "SHFE.rb2505", "direction": "INVALID", "offset": "OPEN", "volume": 1}
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_order_with_exception(self, running_trader, mock_trading_engine):
        """测试撤单时抛出异常"""
        mock_trading_engine.cancel_order.side_effect = Exception("Network error")

        result = await running_trader._req_cancel({"order_id": "order_123"})

        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_start_stop_cycles(self, trader_instance, mock_trading_engine, mock_socket_server, mock_event_engine):
        """测试多次启动停止循环"""
        with patch(
            "src.trader.trader.TradingEngine", return_value=mock_trading_engine
        ), patch(
            "src.trader.trader.SwitchPosManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.JobManager", return_value=MagicMock()
        ), patch(
            "src.trader.trader.SocketServer", return_value=mock_socket_server
        ), patch(
            "src.trader.trader.get_app_context",
            return_value=MagicMock(get_event_engine=MagicMock(return_value=mock_event_engine)),
        ), patch.object(
            trader_instance, "_init_database", new=AsyncMock()
        ), patch.object(
            trader_instance, "_init_strategy_manager", new=AsyncMock()
        ):
            # 第一次启动
            start_task = asyncio.create_task(trader_instance.start())
            await asyncio.sleep(0.1)
            trader_instance._running = False
            await start_task

            # 停止
            trader_instance._running = True  # 重新设置以便第二次启动
            trader_instance.strategy_manager = MagicMock()
            trader_instance.strategy_manager.stop_all = MagicMock()

            # 第二次启动
            start_task = asyncio.create_task(trader_instance.start())
            await asyncio.sleep(0.1)
            trader_instance._running = False
            await start_task

            # 应该成功完成两次启动
            assert True

    @pytest.mark.asyncio
    async def test_request_handler_with_missing_fields(self, running_trader):
        """测试请求处理器缺少必需字段"""
        result = await running_trader._req_order({})

        assert result is None

    @pytest.mark.asyncio
    async def test_stop_when_already_stopped(self, trader_instance):
        """测试停止已停止的Trader"""
        trader_instance._running = False
        trader_instance.trading_engine = None
        trader_instance.strategy_manager = None
        trader_instance.task_scheduler = None
        trader_instance.socket_server = None

        # 不应该抛出异常
        await trader_instance.stop()
        assert trader_instance._running is False
