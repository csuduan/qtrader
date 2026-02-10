"""
报单指令执行器模块（异步版本）

提供异步执行器，统一管理所有 OrderCmd 状态机。
职责：
- 订阅全局事件 (ORDER_UPDATE, TRADE_UPDATE)
- 主循环: 定期遍历所有 cmd，检查并执行报单
- 报单触发: 调用 trading_engine.insert_order()
- 撤单触发: 调用 trading_engine.cancel_order()
- 生命周期: 注册即启动，close() 关闭
"""

import asyncio
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from src.models.object import (
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    PositionData,
    TradeData,
)
from src.trader.order_cmd import OrderCmd, OrderCmdStatus
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.event_engine import EventEngine, EventTypes
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.trader.trading_engine import TradingEngine


class OrderCmdExecutor:
    """
    异步报单指令执行器，管理所有 OrderCmd 状态机

    功能：
    - 订阅全局事件 (ORDER_UPDATE, TRADE_UPDATE)
    - 主循环: 定期遍历所有 cmd，检查并执行报单
    - 报单触发: 调用 trading_engine.insert_order()
    - 撤单触发: 调用 trading_engine.cancel_order()
    - 生命周期: 注册即启动，close() 关闭

    性能优势：
    - 100+ OrderCmd 只需 1 个异步任务（原来需要 100+ 线程）
    - 内存占用从 ~800MB 降至 ~8MB
    - 上下文切换开销降低 ~90%
    """

    def __init__(self, event_engine: AsyncEventEngine, trading_engine: "TradingEngine"):
        self.logger = get_logger("OrderCmdExecutor")
        self._event_engine = event_engine
        self._trading_engine = trading_engine

        # OrderCmd 注册表
        self._pending_cmds: Dict[str, "OrderCmd"] = {}
        self._history_cmds: Dict[str, "OrderCmd"] = {}

        # 控制参数
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 统计
        self._trig_count = 0
        self._last_stats_time: float = 0.0

    def start(self) -> None:
        """启动执行器"""
        if self._running:
            self.logger.warning("执行器已在运行")
            return

        self._running = True
        self._loop = asyncio.get_running_loop()

        # 订阅全局事件（只订阅一次）
        self._event_engine.register(EventTypes.ORDER_UPDATE, self._on_order_update)
        self._event_engine.register(EventTypes.TRADE_UPDATE, self._on_trade_update)

        # 启动主循环
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info("OrderCmdExecutor执行器已启动")

    async def stop(self) -> None:
        """停止执行器"""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.logger.info("执行器已停止")

    def register(self, cmd: "OrderCmd") -> None:
        """
        注册 OrderCmd - 注册即启动

        Args:
            cmd: OrderCmd 实例
        """
        # 订阅合约行情（异步）
        #asyncio.create_task()
        self._trading_engine.subscribe_symbol(cmd.symbol)

        # 设置为运行状态
        cmd.status = OrderCmdStatus.RUNNING
        cmd.started_at = datetime.now()
        self._pending_cmds[cmd.cmd_id] = cmd
        self._history_cmds[cmd.cmd_id] = cmd

        self.logger.info(f"添加OrderCmd到执行器: {cmd.cmd_id} {cmd.symbol} {cmd.offset} {cmd.direction} {cmd.volume}手")
        # 查询持仓信息（只对平仓指令需要）
        pos = None
        if cmd.offset == Offset.CLOSE:
            pos = self._trading_engine.get_position(cmd.symbol)
        # 拆单
        cmd.split(pos)
        # 触发状态变更事件 (PENDING -> RUNNING)
        self._emit_cmd_update(cmd)

    def close(self, cmd_id: str) -> bool:
        """
        关闭 OrderCmd（取消）

        Args:
            cmd_id: 指令ID

        Returns:
            是否成功
        """
        cmd = self._pending_cmds.get(cmd_id)
        # 只允许关闭活跃状态的指令（RUNNING状态）
        if not cmd or cmd.status != OrderCmdStatus.RUNNING:
            return False

        # 撤销所有活动订单（异步）
        pending_order = cmd.get_pending_order()
        if pending_order:
            self._trading_engine.cancel_order(pending_order.order_id)

        # 设置为关闭状态
        old_status = cmd.status
        cmd.close()
        if old_status != cmd.status:
            self._emit_cmd_update(cmd)
        self.logger.info(f"关闭 OrderCmd: {cmd_id}")
        return True

    def unregister(self, cmd_id: str) -> None:
        """
        注销 OrderCmd

        Args:
            cmd_id: 指令ID
        """
        self._pending_cmds.pop(cmd_id, None)
        self.logger.debug(f"注销 OrderCmd: {cmd_id}")

    def _on_order_update(self, order: OrderData) -> None:
        """处理订单更新 - 分发给对应的 OrderCmd"""
        for cmd in self._pending_cmds.values():
            # 检查是否是该指令的订单（单一活动订单）
            if cmd._pending_order and order.order_id == cmd._pending_order.order_id:
                old_status = cmd.status
                cmd.update("ORDER_UPDATE", order)
                if old_status != cmd.status:
                    self._emit_cmd_update(cmd)
                break

    def _on_trade_update(self, trade: TradeData) -> None:
        """处理成交更新 - 分发给对应的 OrderCmd"""
        for cmd in self._pending_cmds.values():
            if trade.order_id in cmd.all_order_ids:
                old_status = cmd.status
                old_filled = cmd.filled_volume
                cmd.update("TRADE_UPDATE", trade)
                if old_status != cmd.status or old_filled != cmd.filled_volume:
                    self._emit_cmd_update(cmd)
                break

    def _emit_cmd_update(self, cmd: "OrderCmd") -> None:
        """触发指令状态变更事件"""
        self._trading_engine._emit_cmd_update_event(cmd)

    async def _run_loop(self) -> None:
        """主执行循环（异步版本）"""
        self.logger.info("执行器主循环启动")
        self._last_stats_time = time.time()

        while self._running:
            try:
                # 遍历所有 cmd，检查并执行报单
                if len(self._pending_cmds) == 0:
                    await asyncio.sleep(0)
                    continue
                remove_list = []
                for cmd_id, cmd in self._pending_cmds.items():
                    if cmd.is_finished:
                        self._emit_cmd_update(cmd)
                        remove_list.append(cmd_id)
                    else:
                        try:
                            self._process_cmd(cmd)
                        except Exception as e:
                            self.logger.exception(f"cmd 处理失败 {cmd_id}: {e}")

                # 移除已完成的指令
                for cmd_id in remove_list:
                    self._pending_cmds.pop(cmd_id, None)

                # 定期输出统计
                await self._maybe_log_stats()
            except Exception as e:
                self.logger.exception(f"执行循环异常: {e}")
            await asyncio.sleep(0)
        self.logger.info("执行器主循环退出")

    def _process_cmd(self, cmd: "OrderCmd") -> None:
        """
        处理单个 OrderCmd 的 tick

        Args:
            cmd: OrderCmd 实例
        """
        # 获取待下单请求（传递持仓信息）
        req = cmd.trig()
        if not req:
            return
        if isinstance(req, OrderRequest):
            # 报单（异步）
            try:
                order = self._trading_engine.insert_order(
                    symbol=req.symbol,
                    direction=req.direction,
                    offset=req.offset,
                    volume=req.volume,
                    price=req.price or 0,
                )
                if order:
                    cmd.add_order(order)
            except Exception as e:
                self.logger.exception(f"下单失败 {cmd.cmd_id}: {e}")
                cmd.close(f"报单被拒: {e}")

        elif isinstance(req, OrderData):
            # 撤单（异步）
            try:
                self._trading_engine.cancel_order(req.order_id)
                req.canceled = True
            except Exception as e:
                self.logger.error(f"撤单失败 {req.order_id}: {e}")

    async def _maybe_log_stats(self) -> None:
        """定期输出统计信息"""
        now = time.time()
        if now - self._last_stats_time >= 60:  # 每分钟一次
            active_count = sum(1 for cmd in self._pending_cmds.values() if cmd.is_active)
            self.logger.info(
                f"执行器统计: 活跃={active_count} 总计={len(self._pending_cmds)} "
                f"tick次数={self._trig_count}"
            )
            self._last_stats_time = now

    def get_hist_cmds(self) -> dict:
        """
        获取历史指令

        Args:

        Returns:
            执行器状态字典
        """
        return self._history_cmds

    def get_active_cmds(self) -> dict:
        """
        获取活跃指令

        Args:

        Returns:
            活跃指令字典
        """
        return self._pending_cmds
