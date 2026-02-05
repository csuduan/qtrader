"""
报单指令执行器测试
"""

import time
from decimal import Decimal
from unittest.mock import MagicMock

from src.models.object import (
    Direction,
    Offset,
    OrderData,
    OrderStatus,
    TradeData,
)
from src.trader.order_cmd import OrderCmd, OrderCmdStatus, SplitStrategyType
from src.trader.order_cmd_executor import OrderCmdExecutor
from src.utils.event_engine import EventEngine


def test_executor_initialization():
    """测试执行器初始化"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    assert executor.active_count == 0
    assert executor.total_count == 0
    assert not executor._running

    status = executor.get_status()
    assert status["running"] is False
    assert status["active_count"] == 0
    assert status["total_count"] == 0
    assert status["active_commands"] == []

    print("test_executor_initialization passed")


def test_executor_start_stop():
    """测试执行器启动和停止"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_event_engine.register.return_value = "handler-1"

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    executor.start()
    assert executor._running is True
    assert executor._thread is not None

    # 验证事件订阅
    assert mock_event_engine.register.call_count == 2

    executor.stop()
    assert executor._running is False

    print("test_executor_start_stop passed")


def test_executor_register_unregister():
    """测试注册和注销"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    # 注册
    executor.register(cmd)
    assert executor.total_count == 1
    assert cmd.cmd_id in executor._order_cmds
    assert cmd.status == OrderCmdStatus.RUNNING
    assert cmd.started_at is not None

    # 注销
    executor.unregister(cmd.cmd_id)
    assert executor.total_count == 0
    assert cmd.cmd_id not in executor._order_cmds

    print("test_executor_register_unregister passed")


def test_executor_close():
    """测试关闭命令"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.cancel_order.return_value = True

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    executor.register(cmd)

    # 添加一个活动订单
    order = OrderData(
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=0,
        price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.NOTTRADED.value,
    )
    cmd._active_orders["order-1"] = order

    # 关闭命令
    result = executor.close(cmd.cmd_id)

    assert result is True
    assert cmd.status == OrderCmdStatus.FINISHED
    assert cmd.finish_reason.value == "CANCELLED"
    mock_trading_engine.cancel_order.assert_called_once_with("order-1")

    print("test_executor_close passed")


def test_executor_status():
    """测试获取执行器状态"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    # 创建活跃命令
    cmd1 = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )
    cmd1.status = OrderCmdStatus.RUNNING
    cmd1.filled_volume = 50

    cmd2 = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.SELL,
        offset=Offset.CLOSE,
        volume=50,
        price=3500.0,
    )
    cmd2.status = OrderCmdStatus.RUNNING
    cmd2.filled_volume = 25

    executor.register(cmd1)
    executor.register(cmd2)

    status = executor.get_status()

    assert status["active_count"] == 2
    assert status["total_count"] == 2
    assert len(status["active_commands"]) == 2

    # 验证命令信息
    cmd1_info = next((c for c in status["active_commands"] if c["cmd_id"] == cmd1.cmd_id), None)
    assert cmd1_info is not None
    assert cmd1_info["symbol"] == "SHFE.rb2505"
    assert cmd1_info["filled_volume"] == 50
    assert cmd1_info["volume"] == 100

    print("test_executor_status passed")


def test_executor_on_order_update():
    """测试订单更新处理"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )
    executor.register(cmd)
    cmd.all_order_ids.append("order-1")

    # 模拟订单更新
    order = OrderData(
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=0,
        price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.NOTTRADED.value,
    )

    executor._on_order_update(order)

    # 验证订单被添加到活动订单
    assert "order-1" in cmd._active_orders

    print("test_executor_on_order_update passed")


def test_executor_on_trade_update():
    """测试成交更新处理"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )
    executor.register(cmd)
    cmd.all_order_ids.append("order-1")

    # 模拟成交更新
    trade = TradeData(
        trade_id="trade-1",
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        price=Decimal("3500"),
        volume=10,
        account_id="test-account",
    )

    executor._on_trade_update(trade)

    # 验证成交数量更新
    assert cmd.filled_volume == 10

    print("test_executor_on_trade_update passed")


def test_executor_process_cmd_tick_with_order_request():
    """测试处理命令 tick 时下单"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.insert_order.return_value = "order-123"

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
        max_volume_per_order=10,
        order_interval=0.1,
    )
    executor.register(cmd)

    now = time.time()
    executor._process_cmd_tick(cmd, now)

    # 验证下单被调用
    mock_trading_engine.insert_order.assert_called_once()
    assert "order-123" in cmd.all_order_ids

    print("test_executor_process_cmd_tick_with_order_request passed")


def test_executor_process_cmd_tick_with_timeout_orders():
    """测试处理超时订单"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.cancel_order.return_value = True

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
        order_timeout=1.0,
        max_retries=3,
    )
    executor.register(cmd)

    # 添加一个超时订单
    cmd.on_order_submitted("order-timeout", 10)
    cmd._active_order_info["order-timeout"].submit_time = time.time() - 2.0

    order = OrderData(
        order_id="order-timeout",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=0,
        price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.NOTTRADED.value,
    )
    cmd._active_orders["order-timeout"] = order

    now = time.time()
    executor._process_cmd_tick(cmd, now)

    # 验证撤单被调用
    mock_trading_engine.cancel_order.assert_called_once_with("order-timeout")

    print("test_executor_process_cmd_tick_with_timeout_orders passed")


if __name__ == "__main__":
    test_executor_initialization()
    test_executor_start_stop()
    test_executor_register_unregister()
    test_executor_close()
    test_executor_status()
    test_executor_on_order_update()
    test_executor_on_trade_update()
    test_executor_process_cmd_tick_with_order_request()
    test_executor_process_cmd_tick_with_timeout_orders()
    print("\nAll executor tests passed!")
