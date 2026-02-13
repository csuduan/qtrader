"""
Trader交易执行器
运行在子进程中，负责交易执行、策略运行、行情处理
"""

import asyncio
import signal
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.app_context import AppContext, get_app_context
from src.trader.alarm_handler import TraderAlarmHandler
from src.trader.job_mgr import JobManager
from src.trader.strategy_manager import StrategyManager
from src.trader.trading_engine import TradingEngine
from src.trader.strategy import BaseStrategy,BaseParam
from src.trader.switch_mgr import SwitchPosManager
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.config_loader import TraderConfig
from src.utils.event_engine import EventTypes
from src.utils.ipc import SocketServer, request
from src.utils.logger import get_logger, logger
from src.utils.scheduler import TaskScheduler

logger = get_logger(__name__)
ctx = get_app_context()


class Trader:
    """
    Trader交易执行器

    职责：
    1. 连接TradingManager (Socket)
    2. 执行交易逻辑
    3. 运行策略
    4. 推送数据到Manager

    """

    def __init__(self, account_config: TraderConfig):
        """
        初始化Trader

        Args:
            account_config: 账户配置
            global_config: 全局配置
        """
        self.account_config = account_config
        self.account_id = account_config.account_id

        # 交易引擎
        self.trading_engine: Optional[TradingEngine] = None

        # 换仓管理器
        self.switchPos_manager: Optional[SwitchPosManager] = None

        # 作业管理器
        self.job_manager: Optional[JobManager] = None

        # 策略管理器
        self.strategy_manager: Optional[StrategyManager] = None

        # 任务调度器
        self.task_scheduler: Optional[TaskScheduler] = None

        # Socket服务器（独立模式）
        self.socket_server: Optional[SocketServer] = None
        self._server_task: Optional[asyncio.Task] = None

        # 运行状态
        self._running = False

    async def start(
        self,
        socket_path: Optional[str] = None,
    ) -> None:
        """
        启动Trader

        Args:
            socket_path: Socket路径（独立进程模式）
        """
        self._running = True
        # 保存socket路径供_run_standalone使用
        self._socket_path = socket_path or self.account_config.socket.socket_dir

        logger.info(f"Trader [{self.account_id}] 开始启动...")

        # 初始化数据库（检查并创建）
        await self._init_database()

        # 注册事件处理器
        self._register_event_handlers()

        # 启动Socket服务器
        self.socket_server = SocketServer(self._socket_path, self.account_id)
        self.socket_server.register_handlers_from_instance(self)
        self._server_task = asyncio.create_task(self.socket_server.start())
        await asyncio.sleep(0.2)
        logger.info(f"Trader [{self.account_id}] SocketServer已启动，继续初始化...")

        # 启用Trader端告警处理器
        alarm_handler = TraderAlarmHandler(self.account_id, self.socket_server)
        logger.add(lambda msg: asyncio.create_task(alarm_handler(msg)), level="ERROR")
        logger.info(f"Trader [{self.account_id}] 告警处理器已启用")

        # 启动交易引擎
        self.trading_engine = TradingEngine(self.account_config)
        await self.trading_engine.start()

        # 启动换仓管理器、作业管理器
        self.switchPos_manager = SwitchPosManager(self.account_config, self.trading_engine)
        ctx.register(AppContext.KEY_SWITCH_POS_MANAGER, self.switchPos_manager)
        self.switchPos_manager.start()
        # 启动任务调度器及作业管理器
        self.job_manager = JobManager(
            self.account_config, self.trading_engine, self.switchPos_manager, self.socket_server
        )
        if self.account_config.scheduler:
            self.task_scheduler = TaskScheduler(self.account_config.scheduler, self.job_manager)
            self.task_scheduler.start()
            logger.info(f"Trader [{self.account_id}] 任务调度器已启动")
        else:
            logger.info(f"Trader [{self.account_id}] 未配置任务调度器")

        # 启动策略管理器
        self.strategy_manager = StrategyManager(
                self.account_config.strategies, self.trading_engine
            )
        ctx.register(AppContext.KEY_STRATEGY_MANAGER, self.strategy_manager)
        await self.strategy_manager.start()

        # 保持运行
        logger.info("=" * 60)
        logger.info(f"Trader [{self.account_id}] 启动成功，持续运行中...")
        logger.info("=" * 60)

        # 等待服务器任务（防止协程结束）
        try:
            await self._server_task
        except asyncio.CancelledError:
            logger.info(f"Trader [{self.account_id}] 服务器任务已取消")

    async def _init_database(self) -> None:
        """
        初始化数据库
        检查数据库文件是否存在，不存在则创建并初始化
        """
        from pathlib import Path

        from src.models.po import SystemParamPo
        from src.utils.config_loader import RiskControlConfig
        from src.utils.database import get_database, init_database

        # 构建数据库文件路径
        db_file = self.account_config.paths.database
        # 检查数据库文件是否存在
        path = Path(db_file)
        if not path.exists():
            logger.info(f"Trader [{self.account_id}] 数据库文件不存在，开始初始化...")

            # 初始化数据库（会自动创建表）
            db = init_database(db_file, account_id=self.account_id, echo=False)

            # 初始化系统参数
            with db.get_session() as session:
                params = []
                risk_control = RiskControlConfig()

                params.append(
                    SystemParamPo(
                        param_key="risk_control.max_daily_orders",
                        param_value=str(risk_control.max_daily_orders),
                        param_type="integer",
                        description="每日最大报单数量",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        param_key="risk_control.max_daily_cancels",
                        param_value=str(risk_control.max_daily_cancels),
                        param_type="integer",
                        description="每日最大撤单数量",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        param_key="risk_control.max_order_volume",
                        param_value=str(risk_control.max_order_volume),
                        param_type="integer",
                        description="单次最大报单手数",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        param_key="risk_control.max_split_volume",
                        param_value=str(risk_control.max_split_volume),
                        param_type="integer",
                        description="最大拆单手数",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        param_key="risk_control.order_timeout",
                        param_value=str(risk_control.order_timeout),
                        param_type="integer",
                        description="报单超时时间（秒）",
                        group="risk_control",
                    )
                )

                session.add_all(params)
                session.commit()

            logger.info(f"Trader [{self.account_id}] 数据库初始化完成")
        else:
            logger.info(f"Trader [{self.account_id}] 数据库文件已存在: {db_file}")
            # 数据库文件已存在，只需连接
            init_database(db_file, account_id=self.account_id, echo=False)

    def get_task_scheduler(self) -> Optional[TaskScheduler]:
        """获取任务调度器"""
        return self.task_scheduler

    async def _heartbeat_loop(self, interval: int = 5) -> None:
        """
        心跳循环

        Args:
            interval: 心跳间隔（秒）
        """
        while self._running:
            try:
                await asyncio.sleep(interval)
                if self.socket_server:
                    await self.socket_server.send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Trader-{self.account_id}] 心跳发送失败: {e}")
                break

    async def _run_standalone(self) -> None:
        """Standalone模式：独立运行（用于测试）"""
        logger.info(f"Trader [{self.account_id}] 启动SocketServer服务。。。")

        # 启动socket，自动收集带 @request 装饰器的方法
        self.socket_server = SocketServer(self._socket_path, self.account_id)
        self.socket_server.register_handlers_from_instance(self)

        # 将服务器作为后台任务启动（方案1：后台任务）
        self._server_task = asyncio.create_task(self.socket_server.start())

        # 等待服务器就绪（短暂延迟或等待信号）
        await asyncio.sleep(0.2)

        # 继续执行后续初始化...
        logger.info(f"Trader [{self.account_id}] SocketServer已启动，继续初始化...")

        # 在这里启动交易引擎等其他组件
        # await self.trading_engine.start()

        # 等待服务器任务（防止协程结束）
        try:
            await self._server_task
        except asyncio.CancelledError:
            logger.info(f"Trader [{self.account_id}] 服务器任务已取消")

    async def _on_account_update(self, data):
        """账户更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_push("account", data.model_dump())
        else:
            logger.info(f"账户更新: {data}")

    async def _on_order_update(self, data):
        """订单更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_push("order", data.model_dump())
        else:
            logger.info(f"订单更新: {data}")

    async def _on_trade_update(self, data):
        """成交更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_push("trade", data.model_dump())
        else:
            logger.info(f"成交更新: {data}")

    async def _on_position_update(self, data):
        """持仓更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_push("position", data.model_dump())
        else:
            logger.info(f"持仓更新: {data}")

    async def _on_tick_update(self, data):
        """行情更新事件处理器"""
        if self.socket_server:
            # 行情数据不实时推送，按需订阅
            await self.socket_server.send_push("tick", data.model_dump())
            pass

    def _register_event_handlers(self) -> None:
        """
        注册事件处理器（推送到Manager）

        """
        # 注册到 AsyncEventEngine
        event_engine: AsyncEventEngine = ctx.get_event_engine()
        event_engine.register(EventTypes.ACCOUNT_UPDATE, self._on_account_update)
        event_engine.register(EventTypes.ACCOUNT_STATUS, self._on_account_update)
        event_engine.register(EventTypes.ORDER_UPDATE, self._on_order_update)
        event_engine.register(EventTypes.TRADE_UPDATE, self._on_trade_update)
        event_engine.register(EventTypes.POSITION_UPDATE, self._on_position_update)
        event_engine.register(EventTypes.TICK_UPDATE, self._on_tick_update)
        logger.info(f"Trader [{self.account_id}] 事件处理器已注册")

    async def stop(self) -> None:
        """停止Trader"""
        self._running = False
        logger.info(f"Trader [{self.account_id}] 停止中...")


        # 停止任务调度器
        if self.task_scheduler:
            self.task_scheduler.shutdown()

        # 断开连接
        if self.trading_engine:
            await self.trading_engine.disconnect()

        # 停止Socket服务器
        if self.socket_server:
            await self.socket_server.stop()

        # 清理PID文件和Socket文件
        if self._socket_path:
            socket_path = Path(self._socket_path)
            pid_file = socket_path.parent / f"qtrader_{self.account_id}.pid"
            try:
                pid_file.unlink(missing_ok=True)
                logger.info(f"已清理PID文件: {pid_file}")

                socket_path.unlink(missing_ok=True)
                logger.info(f"已清理Socket文件: {socket_path}")
            except Exception as e:
                logger.warning(f"清理PID/Socket文件失败: {e}")

        logger.info(f"Trader [{self.account_id}] 已停止")

    # ========== Socket请求处理方法 ==========

    @request("connect_gateway")
    async def _req_connect(self, data: dict) -> bool:
        """处理连接请求"""
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trading_engine.connect()
        logger.info(f"Trader [{self.account_id}] 连接成功")
        return True

    @request("disconnect_gateway")
    async def _req_disconnect(self, data: dict) -> bool:
        """处理断开连接请求"""
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        await self.trading_engine.disconnect()
        logger.info(f"Trader [{self.account_id}] 断开连接成功")
        return True

    @request("subscribe")
    async def _req_subscribe(self, data: dict) -> bool:
        """处理订阅请求"""
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None
        self.trading_engine.subscribe_symbol(data["symbol"])
        logger.info(f"Trader [{self.account_id}] 订阅{data['symbol']}成功")
        return True

    @request("unsubscribe")
    async def _req_unsubscribe(self, data: dict) -> bool:
        """处理取消订阅请求"""
        logger.info(f"Trader [{self.account_id}] 取消订阅成功")
        return True

    @request("order_req")
    async def _req_order(self, data: dict) -> Optional[str]:
        """
        处理下单请求

        Args:
            data: 包含 symbol, direction, offset, volume, price(可选)

        Returns:
            订单ID，失败返回None
        """
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None

        try:
            from src.models.object import Direction, Offset

            symbol = data["symbol"]
            direction = Direction(data["direction"])
            offset = Offset(data["offset"])
            volume = data["volume"]
            price = data.get("price", 0)

            order_id = self.trading_engine.insert_order(
                symbol=symbol,
                direction=direction.value,
                offset=offset.value,
                volume=volume,
                price=price,
            )

            logger.info(f"Trader [{self.account_id}] 下单成功: {order_id}")
            return order_id

        except Exception as e:
            logger.error(f"Trader [{self.account_id}] 下单失败: {e}")
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
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return False

        try:
            order_id = data["order_id"]
            success = self.trading_engine.cancel_order(order_id)

            if success:
                logger.info(f"Trader [{self.account_id}] 撤单成功: {order_id}")
            else:
                logger.warning(f"Trader [{self.account_id}] 撤单失败: {order_id}")

            return success

        except Exception as e:
            logger.error(f"Trader [{self.account_id}] 撤单失败: {e}")
            return False

    @request("get_account")
    async def _req_get_account(self, data: dict) -> Optional[dict]:
        """处理获取账户数据请求"""
        if self.trading_engine is None:
            return None
        account = self.trading_engine.account
        return account.model_dump()

    @request("get_order")
    async def _req_get_order(self, data: dict) -> Optional[dict]:
        """处理获取订单数据请求"""
        if self.trading_engine is None:
            return None
        order_id = data.get("order_id")
        if order_id:
            order = self.trading_engine.orders.get(order_id)
            if order:
                return order.model_dump()
        return None

    @request("get_orders")
    async def _req_get_orders(self, data: dict) -> list:
        """处理获取所有订单数据请求"""
        if self.trading_engine is None:
            return []
        orders = self.trading_engine.orders
        return [order.model_dump() for order in orders.values()]

    @request("get_active_orders")
    async def _req_get_active_orders(self, data: dict) -> list:
        """处理获取活动订单请求"""
        if self.trading_engine is None:
            return []
        orders = self.trading_engine.orders
        return [order.model_dump() for order in orders.values() if order.status == "ACTIVE"]

    @request("get_trade")
    async def _req_get_trade(self, data: dict) -> Optional[dict]:
        """处理获取成交数据请求"""
        if self.trading_engine is None:
            return None
        trade_id = data.get("trade_id")
        if trade_id:
            trade = self.trading_engine.trades.get(trade_id)
            if trade:
                return trade.model_dump()
        return None

    @request("get_trades")
    async def _req_get_trades(self, data: dict) -> list:
        """处理获取所有成交数据请求"""
        if self.trading_engine is None:
            return []
        trades = self.trading_engine.trades
        return [trade.model_dump() for trade in trades.values()]

    @request("get_positions")
    async def _req_get_positions(self, data: dict) -> list:
        """处理获取所有持仓数据请求"""
        if self.trading_engine is None:
            return []
        positions = self.trading_engine.positions
        return [pos.model_dump() for pos in positions.values()]

    @request("get_quotes")
    async def _req_get_quotes(self, data: dict) -> list:
        """处理获取行情请求"""
        if self.trading_engine is None:
            return []
        quotes = self.trading_engine.quotes
        return [quote.model_dump() for quote in quotes.values()]

    @request("get_order_cmds_status")
    async def _req_get_order_cmds_status(self, data: dict) -> Optional[list]:
        """
        处理获取报单指令状态请求

        支持状态过滤:
        - status="active" : 只返回未完成的活跃指令
        - status="finished" : 只返回已完成的指令
        - status=None: 返回所有指令

        Returns:
            执行器状态字典，失败返回None
        """
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return None

        if self.trading_engine._order_cmd_executor is None:
            logger.warning(f"Trader [{self.account_id}] 报单指令执行器未初始化")
            return None

        try:
            status_filter = data.get("status")
            cmds = self.trading_engine._order_cmd_executor.get_hist_cmds()
            if status_filter == "active":
                cmds = [cmd for cmd in cmds.values() if cmd.is_active]
            elif status_filter == "finished":
                cmds = [cmd for cmd in cmds.values() if cmd.is_finished]
            return [cmd.to_dict() for cmd in cmds]
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 获取报单指令状态失败: {e}")
            return None

    @request("get_jobs")
    async def _req_get_jobs(self, data: dict) -> list:
        """处理获取所有任务请求"""
        if self.trading_engine is None:
            return []
        jobs = self.task_scheduler.get_jobs()
        return [job.model_dump() for job in jobs.values()]

    @request("trigger_job")
    async def _req_trigger_job(self, data: dict) -> bool:
        """处理手动触发任务请求"""
        if self.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.task_scheduler.trigger_job(job_id)
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已触发: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 触发任务失败: {job_id}")
        return success

    @request("toggle_job")
    async def _req_toggle_job(self, data: dict) -> bool:
        """处理切换任务状态请求"""
        if self.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        enabled = data.get("enabled")
        if not job_id or enabled is None:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id 或 enabled")
            return False
        success = self.task_scheduler.update_job_status(job_id, enabled)
        if success:
            logger.info(f"Trader [{self.account_id}] 任务状态已更新: {job_id} -> {enabled}")
        else:
            logger.warning(f"Trader [{self.account_id}] 更新任务状态失败: {job_id}")
        return success

    @request("pause_job")
    async def _req_pause_job(self, data: dict) -> bool:
        """处理暂停任务请求"""
        if self.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.task_scheduler.operate_job(job_id, "pause")
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已暂停: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 暂停任务失败: {job_id}")
        return success

    @request("resume_job")
    async def _req_resume_job(self, data: dict) -> bool:
        """处理恢复任务请求"""
        if self.task_scheduler is None:
            logger.error(f"Trader [{self.account_id}] 任务调度器未初始化")
            return False
        job_id = data.get("job_id")
        if not job_id:
            logger.error(f"Trader [{self.account_id}] 缺少 job_id")
            return False
        success = self.task_scheduler.operate_job(job_id, "resume")
        if success:
            logger.info(f"Trader [{self.account_id}] 任务已恢复: {job_id}")
        else:
            logger.warning(f"Trader [{self.account_id}] 恢复任务失败: {job_id}")
        return success

    # ========== 策略管理请求处理 ==========
    @request("list_strategies")
    async def _req_list_strategies(self, data: dict) -> list:
        """处理获取策略列表请求"""
        if self.strategy_manager is None:
            return []
        from src.manager.api.schemas import StrategyRes

        result = []
        for strategy in self.strategy_manager.strategies.values():
            params = strategy.get_params()
            base_fields = set[str](BaseParam.model_fields.keys())
            ext_params = [p for p in params if p["key"] not in base_fields]
            base_params = [p for p in params if p["key"] in base_fields]
            strategy_res = StrategyRes(
                strategy_id=strategy.strategy_id,
                enabled=strategy.enabled,
                opening_paused=strategy.opening_paused,
                closing_paused=strategy.closing_paused,
                inited=strategy.inited,
                config=strategy.config.model_dump(),
                base_params=base_params,
                ext_params=ext_params,
                signal=strategy.get_signal(),
                pos_long=strategy.pos_long,
                pos_short=strategy.pos_short,
                pos_volume=strategy.pos_long - strategy.pos_short,
                pos_price=strategy.pos_price,
                trading_status=strategy.get_trading_status(),
            )
            result.append(strategy_res.model_dump())
        return result

    @request("get_strategy")
    async def _req_get_strategy(self, data: dict) -> Optional[dict]:
        """处理获取指定策略状态请求"""
        if self.strategy_manager is None:
            return None
        from src.manager.api.schemas import StrategyRes

        strategy_id = data.get("strategy_id")
        if strategy_id and strategy_id in self.strategy_manager.strategies:
            strategy = self.strategy_manager.strategies[strategy_id]
            params = strategy.get_params()
            base_fields = set[str](BaseParam.model_fields.keys())
            ext_params = [p for p in params if p["key"] not in base_fields]
            base_params = [p for p in params if p["key"] in base_fields]
            result = StrategyRes(
                strategy_id=strategy.strategy_id,
                enabled=strategy.enabled,
                opening_paused=strategy.opening_paused,
                closing_paused=strategy.closing_paused,
                inited=strategy.inited,
                config=strategy.config.model_dump(),
                base_params=base_params,
                ext_params=ext_params,
                signal=strategy.get_signal(),
                pos_long=strategy.pos_long,
                pos_short=strategy.pos_short,
                pos_volume=strategy.pos_long - strategy.pos_short,
                pos_price=strategy.pos_price,
                trading_status=strategy.get_trading_status(),
            )
            return result.model_dump()
        return None

    @request("replay_all_strategies")
    async def _req_replay_all_strategies(self, data: dict) -> dict:
        """处理回播所有策略请求"""
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        try:
            result = await self.strategy_manager.replay_all_strategies()
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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

    @request("set_strategy_trading_status")
    async def _req_set_strategy_trading_status(self, data: dict) -> dict:
        """
        处理设置策略交易状态请求（统一接口）

        支持同时设置开仓和平仓状态：
        - opening_paused: 暂停/恢复开仓
        - closing_paused: 暂停/恢复平仓
        """
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        status = data.get("status", {})
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            strategy.enable(False)
            return {"success": True, "message": "禁用策略成功"}
        except Exception as e:
            logger.exception(f"禁用策略失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("reload_strategy_params")
    async def _req_reload_strategy_params(self, data: dict) -> dict:
        """
        处理重载策略参数请求
        从配置文件重新加载策略参数
        """
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            from src.trader.strategy_manager import load_strategy_params
            # 从配置文件重新加载参数
            new_params = load_strategy_params(strategy.config, strategy_id)
            if new_params:
                strategy.update_params(new_params)
                logger.info(f"策略 [{strategy_id}] 参数已重载: {new_params}")
                return {"success": True, "message": "参数重载成功", "params": new_params}
            else:
                return {"success": False, "message": "未找到参数配置"}
        except Exception as e:
            logger.exception(f"重载策略参数失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("init_strategy")
    async def _req_init_strategy(self, data: dict) -> dict:
        """
        处理初始化策略请求
        调用策略的 init() 方法
        """
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            result = strategy.init(self.trading_engine.trading_day)
            if result:
                logger.info(f"策略 [{strategy_id}] 初始化成功")
                return {"success": True, "message": "策略初始化成功"}
            else:
                return {"success": False, "message": "策略初始化失败"}
        except Exception as e:
            logger.exception(f"初始化策略失败: {e}")
            return {"success": False, "message": f"操作失败: {str(e)}"}

    @request("get_strategy_order_cmds")
    async def _req_get_strategy_order_cmds(self, data: dict) -> list:
        """处理获取策略报单指令历史请求"""
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return []

        if self.trading_engine._order_cmd_executor is None:
            logger.warning(f"Trader [{self.account_id}] 报单指令执行器未初始化")
            return []

        try:
            strategy_id = data.get("strategy_id")
            status_filter = data.get("status")

            if not strategy_id:
                return []

            cmds = self.trading_engine._order_cmd_executor.get_hist_cmds()

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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        order_cmd_data = data.get("order_cmd")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}
        if not order_cmd_data:
            return {"success": False, "message": "缺少 order_cmd"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
        if not strategy:
            return {"success": False, "message": f"策略 {strategy_id} 不存在"}

        try:
            from src.models.object import Direction, Offset
            from src.trader.order_cmd import OrderCmd

            order_cmd = OrderCmd(
                symbol=order_cmd_data["symbol"],
                direction=Direction(order_cmd_data["direction"]),
                offset=Offset(order_cmd_data["offset"]),
                volume=order_cmd_data["volume"],
                price=order_cmd_data.get("price", 0),
                source=f"手动-{strategy_id}",
            )

            await strategy.send_order_cmd(order_cmd)
            logger.info(f"策略 [{strategy_id}] 已发送报单指令: {order_cmd.symbol} {order_cmd.direction} {order_cmd.offset} {order_cmd.volume}手")
            return {"success": True, "cmd_id": order_cmd.cmd_id}
        except Exception as e:
            logger.exception(f"发送策略报单指令失败: {e}")
            return {"success": False, "message": f"发送失败: {str(e)}"}

    def _build_strategy_config(self, strategy: BaseStrategy) -> dict:
        """构建策略配置对象"""
        from src.manager.api.schemas import StrategyConfig

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
        instructions = self.switchPos_manager.get_today_instructions()
        rotation_status = {"working": False, "is_manual": False}
        if self.switchPos_manager:
            rotation_status = {
                "working": self.switchPos_manager.working,
                "is_manual": self.switchPos_manager.is_manual,
            }

        return {
            "instructions": [
                {
                    "id": ins.id,
                    "account_id": ins.account_id,
                    "strategy_id": ins.strategy_id,
                    "symbol": ins.symbol,
                    "offset": ins.offset,
                    "direction": ins.direction,
                    "volume": ins.volume,
                    "filled_volume": ins.filled_volume,
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
                for ins in instructions
            ],
            "rotation_status": rotation_status
        }

    @request("get_rotation_instruction")
    async def _req_get_rotation_instruction(self, data: dict) -> Optional[dict]:
        """处理获取指定换仓指令请求"""

        instruction_id = data.get("instruction_id")
        instructions = self.switchPos_manager.get_today_instructions()
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
                        instruction.order_placed_time.isoformat()
                        if instruction.order_placed_time
                        else None
                    ),
                    "last_attempt_time": (
                        instruction.last_attempt_time.isoformat()
                        if instruction.last_attempt_time
                        else None
                    ),
                    "error_message": instruction.error_message,
                    "source": instruction.source,
                    "created_at": (
                        instruction.created_at.isoformat() if instruction.created_at else None
                    ),
                    "updated_at": (
                        instruction.updated_at.isoformat() if instruction.updated_at else None
                    ),
                }

    @request("update_rotation_instruction")
    async def _req_update_rotation_instruction(self, data: dict) -> Optional[dict]:
        """处理更新换仓指令请求"""
        instruction_id = data.get("instruction_id")
        if not instruction_id:
            return False

        instruction = self.switchPos_manager.update_instruction(data)
        return instruction


    @request("import_rotation_instructions")
    async def _req_import_rotation_instructions(self, data: dict) -> dict:
        """处理批量导入换仓指令请求"""
        csv_text = data.get("csv_text")
        filename = data.get("filename")
        mode = data.get("mode", "append")

        if self.switchPos_manager:
            return self.switchPos_manager.import_csv(csv_text, filename, mode)
        return {"imported": 0, "skipped": 0, "errors": []}

    @request("execute_rotation")
    async def _req_execute_rotation(self, data: dict) -> bool:
        """处理执行换仓请求"""
        import threading

        if self.switchPos_manager is None:
            return False

        async def execute():
            try:
                logger.info(f"Trader [{self.account_id}] 换仓任务执行开始")
                await self.switchPos_manager.execute_position_rotation(is_manual=True)
                logger.info(f"Trader [{self.account_id}] 换仓任务执行完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 后台换仓任务执行失败: {e}")
     
        asyncio.create_task(execute())
        return True

    @request("batch_delete_instructions")
    async def _req_batch_delete_instructions(self, data: dict) -> dict:
        """处理批量删除换仓指令请求"""
        ids = data.get("ids", [])
        self.switchPos_manager.delete_instruction(ids)
        return {"deleted": len(ids)}

    # ========== 系统参数请求处理 ==========

    @request("list_system_params")
    async def _req_list_system_params(self, data: dict) -> list:
        """处理获取系统参数列表请求"""
        from src.models.po import SystemParamPo
        from src.utils.database import get_database

        db = get_database()
        group = data.get("group")

        with db.get_session() as session:
            query = session.query(SystemParamPo)

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
    async def _req_get_system_param(self, data: dict) -> Optional[dict]:
        """处理获取单个系统参数请求"""
        from src.models.po import SystemParamPo
        from src.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo).filter(SystemParamPo.param_key == param_key).first()
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
    async def _req_update_system_param(self, data: dict) -> Optional[dict]:
        """处理更新系统参数请求"""
        from datetime import datetime

        from src.models.po import SystemParamPo
        from src.utils.database import get_database

        db = get_database()
        param_key = data.get("param_key")
        param_value = data.get("param_value")

        with db.get_session() as session:
            param = (
                session.query(SystemParamPo).filter(SystemParamPo.param_key == param_key).first()
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
    async def _req_get_system_params_by_group(self, data: dict) -> Optional[dict]:
        """处理根据分组获取系统参数请求"""
        from src.models.po import SystemParamPo
        from src.utils.database import get_database

        db = get_database()
        group = data.get("group")

        with db.get_session() as session:
            params = session.query(SystemParamPo).filter(SystemParamPo.group == group).all()

            result = {param.param_key: param.param_value for param in params}
            return result

    @request("pause_trading")
    async def _req_pause_trading(self, data: dict) -> dict:
        """处理暂停交易请求"""
        self.trading_engine.paused = True
        return True

    @request("resume_trading")
    async def _req_resume_trading(self, data: dict) -> dict:
        """处理恢复交易请求"""
        self.trading_engine.paused = False
        return True

    @request("update_alert_wechat")
    async def _req_update_alert_wechat(self, data: dict) -> dict:
        """处理更新微信告警配置请求"""
        alert_wechat = data.get("alert_wechat", False)
        self.account_config.alert_wechat = alert_wechat
        logger.info(f"Trader [{self.account_id}] 微信告警配置已更新: {alert_wechat}")
        return {"alert_wechat": alert_wechat}

    @request("get_alert_wechat")
    async def _req_get_alert_wechat(self, data: dict) -> dict:
        """处理获取微信告警配置请求"""
        return {"alert_wechat": self.account_config.alert_wechat}
