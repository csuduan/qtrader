"""
报单指令功能测试
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock

from src.models.object import (
    Direction,
    Offset,
    OrderCmdFinishReason,
    OrderData,
    OrderRequest,
    OrderStatus,
    TradeData,
)
from src.trader.order_cmd import (
    ActiveOrderInfo,
    OrderCmd,
    OrderCmdStatus,
    SimpleSplitStrategy,
    SplitStrategyType,
    TWAPSplitStrategy,
)


def test_simple_split_strategy():
    """测试简单拆单策略"""
    # 创建模拟的OrderCmd
    cmd = Mock(spec=OrderCmd)
    cmd.max_volume_per_order = 10

    strategy = SimpleSplitStrategy(cmd)

    # 测试100手拆单，最大单次10手
    orders = strategy.split(100)

    assert len(orders) == 10, f"Expected 10 orders, got {len(orders)}"
    for order in orders:
        assert order.volume == 10, f"Expected volume 10, got {order.volume}"

    print("test_simple_split_strategy passed")


def test_twap_split_strategy():
    """测试TWAP拆单策略"""
    cmd = Mock(spec=OrderCmd)
    cmd.max_volume_per_order = 10
    cmd.twap_duration = 60  # 60秒

    strategy = TWAPSplitStrategy(cmd)

    # 测试100手拆单，60秒内执行
    orders = strategy.split(100)

    # 应该拆分为最多60单（每秒最多1单）或者最少10单（按最大手数）
    assert len(orders) >= 10, f"Expected at least 10 orders, got {len(orders)}"
    assert len(orders) <= 60, f"Expected at most 60 orders, got {len(orders)}"

    # 验证时间间隔递增
    for i in range(len(orders) - 1):
        assert (
            orders[i + 1].delay_seconds >= orders[i].delay_seconds
        ), "TWAP orders should have increasing delays"

    print("test_twap_split_strategy passed")


def test_order_cmd_initialization():
    """测试OrderCmd初始化"""
    cmd = OrderCmd(
        cmd_id="test-cmd-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    assert cmd.cmd_id == "test-cmd-1"
    assert cmd.symbol == "SHFE.rb2505"
    assert cmd.direction == Direction.BUY
    assert cmd.offset == Offset.OPEN
    assert cmd.volume == 100
    assert cmd.price == 3500.0
    assert cmd.status == OrderCmdStatus.PENDING
    assert cmd.filled_volume == 0
    assert cmd.remaining_volume == 100

    print("test_order_cmd_initialization passed")


def test_order_cmd_close():
    """测试OrderCmd关闭（取消）"""
    cmd = OrderCmd(
        cmd_id="test-cmd-2",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    # 设置为运行状态
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()

    cmd.close()

    assert cmd.status == OrderCmdStatus.FINISHED
    assert cmd.finish_reason == OrderCmdFinishReason.CANCELLED
    assert cmd.finished_at is not None

    print("test_order_cmd_close passed")


def test_order_cmd_order_update():
    """测试订单更新处理"""
    cmd = OrderCmd(
        cmd_id="test-cmd-3",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    cmd.all_order_ids.append("order-1")

    # 测试活动订单
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

    cmd.update("ORDER_UPDATE", order)
    assert "order-1" in cmd._active_orders

    # 测试非活动订单
    order.status = OrderStatus.ALLTRADED.value
    cmd.update("ORDER_UPDATE", order)
    assert "order-1" not in cmd._active_orders

    print("test_order_cmd_order_update passed")


def test_order_cmd_trade_update():
    """测试成交更新处理"""
    cmd = OrderCmd(
        cmd_id="test-cmd-4",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    cmd.all_order_ids.append("order-1")

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

    cmd.update("TRADE_UPDATE", trade)
    assert cmd.filled_volume == 10
    assert cmd.remaining_volume == 90

    print("test_order_cmd_trade_update passed")


def test_order_cmd_to_dict():
    """测试转换为字典"""
    cmd = OrderCmd(
        cmd_id="test-cmd-5",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
        split_strategy=SplitStrategyType.TWAP,
        twap_duration=300,
    )

    data = cmd.to_dict()

    assert data["cmd_id"] == "test-cmd-5"
    assert data["symbol"] == "SHFE.rb2505"
    assert data["direction"] == "BUY"
    assert data["volume"] == 100
    assert data["filled_volume"] == 0
    assert data["remaining_volume"] == 100
    assert data["split_strategy"] == "TWAP"
    assert data["is_active"] is False  # PENDING状态
    assert data["total_orders"] == 0

    print("test_order_cmd_to_dict passed")


def test_order_cmd_tick_returns_order_request():
    """测试 tick 方法返回 OrderRequest"""
    cmd = OrderCmd(
        cmd_id="test-cmd-6",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
        max_volume_per_order=10,
        order_interval=0.1,
    )

    # 设置为运行状态并初始化拆单策略
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd._init_split_strategy()
    cmd._load_next_split_order()

    now = time.time()
    order_req = cmd.tick(now)

    assert order_req is not None
    assert isinstance(order_req, OrderRequest)
    assert order_req.symbol == "SHFE.rb2505"
    assert order_req.direction == Direction.BUY
    assert order_req.offset == Offset.OPEN
    assert order_req.volume == 10
    assert order_req.price == 3500.0

    print("test_order_cmd_tick_returns_order_request passed")


def test_order_cmd_on_order_submitted():
    """测试订单提交成功回调"""
    cmd = OrderCmd(
        cmd_id="test-cmd-7",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    cmd.on_order_submitted("order-1", 10)

    assert "order-1" in cmd.all_order_ids
    assert "order-1" in cmd._active_order_info
    assert cmd._active_order_info["order-1"].volume == 10
    assert cmd._active_order_info["order-1"].retry_count == 0

    print("test_order_cmd_on_order_submitted passed")


def test_order_cmd_on_order_cancelled():
    """测试订单撤单回调"""
    cmd = OrderCmd(
        cmd_id="test-cmd-8",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    # 先添加订单信息
    cmd.on_order_submitted("order-1", 10)

    # 模拟撤单
    cmd.on_order_cancelled("order-1", 5)  # 5手未成交

    assert "order-1" not in cmd._active_order_info
    assert "order-1" not in cmd._active_orders
    assert cmd._pending_retry_volume == 5

    print("test_order_cmd_on_order_cancelled passed")


def test_order_cmd_get_timeout_orders():
    """测试获取超时订单"""
    cmd = OrderCmd(
        cmd_id="test-cmd-9",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
        order_timeout=1.0,
        max_retries=3,
    )

    # 添加一个超时订单
    cmd.on_order_submitted("order-1", 10)
    cmd._active_order_info["order-1"].submit_time = time.time() - 2.0  # 2秒前

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

    now = time.time()
    timeout_orders = cmd.get_timeout_orders(now)

    assert "order-1" in timeout_orders

    print("test_order_cmd_get_timeout_orders passed")


def test_order_cmd_get_active_orders():
    """测试获取活动订单"""
    cmd = OrderCmd(
        cmd_id="test-cmd-10",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    # 添加活动订单
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

    active_orders = cmd.get_active_orders()

    assert "order-1" in active_orders
    assert len(active_orders) == 1

    print("test_order_cmd_get_active_orders passed")


def test_order_cmd_tick_no_action_when_pending():
    """测试 PENDING 状态下 tick 不返回任何请求"""
    cmd = OrderCmd(
        cmd_id="test-cmd-11",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
    )

    now = time.time()
    order_req = cmd.tick(now)

    assert order_req is None

    print("test_order_cmd_tick_no_action_when_pending passed")


def test_order_cmd_tick_respects_order_interval():
    """测试 tick 遵守订单间隔"""
    cmd = OrderCmd(
        cmd_id="test-cmd-12",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=20,
        price=3500.0,
        max_volume_per_order=10,
        order_interval=1.0,  # 1秒间隔
    )

    # 设置为运行状态并初始化拆单策略
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd._init_split_strategy()
    cmd._load_next_split_order()

    now = time.time()

    # 第一次 tick 应该返回订单请求
    order_req = cmd.tick(now)
    assert order_req is not None

    # 立即再次 tick，应该返回 None（因为间隔时间未到）
    order_req = cmd.tick(now)
    assert order_req is None

    print("test_order_cmd_tick_respects_order_interval passed")


def test_order_cmd_finishes_when_all_filled():
    """测试全部成交后完成"""
    cmd = OrderCmd(
        cmd_id="test-cmd-13",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
    )

    # 设置为运行状态
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()

    # 模拟全部成交
    cmd.filled_volume = 10

    now = time.time()
    order_req = cmd.tick(now)

    assert order_req is None
    assert cmd.status == OrderCmdStatus.FINISHED
    assert cmd.finish_reason == OrderCmdFinishReason.ALL_COMPLETED

    print("test_order_cmd_finishes_when_all_filled passed")


if __name__ == "__main__":
    test_simple_split_strategy()
    test_twap_split_strategy()
    test_order_cmd_initialization()
    test_order_cmd_close()
    test_order_cmd_order_update()
    test_order_cmd_trade_update()
    test_order_cmd_to_dict()
    test_order_cmd_tick_returns_order_request()
    test_order_cmd_on_order_submitted()
    test_order_cmd_on_order_cancelled()
    test_order_cmd_get_timeout_orders()
    test_order_cmd_get_active_orders()
    test_order_cmd_tick_no_action_when_pending()
    test_order_cmd_tick_respects_order_interval()
    test_order_cmd_finishes_when_all_filled()
    print("\nAll tests passed!")
