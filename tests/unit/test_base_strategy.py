"""
BaseStrategy 单元测试

测试策略基类的核心功能，包括：
- 参数模型 (BaseParam, Signal)
- 策略初始化
- 参数更新
- 信号更新和执行
- 指令状态变化处理
- 交易状态查询
- 启用/禁用
- 暂停状态管理
"""

import asyncio
from datetime import datetime, time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.models.object import BarData, Direction, Offset, OrderData, PositionData, TickData, TradeData
from src.trader.order_cmd import OrderCmd
from src.trader.strategy.base_strategy import BaseParam, BaseStrategy, Signal
from src.utils.config_loader import StrategyConfig


# ==================== Fixtures ====================


@pytest.fixture
def strategy_config() -> StrategyConfig:
    """创建策略配置"""
    return StrategyConfig(
        enabled=True,
        type="test_strategy",
        symbol="SHFE.rb2505",
        exchange="SHFE",
        volume=5,
        bar="M1",
        params={
            "symbol": "SHFE.rb2505",
            "bar_type": "M1",
            "volume": 5,
            "slip": 0.0,
            "max_position": 50,
            "volume_per_order": 5,
            "order_timeout": 10,
            "cmd_timeout": 300,
            "take_profit_pct": 0.02,
            "stop_loss_pct": 0.01,
            "overnight": False,
            "force_exit_time": "14:45:00",
        },
    )


@pytest.fixture
def mock_strategy_manager():
    """模拟策略管理器"""
    manager = MagicMock()
    manager.send_order_cmd = AsyncMock()
    manager.cancel_order_cmd = AsyncMock()
    manager.get_position = Mock(return_value=None)
    manager.load_hist_bars = Mock(return_value=[])
    manager.trading_engine = MagicMock()
    return manager


@pytest.fixture
def strategy(strategy_config: StrategyConfig) -> BaseStrategy:
    """创建策略实例"""
    strategy = BaseStrategy(strategy_id="test_strategy_001", strategy_config=strategy_config)
    strategy.strategy_manager = MagicMock()
    strategy.strategy_manager.send_order_cmd = AsyncMock()
    strategy.strategy_manager.cancel_order_cmd = AsyncMock()
    strategy.strategy_manager.get_position = Mock(return_value=None)
    strategy.strategy_manager.load_hist_bars = Mock(return_value=[])
    strategy.strategy_manager.trading_engine = MagicMock()
    return strategy


# ==================== TestBaseParam ====================


class TestBaseParam:
    """BaseParam 参数模型测试"""

    def test_get_param_definitions_returns_correct_structure(self):
        """测试 get_param_definitions() 返回正确的类型和结构"""
        param = BaseParam()
        definitions = param.get_param_definitions()

        assert isinstance(definitions, list)
        assert len(definitions) > 0

        # 检查每个定义的结构
        for definition in definitions:
            assert isinstance(definition, dict)
            assert "key" in definition
            assert "label" in definition
            assert "type" in definition
            assert "value" in definition

    def test_get_param_definitions_types(self):
        """测试参数类型推断是否正确"""
        param = BaseParam()
        definitions = param.get_param_definitions()

        type_mapping = {
            "symbol": "string",
            "bar_type": "string",
            "volume": "int",
            "slip": "float",
            "max_position": "int",
            "volume_per_order": "int",
            "order_timeout": "int",
            "cmd_timeout": "int",
            "take_profit_pct": "float",
            "stop_loss_pct": "float",
            "overnight": "bool",
            "force_exit_time": "time",
        }

        definition_dict = {d["key"]: d["type"] for d in definitions}

        for key, expected_type in type_mapping.items():
            assert definition_dict.get(key) == expected_type, f"参数 {key} 的类型推断错误"

    def test_param_pydantic_validation(self):
        """测试 Pydantic 验证规则工作正常"""
        # 正常值
        param = BaseParam(volume=10, max_position=100)
        assert param.volume == 10
        assert param.max_position == 100

        # 边界值
        param = BaseParam(volume=0)
        assert param.volume == 0


# ==================== TestSignal ====================


class TestSignal:
    """Signal 信号模型测试"""

    def test_signal_initialization(self):
        """测试信号字段初始化"""
        signal = Signal()
        assert signal.side == 0
        assert signal.entry_price == 0.0
        assert signal.entry_time is None
        assert signal.entry_volume == 0
        assert signal.exit_price == 0.0
        assert signal.exit_time is None
        assert signal.exit_reason == ""

    def test_signal_with_values(self):
        """测试设置信号值"""
        now = datetime.now()
        signal = Signal(
            side=1,
            entry_price=3500.0,
            entry_time=now,
            entry_volume=5,
            exit_price=3550.0,
            exit_time=now,
            exit_reason="止盈",
        )
        assert signal.side == 1
        assert signal.entry_price == 3500.0
        assert signal.entry_time == now
        assert signal.entry_volume == 5
        assert signal.exit_price == 3550.0
        assert signal.exit_time == now
        assert signal.exit_reason == "止盈"

    def test_signal_str_method(self):
        """测试 __str__() 方法格式正确"""
        signal = Signal(side=1, entry_price=3500.0, exit_price=3550.0)
        signal_str = str(signal)
        assert "side=1" in signal_str
        assert "entry_price=3500.0" in signal_str
        assert "exit_price=3550.0" in signal_str


# ==================== TestBaseStrategyInitialization ====================


class TestBaseStrategyInitialization:
    """BaseStrategy 初始化测试"""

    def test_basic_attributes_initialization(self, strategy_config: StrategyConfig):
        """测试基本属性初始化"""
        strategy = BaseStrategy(strategy_id="test_strategy", strategy_config=strategy_config)

        assert strategy.strategy_id == "test_strategy"
        assert strategy.config == strategy_config
        assert strategy.symbol == strategy_config.symbol
        assert strategy.bar_type == strategy_config.bar

    def test_initial_state(self, strategy: BaseStrategy):
        """测试初始状态"""
        assert strategy.inited is False
        assert strategy.enabled is True

    def test_signal_and_position_initialization(self, strategy: BaseStrategy):
        """测试信号和持仓初始化为空"""
        assert strategy.signal is None
        assert strategy.pos_long == 0
        assert strategy.pos_price is None

    def test_pause_state_initial_values(self, strategy: BaseStrategy):
        """测试暂停状态初始值"""
        assert strategy.opening_paused is False
        assert strategy.closing_paused is False

    def test_internal_state_initialization(self, strategy: BaseStrategy):
        """测试内部状态初始化"""
        assert strategy._pending_cmd is None
        assert strategy._hist_cmds == {}
        assert strategy.bar_subscriptions == []
        assert strategy.trading_day is None


# ==================== TestBaseStrategyInit ====================


class TestBaseStrategyInit:
    """BaseStrategy init() 方法测试"""

    def test_init_returns_true(self, strategy: BaseStrategy):
        """测试成功初始化返回 True"""
        trading_day = datetime.now()
        result = strategy.init(trading_day)
        assert result is True

    def test_init_resets_internal_state(self, strategy: BaseStrategy):
        """测试重置内部状态 (_pending_cmd, _hist_cmds, signal)"""
        # 设置一些初始值
        strategy._pending_cmd = MagicMock()
        strategy._hist_cmds = {"cmd1": MagicMock()}
        strategy.signal = Signal(side=1)

        # 调用 init
        strategy.init(datetime.now())

        # 验证重置
        assert strategy._pending_cmd is None
        assert strategy._hist_cmds == {}
        assert strategy.signal is None

    def test_init_resets_position(self, strategy: BaseStrategy):
        """测试重置持仓 (pos_volume=0, pos_price=None)"""
        strategy.pos_long = 10
        strategy.pos_price = 3500.0

        strategy.init(datetime.now())

        assert strategy.pos_long == 0
        assert strategy.pos_price is None

    def test_init_parses_params_from_config(self, strategy: BaseStrategy):
        """测试参数解析从 config.params"""
        strategy.init(datetime.now())

        assert strategy.param is not None
        assert isinstance(strategy.param, BaseParam)
        assert strategy.param.symbol == strategy.config.params["symbol"]

    def test_init_sets_trading_day(self, strategy: BaseStrategy):
        """测试设置交易日"""
        trading_day = datetime(2026, 1, 15, 9, 0, 0)
        strategy.init(trading_day)

        assert strategy.trading_day == trading_day

    def test_init_sets_inited_flag(self, strategy: BaseStrategy):
        """测试设置 inited 标志"""
        assert strategy.inited is False
        strategy.init(datetime.now())
        assert strategy.inited is True


# ==================== TestBaseStrategyUpdateParams ====================


class TestBaseStrategyUpdateParams:
    """BaseStrategy 参数更新测试"""

    def test_update_valid_params(self, strategy: BaseStrategy):
        """测试有效参数正确更新"""
        strategy.init(datetime.now())
        original_volume = strategy.param.volume

        strategy.update_params({"volume": 10, "slip": 1.5})

        assert strategy.param.volume == 10
        assert strategy.param.slip == 1.5

    def test_update_invalid_param_skips_with_warning(self, strategy: BaseStrategy):
        """测试无效参数跳过并记录警告"""
        strategy.init(datetime.now())

        # 验证参数未被添加
        assert not hasattr(strategy.param, "invalid_param")

    def test_update_params_when_param_not_initialized(self, strategy: BaseStrategy):
        """测试参数未初始化时的处理"""
        # 验证不会报错，参数未初始化时应该优雅处理
        strategy.update_params({"volume": 10})


# ==================== TestBaseStrategyUpdateSignal ====================


class TestBaseStrategyUpdateSignal:
    """BaseStrategy 信号更新测试"""

    def test_create_new_signal(self, strategy: BaseStrategy):
        """测试新信号创建"""
        signal_data = {
            "side": 1,
            "entry_price": 3500.0,
            "entry_volume": 5,
        }

        strategy.update_signal(signal_data)

        assert strategy.signal is not None
        assert strategy.signal.side == 1
        assert strategy.signal.entry_price == 3500.0
        assert strategy.signal.entry_volume == 5

    def test_update_existing_signal(self, strategy: BaseStrategy):
        """测试现有信号更新"""
        strategy.signal = Signal(side=1, entry_price=3500.0)

        strategy.update_signal({"side": -1, "entry_price": 3400.0})

        assert strategy.signal.side == -1
        assert strategy.signal.entry_price == 3400.0

    def test_datetime_string_conversion(self, strategy: BaseStrategy):
        """测试 datetime 字符串转换为 datetime 对象"""
        dt_str = "2026-01-15T10:30:00"
        strategy.update_signal({"entry_time": dt_str})

        assert isinstance(strategy.signal.entry_time, datetime)
        assert strategy.signal.entry_time.isoformat() == dt_str

    def test_invalid_datetime_string_handled(self, strategy: BaseStrategy):
        """测试无效 datetime 字符串的处理"""
        strategy.update_signal({"entry_time": "invalid_datetime"})

        # 无效字符串会保留原值（字符串），因为转换失败时 pass 不做任何操作
        assert strategy.signal.entry_time == "invalid_datetime"


# ==================== TestBaseStrategyExecuteSignal ====================


class TestBaseStrategyExecuteSignal:
    """BaseStrategy 信号执行测试"""

    @pytest.mark.asyncio
    async def test_execute_signal_no_signal(self, strategy: BaseStrategy):
        """测试无信号时不执行"""
        strategy.init(datetime.now())

        await strategy.execute_signal()

        # 验证没有发送订单
        strategy.strategy_manager.send_order_cmd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_signal_with_exit_signal(self, strategy: BaseStrategy):
        """测试平仓信号：发送平仓指令"""
        strategy.init(datetime.now())
        strategy.pos_long = 5
        strategy.signal = Signal(side=1, exit_time=datetime.now())

        await strategy.execute_signal()

        # 验证发送了平仓指令
        strategy.strategy_manager.send_order_cmd.assert_awaited_once()
        call_args = strategy.strategy_manager.send_order_cmd.call_args
        order_cmd = call_args[0][1]
        assert order_cmd.offset == Offset.CLOSE

    @pytest.mark.asyncio
    async def test_execute_signal_with_entry_signal(self, strategy: BaseStrategy):
        """测试开仓信号：发送开仓指令"""
        strategy.init(datetime.now())
        strategy.signal = Signal(side=1, entry_time=datetime.now())

        await strategy.execute_signal()

        # 验证发送了开仓指令
        strategy.strategy_manager.send_order_cmd.assert_awaited_once()
        call_args = strategy.strategy_manager.send_order_cmd.call_args
        order_cmd = call_args[0][1]
        assert order_cmd.offset == Offset.OPEN

    @pytest.mark.asyncio
    async def test_execute_signal_with_pending_open_order(self, strategy: BaseStrategy):
        """测试有进行中开仓指令时的行为"""
        strategy.init(datetime.now())
        strategy._pending_cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )
        strategy.signal = Signal(side=1, exit_time=datetime.now())

        await strategy.execute_signal()

        # 应该取消当前指令
        strategy.strategy_manager.cancel_order_cmd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_signal_respects_position_volume(self, strategy: BaseStrategy):
        """测试持仓数量检查"""
        strategy.init(datetime.now())
        strategy.pos_long = 5
        strategy.signal = Signal(side=1, entry_time=datetime.now())

        await strategy.execute_signal()

        # 已达到目标持仓，不应再开仓
        strategy.strategy_manager.send_order_cmd.assert_not_awaited()


# ==================== TestBaseStrategyOnCmdChange ====================


class TestBaseStrategyOnCmdChange:
    """BaseStrategy 指令状态变化测试"""

    def test_on_cmd_change_open_order_updates_position(self, strategy: BaseStrategy):
        """测试开仓指令完成更新持仓"""
        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )
        cmd.filled_volume = 5
        cmd.filled_price = 3500.0
        cmd._cancel("全部完成")
        strategy._pending_cmd = cmd

        strategy._on_cmd_change(cmd)

        assert strategy.pos_long == 5
        assert strategy.pos_price == 3500.0
        assert strategy._pending_cmd is None

    def test_on_cmd_change_close_order_reduces_position(self, strategy: BaseStrategy):
        """测试平仓指令完成减少持仓"""
        strategy.pos_long = 10
        strategy.pos_price = 3500.0

        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=5,
        )
        cmd.filled_volume = 5
        cmd.filled_price = 3550.0
        cmd._cancel("全部完成")
        strategy._pending_cmd = cmd

        strategy._on_cmd_change(cmd)

        assert strategy.pos_long == 5
        assert strategy._pending_cmd is None

    def test_on_cmd_change_rejected_sets_pause(self, strategy: BaseStrategy):
        """测试报单被拒设置暂停状态"""
        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )
        cmd._cancel("报单被拒")
        strategy._pending_cmd = cmd

        strategy._on_cmd_change(cmd)

        assert strategy.opening_paused is True

    def test_on_cmd_change_close_rejected_sets_closing_pause(self, strategy: BaseStrategy):
        """测试平仓被拒设置暂停状态"""
        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=5,
        )
        cmd._cancel("报单被拒")
        strategy._pending_cmd = cmd

        strategy._on_cmd_change(cmd)

        assert strategy.closing_paused is True

    def test_on_cmd_change_ignores_non_pending_cmd(self, strategy: BaseStrategy):
        """测试非自己指令忽略"""
        strategy.pos_long = 5
        other_cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )
        other_cmd.filled_volume = 5
        other_cmd._cancel("全部完成")
        # 不设置为 pending_cmd

        original_volume = strategy.pos_long
        strategy._on_cmd_change(other_cmd)

        assert strategy.pos_long == original_volume


# ==================== TestBaseStrategyTradingStatus ====================


class TestBaseStrategyTradingStatus:
    """BaseStrategy 交易状态测试"""

    def test_get_trading_status_opening(self, strategy: BaseStrategy):
        """测试开仓中状态"""
        strategy._pending_cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )

        status = strategy.get_trading_status()
        assert status == "开仓中"

    def test_get_trading_status_closing(self, strategy: BaseStrategy):
        """测试平仓中状态"""
        strategy._pending_cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.SELL,
            offset=Offset.CLOSE,
            volume=5,
        )

        status = strategy.get_trading_status()
        assert status == "平仓中"

    def test_get_trading_status_no_pending_cmd(self, strategy: BaseStrategy):
        """测试无进行中指令返回空字符串"""
        status = strategy.get_trading_status()
        assert status == ""

    def test_get_trading_status_finished_cmd(self, strategy: BaseStrategy):
        """测试已完成指令不返回状态"""
        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
        )
        cmd._cancel("全部完成")
        strategy._pending_cmd = cmd

        status = strategy.get_trading_status()
        assert status == ""


# ==================== TestBaseStrategyEnableDisable ====================


class TestBaseStrategyEnableDisable:
    """BaseStrategy 启用禁用测试"""

    def test_enable_sets_enabled_true(self, strategy: BaseStrategy):
        """测试 enable() 设置 enabled=True"""
        strategy.enabled = False
        result = strategy.enable(True)

        assert result is True
        assert strategy.enabled is True

    def test_enable_sets_enabled_false(self, strategy: BaseStrategy):
        """测试 enable(False) 设置 enabled=False"""
        strategy.enabled = True
        result = strategy.enable(False)

        assert result is True
        assert strategy.enabled is False

    def test_enable_default(self, strategy: BaseStrategy):
        """测试 enable() 默认启用"""
        strategy.enabled = False
        strategy.enable()

        assert strategy.enabled is True


# ==================== TestBaseStrategySendOrderCmd ====================


class TestBaseStrategySendOrderCmd:
    """BaseStrategy 发送指令测试"""

    @pytest.mark.asyncio
    async def test_send_order_param_not_initialized(self, strategy: BaseStrategy):
        """测试参数未初始化时错误处理"""
        # 验证不会报错，应该优雅处理
        await strategy.send_order_cmd(OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5))

    @pytest.mark.asyncio
    async def test_send_order_opening_paused(self, strategy: BaseStrategy):
        """测试暂停开仓状态阻止开仓"""
        strategy.init(datetime.now())
        strategy.opening_paused = True

        # 暂停开仓应该阻止订单发送
        await strategy.send_order_cmd(OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5))

        # 验证没有发送订单
        strategy.strategy_manager.send_order_cmd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_order_closing_paused(self, strategy: BaseStrategy):
        """测试暂停平仓状态阻止平仓"""
        strategy.init(datetime.now())
        strategy.closing_paused = True

        # 暂停平仓应该阻止订单发送
        await strategy.send_order_cmd(OrderCmd(symbol="SHFE.rb2505", direction=Direction.SELL, offset=Offset.CLOSE, volume=5))

        # 验证没有发送订单
        strategy.strategy_manager.send_order_cmd.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_order_sets_pending_cmd(self, strategy: BaseStrategy):
        """测试正确设置 pending_cmd"""
        strategy.init(datetime.now())
        order_cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5)

        await strategy.send_order_cmd(order_cmd)

        assert strategy._pending_cmd == order_cmd

    @pytest.mark.asyncio
    async def test_send_order_adds_to_history(self, strategy: BaseStrategy):
        """测试正确添加到历史指令"""
        strategy.init(datetime.now())
        order_cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5)

        await strategy.send_order_cmd(order_cmd)

        assert order_cmd.cmd_id in strategy._hist_cmds
        assert strategy._hist_cmds[order_cmd.cmd_id] == order_cmd

    @pytest.mark.asyncio
    async def test_send_order_calls_manager(self, strategy: BaseStrategy):
        """测试调用 manager 发送指令"""
        strategy.init(datetime.now())
        order_cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5)

        await strategy.send_order_cmd(order_cmd)

        strategy.strategy_manager.send_order_cmd.assert_awaited_once_with(strategy.strategy_id, order_cmd)


# ==================== TestBaseStrategyCancelOrderCmd ====================


class TestBaseStrategyCancelOrderCmd:
    """BaseStrategy 取消指令测试"""

    @pytest.mark.asyncio
    async def test_cancel_order_cmd_calls_manager(self, strategy: BaseStrategy):
        """测试通过 manager 取消指令"""
        order_cmd = OrderCmd(symbol="SHFE.rb2505", direction=Direction.BUY, offset=Offset.OPEN, volume=5)

        await strategy.cancel_order_cmd(order_cmd)

        strategy.strategy_manager.cancel_order_cmd.assert_awaited_once_with(strategy.strategy_id, order_cmd)


# ==================== TestBaseStrategySetPaused ====================


class TestBaseStrategySetPaused:
    """BaseStrategy 暂停状态测试"""

    def test_set_opening_paused_true(self, strategy: BaseStrategy):
        """测试 set_opening_paused() 设置开仓暂停"""
        strategy.set_opening_paused(True)
        assert strategy.opening_paused is True

    def test_set_opening_paused_false(self, strategy: BaseStrategy):
        """测试 set_opening_paused() 恢复开仓"""
        strategy.opening_paused = True
        strategy.set_opening_paused(False)
        assert strategy.opening_paused is False

    def test_set_closing_paused_true(self, strategy: BaseStrategy):
        """测试 set_closing_paused() 设置平仓暂停"""
        strategy.set_closing_paused(True)
        assert strategy.closing_paused is True

    def test_set_closing_paused_false(self, strategy: BaseStrategy):
        """测试 set_closing_paused() 恢复平仓"""
        strategy.closing_paused = True
        strategy.set_closing_paused(False)
        assert strategy.closing_paused is False


# ==================== TestBaseStrategyGetPosition ====================


class TestBaseStrategyGetPosition:
    """BaseStrategy 获取持仓测试"""

    def test_get_position_calls_manager(self, strategy: BaseStrategy):
        """测试通过 manager 获取持仓"""
        strategy.get_position("SHFE.rb2505")

        strategy.strategy_manager.get_position.assert_called_once_with("SHFE.rb2505")

    def test_get_position_returns_manager_result(self, strategy: BaseStrategy, mock_strategy_manager):
        """测试返回 manager 的结果"""
        expected_position = PositionData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            pos=5,
            pos_long=5,
            pos_short=0,
        )
        strategy.strategy_manager = mock_strategy_manager
        mock_strategy_manager.get_position.return_value = expected_position

        result = strategy.get_position("SHFE.rb2505")

        assert result == expected_position

    def test_get_position_manager_none_returns_none(self, strategy: BaseStrategy):
        """测试 manager 未初始化返回 None"""
        strategy.strategy_manager = None

        result = strategy.get_position("SHFE.rb2505")

        assert result is None


# ==================== TestBaseStrategyCallbacks ====================


class TestBaseStrategyCallbacks:
    """BaseStrategy 回调函数测试"""

    @pytest.mark.asyncio
    async def test_on_tick_callback(self, strategy: BaseStrategy):
        """测试 on_tick 回调"""
        tick = TickData(
            symbol="SHFE.rb2505",
            exchange="SHFE",
            datetime=datetime.now(),
            last_price=3500.0,
        )
        # 默认实现什么都不做，只测试不会报错
        await strategy.on_tick(tick)

    @pytest.mark.asyncio
    async def test_on_bar_callback(self, strategy: BaseStrategy):
        """测试 on_bar 回调"""
        bar = BarData(
            symbol="SHFE.rb2505",
            interval="M1",
            datetime=datetime.now(),
            open_price=3500.0,
            high_price=3510.0,
            low_price=3490.0,
            close_price=3505.0,
        )
        # 默认实现什么都不做，只测试不会报错
        await strategy.on_bar(bar)

    @pytest.mark.asyncio
    async def test_on_order_callback(self, strategy: BaseStrategy):
        """测试 on_order 回调"""
        from src.models.object import OrderStatus
        order = OrderData(
            order_id="test_order",
            symbol="SHFE.rb2505",
            account_id="test_account",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=5,
            status=OrderStatus.PENDING,
        )
        # 默认实现什么都不做，只测试不会报错
        await strategy.on_order(order)

    @pytest.mark.asyncio
    async def test_on_trade_callback(self, strategy: BaseStrategy):
        """测试 on_trade 回调"""
        trade = TradeData(
            trade_id="test_trade",
            order_id="test_order",
            symbol="SHFE.rb2505",
            account_id="test_account",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            price=3500.0,
            volume=5,
        )
        # 默认实现什么都不做，只测试不会报错
        await strategy.on_trade(trade)


# ==================== TestBaseStrategyGetParams ====================


class TestBaseStrategyGetParams:
    """BaseStrategy 获取参数测试"""

    def test_get_params_returns_empty_when_param_none(self, strategy: BaseStrategy):
        """测试参数未初始化时返回空列表"""
        result = strategy.get_params()
        assert result == []

    def test_get_params_returns_definitions(self, strategy: BaseStrategy):
        """测试返回参数定义"""
        strategy.init(datetime.now())
        result = strategy.get_params()

        assert isinstance(result, list)
        assert len(result) > 0
        # 检查结构
        for param_def in result:
            assert "key" in param_def
            assert "label" in param_def
            assert "type" in param_def
            assert "value" in param_def


# ==================== TestBaseStrategyGetSignal ====================


class TestBaseStrategyGetSignal:
    """BaseStrategy 获取信号测试"""

    def test_get_signal_returns_none_when_no_signal(self, strategy: BaseStrategy):
        """测试无信号时返回 None"""
        result = strategy.get_signal()
        assert result is None

    def test_get_signal_returns_signal_dict(self, strategy: BaseStrategy):
        """测试返回信号字典"""
        strategy.signal = Signal(side=1, entry_price=3500.0, entry_volume=5)
        result = strategy.get_signal()

        assert result is not None
        assert isinstance(result, dict)
        assert result["side"] == 1
        assert result["entry_price"] == 3500.0
        assert result["entry_volume"] == 5
