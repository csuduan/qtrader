"""
连接、行情订阅、订单/成交/持仓/合约查询等基础请求处理
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qtrader.trader.req.base import BaseReqHandler
from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.models.po import RotationInstructionPo

logger = get_logger(__name__)


class ConnectionReqHandler(BaseReqHandler):
    @request("connect_gateway")
    async def _req_connect(self, data: dict) -> bool | None:
        """处理连接请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trader.trading_engine.connect()
        logger.info(f"Trader [{self.account_id}] 连接成功")
        return True

    @request("disconnect_gateway")
    async def _req_disconnect(self, data: dict) -> bool | None:
        """处理断开连接请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trader.trading_engine.disconnect()
        logger.info(f"Trader [{self.account_id}] 断开连接成功")
        return True

    @request("subscribe")
    async def _req_subscribe(self, data: dict) -> bool | None:
        """处理订阅请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        self.trader.trading_engine.subscribe_symbol(data["symbol"])
        logger.info(f"Trader [{self.account_id}] 订阅{data['symbol']}成功")
        return True

    @request("unsubscribe")
    async def _req_unsubscribe(self, data: dict) -> bool:
        """处理取消订阅请求"""
        logger.info(f"Trader [{self.account_id}] 取消订阅成功")
        return True

    @request("order_req")
    async def _req_order(self, data: dict) -> str | None:
        """
        处理下单请求

        Args:
            data: 包含 symbol, direction, offset, volume, price(可选)

        Returns:
            订单ID，失败返回None
        """
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None

        from qtrader.models.object import Direction, Offset

        symbol = data["symbol"]
        direction = Direction(data["direction"])
        offset = Offset(data["offset"])
        volume = data["volume"]
        price = data.get("price", 0)

        # 异常（参数错误/非交易时段拦截/风控拒绝等）直接上抛，
        # 由 SocketServer 统一记日志并包装为错误响应回传 Manager
        order_data = self.trader.trading_engine.insert_order(
            symbol=symbol,
            direction=direction.value,
            offset=offset.value,
            volume=volume,
            price=price,
        )
        if order_data is None:
            logger.error(f"Trader [{self.account_id}] 下单失败: 返回空订单")
            return None

        logger.info(f"Trader [{self.account_id}] 下单成功: {order_data.order_id}")
        return order_data.order_id

    @request("cancel_req")
    async def _req_cancel(self, data: dict) -> bool:
        """
        处理撤单请求

        Args:
            data: 包含 order_id

        Returns:
            是否成功
        """
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return False

        order_id = data["order_id"]
        success = self.trader.trading_engine.cancel_order(order_id)

        if success:
            logger.info(f"Trader [{self.account_id}] 撤单成功: {order_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 撤单失败: {order_id}")

        return success

    @request("get_account")
    async def _req_get_account(self, data: dict) -> dict | None:
        """处理获取账户数据请求"""
        if self.trader.trading_engine is None:
            return None
        account = self.trader.trading_engine.account
        return account.model_dump() if account else None

    @request("get_order")
    async def _req_get_order(self, data: dict) -> dict | None:
        """处理获取订单数据请求"""
        if self.trader.trading_engine is None:
            return None
        order_id = data.get("order_id")
        if order_id:
            order = self.trader.trading_engine.orders.get(order_id)
            if order:
                return order.model_dump()
        return None

    @request("get_orders")
    async def _req_get_orders(self, data: dict) -> list:
        """处理获取所有订单数据请求"""
        if self.trader.trading_engine is None:
            return []
        orders = self.trader.trading_engine.orders
        return [order.model_dump() for order in orders.values()]

    @request("get_active_orders")
    async def _req_get_active_orders(self, data: dict) -> list:
        """处理获取活动订单请求"""
        if self.trader.trading_engine is None:
            return []
        from qtrader.models.object import OrderStatus

        orders = self.trader.trading_engine.orders
        return [
            order.model_dump() for order in orders.values() if order.status == OrderStatus.PENDING
        ]

    @request("get_trade")
    async def _req_get_trade(self, data: dict) -> dict | None:
        """处理获取成交数据请求"""
        if self.trader.trading_engine is None:
            return None
        trade_id = data.get("trade_id")
        if trade_id:
            trade = self.trader.trading_engine.trades.get(trade_id)
            if trade:
                return trade.model_dump()
        return None

    @request("get_trades")
    async def _req_get_trades(self, data: dict) -> list:
        """处理获取所有成交数据请求"""
        if self.trader.trading_engine is None:
            return []
        trades = self.trader.trading_engine.trades
        return [trade.model_dump() for trade in trades.values()]

    @request("get_positions")
    async def _req_get_positions(self, data: dict) -> list:
        """处理获取所有持仓数据请求"""
        if self.trader.trading_engine is None:
            return []
        positions = self.trader.trading_engine.positions
        return [pos.model_dump() for pos in positions.values()]

    @request("get_quotes")
    async def _req_get_quotes(self, data: dict) -> list:
        """处理获取行情请求"""
        if self.trader.trading_engine is None:
            return []
        quotes = self.trader.trading_engine.quotes
        return [quote.model_dump() for quote in quotes.values()]

    @request("get_account_details")
    async def _req_get_account_details(self, data: dict) -> dict:
        """
        获取账户完整数据

        返回包括：账户信息、持仓列表、挂单列表、成交列表、行情列表
        """
        if self.trader.trading_engine is None:
            return {
                "account": None,
                "positions": [],
                "orders": [],
                "trades": [],
                "quotes": [],
            }

        # 获取账户数据
        account = self.trader.trading_engine.account

        # 获取持仓列表
        positions = self.trader.trading_engine.positions

        # 获取挂单列表（未终态订单）
        from qtrader.models.object import OrderStatus

        orders = self.trader.trading_engine.orders
        active_orders = [o for o in orders.values() if o.status == OrderStatus.PENDING]

        # 获取成交列表（今日）
        trades = self.trader.trading_engine.trades

        # 获取行情列表
        quotes = self.trader.trading_engine.quotes

        return {
            "account": account.model_dump() if account else None,
            "positions": [p.model_dump() for p in positions.values()],
            "orders": [o.model_dump() for o in active_orders],
            "trades": [t.model_dump() for t in trades.values()],
            "quotes": [q.model_dump() for q in quotes.values()],
        }

    @request("get_contracts")
    async def _req_get_contracts(self, data: dict) -> list:
        """
        处理获取合约列表请求

        从内存中获取合约信息（从 Gateway 缓存）
        """
        if self.trader.trading_engine is None or self.trader.trading_engine.gateway is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎或 Gateway 未初始化")
            return []

        contracts = self.trader.trading_engine.gateway.get_contracts()
        result = []
        for contract in contracts.values():
            contract_dict = contract.model_dump()
            # 添加 update_date 字段（使用今天的日期）
            contract_dict["update_date"] = datetime.now().strftime("%Y-%m-%d")
            result.append(contract_dict)
        return result

    @request("get_order_cmds_status")
    async def _req_get_order_cmds_status(self, data: dict) -> list | None:
        """
        处理获取报单指令状态请求

        支持状态过滤:
        - status="active" : 只返回未完成的活跃指令
        - status="finished" : 只返回已完成的指令
        - status=None: 返回所有指令

        Returns:
            执行器状态字典，失败返回None
        """
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None

        if self.trader.trading_engine._order_cmd_executor is None:
            logger.warning(f"Trader [{self.account_id}] 报单指令执行器未初始化")
            return None

        status_filter = data.get("status")
        cmds = self.trader.trading_engine._order_cmd_executor.get_hist_cmds()
        if status_filter == "active":
            cmd_list = [cmd for cmd in cmds.values() if cmd.is_active]
        elif status_filter == "finished":
            cmd_list = [cmd for cmd in cmds.values() if cmd.is_finished]
        else:
            cmd_list = list(cmds.values())
        return [cmd.to_dict() for cmd in cmd_list]

    @request("cancel_order_cmd")
    async def _req_cancel_order_cmd(self, data: dict) -> dict:
        """
        处理取消报单指令请求

        Args:
            data: {"cmd_id": 指令ID}

        Returns:
            {"success": bool, "message": str}
        """
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

        cmd_id = data.get("cmd_id")
        if not cmd_id:
            return {"success": False, "message": "缺少指令ID"}

        try:
            result = await self.trader.trading_engine.cancel_order_cmd(cmd_id)
            if result:
                return {"success": True, "message": "取消指令已发送"}
            else:
                return {"success": False, "message": "取消指令失败，指令可能已完成或不存在"}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 取消报单指令失败: {e}")
            return {"success": False, "message": f"取消失败: {str(e)}"}

    @request("get_jobs")
    async def _req_get_jobs(self, data: dict) -> list:
        """处理获取所有任务请求"""
        if self.trader.trading_engine is None or self.trader.task_scheduler is None:
            return []
        jobs = self.trader.task_scheduler.get_jobs()
        return [job.model_dump() for job in jobs.values()]

    @request("trigger_job")
    async def _req_trigger_job(self, data: dict) -> bool:
        """处理手动触发任务请求"""
        if self.trader.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.trader.task_scheduler.trigger_job(job_id)
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已触发: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 触发任务失败: {job_id}")
        return success

    @request("toggle_job")
    async def _req_toggle_job(self, data: dict) -> bool:
        """处理切换任务状态请求"""
        if self.trader.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        enabled = data.get("enabled")
        if not job_id or enabled is None:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id 或 enabled")
            return False
        success = self.trader.task_scheduler.update_job_status(job_id, enabled)
        if success:
            logger.info(f"Trader [{self.account_id}] 任务状态已更新: {job_id} -> {enabled}")
        else:
            logger.warning(f"Trader [{self.account_id}] 更新任务状态失败: {job_id}")
        return success

    @request("pause_job")
    async def _req_pause_job(self, data: dict) -> bool:
        """处理暂停任务请求"""
        if self.trader.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.trader.task_scheduler.operate_job(job_id, "pause")
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已暂停: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 暂停任务失败: {job_id}")
        return success

    @request("resume_job")
    async def _req_resume_job(self, data: dict) -> bool:
        """处理恢复任务请求"""
        if self.trader.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.trader.task_scheduler.operate_job(job_id, "resume")
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已恢复: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 恢复任务失败: {job_id}")
        return success
