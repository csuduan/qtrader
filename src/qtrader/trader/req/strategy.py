"""
策略管理请求处理（含定时任务查询/触发）
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from qtrader.trader.req.base import BaseReqHandler
from qtrader.utils.ipc import request
from qtrader.utils.logger import get_logger

if TYPE_CHECKING:
    from qtrader.trader.strategy.base_strategy import BaseStrategy

logger = get_logger(__name__)


class StrategyReqHandler(BaseReqHandler):
    def _calc_position_profit(
        self, strategy: BaseStrategy, symbol: str, last_price: float
    ) -> float:
        """计算策略持仓盈亏"""
        position = strategy.get_position(symbol)
        if not position or last_price <= 0:
            return 0.0

        multiple = position.multiple or 0

        # 计算多头持仓盈亏
        long_profit = 0.0
        if position.pos_long > 0 and cast(float, position.hold_price_long) > 0:
            long_profit = (
                (last_price - cast(float, position.hold_price_long)) * position.pos_long * multiple
            )

        # 计算空头持仓盈亏
        short_profit = 0.0
        if position.pos_short > 0 and cast(float, position.hold_price_short) > 0:
            short_profit = (
                (cast(float, position.hold_price_short) - last_price)
                * position.pos_short
                * multiple
            )

        return long_profit + short_profit

    @request("list_strategies")
    async def _req_list_strategies(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """处理获取策略列表请求"""
        if self.trader.strategy_manager is None:
            return []
        from qtrader.trader.req.schemas import StrategyPositionRes, StrategyRes
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
                    last_price = (tick.last_price if tick else 0.0) or 0.0
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
    async def _req_get_strategy(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """处理获取指定策略状态请求"""
        if self.trader.strategy_manager is None:
            return None
        from qtrader.trader.req.schemas import StrategyPositionRes, StrategyRes
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
                    last_price = (tick.last_price if tick else 0.0) or 0.0
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
    async def _req_replay_all_strategies(self, data: dict[str, Any]) -> dict[str, Any]:
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
            logger.exception("回播策略失败")
            return {"success": False, "message": f"回播策略失败: {e}"}

    @request("update_strategy_params")
    async def _req_update_strategy_params(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理更新策略参数请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("更新策略参数失败")
            return {"success": False, "message": f"更新失败: {e}"}

    @request("update_strategy_signal")
    async def _req_update_strategy_signal(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理更新策略信号请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("更新策略信号失败")
            return {"success": False, "message": f"更新失败: {e}"}

    @request("clear_strategy_signal")
    async def _req_clear_strategy_signal(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理清除策略信号请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("清除策略信号失败")
            return {"success": False, "message": f"清除失败: {e}"}

    @request("update_strategy_position_detail")
    async def _req_update_strategy_position_detail(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理更新策略持仓详情请求（单个合约）"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("更新策略持仓详情失败")
            return {"success": False, "message": f"更新失败: {e}"}

    @request("delete_strategy_position")
    async def _req_delete_strategy_position(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理删除策略持仓请求（清空单个合约持仓）"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
                    await service.clear_position(account_id, strategy_id, symbol)

            logger.info(f"策略 [{strategy_id}] {symbol} 持仓已删除")
            return {"success": True, "message": "持仓已删除"}
        except Exception as e:
            logger.exception("删除策略持仓失败")
            return {"success": False, "message": f"删除失败: {e}"}

    @request("set_strategy_trading_status")
    async def _req_set_strategy_trading_status(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理设置策略交易状态请求（统一接口）

        支持同时设置开仓和平仓状态：
        - opening_paused: 暂停/恢复开仓
        - closing_paused: 暂停/恢复平仓
        """
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("设置策略交易状态失败")
            return {"success": False, "message": f"操作失败: {e}"}

    @request("enable_strategy")
    async def _req_enable_strategy(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理启用策略请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("启用策略失败")
            return {"success": False, "message": f"操作失败: {e}"}

    @request("disable_strategy")
    async def _req_disable_strategy(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理禁用策略请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("禁用策略失败")
            return {"success": False, "message": f"操作失败: {e}"}

    @request("init_strategy")
    async def _req_init_strategy(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        处理初始化策略请求
        调用策略的 init() 方法
        """
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        try:
            strategy = self.trader.strategy_manager.strategies.get(strategy_id)
            if not strategy:
                return {"success": False, "message": f"策略 {strategy_id} 不存在"}
            await self.trader.strategy_manager.init_strategy(strategy)
            logger.info(f"策略 [{strategy_id}] 初始化成功")
            return {"success": True, "message": "策略初始化成功"}
        except Exception as e:
            logger.exception("初始化策略失败")
            return {"success": False, "message": f"操作失败: {e}"}

    @request("get_strategy_order_cmds")
    async def _req_get_strategy_order_cmds(self, data: dict[str, Any]) -> list[dict[str, Any]]:
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
        except Exception:
            logger.exception("Trader [{}] 获取策略报单指令失败", self.account_id)
            return []

    @request("send_strategy_order_cmd")
    async def _req_send_strategy_order_cmd(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理发送策略报单指令请求"""
        if self.trader.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}
        if self.trader.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

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
            logger.exception("发送策略报单指令失败")
            return {"success": False, "message": f"发送失败: {e}"}

    @request("send_order_cmd")
    async def _req_send_order_cmd(self, data: dict[str, Any]) -> dict[str, Any]:
        """处理发送账户级报单指令请求（手动报单/平仓等，不依赖策略）"""
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
                source=order_cmd_data.get("source") or "手动报单",
            )

            engine.insert_order_cmd(order_cmd)
            logger.info(
                f"账户 [{self.trader.account_id}] 已发送报单指令: "
                f"{order_cmd.symbol} {order_cmd.direction} {order_cmd.offset} {order_cmd.volume}手"
            )
            return {"success": True, "cmd_id": order_cmd.cmd_id}
        except Exception as e:
            logger.exception("发送报单指令失败")
            return {"success": False, "message": f"发送失败: {e}"}
