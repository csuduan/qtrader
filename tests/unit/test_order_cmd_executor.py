"""
报单指令执行器测试
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from qtrader.models.object import (
    Direction,
    Offset,
    OrderData,
    OrderStatus,
    TradeData,
)
from qtrader.trader.order_cmd import OrderCmd, OrderCmdStatus, SplitStrategyType
from qtrader.trader.order_executor import OrderCmdExecutor
from qtrader.utils.async_event_engine import AsyncEventEngine


def make_executor():
    """构造执行器与 mock 引擎（get_contract 返回 None 保持默认拆单参数）"""
    mock_event_engine = MagicMock(spec=AsyncEventEngine)
    mock_trading_engine = MagicMock()
    mock_trading_engine.get_contract.return_value = None
    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)
    return executor, mock_event_engine, mock_trading_engine


def test_executor_initialization():
    """测试执行器初始化"""
    mock_event_engine = MagicMock(spec=AsyncEventEngine)
    mock_trading_engine = MagicMock()

    executor = OrderCmdExecutor(mock_event_engine, mock_trading_engine)

    assert not executor._running

    print("test_executor_initialization passed")


@pytest.mark.asyncio
async def test_executor_start_stop():
    """测试执行器启动和停止（异步任务模型）"""
    import pytest

    executor, mock_event_engine, _ = make_executor()

    executor.start()
    assert executor._running is True
    assert executor._task is not None

    # 验证事件订阅（订单+成交）
    assert mock_event_engine.register.call_count == 2

    await executor.stop()
    assert executor._running is False


def test_executor_register_unregister():
    """测试注册和注销"""
    executor, _, _ = make_executor()

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


def test_executor_history_trimmed_to_capacity():
    """历史指令超出容量时淘汰最旧的已完成指令"""
    from datetime import datetime, timedelta

    executor, _, _ = make_executor()
    executor._history_capacity = 5

    # 注册 7 个已完成指令，启动时间递增
    base = datetime.now()
    for i in range(7):
        cmd = OrderCmd(
            symbol="SHFE.rb2505",
            direction=Direction.BUY,
            offset=Offset.OPEN,
            volume=1,
            price=3500.0,
        )
        executor._pending_cmds[cmd.cmd_id] = cmd
        cmd.started_at = base + timedelta(seconds=i)
        cmd.status = OrderCmdStatus.FINISHED
        executor._history_cmds[cmd.cmd_id] = cmd
        executor._pending_cmds.pop(cmd.cmd_id)  # 模拟已完成退出 pending
        executor._trim_history()

    # 保留最近 5 条
    assert len(executor._history_cmds) == 5


def test_executor_close():
    """测试关闭命令"""
    executor, _, mock_trading_engine = make_executor()
    mock_trading_engine.cancel_order.return_value = True

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
    # 仍有活跃挂单：先进入 CANCELING，撤单回报后才 FINISHED
    assert cmd.status == OrderCmdStatus.CANCELING
    assert cmd.finish_reason == "指令已取消"
    mock_trading_engine.cancel_order.assert_called_once_with("order-1")


def test_executor_status():
    """测试获取执行器状态"""
    from qtrader.models.object import Exchange, PositionData

    executor, _, mock_trading_engine = make_executor()

    # 为平仓指令提供持仓数据（pos_long 为派生属性，由今昨仓求和）
    mock_position = PositionData(
        symbol="SHFE.rb2505",
        exchange=Exchange.SHFE,
        account_id="test-account",
        pos_long_yd=30,
        pos_long_td=20,
    )
    mock_trading_engine.get_position.return_value = mock_position

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
    executor, _, _ = make_executor()

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
    executor, _, _ = make_executor()

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
    executor, _, mock_trading_engine = make_executor()
    mock_trading_engine.insert_order.return_value = MagicMock(order_id="order-123")

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

    executor, _, mock_trading_engine = make_executor()
    mock_trading_engine.cancel_order.return_value = True

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


def test_executor_process_cmd_cancel_not_accepted_keeps_retryable():
    """回归：撤单请求未受理（返回False）时不得标记 canceled，保留状态机重试能力"""
    from datetime import datetime, timedelta

    executor, _, mock_trading_engine = make_executor()
    mock_trading_engine.cancel_order.return_value = False  # 风控拦截/网关未连接

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
        order_timeout=1.0,
    )
    executor.register(cmd)

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

    mock_trading_engine.cancel_order.assert_called_once_with("order-timeout")
    assert order.canceled is False  # 未受理不得标记已撤


def test_executor_pass_position_to_cmd():
    """测试执行器向平仓指令传递持仓"""
    from qtrader.models.object import Exchange, PositionData

    executor, _, mock_trading_engine = make_executor()
    mock_trading_engine.insert_order.return_value = MagicMock(order_id="order-123")
    mock_trading_engine.get_position.return_value = PositionData(
        symbol="SHFE.rb2505", exchange=Exchange.SHFE, pos_long_td=10
    )

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.SELL,
        offset=Offset.CLOSE,
        volume=10,
        price=3500.0,
        max_volume_per_order=10,
        order_interval=0.1,
    )
    executor.register(cmd)

    # 注册时即查询持仓并传递给拆单逻辑
    mock_trading_engine.get_position.assert_called_once_with("SHFE.rb2505")


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
