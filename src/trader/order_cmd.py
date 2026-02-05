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
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional
from xxlimited import Str
from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger(__name__)

from src.models.object import (
    Direction,
    Offset,
    OrderCmdFinishReason,
    OrderData,
    OrderRequest,
    OrderStatus,
    TradeData,
)


class OrderCmdStatus(str):
    """报单指令状态"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


class SplitStrategyType(str):
    """拆单策略类型"""

    SIMPLE = "SIMPLE"
    TWAP = "TWAP"


@dataclass
class SplitOrder:
    """拆单后的单个订单"""

    volume: int
    delay_seconds: float = 0.0


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
        self._order_queue: List[SplitOrder] = []

    @abstractmethod
    def split(self, total_volume: int) -> List[SplitOrder]:
        """拆单"""
        pass

    def get_next(self) -> Optional[SplitOrder]:
        """获取下一个订单"""
        if not self._order_queue:
            return None
        return self._order_queue.pop(0)


class SimpleSplitStrategy(BaseSplitStrategy):
    """简单拆单策略"""

    def split(self, total_volume: int) -> List[SplitOrder]:
        """拆单 - 按最大单次手数均分"""
        max_volume = self.cmd.max_volume_per_order
        orders = []
        remaining = total_volume
        while remaining > 0:
            volume = min(remaining, max_volume)
            orders.append(SplitOrder(volume=volume))
            remaining -= volume
        self._order_queue = orders
        return orders


class TWAPSplitStrategy(BaseSplitStrategy):
    """TWAP拆单策略 - 时间加权平均价格"""

    def split(self, total_volume: int) -> List[SplitOrder]:
        """拆单 - 在指定时长内均匀分配"""
        duration = self.cmd.twap_duration or 300
        max_volume = self.cmd.max_volume_per_order
        num_orders = max(
            1, min((total_volume + max_volume - 1) // max_volume, duration // 1)
        )
        time_interval = duration / num_orders
        orders = []
        for i in range(num_orders):
            volume = total_volume // num_orders + (
                1 if i < total_volume % num_orders else 0
            )
            delay = i * time_interval
            orders.append(SplitOrder(volume=volume, delay_seconds=delay))
        self._order_queue = orders
        return orders


class OrderCmd():
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
        # 拆单参数
        split_strategy: str = SplitStrategyType.SIMPLE,
        max_volume_per_order: int = 10,
        order_interval: float = 0.5,
        twap_duration: Optional[int] = None,
        # 控制参数
        total_timeout: int = 300,
        max_retries: int = 3, 
        order_timeout: float = 15.0,
    ):
        self.cmd_id = uuid.uuid4().hex
        self.symbol = symbol
        self.direction = direction
        self.offset = offset
        self.volume = volume
        self.price = price
        self.split_strategy = split_strategy
        self.max_volume_per_order = max_volume_per_order
        self.order_interval = order_interval
        self.twap_duration = twap_duration
        self.total_timeout = total_timeout #总超时时间
        self.max_retries = max_retries #超时重试次数
        self.order_timeout = order_timeout #单次报单超时

        # 状态
        self.status = OrderCmdStatus.PENDING
        self.finish_reason: Optional[Str] = None
        self.filled_volume = 0 #已成交
        self.filled_price = 0.0  #已成交均价
        self._filled_amount = 0.0  #已成交总金额（价格×数量）

        # 时间记录
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None

        # 订单追踪
        self.all_order_ids: List[str] = []
        self._active_orders: Dict[str, OrderData] = {}
        self._active_order_info: Dict[str, ActiveOrderInfo] = {}
        self._order_last_tracked: Dict[str, int] = {}  # 跟踪每个订单上一次已统计的成交数量
        self._pending_retry_volume: int = 0  # 待重试的手数

        # 拆单策略
        self._strategy: Optional[BaseSplitStrategy] = None

        # 状态机控制
        self._last_order_time: float = 0
        self._next_split_order: Optional[SplitOrder] = None
        self._split_order_ready_time: float = 0  # 下一个拆单准备就绪的时间
        self._error_count = 0

    def _init_split_strategy(self) -> None:
        """初始化拆单策略"""
        if self.split_strategy == SplitStrategyType.TWAP:
            self._strategy = TWAPSplitStrategy(self)
        else:
            self._strategy = SimpleSplitStrategy(self)

        # 执行拆单
        orders = self._strategy.split(self.volume)
        logger.info(
            f"指令启动: {self.symbol} {self.direction} {self.volume}手, 拆分为{len(orders)}单"
        )

    def _load_next_split_order(self) -> None:
        """加载下一个拆单"""
        if self._strategy is None:
            return

        self._next_split_order = self._strategy.get_next()
        if self._next_split_order is not None:
            # 计算准备就绪时间（TWAP延迟）
            self._split_order_ready_time = time.time() + self._next_split_order.delay_seconds

    def tick(self, now: float) -> Optional[OrderRequest]:
        """
        时间驱动状态转换

        Args:
            now: 当前时间戳

        Returns:
            待提交的订单请求，如果无需下单则返回 None
        """
        if self.status != OrderCmdStatus.RUNNING:
            return None

        # 检查总超时
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            if elapsed >= self.total_timeout:
                self._finish("超时指令")
                return None

        # 检查是否完成
        if self.filled_volume >= self.volume:
            self._finish("全部完成")
            return None

        # 处理待重试的手数
        if self._pending_retry_volume > 0:
            if now - self._last_order_time >= self.order_interval:
                return self._create_retry_order_request()
            return None

        # 处理下一个拆单
        if self._next_split_order is not None:
            if now >= self._split_order_ready_time:
                if now - self._last_order_time >= self.order_interval:
                    return self._create_split_order_request()
            return None

        # 加载下一个拆单
        self._load_next_split_order()
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

    def close(self) -> None:
        """关闭指令（取消）"""
        if self.status != OrderCmdStatus.RUNNING:
            return
        self.status = OrderCmdStatus.FINISHED
        self.finish_reason = "取消指令"
        self.finished_at = datetime.now()
        logger.info(f"指令已取消: {self.cmd_id}")

    def get_active_orders(self) -> List[str]:
        """获取需要撤单的活动订单ID列表（关闭时使用）"""
        return list(self._active_orders.keys())

    def get_timeout_orders(self, now: float) -> List[str]:
        """
        获取超时订单ID列表

        Args:
            now: 当前时间戳

        Returns:
            超时的订单ID列表
        """
        if self.order_timeout <= 0:
            return []

        timed_out = []
        for order_id, info in self._active_order_info.items():
            if now - info.submit_time >= self.order_timeout:
                order = self._active_orders.get(order_id)
                if order and order.is_active() and info.retry_count < self.max_retries:
                    timed_out.append(order_id)
        return timed_out

    def on_order_submitted(self, order_id: str, volume: int) -> None:
        """
        订单提交成功回调

        Args:
            order_id: 订单ID
            volume: 委托数量
        """
        self.all_order_ids.append(order_id)
        self._active_order_info[order_id] = ActiveOrderInfo(
            order_id=order_id, volume=volume, submit_time=time.time(), retry_count=0
        )
        self._last_order_time = time.time()

    def on_order_cancelled(self, order_id: str, unfilled_volume: int) -> None:
        """
        订单撤单回调（超时撤单）

        Args:
            order_id: 订单ID
            unfilled_volume: 未成交手数
        """
        info = self._active_order_info.get(order_id)
        if info:
            self._active_order_info[order_id].retry_count += 1
        self._active_order_info.pop(order_id, None)
        self._active_orders.pop(order_id, None)

        if unfilled_volume > 0:
            self._pending_retry_volume += unfilled_volume
            logger.info(
                f"订单 {order_id} 超时撤单，未成交 {unfilled_volume} 手加入重试队列，"
                f"当前待重试: {self._pending_retry_volume} 手"
            )

    def _create_split_order_request(self) -> Optional[OrderRequest]:
        """创建拆单订单请求"""
        if self._next_split_order is None:
            return None

        volume = self._next_split_order.volume
        req = OrderRequest(
            symbol=self.symbol,
            direction=self.direction,
            offset=self.offset,
            volume=volume,
            price=self.price,
        )

        # 清空当前拆单
        self._next_split_order = None
        return req

    def _create_retry_order_request(self) -> Optional[OrderRequest]:
        """创建重试订单请求"""
        volume_to_submit = min(self._pending_retry_volume, self.max_volume_per_order)
        req = OrderRequest(
            symbol=self.symbol,
            direction=self.direction,
            offset=self.offset,
            volume=volume_to_submit,
            price=self.price,
        )

        self._pending_retry_volume -= volume_to_submit
        return req

    def _handle_order_update(self, order: OrderData) -> None:
        """处理订单更新"""
        if order.order_id not in self.all_order_ids:
            return

        # 初始化跟踪
        if order.order_id not in self._order_last_tracked:
            self._order_last_tracked[order.order_id] = 0

        # 计算成交增量（确保每笔成交只统计一次）
        last_traded = self._order_last_tracked[order.order_id]
        traded_delta = order.traded - last_traded

        if traded_delta > 0 and order.traded_price:
            # 更新成交数量和总金额
            self.filled_volume += traded_delta
            self._filled_amount += order.traded_price * traded_delta
            # 计算加权平均价格
            if self.filled_volume > 0:
                self.filled_price = self._filled_amount / self.filled_volume
            # 更新已跟踪的成交数量
            self._order_last_tracked[order.order_id] = order.traded
            logger.info(
                f"订单成交: {order.symbol} {order.order_id} +{traded_delta}手@{order.traded_price}, "
                f"均价={self.filled_price:.2f}, 累计成交: {self.filled_volume}"
            )

        if order.is_active():
            self._active_orders[order.order_id] = order
        else:
            self._active_orders.pop(order.order_id, None)
            # 清理订单信息
            self._active_order_info.pop(order.order_id, None)
            if order.status == "REJECTED":
                # self._error_count += 1
                # if self._error_count >= 3:
                self._finish(f"订单失败：{order.status_msg}")

        self._check_completion()

    def _handle_trade_update(self, trade: TradeData) -> None:
        """处理成交更新（成交统计已由订单更新处理）"""
        # 成交统计已在 _handle_order_update 中通过 traded 和 traded_price 完成
        # 这里只做完成检查
        self._check_completion()

    def _check_completion(self) -> None:
        """检查是否完成"""
        # 全部成交
        if self.filled_volume >= self.volume:
            self._finish("全部完成")
            return

        # 超时检查
        if self.started_at:
            elapsed = (datetime.now() - self.started_at).total_seconds()
            if elapsed >= self.total_timeout:
                self._finish("超时指令")
                return


    def _finish(self, reason: str) -> None:
        """结束指令"""
        if self.status == OrderCmdStatus.FINISHED:
            return

        self.status = OrderCmdStatus.FINISHED
        self.finish_reason = reason
        self.finished_at = datetime.now()
        logger.info(
            f"指令结束: 原因={reason} "
            f"目标={self.volume} 成交={self.filled_volume} "
            f"均价={self.filled_price:.2f}"
        )

    @property
    def remaining_volume(self) -> int:
        """剩余手数"""
        return self.volume - self.filled_volume

    @property
    def is_active(self) -> bool:
        """是否活跃"""
        return self.status == OrderCmdStatus.RUNNING

    @property
    def is_finished(self) -> bool:
        """是否完成"""
        return self.status == OrderCmdStatus.FINISHED

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "cmd_id": self.cmd_id,
            "status": self.status,
            "finish_reason": self.finish_reason if self.finish_reason else None,
            "symbol": self.symbol,
            "direction": self.direction,
            "offset": self.offset,
            "volume": self.volume,
            "filled_volume": self.filled_volume,
            "filled_price": round(self.filled_price, 2),
            "remaining_volume": self.remaining_volume,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "split_strategy": self.split_strategy,
            "total_orders": len(self.all_order_ids),
        }
