"""
报单指令模块

提供拆单和执行策略，支持简单拆单和TWAP拆单。
OrderCmd 是纯状态机，无外部依赖。
"""

import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Deque, Dict, List, Optional

from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger(__name__)

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


class OrderCmdStatus(str):
    """报单指令状态"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELING = "CANCELING"  # 取消中（有挂单需要撤销）
    FINISHED = "FINISHED"


class SplitStrategyType(str):
    """拆单策略类型"""

    DYNAMIC = "DYNAMIC"  # 动态拆单策略


@dataclass
class SplitOrder:
    """拆单后的单个订单"""

    volume: int
    delay_seconds: float = 0.0
    offset: Optional[Offset] = None  # 开平类型（平仓策略使用）


@dataclass
class ActiveOrderInfo:
    """活动订单信息"""

    order_id: str
    volume: int  # 委托数量
    submit_time: float  # 下单时间戳
    retry_count: int = 0  # 已重试次数


class BaseSplitStrategy(ABC):
    """拆单策略基类"""

    def __init__(self, cmd: "OrderCmd"):
        self.cmd = cmd
        self._left_retry_times = 0
        self._order_queue: List[SplitOrder] = []

    @abstractmethod
    def split(self, pos: PositionData) -> int:
        """拆单"""
        pass

    def get_next(self) -> Optional[SplitOrder]:
        """获取下一个订单"""
        if not self._order_queue:
            return None
        return self._order_queue.pop(0)


class SimpleSplitStrategy(BaseSplitStrategy):
    """简单拆单策略"""

    def split(self, pos: PositionData | None) -> int:
        cmd = self.cmd
        total_volume = cmd.volume
        total_td_volume = 0
        if pos and cmd.offset == Offset.CLOSE:
            # 建议持仓是否足够
            pos_volume = pos.pos_long if cmd.direction == Direction.SELL else pos.pos_short
            if pos_volume < cmd.volume:
                total_volume = pos_volume
            if pos.exchange in [Exchange.SHFE, Exchange.GFEX, Exchange.INE]:
                # 上期所(SHFE)、广期所(GFEX)、上能源(INE)不支持平昨
                td_volume = pos.pos_long_td if cmd.direction == Direction.SELL else pos.pos_short_td
                if td_volume is not None:
                    total_td_volume = min(cmd.volume, td_volume)
                    total_volume = total_volume - total_td_volume

        # 拆单处理
        while total_td_volume > 0:
            # 平今拆单
            volume = min(total_td_volume, cmd.volume_per_order)
            self._order_queue.append(
                SplitOrder(volume=volume, offset=Offset.CLOSETODAY, delay_seconds=0)
            )
            total_td_volume -= volume

        while total_volume > 0:
            # 平昨拆单
            volume = min(total_volume, cmd.volume_per_order)
            self._order_queue.append(SplitOrder(volume=volume, offset=cmd.offset, delay_seconds=0))
            total_volume -= volume
        logger.info(
            f"拆单完成，拆成{len(self._order_queue)}个订单，每个订单最大手数{cmd.volume_per_order}"
        )
        return len(self._order_queue)


class OrderCmd:
    """
    报单指令状态机 - 无外部依赖，纯业务逻辑

    职责：
    - 维护状态机状态（PENDING → RUNNING → FINISHED）
    - 拆单逻辑（SimpleSplitStrategy, TWAPSplitStrategy）
    - 状态更新（tick, update）

    不负责：
    - 事件订阅（由 OrderCmdExecutor 负责）
    - 报单触发（由 OrderCmdExecutor 负责）
    - 生命周期管理（由 OrderCmdExecutor 负责）
    """

    def __init__(
        self,
        symbol: str,
        direction: Direction,
        offset: Offset,
        volume: int,
        price: Optional[float] = None,
        # 最大单次手数(默认10手)
        max_volume_per_order: int = 5,
        # 报单间隔(默认1秒)
        order_interval: float = 1,
        # 控制参数(默认5分钟)
        total_timeout: int = 60*5,
        # 单次报单超时时间(默认10秒)
        order_timeout: int = 10,
        # 来源标识
        source: str = "",
        on_change: Optional[Callable[[Any], None]] = None,
    ):
        self.cmd_id = uuid.uuid4().hex
        self.symbol = symbol
        self.direction = direction
        self.offset = offset
        self.price = price  # 报单价格，0或None表示市价
        self.volume_per_order = max_volume_per_order  # 最大单次手数
        self.order_interval = order_interval  # 报单间隔
        self.order_timeout = order_timeout  # 单次报单超时
        self.cmd_timeout = total_timeout  # 总超时时间
        self.source = source  # 来源标识，格式："策略-{strategy_id}" 或 "换仓-{strategy_id}"
        self.on_change = on_change  # 状态变化回调
        self.volume = volume  # 目标手数

        # 状态
        self.status = OrderCmdStatus.PENDING
        self.finish_reason: Optional[str] = None
        self.filled_volume = 0  # 已成交
        self.filled_price = 0.0  # 已成交均价

        # 时间记录
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None

        # 所有订单id
        self.all_order_ids: List[str] = []
        # 单一活动订单（替代原来的 _pending_orders 字典）
        self._pending_order: Optional[OrderData] = None
        self._active_order_info: Optional[ActiveOrderInfo] = None
        self._pending_retry_volume: int = 0  # 待重试的手数
        self._left_retry_times = 0  # 剩余重试次数
        # 拆单策略
        self._strategy: Optional[BaseSplitStrategy] = None

        # 用于控制报单间隔
        self._last_order_time: Optional[datetime] = None
        # 当前拆单
        self._cur_split_order: Optional[SplitOrder] = None

    def split(self, pos: PositionData|None) -> None:
        """拆单"""
        self._strategy = SimpleSplitStrategy(self)
        count=self._strategy.split(pos)
        self._left_retry_times = 2 * count + 1

    def _load_next_split_order(self) -> Optional[SplitOrder]:
        """加载下一个拆单"""
        if self._strategy is None:
            return None
        # 当前拆单还没有结束
        if self._cur_split_order and self._cur_split_order.volume > 0:
            return self._cur_split_order

        # 获取新的拆单
        self._cur_split_order = self._strategy.get_next()
        return self._cur_split_order

    def trig(self) -> Optional[OrderRequest | OrderData]:
        """
        触发

        Args:
            position: 当前持仓信息（用于平仓指令动态调整）

        Returns:
            待提交的订单请求，如果无需下单则返回 None
        """
        now = datetime.now()

        if  self.is_finished:
            return None

        #1. 取消中处理
        if self.status == OrderCmdStatus.CANCELING :
            # 取消中，有挂单，且可以撤单
            if self._pending_order and self._pending_order.can_cancel():
                return self._pending_order
            # 取消中，无挂单
            if not self._pending_order or not self._pending_order.is_active():
                self.status = OrderCmdStatus.FINISHED
                self._notify_change()
            return None

        #2. 运行中处理
        # 检查总超时
        if self.started_at is not None:
            elapsed = now - self.started_at
            if elapsed.total_seconds() >= self.cmd_timeout:
                self._cancel("超时指令")

        # 检查是否完成
        if self.filled_volume >= self.volume:
            self._cancel("全部完成")

        # 检查当前报单是否超时
        if self._pending_order and self._pending_order.can_cancel():
            insert_time = self._pending_order.insert_time
            if insert_time is not None:
                elapsed = now - insert_time
                if elapsed.total_seconds() >= self.order_timeout:
                    return self._pending_order

        # 重试处理
        if self._left_retry_times > 0:
            # 处理下一个拆单
            split_order = self._load_next_split_order()
            if split_order and not self._pending_order:
                # 控制拆单报单时间
                if (
                    self._last_order_time is None
                    or (now - self._last_order_time).total_seconds() >= self.order_interval
                ):
                    self._last_order_time = now
                    self._left_retry_times -= 1
                    return self._create_order_request(split_order)
                return None
        return None

    def update(self, event_type: str, data: Any) -> None:
        """
        事件驱动更新

        Args:
            event_type: ORDER_UPDATE 或 TRADE_UPDATE
            data: OrderData 或 TradeData
        """
        if event_type == "ORDER_UPDATE":
            self._handle_order_update(data)
        elif event_type == "TRADE_UPDATE":
            self._handle_trade_update(data)

    def close(self,reason="指令已取消") -> None:
        """关闭指令（取消）"""
        if self.status in [OrderCmdStatus.FINISHED, OrderCmdStatus.CANCELING]:
            return
        self._cancel(reason)

    def get_pending_order(self) -> Optional[OrderData]:
        """获取当前挂单"""
        return (
            self._pending_order if self._pending_order and self._pending_order.is_active() else None
        )

    def add_order(self, order: OrderData) -> None:
        """
        添加订单
        Args:
            order: 订单数据
        """
        self.all_order_ids.append(order.order_id)
        self._pending_order = order

    def _create_order_request(self, split_order: SplitOrder) -> Optional[OrderRequest]:
        """创建拆单订单请求"""
        volume = split_order.volume
        # 使用 SplitOrder 中的 offset（如果有），否则使用命令的 offset
        req = OrderRequest(
            symbol=self.symbol,
            direction=self.direction,
            offset=split_order.offset or self.offset,
            volume=volume,
            price=self.price,
        )
        return req

    def _handle_order_update(self, order: OrderData) -> None:
        """处理订单更新"""
        if not self._pending_order or order.order_id != self._pending_order.order_id:
            return

        if order.status not in [OrderStatus.FINISHED, OrderStatus.REJECTED]:
            # 未完结报单不处理
            return

        # 订单完成后清理
        self._pending_order = None
        traded = order.traded if order.traded is not None else 0
        if traded > 0:
            # 更新报单指令
            traded_price = order.traded_price or 0.0
            total_cost = self.filled_volume * self.filled_price + traded * traded_price
            self.filled_volume += traded
            if self.filled_volume > 0:
                self.filled_price = total_cost / self.filled_volume
            logger.info(
                f"报单指令-更新成交: "
                f"均价={self.filled_price:.2f}, 累计成交: {self.filled_volume}"
            )
            # 更新拆单手数
            if self._cur_split_order is not None:
                self._cur_split_order.volume -= traded

        if order.status == OrderStatus.REJECTED:
            self._left_retry_times = 0
            self._cancel(f"报单被拒：{order.status_msg}")

        self._notify_change()
    def _handle_trade_update(self, trade: TradeData) -> None:
        """处理成交更新（成交统计已由订单更新处理）"""
        # 成交统计已在 _handle_order_update 中通过 traded 和 traded_price 完成
        # 这里只做完成检查
        pass

    def _cancel(self, reason: str) -> None:
        """结束指令"""
        if self.status == OrderCmdStatus.FINISHED or self.status == OrderCmdStatus.CANCELING:
            #指令已完成或者取消中
            return

        if not "全部完成" in reason:
            logger.error(f"报单指令取消：{reason}")

        # 检查是否有未完成的挂单
        if self._pending_order and self._pending_order.is_active():
            # 有挂单需要撤销，进入取消中状态
            self.status = OrderCmdStatus.CANCELING
        else:
            # 无挂单，直接完成
            self.status = OrderCmdStatus.FINISHED
            self.finished_at = datetime.now()

        self.finish_reason = reason
        self._left_retry_times = 0   
        self._notify_change()
    
    def _notify_change(self) -> None:
        """通知指令状态变更"""
        logger.info(
            f"指令结束: 原因={self.finish_reason} 目标={self.volume} 成交={self.filled_volume} 均价={self.filled_price:.2f},  状态={self.status},已报单次数={len(self.all_order_ids)}"
        )
        if self.on_change:
            self.on_change(self)

    @property
    def remaining_volume(self) -> int:
        """剩余手数"""
        return self.volume - self.filled_volume

    @property
    def is_active(self) -> bool:
        """是否活跃（CANCELING状态也视为活跃，因为有挂单需要撤销）"""
        return self.status not in [OrderCmdStatus.FINISHED]

    @property
    def is_finished(self) -> bool:
        """是否完成(状态完成且没有挂单)"""
        return self.status == OrderCmdStatus.FINISHED

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "cmd_id": self.cmd_id,
            "status": (
                self.status.value
                if isinstance(self.status, (OrderStatus, Direction, Offset))
                else self.status
            ),
            "finish_reason": self.finish_reason if self.finish_reason else None,
            "symbol": self.symbol,
            "direction": (
                self.direction.value
                if isinstance(self.direction, (Direction, Offset))
                else self.direction
            ),
            "offset": (
                self.offset.value if isinstance(self.offset, (Direction, Offset)) else self.offset
            ),
            "volume": self.volume,
            "filled_volume": self.filled_volume,
            "filled_price": round(self.filled_price, 2),
            "remaining_volume": self.remaining_volume,
            "is_active": self.is_active,
            "source": self.source,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_orders": len(self.all_order_ids),
        }
