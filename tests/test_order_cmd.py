"""
报单指令功能测试
"""

import time
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, Mock

from src.models.object import (
    Direction,
    Exchange,
    Offset,
    OrderCmdFinishReason,
    OrderData,
    OrderRequest,
    OrderStatus,
    PositionData,
    TradeData,
)
from src.trader.order_cmd import (
    ActiveOrderInfo,
    SimpleSplitStrategy,
    OrderCmd,
    OrderCmdStatus,
    SplitStrategyType,
    SplitOrder,
)


def test_simple_split_strategy():
    """测试简单拆单策略"""
    # 创建模拟的 OrderCmd
    cmd = Mock(spec=OrderCmd)
    cmd.max_volume_per_order = 10
    cmd.volume = 100
    cmd.direction = Direction.BUY
    cmd.offset = Offset.OPEN

    strategy = SimpleSplitStrategy(cmd)

    # 测试拆单 - 应该返回10个订单
    pos = None  # 开仓不需要持仓
    count = strategy.split(pos)
    assert count == 10, f"Expected 10 orders, got {count}"

    # 测试 get_next 获取订单
    order1 = strategy.get_next()
    assert order1 is not None, "Expected first order"
    assert order1.volume == 10, f"Expected volume 10, got {order1.volume}"

    print("test_simple_split_strategy passed")


def test_simple_split_strategy_close_today_yesterday():
    """测试平今平昨拆单"""
    # 创建模拟的 OrderCmd
    cmd = Mock(spec=OrderCmd)
    cmd.max_volume_per_order = 10
    cmd.volume = 80
    cmd.direction = Direction.SELL
    cmd.offset = Offset.CLOSE

    # 创建持仓数据
    pos = Mock(spec=PositionData)
    pos.pos_long = 100
    pos.pos_short = 0
    pos.pos_long_td = 50  # 今仓50
    pos.exchange = Exchange.SHFE

    strategy = SimpleSplitStrategy(cmd)

    # 测试拆单
    count = strategy.split(pos)
    # 应该拆成: 平今5个订单(50手) + 平昨3个订单(30手) = 8个订单
    assert count == 8, f"Expected 8 orders, got {count}"

    # 先获取平今订单
    for _ in range(5):
        order = strategy.get_next()
        assert order is not None
        assert order.volume == 10
        assert order.offset == Offset.CLOSETODAY

    # 再获取平昨订单
    for _ in range(3):
        order = strategy.get_next()
        assert order is not None
        assert order.volume == 10
        assert order.offset == Offset.CLOSE

    # 没有更多订单
    order = strategy.get_next()
    assert order is None

    print("test_simple_split_strategy_close_today_yesterday passed")


def test_order_cmd_initialization():
    """测试OrderCmd初始化"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    assert cmd.cmd_id is not None
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
    assert cmd.finish_reason == "指令已取消"
    assert cmd.finished_at is not None

    print("test_order_cmd_close passed")


def test_order_cmd_order_update():
    """测试订单更新处理"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    cmd.all_order_ids.append("order-1")
    cmd._cur_split_order = SplitOrder(volume=10)

    # 测试非活动订单 - 需要先设置 _pending_order
    order = OrderData(
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=10,
        price=Decimal("3500"),
        traded_price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.FINISHED,
    )

    cmd._pending_order = order
    cmd.update("ORDER_UPDATE", order)

    # 已完成订单应该被清除
    assert cmd._pending_order is None
    # 成交应该被统计
    assert cmd.filled_volume == 10
    assert cmd.filled_price == 3500.0

    print("test_order_cmd_order_update passed")


def test_order_cmd_order_update_rejected():
    """测试订单被拒处理"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()

    cmd.all_order_ids.append("order-1")

    # 模拟订单被拒
    order = OrderData(
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=0,
        price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.REJECTED,
        status_msg="资金不足",
    )

    cmd._pending_order = order
    cmd.update("ORDER_UPDATE", order)

    # 订单应该被清除
    assert cmd._pending_order is None
    # 指令应该完成
    assert cmd.status == OrderCmdStatus.FINISHED
    assert "订单被拒" in cmd.finish_reason

    print("test_order_cmd_order_update_rejected passed")


def test_order_cmd_trade_update():
    """测试成交更新处理"""
    cmd = OrderCmd(
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
    # 成交统计通过订单更新处理
    assert cmd.filled_volume == 0
    assert cmd.remaining_volume == 100

    print("test_order_cmd_trade_update passed")


def test_order_cmd_to_dict():
    """测试转换为字典"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

    data = cmd.to_dict()

    assert data["cmd_id"] is not None
    assert data["symbol"] == "SHFE.rb2505"
    assert data["direction"] == "BUY"
    assert data["volume"] == 100
    assert data["filled_volume"] == 0
    assert data["remaining_volume"] == 100
    assert "split_strategy" not in data  # 这个字段已移除
    assert data["is_active"] is True  # PENDING状态也是活跃状态（非FINISHED）
    assert data["total_orders"] == 0

    print("test_order_cmd_to_dict passed")


def test_order_cmd_trig_returns_order_request():
    """测试 trig 方法返回 OrderRequest"""
    cmd = OrderCmd(
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
    cmd.split(None)  # 开仓不需要持仓
    cmd._load_next_split_order()

    order_req = cmd.trig()

    assert order_req is not None
    assert isinstance(order_req, OrderRequest)
    assert order_req.symbol == "SHFE.rb2505"
    assert order_req.direction == Direction.BUY
    assert order_req.offset == Offset.OPEN
    assert order_req.volume == 10
    assert order_req.price == 3500.0

    print("test_order_cmd_trig_returns_order_request passed")


def test_order_cmd_add_order():
    """测试添加订单"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,
        price=3500.0,
    )

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

    assert "order-1" in cmd.all_order_ids
    assert cmd._pending_order is not None
    assert cmd._pending_order.order_id == "order-1"

    print("test_order_cmd_add_order passed")


def test_order_cmd_trig_no_action_when_pending():
    """测试 PENDING 状态下 trig 不返回任何请求"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
    )

    order_req = cmd.trig()

    assert order_req is None

    print("test_order_cmd_trig_no_action_when_pending passed")


def test_order_cmd_trig_respects_order_interval():
    """测试 trig 遵守订单间隔"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=20,
        price=3500.0,
        max_volume_per_order=10,
        order_interval=0.2,  # 0.2秒间隔
    )

    # 设置为运行状态并初始化拆单策略
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd.split(None)  # 开仓不需要持仓
    cmd._load_next_split_order()

    # 第一次 trig 应该返回订单请求
    order_req = cmd.trig()
    assert order_req is not None

    # 立即再次 trig，应该返回 None（因为间隔时间未到）
    order_req = cmd.trig()
    assert order_req is None

    # 等待间隔时间后再 trig，应该返回订单请求
    time.sleep(0.25)
    order_req = cmd.trig()
    assert order_req is not None

    print("test_order_cmd_trig_respects_order_interval passed")


def test_order_cmd_finishes_when_all_filled():
    """测试全部成交后完成"""
    cmd = OrderCmd(
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

    order_req = cmd.trig()

    assert order_req is None
    assert cmd.status == OrderCmdStatus.FINISHED
    assert cmd.finish_reason == "全部完成"

    print("test_order_cmd_finishes_when_all_filled passed")


def test_order_cmd_left_retry_times_calculation():
    """测试剩余重试次数计算公式"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=100,  # 100手
        price=3500.0,
        max_volume_per_order=10,  # 每单最大10手
    )

    # 设置为运行状态以触发拆单
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd.split(None)  # 开仓不需要持仓

    # 100手 / 10手每单 = 10单
    # _left_retry_times = 2 * 10 + 1 = 21
    expected_left_retry_times = 21
    assert cmd._left_retry_times == expected_left_retry_times, f"Expected _left_retry_times={expected_left_retry_times}, got {cmd._left_retry_times}"

    print("test_order_cmd_left_retry_times_calculation passed")


def test_order_cmd_trig_timeout_returns_order_for_cancel():
    """测试 trig 方法超时时返回待撤单的 OrderData"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
        total_timeout=1,  # 1秒总超时
    )

    # 设置为运行状态
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now() - timedelta(seconds=2)  # 2秒前开始

    # 模拟一个活动订单
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
        insert_time=datetime.now() - timedelta(seconds=2),
    )
    cmd._pending_order = order

    result = cmd.trig()

    # 应该返回订单用于撤单
    assert result is not None
    assert isinstance(result, OrderData)
    assert result.order_id == "order-1"

    print("test_order_cmd_trig_timeout_returns_order_for_cancel passed")


def test_order_cmd_dynamic_split_with_multiple_orders():
    """测试拆单多次下单"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=25,  # 25手，每单最大10手，应该拆分为 10, 10, 5
        price=3500.0,
        max_volume_per_order=10,
        order_interval=0.1,
    )

    # 设置为运行状态并初始化拆单策略
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd.split(None)  # 开仓不需要持仓
    cmd._load_next_split_order()

    # 第一次：应该下10手
    order_req1 = cmd.trig()
    assert order_req1 is not None
    assert order_req1.volume == 10

    # 模拟订单成交
    order = OrderData(
        order_id="order-1",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=10,
        price=Decimal("3500"),
        traded_price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.FINISHED,
    )
    cmd._pending_order = order
    cmd.update("ORDER_UPDATE", order)
    # 订单完成后，_cur_split_order.volume 已减为0，需要加载下一个
    cmd._load_next_split_order()

    # 第二次：应该下10手（需要等待间隔时间）
    time.sleep(0.15)  # 等待超过 order_interval (0.1秒)
    order_req2 = cmd.trig()
    assert order_req2 is not None
    assert order_req2.volume == 10

    # 模拟订单成交
    order2 = OrderData(
        order_id="order-2",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        traded=10,
        price=Decimal("3500"),
        traded_price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.FINISHED,
    )
    cmd._pending_order = order2
    cmd.update("ORDER_UPDATE", order2)
    # 订单完成后，_cur_split_order.volume 已减为0，需要加载下一个
    cmd._load_next_split_order()

    # 第三次：应该下5手（剩余5手）
    time.sleep(0.15)
    order_req3 = cmd.trig()
    assert order_req3 is not None
    assert order_req3.volume == 5

    # 模拟订单成交
    order3 = OrderData(
        order_id="order-3",
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=5,
        traded=5,
        price=Decimal("3500"),
        traded_price=Decimal("3500"),
        account_id="test-account",
        status=OrderStatus.FINISHED,
    )
    cmd._pending_order = order3
    cmd.update("ORDER_UPDATE", order3)
    # 订单完成后，_cur_split_order.volume 已减为0，需要加载下一个
    cmd._load_next_split_order()

    # 第四次：应该返回None（已完成）
    time.sleep(0.15)
    order_req4 = cmd.trig()
    assert order_req4 is None
    assert cmd.status == OrderCmdStatus.FINISHED

    print("test_order_cmd_dynamic_split_with_multiple_orders passed")


def test_order_cmd_close_today_yesterday_split():
    """测试平今平昨拆单"""
    position = PositionData(
        symbol="SHFE.rb2505",
        exchange=Exchange.SHFE,
        account_id="test-account",
        pos=100,
        pos_long=100,
        pos_short=0,
        pos_long_yd=50,
        pos_long_td=50,
    )

    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.SELL,
        offset=Offset.CLOSE,
        volume=80,  # 平80手，应该先平今50手，再平昨30手
        price=3500.0,
        max_volume_per_order=10,
    )

    # 设置为运行状态并初始化拆单策略
    cmd.status = OrderCmdStatus.RUNNING
    cmd.started_at = datetime.now()
    cmd.split(position)

    # 验证拆单数量: 平今5个 + 平昨3个 = 8个
    assert cmd._strategy is not None
    assert cmd._left_retry_times == 2 * 8 + 1

    print("test_order_cmd_close_today_yesterday_split passed")


def test_order_cmd_open_position_no_position_needed():
    """测试开仓指令不需要持仓"""
    cmd = OrderCmd(
        symbol="SHFE.rb2505",
        direction=Direction.BUY,
        offset=Offset.OPEN,
        volume=10,
        price=3500.0,
        max_volume_per_order=10,
    )

    # 开仓指令 split 不需要持仓
    cmd.split(None)

    assert cmd._strategy is not None
    assert cmd._left_retry_times == 2 * 1 + 1  # 1个订单

    print("test_order_cmd_open_position_no_position_needed passed")


if __name__ == "__main__":
    test_simple_split_strategy()
    test_simple_split_strategy_close_today_yesterday()
    test_order_cmd_initialization()
    test_order_cmd_close()
    test_order_cmd_order_update()
    test_order_cmd_order_update_rejected()
    test_order_cmd_trade_update()
    test_order_cmd_to_dict()
    test_order_cmd_trig_returns_order_request()
    test_order_cmd_add_order()
    test_order_cmd_trig_no_action_when_pending()
    test_order_cmd_trig_respects_order_interval()
    test_order_cmd_finishes_when_all_filled()
    test_order_cmd_left_retry_times_calculation()
    test_order_cmd_trig_timeout_returns_order_for_cancel()
    test_order_cmd_dynamic_split_with_multiple_orders()
    test_order_cmd_close_today_yesterday_split()
    test_order_cmd_open_position_no_position_needed()
    print("\nAll tests passed!")
