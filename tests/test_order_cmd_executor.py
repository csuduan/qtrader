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
from src.trader.order_executor import OrderCmdExecutor
from src.utils.event_engine import EventEngine


def test_executor_initialization():
    """测试执行器初始化"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    assert not executor._running

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
    assert cmd.cmd_id in executor._pending_cmds
    assert cmd.status == OrderCmdStatus.RUNNING
    assert cmd.started_at is not None

    # 注销
    executor.unregister(cmd.cmd_id)
    assert cmd.cmd_id not in executor._pending_cmds

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
        status=OrderStatus.PENDING,
    )
    cmd.add_order(order)

    # 关闭命令
    result = executor.close(cmd.cmd_id)

    assert result is True
    assert cmd.status == OrderCmdStatus.FINISHED
    assert cmd.finish_reason == "指令已取消"
    mock_trading_engine.cancel_order.assert_called_once_with("order-1")

    print("test_executor_close passed")


def test_executor_status():
    """测试获取执行器状态"""
    from src.models.object import PositionData, Exchange

    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()

    # 为平仓指令提供持仓数据
    mock_position = PositionData(
        symbol="SHFE.rb2505",
        exchange=Exchange.SHFE,
        account_id="test-account",
        pos=50,
        pos_long=50,
        pos_short=0,
        pos_long_yd=30,
        pos_long_td=20,
    )
    mock_trading_engine.get_position.return_value = mock_position

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

    # 检查活跃命令数量
    assert len(executor._pending_cmds) == 2
    assert len(executor.get_active_cmds()) == 2

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
        status=OrderStatus.PENDING,
    )

    executor._on_order_update(order)

    # 由于 _pending_order 是 None，订单不会被匹配
    assert cmd._pending_order is None

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

    # 成交统计通过订单更新处理，不是通过成交更新
    # 所以 filled_volume 应该仍然是 0
    assert cmd.filled_volume == 0

    print("test_executor_on_trade_update passed")


def test_executor_process_cmd_trig_with_order_request():
    """测试处理命令 trig 时下单"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.insert_order.return_value = MagicMock(order_id="order-123")

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

    executor._process_cmd(cmd)

    # 验证下单被调用
    mock_trading_engine.insert_order.assert_called_once()
    assert "order-123" in cmd.all_order_ids

    print("test_executor_process_cmd_trig_with_order_request passed")


def test_executor_process_cmd_trig_with_timeout_orders():
    """测试处理超时订单"""
    from datetime import datetime, timedelta

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
    )
    executor.register(cmd)

    # 添加一个超时订单
    order = OrderData(
        order_id="order-timeout",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=0,
        price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.PENDING,
        insert_time=datetime.now() - timedelta(seconds=2),
    )
    cmd.add_order(order)

    executor._process_cmd(cmd)

    # 验证撤单被调用
    mock_trading_engine.cancel_order.assert_called_once_with("order-timeout")

    print("test_executor_process_cmd_trig_with_timeout_orders passed")


def test_executor_pass_position_to_cmd():
    """测试执行器传递持仓给命令"""
    mock_event_engine = MagicMock(spec=EventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.insert_order.return_value = MagicMock(order_id="order-123")
    mock_trading_engine.positions.get.return_value = MagicMock(pos_long=100)

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

    executor._process_cmd(cmd)

    # 验证持仓查询被调用
    mock_trading_engine.positions.get.assert_called_once_with("SHFE.rb2505")

    print("test_executor_pass_position_to_cmd passed")


if __name__ == "__main__":
    test_executor_initialization()
    test_executor_start_stop()
    test_executor_register_unregister()
    test_executor_close()
    test_executor_status()
    test_executor_on_order_update()
    test_executor_on_trade_update()
    test_executor_process_cmd_trig_with_order_request()
    test_executor_process_cmd_trig_with_timeout_orders()
    test_executor_pass_position_to_cmd()
    print("\nAll executor tests passed!")
