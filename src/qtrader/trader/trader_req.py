"""
Trader Socket请求处理器

将Trader中所有@request装饰的Socket请求处理方法集中管理
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.trader.trader import Trader

logger = get_logger(__name__)


class TraderReqHandler:
    """
    Socket请求处理器

    负责处理Manager通过Socket发送过来的所有请求
    """

    def __init__(self, trader: "Trader"):
        self.trader = trader
        self.account_id = trader.account_id

    # ========== Socket请求处理方法 ==========

    @request("connect_gateway")
    async def _req_connect(self, data: dict) -> bool:
        """处理连接请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trader.trading_engine.connect()
        logger.info(f"Trader [{self.account_id}] 连接成功")
        return True

    @request("disconnect_gateway")
    async def _req_disconnect(self, data: dict) -> bool:
        """处理断开连接请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trader.trading_engine.disconnect()
        logger.info(f"Trader [{self.account_id}] 断开连接成功")
        return True

    @request("subscribe")
    async def _req_subscribe(self, data: dict) -> bool:
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

        try:
            from qtrader.models.object import Direction, Offset

            symbol = data["symbol"]
            direction = Direction(data["direction"])
            offset = Offset(data["offset"])
            volume = data["volume"]
            price = data.get("price", 0)

            order_id = self.trader.trading_engine.insert_order(
                symbol=symbol,
                direction=direction.value,
                offset=offset.value,
                volume=volume,
                price=price,
            )

            logger.info(f"Trader [{self.account_id}] 下单成功: {order_id}")
            return order_id

        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 下单失败: {e}")
            return None

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

        try:
            order_id = data["order_id"]
            success = self.trader.trading_engine.cancel_order(order_id)

            if success:
                logger.info(f"Trader [{self.account_id}] 撤单成功: {order_id}")
            else:
                logger.warning(f"Trader [{self.account_id}] 撤单失败: {order_id}")

            return success

        except Exception as e:
            logger.error(f"Trader [{self.account_id}] 撤单失败: {e}")
            return False

    @request("get_account")
    async def _req_get_account(self, data: dict) -> dict | None:
        """处理获取账户数据请求"""
        if self.trader.trading_engine is None:
            return None
        account = self.trader.trading_engine.account
        return account.model_dump()

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
        orders = self.trader.trading_engine.orders
        return [order.model_dump() for order in orders.values() if order.status == "ACTIVE"]

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

        # 获取挂单列表（状态为ALIVE/PENDING的订单）
        orders = self.trader.trading_engine.orders
        active_orders = [o for o in orders.values() if o.status in ("ALIVE", "PENDING")]

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

        try:
            contracts = self.trader.trading_engine.gateway.get_contracts()
            result = []
            for contract in contracts.values():
                contract_dict = contract.model_dump()
                # 添加 update_date 字段（使用今天的日期）
                contract_dict["update_date"] = datetime.now().strftime("%Y-%m-%d")
                result.append(contract_dict)
            return result
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 获取合约列表失败: {e}")
            return []

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

        try:
            status_filter = data.get("status")
            cmds = self.trader.trading_engine._order_cmd_executor.get_hist_cmds()
            if status_filter == "active":
                cmds = [cmd for cmd in cmds.values() if cmd.is_active]
            elif status_filter == "finished":
                cmds = [cmd for cmd in cmds.values() if cmd.is_finished]
            return [cmd.to_dict() for cmd in cmds]
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 获取报单指令状态失败: {e}")
            return None

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
        if self.trader.trading_engine is None:
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

    # ========== 策略管理请求处理 ==========

    def _calc_position_profit(self, strategy, symbol: str, last_price: float) -> float:
        """计算策略持仓盈亏"""
        position = strategy.get_position(symbol)
        if not position or last_price <= 0:
            return 0.0

        multiple = position.multiple or 0

        # 计算多头持仓盈亏
        long_profit = 0.0
        if position.pos_long > 0 and position.hold_price_long > 0:
            long_profit = (last_price - position.hold_price_long) * position.pos_long * multiple

        # 计算空头持仓盈亏
        short_profit = 0.0
        if position.pos_short > 0 and position.hold_price_short > 0:
            short_profit = (position.hold_price_short - last_price) * position.pos_short * multiple

        return long_profit + short_profit

    @request("list_strategies")
    async def _req_list_strategies(self, data: dict) -> list:
        """处理获取策略列表请求"""
        if self.trader.strategy_manager is None:
            return []
        from qtrader.manager.api.schemas import StrategyPositionRes, StrategyRes
        from qtrader.trader.strategy import BaseParam

        # 获取最新行情数据
        quotes = self.trader.trading_engine.quotes if self.trader.trading_engine else {}

        result = []
        for strategy in self.trader.strategy_manager.strategies.values():
            params = strategy.get_params()
            base_fields = set[str](BaseParam.model_fields.keys())
            ext_params = [p for p in params if p["key"] not in base_fields]
            base_params = [p for p in params if p["key"] in base_fields]

            # 构建多合约持仓列表
            positions: list[StrategyPositionRes] = []
            for symbol, pos in strategy.get_all_positions().items():
                if pos.total_pos > 0:  # 只返回有持仓的
                    # 获取最新价格并计算持仓盈亏
                    tick = quotes.get(symbol)
                    last_price = tick.last_price if tick else 0.0
                    position_profit = self._calc_position_profit(strategy, symbol, last_price)

                    positions.append(
                        StrategyPositionRes(
                            symbol=symbol,
                            pos_long=pos.pos_long,
                            pos_long_td=pos.pos_long_td or 0,
                            pos_long_yd=pos.pos_long_yd or 0,
                            pos_short=pos.pos_short,
                            pos_short_td=pos.pos_short_td or 0,
                            pos_short_yd=pos.pos_short_yd or 0,
                            pos_net=pos.pos,
                            hold_price_long=pos.hold_price_long or 0,
                            hold_price_short=pos.hold_price_short or 0,
                            position_profit=position_profit,
                            close_profit=(pos.close_profit_long or 0)
                            + (pos.close_profit_short or 0),
                        )
                    )

            strategy_res = StrategyRes(
                strategy_id=strategy.strategy_id,
                enabled=strategy.enabled,
                opening_paused=strategy.opening_paused,
                closing_paused=strategy.closing_paused,
                inited=strategy.inited,
                symbol=strategy.symbol,
                config=strategy.config.model_dump(),
                base_params=base_params,
                ext_params=ext_params,
                signal=strategy.get_signal(),
                pos_long=sum(pos.pos_long for pos in positions),
                pos_short=sum(pos.pos_short for pos in positions),
                positions=positions,
                trading_status=strategy.get_trading_status(),
            )
            result.append(strategy_res.model_dump())
        return result

    @request("get_strategy")
    async def _req_get_strategy(self, data: dict) -> dict | None:
        """处理获取指定策略状态请求"""
        if self.trader.strategy_manager is None:
            return None
        from qtrader.manager.api.schemas import StrategyPositionRes, StrategyRes
        from qtrader.trader.strategy import BaseParam

        strategy_id = data.get("strategy_id")
        if strategy_id and strategy_id in self.trader.strategy_manager.strategies:
            strategy = self.trader.strategy_manager.strategies[strategy_id]
            params = strategy.get_params()
            base_fields = set[str](BaseParam.model_fields.keys())
            ext_params = [p for p in params if p["key"] not in base_fields]
            base_params = [p for p in params if p["key"] in base_fields]

            # 获取最新行情数据
            quotes = self.trader.trading_engine.quotes if self.trader.trading_engine else {}

            # 构建多合约持仓列表
            positions: list[StrategyPositionRes] = []
            for symbol, pos in strategy.get_all_positions().items():
                if pos.total_pos > 0:  # 只返回有持仓的
                    # 获取最新价格并计算持仓盈亏
                    tick = quotes.get(symbol)
                    last_price = tick.last_price if tick else 0.0
                    position_profit = self._calc_position_profit(strategy, symbol, last_price)

                    positions.append(
                        StrategyPositionRes(
                            symbol=symbol,
                            pos_long=pos.pos_long,
                            pos_long_td=pos.pos_long_td or 0,
                            pos_long_yd=pos.pos_long_yd or 0,
                            pos_short=pos.pos_short,
                            pos_short_td=pos.pos_short_td or 0,
                            pos_short_yd=pos.pos_short_yd or 0,
                            pos_net=pos.pos,
                            hold_price_long=pos.hold_price_long or 0,
                            hold_price_short=pos.hold_price_short or 0,
                            position_profit=position_profit,
                            close_profit=(pos.close_profit_long or 0)
                            + (pos.close_profit_short or 0),
                        )
                    )

            result = StrategyRes(
                strategy_id=strategy.strategy_id,
                enabled=strategy.enabled,
                opening_paused=strategy.opening_paused,
                closing_paused=strategy.closing_paused,
                inited=strategy.inited,
                symbol=strategy.symbol,
                config=strategy.config.model_dump(),
                base_params=base_params,
                ext_params=ext_params,
                signal=strategy.get_signal(),
                pos_long=sum(pos.pos_long for pos in positions),
                pos_short=sum(pos.pos_short for pos in positions),
                positions=positions,
                trading_status=strategy.get_trading_status(),
            )
            return result.model_dump()
        return None

    @request("replay_all_strategies")
    async def _req_replay_all_strategies(self, data: dict) -> dict:
        """处理回播所有策略请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        try:
            result = await self.trader.strategy_manager.replay_all_strategies()
            if result.get("success"):
                return {
                    "success": True,
                    "message": "回播完成",
                    "replayed_count": result.get("replayed_count", 0),
                }
            else:
                return {"success": False, "message": result.get("message", "回播失败")}
        except Exception as e:
            logger.exception(f"回播策略失败: {e}")
            return {"success": False, "message": f"回播策略失败: {str(e)}"}

    @request("update_strategy_params")
    async def _req_update_strategy_params(self, data: dict) -> dict:
        """处理更新策略参数请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            params = data.get("params", {})
            strategy.update_params(params)
            logger.info(f"策略 [{strategy_id}] 参数已更新: {params}")
            return {"success": True, "message": "参数更新成功"}
        except Exception as e:
            logger.exception(f"更新策略参数失败: {e}")
            return {"success": False, "message": f"更新失败: {str(e)}"}

    @request("update_strategy_signal")
    async def _req_update_strategy_signal(self, data: dict) -> dict:
        """处理更新策略信号请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            signal = data.get("signal", {})
            strategy.update_signal(signal)
            logger.info(f"策略 [{strategy_id}] 信号已更新: {signal}")
            return {"success": True, "message": "信号更新成功"}
        except Exception as e:
            logger.exception(f"更新策略信号失败: {e}")
            return {"success": False, "message": f"更新失败: {str(e)}"}

    @request("clear_strategy_signal")
    async def _req_clear_strategy_signal(self, data: dict) -> dict:
        """处理清除策略信号请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            strategy.clear_signal()
            return {"success": True, "message": "信号已清除"}
        except Exception as e:
            logger.exception(f"清除策略信号失败: {e}")
            return {"success": False, "message": f"清除失败: {str(e)}"}

    @request("update_strategy_position_detail")
    async def _req_update_strategy_position_detail(self, data: dict) -> dict:
        """处理更新策略持仓详情请求（单个合约）"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            position_data = data.get("position", {})
            symbol = position_data.get("symbol")
            if not symbol:
                return {"success": False, "message": "合约代码不能为空"}

            # 获取请求中的持仓数据
            new_pos_long_td = position_data.get("pos_long_td", 0)
            new_pos_long_yd = position_data.get("pos_long_yd", 0)
            new_pos_short_td = position_data.get("pos_short_td", 0)
            new_pos_short_yd = position_data.get("pos_short_yd", 0)

            # 检查账户持仓限制
            account_positions = self.trader.trading_engine.positions
            account_position = account_positions.get(symbol)

            if account_position:
                # 获取账户持仓数量
                account_pos_long_td = account_position.pos_long_td or 0
                account_pos_long_yd = account_position.pos_long_yd or 0
                account_pos_short_td = account_position.pos_short_td or 0
                account_pos_short_yd = account_position.pos_short_yd or 0

                # 分别检查多头今仓、多头昨仓、空头今仓、空头昨仓
                if new_pos_long_td > account_pos_long_td:
                    return {
                        "success": False,
                        "message": f"多头今仓({new_pos_long_td})不能超过账户多头今仓({account_pos_long_td})",
                    }

                if new_pos_long_yd > account_pos_long_yd:
                    return {
                        "success": False,
                        "message": f"多头昨仓({new_pos_long_yd})不能超过账户多头昨仓({account_pos_long_yd})",
                    }

                if new_pos_short_td > account_pos_short_td:
                    return {
                        "success": False,
                        "message": f"空头今仓({new_pos_short_td})不能超过账户空头今仓({account_pos_short_td})",
                    }

                if new_pos_short_yd > account_pos_short_yd:
                    return {
                        "success": False,
                        "message": f"空头昨仓({new_pos_short_yd})不能超过账户空头昨仓({account_pos_short_yd})",
                    }
            else:
                # 账户没有该合约持仓，策略也不能有持仓
                if (
                    new_pos_long_td > 0
                    or new_pos_long_yd > 0
                    or new_pos_short_td > 0
                    or new_pos_short_yd > 0
                ):
                    return {
                        "success": False,
                        "message": f"账户没有 {symbol} 的持仓，无法设置策略持仓",
                    }

            # 获取或创建持仓对象
            position = strategy._get_or_create_position(symbol)

            # 更新持仓字段
            position.pos_long_td = new_pos_long_td
            position.pos_long_yd = new_pos_long_yd
            position.pos_short_td = new_pos_short_td
            position.pos_short_yd = new_pos_short_yd
            position.hold_price_long = position_data.get("hold_price_long", 0.0)
            position.hold_price_short = position_data.get("hold_price_short", 0.0)
            position.close_profit_long = position_data.get("close_profit_long", 0.0)
            position.close_profit_short = position_data.get("close_profit_short", 0.0)

            # 保存到数据库
            strategy.save_positions()

            logger.info(
                f"策略 [{strategy_id}] {symbol} 持仓已更新: 多{position.pos_long} 空{position.pos_short}"
            )
            return {"success": True, "message": "持仓更新成功"}
        except Exception as e:
            logger.exception(f"更新策略持仓详情失败: {e}")
            return {"success": False, "message": f"更新失败: {str(e)}"}

    @request("delete_strategy_position")
    async def _req_delete_strategy_position(self, data: dict) -> dict:
        """处理删除策略持仓请求（清空单个合约持仓）"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            symbol = data.get("symbol")
            if not symbol:
                return {"success": False, "message": "合约代码不能为空"}

            # 从内存中删除持仓
            if symbol in strategy._positions:
                del strategy._positions[symbol]

            # 从数据库中删除持仓
            if strategy.strategy_manager:
                account_id = (
                    strategy.strategy_manager.trading_engine.account_id
                    if strategy.strategy_manager.trading_engine
                    else None
                )
                if account_id:
                    from qtrader.trader.dao.position_dao import StrategyPositionService

                    service = StrategyPositionService()
                    service.clear_position(account_id, strategy_id, symbol)

            logger.info(f"策略 [{strategy_id}] {symbol} 持仓已删除")
            return {"success": True, "message": "持仓已删除"}
        except Exception as e:
            logger.exception(f"删除策略持仓失败: {e}")
            return {"success": False, "message": f"删除失败: {str(e)}"}

    @request("set_strategy_trading_status")
    async def _req_set_strategy_trading_status(self, data: dict) -> dict:
        """
        处理设置策略交易状态请求（统一接口）

        支持同时设置开仓和平仓状态：
        - opening_paused: 暂停/恢复开仓
        - closing_paused: 暂停/恢复平仓
        """
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        status = data.get("status", {})
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            result_data = {}
            if "opening_paused" in status:
                strategy.set_opening_paused(status["opening_paused"])
                result_data["opening_paused"] = status["opening_paused"]
            if "closing_paused" in status:
                strategy.set_closing_paused(status["closing_paused"])
                result_data["closing_paused"] = status["closing_paused"]
            return {"success": True, "message": "设置成功", "data": result_data}
        except Exception as e:
            logger.exception(f"设置策略交易状态失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("enable_strategy")
    async def _req_enable_strategy(self, data: dict) -> dict:
        """处理启用策略请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            strategy.enable()
            return {"success": True, "message": "启用策略成功"}
        except Exception as e:
            logger.exception(f"启用策略失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("disable_strategy")
    async def _req_disable_strategy(self, data: dict) -> dict:
        """处理禁用策略请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            strategy.enable(False)
            return {"success": True, "message": "禁用策略成功"}
        except Exception as e:
            logger.exception(f"禁用策略失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("init_strategy")
    async def _req_init_strategy(self, data: dict) -> dict:
        """
        处理初始化策略请求
        调用策略的 init() 方法
        """
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        try:
            strategy = self.trader.strategy_manager.strategies.get(strategy_id)
            if not strategy:
                return {"success": False, "message": f"策略 {strategy_id} 不存在"}
            self.trader.strategy_manager.init_strategy(strategy)
            logger.info(f"策略 [{strategy_id}] 初始化成功")
            return {"success": True, "message": "策略初始化成功"}
        except Exception as e:
            logger.exception(f"初始化策略失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("get_strategy_order_cmds")
    async def _req_get_strategy_order_cmds(self, data: dict) -> list:
        """处理获取策略报单指令历史请求"""
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return []

        if self.trader.trading_engine._order_cmd_executor is None:
            logger.warning(f"Trader [{self.account_id}] 报单指令执行器未初始化")
            return []

        try:
            strategy_id = data.get("strategy_id")
            status_filter = data.get("status")

            if not strategy_id:
                return []

            cmds = self.trader.trading_engine._order_cmd_executor.get_hist_cmds()

            # 按策略ID过滤
            prefix = f"策略-{strategy_id}"
            filtered_cmds = []
            for cmd in cmds.values():
                if cmd.source and cmd.source.startswith(prefix):
                    # 按状态过滤
                    if status_filter == "active":
                        if cmd.is_active:
                            filtered_cmds.append(cmd)
                    elif status_filter == "finished":
                        if cmd.is_finished:
                            filtered_cmds.append(cmd)
                    else:
                        filtered_cmds.append(cmd)

            return [cmd.to_dict() for cmd in filtered_cmds]
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 获取策略报单指令失败: {e}")
            return []

    @request("send_strategy_order_cmd")
    async def _req_send_strategy_order_cmd(self, data: dict) -> dict:
        """处理发送策略报单指令请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        order_cmd_data = data.get("order_cmd")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}
        if not order_cmd_data:
            return {"success": False, "message": "缺少 order_cmd"}

        strategy = self.trader.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            from qtrader.models.object import Direction, Offset
            from qtrader.trader.order_cmd import OrderCmd

            order_cmd = OrderCmd(
                symbol=order_cmd_data["symbol"],
                direction=Direction(order_cmd_data["direction"]),
                offset=Offset(order_cmd_data["offset"]),
                volume=order_cmd_data["volume"],
                price=order_cmd_data.get("price", 0),
                source=f"手动-{strategy_id}",
            )

            await strategy.send_order_cmds([order_cmd])
            logger.info(
                f"策略 [{strategy_id}] 已发送报单指令: {order_cmd.symbol} {order_cmd.direction} {order_cmd.offset} {order_cmd.volume}手"
            )
            return {"success": True, "cmd_id": order_cmd.cmd_id}
        except Exception as e:
            logger.exception(f"发送策略报单指令失败: {e}")
            return {"success": False, "message": f"发送失败: {str(e)}"}

    @request("send_order_cmd")
    async def _req_send_order_cmd(self, data: dict) -> dict:
        """处理发送账户级报单指令请求（手动平仓等，不依赖策略）"""
        engine = self.trader.trading_engine
        if engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

        order_cmd_data = data.get("order_cmd")
        if not order_cmd_data:
            return {"success": False, "message": "缺少 order_cmd"}

        try:
            from qtrader.models.object import Direction, Offset
            from qtrader.trader.order_cmd import OrderCmd

            max_split_volume = 5
            if engine.risk_control and engine.risk_control.config:
                max_split_volume = engine.risk_control.config.max_split_volume

            order_cmd = OrderCmd(
                symbol=order_cmd_data["symbol"],
                direction=Direction(order_cmd_data["direction"]),
                offset=Offset(order_cmd_data["offset"]),
                volume=order_cmd_data["volume"],
                price=order_cmd_data.get("price", 0),
                max_volume_per_order=max_split_volume,
                source="手动平仓",
            )

            engine.insert_order_cmd(order_cmd)
            logger.info(
                f"账户 [{self.trader.account_id}] 已发送报单指令: "
                f"{order_cmd.symbol} {order_cmd.direction} {order_cmd.offset} {order_cmd.volume}手"
            )
            return {"success": True, "cmd_id": order_cmd.cmd_id}
        except Exception as e:
            logger.exception(f"发送报单指令失败: {e}")
            return {"success": False, "message": f"发送失败: {str(e)}"}

    def _build_strategy_config(self, strategy) -> dict:
        """构建策略配置对象"""
        from qtrader.manager.api.schemas import StrategyConfig

        config = strategy.config
        params = strategy.get_params()
        strategy_config = StrategyConfig(
            enabled=config.get("enabled", True),
            strategy_type=config.get("type", "bar"),
            symbol=config.get("symbol", ""),
            exchange=config.get("exchange", ""),
            volume_per_trade=config.get("volume_per_trade", config.get("volume", 1)),
            max_position=config.get("max_position", 5),
            bar=config.get("bar"),
            params_file=config.get("params_file"),
            take_profit_pct=config.get("take_profit_pct", config.get("TpRet")),
            stop_loss_pct=config.get("stop_loss_pct", config.get("SlRet")),
            fee_rate=config.get("fee_rate"),
            trade_start_time=config.get("trade_start_time", config.get("StartTime")),
            trade_end_time=config.get("trade_end_time", config.get("EndTime")),
            force_exit_time=config.get("force_exit_time", config.get("ForceExitTime")),
            one_trade_per_day=config.get("one_trade_per_day"),
            rsi_period=config.get("rsi_period"),
            rsi_long_threshold=config.get("rsi_long_threshold"),
            rsi_short_threshold=config.get("rsi_short_threshold"),
            short_kline_period=config.get("short_kline_period"),
            long_kline_period=config.get("long_kline_period"),
            dir_threshold=config.get("dir_threshold", config.get("DirThr")),
            used_signal=config.get("used_signal", config.get("UsedSignal")),
        )
        return strategy_config.model_dump()

    # ========== 换仓管理请求处理 ==========

    @request("get_rotation_instructions")
    async def _req_get_rotation_instructions(self, data: dict) -> dict:
        """处理获取换仓指令列表请求"""
        instructions = self.trader.switchPos_manager.get_today_instructions()
        rotation_status = {"working": False, "is_manual": False}
        if self.trader.switchPos_manager:
            rotation_status = {
                "working": self.trader.switchPos_manager.working,
                "is_manual": self.trader.switchPos_manager.is_manual,
            }

        result = []
        for ins in instructions:
            # 计算进行中手数（当前挂单中尚未成交的手数）
            pending_volume = 0
            if ins.current_order_id and ins.status == "RUNNING":
                cmd_dict = self.trader.trading_engine.get_order_cmd(ins.current_order_id)
                if cmd_dict:
                    pending_volume = cmd_dict.get("pending_volume", 0)

            result.append(
                {
                    "id": ins.id,
                    "account_id": ins.account_id,
                    "strategy_id": ins.strategy_id,
                    "symbol": ins.symbol,
                    "offset": ins.offset,
                    "direction": ins.direction,
                    "volume": ins.volume,
                    "filled_volume": ins.filled_volume,
                    "pending_volume": pending_volume,
                    "price": ins.price,
                    "order_time": ins.order_time,
                    "trading_date": ins.trading_date,
                    "enabled": ins.enabled,
                    "status": ins.status,
                    "attempt_count": ins.attempt_count,
                    "remaining_attempts": ins.remaining_attempts,
                    "remaining_volume": ins.remaining_volume,
                    "current_order_id": ins.current_order_id,
                    "order_placed_time": (
                        ins.order_placed_time.isoformat() if ins.order_placed_time else None
                    ),
                    "last_attempt_time": (
                        ins.last_attempt_time.isoformat() if ins.last_attempt_time else None
                    ),
                    "error_message": ins.error_message,
                    "source": ins.source,
                    "created_at": ins.created_at.isoformat() if ins.created_at else None,
                    "updated_at": ins.updated_at.isoformat() if ins.updated_at else None,
                }
            )

        return {
            "instructions": result,
            "rotation_status": rotation_status,
        }

    @request("get_rotation_instruction")
    async def _req_get_rotation_instruction(self, data: dict) -> dict | None:
        """处理获取指定换仓指令请求"""

        instruction_id = data.get("instruction_id")
        instructions = self.trader.switchPos_manager.get_today_instructions()
        instruction = next((x for x in instructions if x.id == instruction_id), None)
        if not instruction:
            return None

        return {
            "id": instruction.id,
            "account_id": instruction.account_id,
            "strategy_id": instruction.strategy_id,
            "symbol": instruction.symbol,
            "exchange_id": instruction.exchange_id,
            "offset": instruction.offset,
            "direction": instruction.direction,
            "volume": instruction.volume,
            "filled_volume": instruction.filled_volume,
            "price": instruction.price,
            "order_time": instruction.order_time,
            "trading_date": instruction.trading_date,
            "enabled": instruction.enabled,
            "status": instruction.status,
            "attempt_count": instruction.attempt_count,
            "remaining_attempts": instruction.remaining_attempts,
            "remaining_volume": instruction.remaining_volume,
            "current_order_id": instruction.current_order_id,
            "order_placed_time": (
                instruction.order_placed_time.isoformat() if instruction.order_placed_time else None
            ),
            "last_attempt_time": (
                instruction.last_attempt_time.isoformat() if instruction.last_attempt_time else None
            ),
            "error_message": instruction.error_message,
            "source": instruction.source,
            "created_at": (instruction.created_at.isoformat() if instruction.created_at else None),
            "updated_at": (instruction.updated_at.isoformat() if instruction.updated_at else None),
        }

    @request("update_rotation_instruction")
    async def _req_update_rotation_instruction(self, data: dict) -> dict | None:
        """处理更新换仓指令请求"""
        instruction_id = data.get("instruction_id")
        if not instruction_id:
            return False

        instruction = self.trader.switchPos_manager.update_instruction(data)
        return instruction

    @request("import_rotation_instructions")
    async def _req_import_rotation_instructions(self, data: dict) -> dict:
        """处理批量导入换仓指令请求"""
        csv_text = data.get("csv_text")
        filename = data.get("filename")
        mode = data.get("mode", "append")

        if self.trader.switchPos_manager:
            return self.trader.switchPos_manager.import_csv(csv_text, filename, mode)
        return {"imported": 0, "skipped": 0, "errors": []}

    @request("execute_rotation")
    async def _req_execute_rotation(self, data: dict) -> bool:
        """处理执行换仓请求"""
        if self.trader.switchPos_manager is None:
            return False

        async def execute():
            try:
                logger.info(f"Trader [{self.account_id}] 换仓任务执行开始")
                await self.trader.switchPos_manager.execute_position_rotation(is_manual=True)
                logger.info(f"Trader [{self.account_id}] 换仓任务执行完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 后台换仓任务执行失败: {e}")

        asyncio.create_task(execute())
        return True

    @request("stop_rotation")
    async def _req_stop_rotation(self, data: dict) -> bool:
        """处理停止换仓请求"""
        if self.trader.switchPos_manager is None:
            return False
        self.trader.switchPos_manager.stop_rotation()
        return True

    @request("batch_delete_instructions")
    async def _req_batch_delete_instructions(self, data: dict) -> dict:
        """处理批量删除换仓指令请求"""
        ids = data.get("ids", [])
        self.trader.switchPos_manager.delete_instruction(ids)
        return {"deleted": len(ids)}

    # ========== 目标仓位换仓请求处理 ==========

    @request("get_target_instructions")
    async def _req_get_target_instructions(self, data: dict) -> dict:
        """处理获取目标仓位指令列表请求"""
        if self.trader.targetPos_manager is None:
            return {"instructions": [], "rotation_status": {"working": False, "is_manual": False}}
        instructions = self.trader.targetPos_manager.get_today_instructions()
        return {
            "instructions": instructions,
            "rotation_status": {
                "working": self.trader.targetPos_manager.working,
                "is_manual": self.trader.targetPos_manager.is_manual,
            },
        }

    @request("import_target_instructions")
    async def _req_import_target_instructions(self, data: dict) -> dict:
        """处理导入目标仓位文件请求"""
        if self.trader.targetPos_manager is None:
            return {"imported": 0, "skipped": False, "errors": []}
        csv_text = data.get("csv_text", "")
        filename = data.get("filename", "")
        if not csv_text or not filename:
            return {"imported": 0, "skipped": False, "errors": ["缺少 csv_text 或 filename"]}
        try:
            return self.trader.targetPos_manager.import_target_file(csv_text, filename)
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 导入目标仓位文件失败: {e}")
            return {"imported": 0, "skipped": False, "errors": [str(e)]}

    @request("execute_target_position")
    async def _req_execute_target_position(self, data: dict) -> bool:
        """处理执行目标仓位换仓请求"""
        if self.trader.targetPos_manager is None:
            return False

        async def execute():
            try:
                logger.info(f"Trader [{self.account_id}] 目标仓位换仓开始")
                await self.trader.targetPos_manager.execute_target_position(is_manual=True)
                logger.info(f"Trader [{self.account_id}] 目标仓位换仓完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 目标仓位换仓失败: {e}")

        asyncio.create_task(execute())
        return True

    @request("stop_target_position")
    async def _req_stop_target_position(self, data: dict) -> bool:
        """处理停止目标仓位换仓请求"""
        if self.trader.targetPos_manager is None:
            return False
        self.trader.targetPos_manager.stop_target_position()
        return True

    @request("batch_delete_target_instructions")
    async def _req_batch_delete_target_instructions(self, data: dict) -> dict:
        """处理批量删除目标仓位指令请求"""
        if self.trader.targetPos_manager is None:
            return {"deleted": 0}
        ids = data.get("ids", []) or []
        deleted = self.trader.targetPos_manager.delete_instructions(ids)
        return {"deleted": deleted}

    @request("update_target_instruction")
    async def _req_update_target_instruction(self, data: dict) -> dict | None:
        """处理更新目标仓位指令请求（启用/禁用、目标手数）"""
        if self.trader.targetPos_manager is None:
            return None
        try:
            return self.trader.targetPos_manager.update_instruction(data)
        except ValueError as e:
            # 业务校验失败（如执行中禁止修改）需将错误信息带回页面，不触发 DB 回退
            return {"error": str(e)}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 更新目标仓位指令失败: {e}")
            return None

    # ========== 系统参数请求处理 ==========

    @request("list_system_params")
    async def _req_list_system_params(self, data: dict) -> list:
        """处理获取系统参数列表请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        group = data.get("group")

        with db.get_session() as session:
            query = session.query(SystemParamPo).filter(
                (SystemParamPo.account_id == self.account_id) | (SystemParamPo.account_id.is_(None))
            )

            if group:
                query = query.filter(SystemParamPo.group == group)

            params = query.order_by(SystemParamPo.group, SystemParamPo.param_key).all()

            return [
                {
                    "id": param.id,
                    "param_key": param.param_key,
                    "param_value": param.param_value,
                    "param_type": param.param_type,
                    "description": param.description,
                    "group": param.group,
                    "created_at": param.created_at.isoformat() if param.created_at else None,
                    "updated_at": param.updated_at.isoformat() if param.updated_at else None,
                }
                for param in params
            ]

    @request("get_system_param")
    async def _req_get_system_param(self, data: dict) -> dict | None:
        """处理获取单个系统参数请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.param_key == param_key,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .first()
            )

            if param:
                return {
                    "id": param.id,
                    "param_key": param.param_key,
                    "param_value": param.param_value,
                    "param_type": param.param_type,
                    "description": param.description,
                    "group": param.group,
                    "updated_at": param.updated_at.isoformat() if param.updated_at else None,
                }
        return None

    @request("update_system_param")
    async def _req_update_system_param(self, data: dict) -> dict | None:
        """处理更新系统参数请求"""
        from datetime import datetime

        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")
        param_value = data.get("param_value")

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.param_key == param_key,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .first()
            )

            if not param:
                return None

            param.param_value = param_value
            param.updated_at = datetime.now()

            session.commit()
            session.refresh(param)

            logger.info(f"Trader [{self.account_id}] 系统参数已更新: {param_key} = {param_value}")

            return {
                "id": param.id,
                "param_key": param.param_key,
                "param_value": param.param_value,
                "param_type": param.param_type,
                "description": param.description,
                "group": param.group,
                "updated_at": param.updated_at.isoformat() if param.updated_at else None,
            }

    @request("get_system_params_by_group")
    async def _req_get_system_params_by_group(self, data: dict) -> dict | None:
        """处理根据分组获取系统参数请求"""
        from qtrader.models.po import SystemParamPo
        from qtrader.utils.database import get_database

        db = get_database()
        group = data.get("group")

        with db.get_session() as session:
            params = (
                session.query(SystemParamPo)
                .filter(
                    SystemParamPo.group == group,
                    (SystemParamPo.account_id == self.account_id)
                    | (SystemParamPo.account_id.is_(None)),
                )
                .all()
            )

            result = {param.param_key: param.param_value for param in params}
            return result

    @request("pause_trading")
    async def _req_pause_trading(self, data: dict) -> dict:
        """处理暂停交易请求"""
        self.trader.trading_engine.paused = True
        return True

    @request("resume_trading")
    async def _req_resume_trading(self, data: dict) -> dict:
        """处理恢复交易请求"""
        self.trader.trading_engine.paused = False
        return True

    @request("update_alert_wechat")
    async def _req_update_alert_wechat(self, data: dict) -> dict:
        """处理更新微信告警配置请求（已废弃，请使用 update_alert_config）"""
        alert_wechat = data.get("alert_wechat", False)
        self.trader.account_config.alert.immediate = alert_wechat
        self.trader.account_config.alert.threshold = alert_wechat
        logger.warning(
            f"Trader [{self.account_id}] update_alert_wechat 已废弃，请使用 update_alert_config"
        )
        logger.info(
            f"Trader [{self.account_id}] 告警配置已更新: immediate={alert_wechat}, threshold={alert_wechat}"
        )
        return {"alert_wechat": alert_wechat}

    @request("get_alert_wechat")
    async def _req_get_alert_wechat(self, data: dict) -> dict:
        """处理获取微信告警配置请求（已废弃，请使用 get_alert_config）"""
        logger.warning(
            f"Trader [{self.account_id}] get_alert_wechat 已废弃，请使用 get_alert_config"
        )
        legacy_value = (
            self.trader.account_config.alert.immediate or self.trader.account_config.alert.threshold
        )
        return {"alert_wechat": legacy_value}

    @request("update_alert_config")
    async def _req_update_alert_config(self, data: dict) -> dict:
        """处理更新告警配置请求"""
        immediate = data.get("immediate")
        threshold = data.get("threshold")
        threshold_count = data.get("threshold_count")
        threshold_window = data.get("threshold_window")
        dnd_start = data.get("dnd_start")
        dnd_end = data.get("dnd_end")

        if immediate is not None:
            self.trader.account_config.alert.immediate = immediate
        if threshold is not None:
            self.trader.account_config.alert.threshold = threshold
        if threshold_count is not None:
            self.trader.account_config.alert.threshold_count = threshold_count
        if threshold_window is not None:
            self.trader.account_config.alert.threshold_window = threshold_window
        if dnd_start is not None:
            self.trader.account_config.alert.dnd_start = dnd_start
        if dnd_end is not None:
            self.trader.account_config.alert.dnd_end = dnd_end

        logger.info(
            f"Trader [{self.account_id}] 告警配置已更新: "
            f"immediate={self.trader.account_config.alert.immediate}, "
            f"threshold={self.trader.account_config.alert.threshold}, "
            f"threshold_count={self.trader.account_config.alert.threshold_count}, "
            f"threshold_window={self.trader.account_config.alert.threshold_window}, "
            f"dnd={self.trader.account_config.alert.dnd_start}-{self.trader.account_config.alert.dnd_end}"
        )
        return {
            "immediate": self.trader.account_config.alert.immediate,
            "threshold": self.trader.account_config.alert.threshold,
            "threshold_count": self.trader.account_config.alert.threshold_count,
            "threshold_window": self.trader.account_config.alert.threshold_window,
            "dnd_start": self.trader.account_config.alert.dnd_start,
            "dnd_end": self.trader.account_config.alert.dnd_end,
        }

    @request("get_alert_config")
    async def _req_get_alert_config(self, data: dict) -> dict:
        """处理获取告警配置请求"""
        return {
            "immediate": self.trader.account_config.alert.immediate,
            "threshold": self.trader.account_config.alert.threshold,
            "threshold_count": self.trader.account_config.alert.threshold_count,
            "threshold_window": self.trader.account_config.alert.threshold_window,
            "dnd_start": self.trader.account_config.alert.dnd_start,
            "dnd_end": self.trader.account_config.alert.dnd_end,
        }

    @request("get_rotation_config")
    async def _req_get_rotation_config(self, data: dict) -> dict:
        """处理获取换仓开关配置请求"""
        cfg = self.trader.account_config
        return {
            "enable_instruction_rotation": cfg.enable_instruction_rotation,
            "enable_target_pos_rotation": cfg.enable_target_pos_rotation,
        }

    @request("update_rotation_config")
    async def _req_update_rotation_config(self, data: dict) -> dict:
        """处理更新换仓开关请求（内存即时生效，并持久化到账户配置文件）"""
        from qtrader.utils.config_loader import get_config_loader

        cfg = self.trader.account_config
        fields: dict[str, bool] = {}
        if data.get("enable_instruction_rotation") is not None:
            cfg.enable_instruction_rotation = bool(data["enable_instruction_rotation"])
            fields["enable_instruction_rotation"] = cfg.enable_instruction_rotation
        if data.get("enable_target_pos_rotation") is not None:
            cfg.enable_target_pos_rotation = bool(data["enable_target_pos_rotation"])
            fields["enable_target_pos_rotation"] = cfg.enable_target_pos_rotation

        if fields and self.account_id:
            for key, value in fields.items():
                get_config_loader().update_account_config_field(self.account_id, key, value)
            logger.info(f"Trader [{self.account_id}] 换仓开关已更新: {fields}")

        return {
            "enable_instruction_rotation": cfg.enable_instruction_rotation,
            "enable_target_pos_rotation": cfg.enable_target_pos_rotation,
        }

    @request("export_positions")
    async def _req_export_positions(self, data: dict) -> dict:
        """
        处理导出持仓请求

        调用 JobManager 的 post_market_export 导出本账户持仓到 CSV。
        """
        if self.trader.job_manager is None:
            logger.error(f"Trader [{self.account_id}] 作业管理器未初始化")
            return {"success": False, "message": "作业管理器未初始化"}

        try:
            await self.trader.job_manager.post_market_export()
            return {"success": True, "message": "持仓导出成功"}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 导出持仓失败: {e}")
            return {"success": False, "message": f"导出失败: {str(e)}"}

    @request("refresh_contracts")
    async def _req_refresh_contracts(self, data: dict) -> dict:
        """
        处理强制刷新合约信息请求

        Returns:
            {"success": bool, "message": str}
        """
        if self.trader.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return {"success": False, "message": "交易引擎未初始化"}

        try:
            success = self.trader.trading_engine.refresh_contracts()
            if success:
                logger.info(f"Trader [{self.account_id}] 合约信息刷新成功")
                return {"success": True, "message": "合约信息刷新成功"}
            else:
                logger.warning(f"Trader [{self.account_id}] 合约信息刷新失败")
                return {"success": False, "message": "合约信息刷新失败，请检查网关连接状态"}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 刷新合约信息失败: {e}")
            return {"success": False, "message": f"刷新失败: {str(e)}"}

    @request("init_public_data")
    async def _req_init_public_data(self, data: dict) -> dict:
        """
        接收 Manager 推送的公共数据（合约信息）

        Manager 在检测到本 Trader 进程启动后，会从共享数据库中读取合约信息
        并通过此请求推送过来，Trader 将数据加载到 Gateway 的合约缓存中。

        Args:
            data: {"contracts": [{合约信息字典}, ...]}

        Returns:
            {"success": bool, "message": str, "count": int}
        """
        contracts = data.get("contracts", [])
        if not contracts:
            logger.info(f"Trader [{self.account_id}] 收到空的公共数据推送")
            self.trader._public_data_initialized = True
            if self.trader._init_data_future and not self.trader._init_data_future.done():
                self.trader._init_data_future.set_result(True)
            return {"success": True, "message": "无合约数据", "count": 0}

        try:
            # 将合约数据加载到 Gateway
            if self.trader.trading_engine and self.trader.trading_engine.gateway:
                count = self.trader.trading_engine.gateway.load_contracts_from_init_data(contracts)
                self.trader._public_data_initialized = True
                # 唤醒等待中的 _wait_for_init_data
                if self.trader._init_data_future and not self.trader._init_data_future.done():
                    self.trader._init_data_future.set_result(True)
                logger.info(f"Trader [{self.account_id}] 已从 Manager 加载 {count} 个合约信息")
                return {"success": True, "message": "合约数据已加载", "count": count}
            else:
                logger.warning(
                    f"Trader [{self.account_id}] 交易引擎或 Gateway 未初始化，无法加载合约数据"
                )
                return {"success": False, "message": "交易引擎未初始化", "count": 0}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 加载公共数据失败: {e}")
            return {"success": False, "message": f"加载失败: {str(e)}", "count": 0}
