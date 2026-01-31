"""
Trader交易执行器
运行在子进程中，负责交易执行、策略运行、行情处理
"""

import asyncio
import signal
from pathlib import Path
from typing import Optional, Dict, Callable, Any

from src.app_context import AppContext, get_app_context
from src.utils.config_loader import TraderConfig
from src.job_mgr import JobManager
from src.scheduler import TaskScheduler
from src.trader.core.socket_server import SocketServer, request
from src.trader.core.strategy_manager import StrategyManager
from src.trader.core.trading_engine import TradingEngine
from src.trader.switch_mgr import SwitchPosManager
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.event_engine import EventTypes
from src.utils.logger import get_logger

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

        # 运行状态
        self._running = False

    def set_proxy_callback(self, callback: callable) -> None:
        """
        设置代理回调函数（用于内嵌模式）

        Args:
            callback: 回调函数，签名为 callback(msg_type: str, data: dict)
        """
        self._proxy_msg_callback = callback
        logger.info(f"Trader [{self.account_id}] 设置代理回调函数")

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

        # 初始化交易引擎
        self.trading_engine = TradingEngine(self.account_config)

        # 初始化换仓管理器、作业管理器、作业调度器
        self.switchPos_manager = SwitchPosManager(self.account_config, self.trading_engine)
        self.job_manager = JobManager(
            self.account_config, self.trading_engine, self.switchPos_manager
        )
        # 初始化任务调度器
        if self.account_config.scheduler:
            self.task_scheduler = TaskScheduler(self.account_config.scheduler, self.job_manager)
            self.task_scheduler.start()
            logger.info(f"Trader [{self.account_id}] 任务调度器已启动")
        else:
            logger.info(f"Trader [{self.account_id}] 未配置任务调度器")

        await self._run_standalone()

        # 连接交易系统
        if not self.trading_engine.connect():
            logger.error(f"Trader [{self.account_id}] 连接交易系统失败")

        logger.info(f"Trader [{self.account_id}] 交易引擎已启动")

        # 初始化策略管理器
        await self._init_strategy_manager()

        # 保持运行
        logger.info(f"Trader [{self.account_id}] 启动完成，持续运行中...")
        while self._running:
            await asyncio.sleep(1)

    async def _init_strategy_manager(self) -> None:
        """初始化策略管理器"""
        self.strategy_manager = StrategyManager()
        # 使用账户配置中的策略配置
        strategies_config = self.account_config.strategies
        if strategies_config and strategies_config.strategies:
            # 直接使用配置中的策略数据，不从文件加载
            self.strategy_manager.configs = strategies_config.strategies
            # 加载并实例化策略
            self.strategy_manager._load_strategies()
            # 注册事件
            self.strategy_manager._register_events()
            # 启动所有策略
            self.strategy_manager.start_all()
        logger.info(f"Trader [{self.account_id}] 策略管理器已启动")

    async def _init_database(self) -> None:
        """
        初始化数据库
        检查数据库文件是否存在，不存在则创建并初始化
        """
        from pathlib import Path
        from src.db.database import init_database, get_database
        from src.models.po import SystemParamPo
        from src.utils.config_loader import RiskControlConfig

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
        logger.info(f"Trader [{self.account_id}] 以独立模式运行")

        # 启动socket，自动收集带 @request 装饰器的方法
        self.socket_server = SocketServer(self._socket_path, self.account_id)
        self.socket_server.register_handlers_from_instance(self)
        await self.socket_server.start()

    async def _on_account_update(self, data):
        """账户更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_message("account", data.model_dump())
        else:
            logger.info(f"账户更新: {data}")

    async def _on_order_update(self, data):
        """订单更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_message("order", data.model_dump())
        else:
            logger.info(f"订单更新: {data}")

    async def _on_trade_update(self, data):
        """成交更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_message("trade", data.model_dump())
        else:
            logger.info(f"成交更新: {data}")

    async def _on_position_update(self, data):
        """持仓更新事件处理器"""
        if self.socket_server:
            await self.socket_server.send_message("position", data.model_dump())
        else:
            logger.info(f"持仓更新: {data}")

    async def _on_tick_update(self, data):
        """行情更新事件处理器"""
        if self.socket_server:
            # 行情数据不实时推送，按需订阅
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

        # 停止所有策略
        if self.strategy_manager:
            self.strategy_manager.stop_all()

        # 停止任务调度器
        if self.task_scheduler:
            self.task_scheduler.shutdown()

        # 断开连接
        if self.trading_engine:
            self.trading_engine.disconnect()

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

    @request("connect")
    async def _req_connect(self, data: dict) -> bool:
        """处理连接请求"""
        logger.info(f"Trader [{self.account_id}] 连接成功")
        return True

    @request("disconnect")
    async def _req_disconnect(self, data: dict) -> bool:
        """处理断开连接请求"""
        logger.info(f"Trader [{self.account_id}] 断开连接成功")
        return True

    @request("subscribe")
    async def _req_subscribe(self, data: dict) -> bool:
        """处理订阅请求"""
        logger.info(f"Trader [{self.account_id}] 订阅成功")
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

    @request("cancel")
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
    
    @request("get_jobs")
    async def _req_get_jobs(self, data: dict) -> list:
        """处理获取所有任务请求"""
        if self.trading_engine is None:
            return []
        jobs = self.task_scheduler.get_jobs()
        return [job.model_dump() for job in jobs.values()]

    # ========== 策略管理请求处理 ==========

    @request("list_strategies")
    async def _req_list_strategies(self, data: dict) -> list:
        """处理获取策略列表请求"""
        if self.strategy_manager is None:
            return []
        from src.manager.api.schemas import StrategyRes

        result = []
        for strategy in self.strategy_manager.strategies.values():
            strategy_res = StrategyRes(
                strategy_id=strategy.strategy_id,
                active=strategy.active,
                config=self._build_strategy_config(strategy),
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
            result = StrategyRes(
                strategy_id=strategy.strategy_id,
                active=strategy.active,
                config=self._build_strategy_config(strategy),
            )
            return result.model_dump()
        return None

    @request("start_strategy")
    async def _req_start_strategy(self, data: dict) -> bool:
        """处理启动策略请求"""
        if self.strategy_manager is None:
            return False
        strategy_id = data.get("strategy_id")
        if strategy_id:
            return self.strategy_manager.start_strategy(strategy_id)
        return False

    @request("stop_strategy")
    async def _req_stop_strategy(self, data: dict) -> bool:
        """处理停止策略请求"""
        if self.strategy_manager is None:
            return False
        strategy_id = data.get("strategy_id")
        if strategy_id:
            return self.strategy_manager.stop_strategy(strategy_id)
        return False

    @request("start_all_strategies")
    async def _req_start_all_strategies(self, data: dict) -> bool:
        """处理启动所有策略请求"""
        if self.strategy_manager is None:
            return False
        self.strategy_manager.start_all()
        return True

    @request("stop_all_strategies")
    async def _req_stop_all_strategies(self, data: dict) -> bool:
        """处理停止所有策略请求"""
        if self.strategy_manager is None:
            return False
        self.strategy_manager.stop_all()
        return True

    def _build_strategy_config(self, strategy) -> dict:
        """构建策略配置对象"""
        from src.manager.api.schemas import StrategyConfig

        config = strategy.config.copy()
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
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo

        db = get_database()
        limit = data.get("limit", 100)
        offset = data.get("offset", 0)
        status_filter = data.get("status")
        enabled_filter = data.get("enabled")

        with db.get_session() as session:
            query = session.query(RotationInstructionPo).filter(
                RotationInstructionPo.is_deleted == False
            )

            if status_filter:
                query = query.filter(RotationInstructionPo.status == status_filter)
            if enabled_filter is not None:
                query = query.filter(RotationInstructionPo.enabled == bool(enabled_filter))

            total = query.count()
            instructions = (
                query.order_by(RotationInstructionPo.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            rotation_status = {"working": False, "is_manual": False}
            if self.switchPos_manager:
                rotation_status = {
                    "working": self.switchPos_manager.is_working,
                    "is_manual": self.switchPos_manager.is_manual,
                }

            return {
                "instructions": [
                    {
                        "id": ins.id,
                        "account_id": ins.account_id,
                        "strategy_id": ins.strategy_id,
                        "symbol": ins.symbol,
                        "exchange_id": ins.exchange_id,
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
                "rotation_status": rotation_status,
                "total": total,
                "limit": limit,
                "offset": offset,
            }

    @request("get_rotation_instruction")
    async def _req_get_rotation_instruction(self, data: dict) -> Optional[dict]:
        """处理获取指定换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo

        db = get_database()
        instruction_id = data.get("instruction_id")

        with db.get_session() as session:
            instruction = (
                session.query(RotationInstructionPo)
                .filter_by(id=instruction_id, is_deleted=False)
                .first()
            )
            if instruction:
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
        return None

    @request("create_rotation_instruction")
    async def _req_create_rotation_instruction(self, data: dict) -> Optional[dict]:
        """处理创建换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()

        trading_date = data.get("trading_date")
        if not trading_date:
            trading_date = datetime.now().strftime("%Y%m%d")

        instruction = RotationInstructionPo(
            account_id=data.get("account_id", self.account_id),
            strategy_id=data.get("strategy_id"),
            symbol=data.get("symbol"),
            exchange_id=data.get("exchange_id"),
            offset=data.get("offset"),
            direction=data.get("direction"),
            volume=data.get("volume"),
            filled_volume=0,
            price=data.get("price", 0),
            order_time=data.get("order_time"),
            trading_date=trading_date,
            enabled=data.get("enabled", True),
            status="PENDING",
            attempt_count=0,
            remaining_attempts=0,
            remaining_volume=data.get("volume"),
            current_order_id=None,
            order_placed_time=None,
            last_attempt_time=None,
            error_message=None,
            source="手动添加",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        with db.get_session() as session:
            session.add(instruction)
            session.commit()
            session.refresh(instruction)

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
                "created_at": instruction.created_at.isoformat() if instruction.created_at else None,
            }

    @request("update_rotation_instruction")
    async def _req_update_rotation_instruction(self, data: dict) -> Optional[dict]:
        """处理更新换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()
        instruction_id = data.get("instruction_id")

        with db.get_session() as session:
            instruction = (
                session.query(RotationInstructionPo)
                .filter_by(id=instruction_id, is_deleted=False)
                .first()
            )

            if not instruction:
                return None

            if data.get("enabled") is not None:
                instruction.enabled = data["enabled"]
            if data.get("status") is not None:
                instruction.status = data["status"]
            if data.get("filled_volume") is not None:
                instruction.filled_volume = data["filled_volume"]

            instruction.updated_at = datetime.now()

            session.add(instruction)
            session.commit()
            session.refresh(instruction)

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
                "created_at": instruction.created_at.isoformat() if instruction.created_at else None,
                "updated_at": instruction.updated_at.isoformat() if instruction.updated_at else None,
            }

    @request("delete_rotation_instruction")
    async def _req_delete_rotation_instruction(self, data: dict) -> bool:
        """处理删除换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()
        instruction_id = data.get("instruction_id")

        with db.get_session() as session:
            instruction = (
                session.query(RotationInstructionPo)
                .filter_by(id=instruction_id, is_deleted=False)
                .first()
            )

            if not instruction:
                return False

            instruction.is_deleted = True
            instruction.updated_at = datetime.now()

            session.add(instruction)
            session.commit()

        return True

    @request("clear_rotation_instructions")
    async def _req_clear_rotation_instructions(self, data: dict) -> bool:
        """处理清除已完成换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()

        with db.get_session() as session:
            session.query(RotationInstructionPo).filter(
                RotationInstructionPo.is_deleted == False,
                RotationInstructionPo.status == "COMPLETED",
            ).update({"is_deleted": True, "updated_at": datetime.now()}, synchronize_session=False)
            session.commit()

        return True

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

        def execute():
            try:
                self.switchPos_manager.execute_position_rotation(is_manual=True)
                logger.info(f"Trader [{self.account_id}] 换仓任务执行完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 后台换仓任务执行失败: {e}")

        thread = threading.Thread(target=execute, daemon=True)
        thread.start()

        return True

    @request("close_all_positions")
    async def _req_close_all_positions(self, data: dict) -> bool:
        """处理一键平仓请求"""
        import threading

        if self.switchPos_manager is None:
            return False

        def execute():
            try:
                self.switchPos_manager.close_all_positions()
                logger.info(f"Trader [{self.account_id}] 一键平仓执行完成")
            except Exception as e:
                logger.error(f"Trader [{self.account_id}] 一键平仓执行失败: {e}")

        thread = threading.Thread(target=execute, daemon=True)
        thread.start()

        return True

    @request("batch_execute_instructions")
    async def _req_batch_execute_instructions(self, data: dict) -> dict:
        """处理批量执行换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()
        ids = data.get("ids", [])

        with db.get_session() as session:
            instructions = (
                session.query(RotationInstructionPo)
                .filter(
                    RotationInstructionPo.id.in_(ids), RotationInstructionPo.is_deleted == False
                )
                .all()
            )

            if not instructions:
                return {"success": 0, "failed": 0, "total": 0}

            success_count = 0
            failed_count = 0

            for instruction in instructions:
                if not instruction.enabled:
                    failed_count += 1
                    continue

                if instruction.status == "COMPLETED":
                    failed_count += 1
                    continue

                try:
                    instruction.status = "EXECUTING"
                    instruction.last_attempt_time = datetime.now()
                    instruction.attempt_count += 1
                    instruction.updated_at = datetime.now()

                    session.add(instruction)
                    success_count += 1

                except Exception as e:
                    logger.error(f"Trader [{self.account_id}] 执行指令失败: {e}")
                    failed_count += 1

            session.commit()

        return {"success": success_count, "failed": failed_count, "total": len(instructions)}

    @request("batch_delete_instructions")
    async def _req_batch_delete_instructions(self, data: dict) -> dict:
        """处理批量删除换仓指令请求"""
        from src.db.database import get_database
        from src.models.po import RotationInstructionPo
        from datetime import datetime

        db = get_database()
        ids = data.get("ids", [])

        with db.get_session() as session:
            deleted_count = (
                session.query(RotationInstructionPo)
                .filter(RotationInstructionPo.id.in_(ids))
                .update({"is_deleted": True, "updated_at": datetime.now()}, synchronize_session=False)
            )

            session.commit()

        return {"deleted": deleted_count}

    # ========== 系统参数请求处理 ==========

    @request("list_system_params")
    async def _req_list_system_params(self, data: dict) -> list:
        """处理获取系统参数列表请求"""
        from src.db.database import get_database
        from src.models.po import SystemParamPo

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
        from src.db.database import get_database
        from src.models.po import SystemParamPo

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
                    "created_at": param.created_at.isoformat() if param.created_at else None,
                    "updated_at": param.updated_at.isoformat() if param.updated_at else None,
                }
        return None

    @request("update_system_param")
    async def _req_update_system_param(self, data: dict) -> Optional[dict]:
        """处理更新系统参数请求"""
        from src.db.database import get_database
        from src.models.po import SystemParamPo
        from datetime import datetime

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
                "created_at": param.created_at.isoformat() if param.created_at else None,
                "updated_at": param.updated_at.isoformat() if param.updated_at else None,
            }

    @request("get_system_params_by_group")
    async def _req_get_system_params_by_group(self, data: dict) -> Optional[dict]:
        """处理根据分组获取系统参数请求"""
        from src.db.database import get_database
        from src.models.po import SystemParamPo

        db = get_database()
        group = data.get("group")

        with db.get_session() as session:
            params = session.query(SystemParamPo).filter(SystemParamPo.group == group).all()

            result = {param.param_key: param.param_value for param in params}
            return result
