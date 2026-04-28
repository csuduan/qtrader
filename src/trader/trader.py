"""
Trader交易执行器
运行在子进程中，负责交易执行、策略运行、行情处理
"""

import asyncio
import signal
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.app_context import AppContext, get_app_context
from src.models.object import OrderData, TradeData
from src.trader.alarm_handler import TraderAlarmHandler
from src.trader.job_mgr import JobManager
from src.trader.strategy_manager import StrategyManager
from src.trader.switch_mgr import SwitchPosManager
from src.trader.trader_req import TraderReqHandler
from src.trader.trading_engine import TradingEngine
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.config_loader import TraderConfig
from src.utils.event_engine import EventTypes
from src.utils.ipc import SocketServer
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
        self.trading_engine: TradingEngine | None = None

        # 换仓管理器
        self.switchPos_manager: SwitchPosManager | None = None

        # 作业管理器
        self.job_manager: JobManager | None = None

        # 策略管理器
        self.strategy_manager: StrategyManager | None = None

        # 任务调度器
        self.task_scheduler: TaskScheduler | None = None

        # Socket服务器（独立模式）
        self.socket_server: SocketServer | None = None
        self._server_task: asyncio.Task | None = None

        # 运行状态
        self._running = False
        self._td_connected: bool = False  # 上一次TD连接状态

        # 公共数据初始化状态
        # Manager 启动后会通过 init_public_data 消息推送合约信息
        self._public_data_initialized: bool = False
        # 用于等待 Manager 推送公共数据的 Future
        self._init_data_future: asyncio.Future | None = None

        # 批量持久化相关
        self._pending_accounts = None
        self._cached_account: dict[str, Any] = {}
        self._pending_positions: dict[str, Any] = {}  # key: symbol
        self._persist_interval: float = 30.0  # 30秒批量写一次
        self._persist_task: asyncio.Task | None = None

        # Tick批量推送相关
        self._pending_ticks: list[dict] = []
        self._tick_push_interval: float = 1.0  # 每秒批量推送一次
        self._tick_push_task: asyncio.Task | None = None

    async def start(
        self,
        socket_path: str | None = None,
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
        req_handler = TraderReqHandler(self)
        self.socket_server.register_handlers_from_instance(req_handler)
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

        # 从全局配置获取账户定时任务
        scheduler_config = None
        try:
            from src.utils.config_loader import get_config_loader

            loader = get_config_loader()
            app_config = loader._load_app_config()
            scheduler_config = app_config.account_scheduler
        except Exception as e:
            logger.warning(f"Trader [{self.account_id}] 无法加载全局定时任务配置: {e}")

        if scheduler_config and scheduler_config.jobs:
            self.task_scheduler = TaskScheduler(scheduler_config, self.job_manager)
            self.task_scheduler.start()
            logger.info(f"Trader [{self.account_id}] 任务调度器已启动")
        else:
            logger.info(f"Trader [{self.account_id}] 未配置任务调度器")

        # 启动策略管理器
        self.strategy_manager = StrategyManager(self.account_config.strategies, self.trading_engine)
        ctx.register(AppContext.KEY_STRATEGY_MANAGER, self.strategy_manager)
        await self.strategy_manager.start()

        # 启动定时批量持久化任务
        self._persist_task = asyncio.create_task(self._periodic_persist())
        logger.info(
            f"Trader [{self.account_id}] 批量持久化任务已启动(间隔{self._persist_interval}秒)"
        )

        # 启动Tick批量推送任务
        self._tick_push_task = asyncio.create_task(self._tick_push_loop())
        logger.info(f"Trader [{self.account_id}] Tick批量推送任务已启动(间隔{self._tick_push_interval}秒)")

        # 连接网关
        await self.trading_engine.connect()

        # 保持运行
        logger.info("=" * 60)
        logger.info(f"Trader [{self.account_id}] 启动成功，持续运行中...")
        logger.info("=" * 60)


    async def _init_database(self) -> None:
        """
        连接到共享数据库（PostgreSQL）
        Manager 负责创建数据库和表，Trader 只需连接并读取
        """
        from src.models.po import SystemParamPo
        from src.utils.config_loader import RiskControlConfig, get_config_loader
        from src.utils.database import get_database, init_database
        from src.utils.db_url import build_db_url

        # 从全局配置获取数据库连接
        loader = get_config_loader()
        app_config = loader._load_app_config()
        db_config = app_config.data_base
        db_url = build_db_url(db_config)

        # 连接到共享数据库
        db = init_database(
            db_url,
            account_id=self.account_id,
            echo=False,
            pool_size=db_config.pg.pool_size,
            max_overflow=db_config.pg.max_overflow,
        )
        logger.info(f"Trader [{self.account_id}] 已连接到共享数据库")

        # 初始化账户级别的系统参数（如果不存在）
        with db.get_session() as session:
            existing = (
                session.query(SystemParamPo)
                .filter(SystemParamPo.account_id == self.account_id)
                .first()
            )

            if not existing:
                params = []
                risk_control = RiskControlConfig()

                params.append(
                    SystemParamPo(
                        account_id=self.account_id,
                        param_key="risk_control.max_daily_orders",
                        param_value=str(risk_control.max_daily_orders),
                        param_type="integer",
                        description="每日最大报单数量",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        account_id=self.account_id,
                        param_key="risk_control.max_daily_cancels",
                        param_value=str(risk_control.max_daily_cancels),
                        param_type="integer",
                        description="每日最大撤单数量",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        account_id=self.account_id,
                        param_key="risk_control.max_order_volume",
                        param_value=str(risk_control.max_order_volume),
                        param_type="integer",
                        description="单次最大报单手数",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        account_id=self.account_id,
                        param_key="risk_control.max_split_volume",
                        param_value=str(risk_control.max_split_volume),
                        param_type="integer",
                        description="最大拆单手数",
                        group="risk_control",
                    )
                )

                params.append(
                    SystemParamPo(
                        account_id=self.account_id,
                        param_key="risk_control.order_timeout",
                        param_value=str(risk_control.order_timeout),
                        param_type="integer",
                        description="报单超时时间（秒）",
                        group="risk_control",
                    )
                )

                session.add_all(params)
                session.commit()
                logger.info(f"Trader [{self.account_id}] 系统参数初始化完成")

    def get_task_scheduler(self) -> TaskScheduler | None:
        """获取任务调度器"""
        return self.task_scheduler

    async def _wait_for_init_data(self, timeout: float = 30.0) -> bool:
        """
        等待 Manager 推送公共数据（合约信息）

        Trader 启动后调用此方法阻塞等待 Manager 的 init_public_data 消息。
        若超时则返回 False，Trader 将自行从网关拉取合约信息。

        Args:
            timeout: 最大等待时间（秒）

        Returns:
            是否收到公共数据
        """
        if self._public_data_initialized:
            return True

        loop = asyncio.get_event_loop()
        self._init_data_future = loop.create_future()
        logger.info(f"Trader [{self.account_id}] 等待 Manager 推送公共数据（最多 {timeout}s）...")

        try:
            await asyncio.wait_for(asyncio.shield(self._init_data_future), timeout=timeout)
            logger.info(f"Trader [{self.account_id}] 已收到 Manager 公共数据")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Trader [{self.account_id}] 等待公共数据超时，将自行从网关加载合约信息")
            return False
        finally:
            self._init_data_future = None

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

        # 启动socket，通过 TraderReqHandler 注册请求处理器
        self.socket_server = SocketServer(self._socket_path, self.account_id)
        req_handler = TraderReqHandler(self)
        self.socket_server.register_handlers_from_instance(req_handler)

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
        try:
            # 缓存账户数据，等待批量写入
            self._cache_account_data(data)
            account_dict = data.model_dump() if hasattr(data, "model_dump") else data
            await self.socket_server.send_push("account", account_dict)
            # 推送给manager
        except Exception as e:
            logger.exception(f"账户更新处理失败: {e}")

    async def _on_account_ready(self, data):
        """发送账户就绪通知"""
        try:
            if self.socket_server:
                await self.socket_server.send_push(
                    "trader_ready",
                    {
                        "account_id": self.account_id,
                        "timestamp": datetime.now().isoformat(),
                    },
                )
                logger.info(f"Trader [{self.account_id}] 就绪通知已发送")
        except Exception as e:
            logger.exception(f"账户状态处理失败: {e}")

    async def _on_order_update(self, data):
        """订单更新事件处理器 - 写入PG后直接广播完整数据"""
        try:
            # 1. 先写入PG
            self._persist_order(data)

            # 2. 广播完整订单数据给Manager
            if self.socket_server:
                order_dict = data.model_dump() if hasattr(data, "model_dump") else data
                await self.socket_server.send_push("order", order_dict)
                logger.debug(f"订单更新已广播: {data.order_id}")
        except Exception as e:
            logger.exception(f"订单更新处理失败: {e}")

    async def _on_trade_update(self, data):
        """成交更新事件处理器 - 写入PG后直接广播完整数据"""
        try:
            # 1. 先写入PG
            self._persist_trade(data)

            # 2. 广播完整成交数据给Manager
            if self.socket_server:
                trade_dict = data.model_dump() if hasattr(data, "model_dump") else data
                await self.socket_server.send_push("trade", trade_dict)
                logger.debug(f"成交更新已广播: {data.trade_id}")
        except Exception as e:
            logger.exception(f"成交更新处理失败: {e}")

    async def _on_position_update(self, data):
        """持仓更新事件处理器 - 缓存并推送给Manager

        所有持仓变更都实时推送给Manager（增量推送）。
        全量快照在TD连接成功时由 _push_full_positions 发送。
        """
        try:
            # 移除内部source标记（不推给Manager）
            if isinstance(data, dict):
                data.pop("_source", None)

            # 缓存持仓数据，等待批量写入DB
            self._cache_position_data(data)

            # 增量推送给Manager
            if self.socket_server:
                pos_dict = data.model_dump() if hasattr(data, "model_dump") else data
                await self.socket_server.send_push("position", pos_dict)
                symbol = pos_dict.get("symbol", "")
                logger.debug(f"持仓更新已广播: {symbol}")
        except Exception as e:
            logger.exception(f"持仓更新处理失败: {e}")

    async def _on_tick_update(self, data):
        """行情更新事件处理器 - 缓存Tick等待批量推送"""
        tick_dict = data.model_dump() if hasattr(data, "model_dump") else data
        self._pending_ticks.append(tick_dict)

    async def _tick_push_loop(self) -> None:
        """Tick批量推送循环 - 每秒推送一次缓存的Tick数据及账户信息"""
        while self._running:
            try:
                await asyncio.sleep(self._tick_push_interval)
                if not self._pending_ticks or not self.socket_server:
                    continue

                # 取出当前缓存的所有Tick
                ticks = self._pending_ticks
                self._pending_ticks = []

                # 获取当前账户数据
                account_dict = None
                if self.trading_engine and self.trading_engine.account:
                    account = self.trading_engine.account
                    account_dict = account.model_dump() if hasattr(account, "model_dump") else account

                payload = {"ticks": ticks}
                if account_dict:
                    payload["account"] = account_dict

                await self.socket_server.send_push("tick_batch", payload)
                logger.debug(f"Tick批量推送: {len(ticks)} 条")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Tick批量推送失败: {e}")

    async def _push_full_positions(self) -> None:
        """TD连接成功后，延迟推送全量持仓快照给Manager

        等待Gateway加载完持仓数据后，将所有持仓一次性推送给Manager。
        """
        try:
            # 等待持仓数据加载完成
            await asyncio.sleep(3)

            if not self.trading_engine or not self.socket_server:
                return

            positions = self.trading_engine.positions
            if not positions:
                logger.info(f"Trader [{self.account_id}] 无持仓数据，跳过全量推送")
                return

            count = 0
            for symbol, pos in positions.items():
                pos_dict = pos.model_dump() if hasattr(pos, "model_dump") else pos
                await self.socket_server.send_push("position", pos_dict)
                count += 1

            logger.info(f"Trader [{self.account_id}] 全量持仓已推送: {count} 个")
        except Exception as e:
            logger.exception(f"推送全量持仓失败: {e}")

    async def _notify_ready(self) -> None:
        """Trader就绪后通知Manager进行全量同步

        等待持仓数据加载完成后发送就绪通知
        """
        try:
            await asyncio.sleep(5)  # 等待持仓数据加载完成
            if self.socket_server:
                await self.socket_server.send_push(
                    "trader_ready",
                    {
                        "account_id": self.account_id,
                        "timestamp": datetime.now().isoformat(),
                    },
                )
                logger.info(f"Trader [{self.account_id}] 就绪通知已发送")
        except Exception as e:
            logger.exception(f"发送就绪通知失败: {e}")

    def _persist_account(self, data) -> None:
        """持久化账户数据到PG"""
        try:
            from decimal import Decimal

            from src.models.po import AccountPo
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            with db.get_session() as session:
                account_po = session.query(AccountPo).filter_by(account_id=self.account_id).first()
                if not account_po:
                    account_po = AccountPo(account_id=self.account_id)

                account_po.balance = (
                    Decimal(str(data.balance)) if hasattr(data, "balance") else Decimal("0")
                )
                account_po.available = (
                    Decimal(str(data.available)) if hasattr(data, "available") else Decimal("0")
                )
                account_po.margin = (
                    Decimal(str(data.margin)) if hasattr(data, "margin") else Decimal("0")
                )
                account_po.position_profit = (
                    Decimal(str(data.hold_profit)) if hasattr(data, "hold_profit") else Decimal("0")
                )
                account_po.close_profit = (
                    Decimal(str(data.close_profit))
                    if hasattr(data, "close_profit")
                    else Decimal("0")
                )
                account_po.risk_ratio = (
                    Decimal(str(data.risk_ratio)) if hasattr(data, "risk_ratio") else Decimal("0")
                )
                account_po.updated_at = datetime.now()

                session.add(account_po)
                logger.debug(f"账户数据已持久化: {self.account_id}")
        except Exception as e:
            logger.exception(f"持久化账户数据失败: {e}")

    def _persist_order(self, data: OrderData) -> None:
        """持久化订单数据到PG"""
        try:
            from decimal import Decimal

            from src.models.po import OrderPo
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            with db.get_session() as session:
                order_id = data.order_id if hasattr(data, "order_id") else None
                if not order_id:
                    return

                order_po = (
                    session.query(OrderPo)
                    .filter_by(account_id=self.account_id, order_id=order_id)
                    .first()
                )
                if not order_po:
                    order_po = OrderPo(account_id=self.account_id, order_id=order_id)

                order_po.symbol = data.symbol if hasattr(data, "symbol") else ""
                order_po.direction = data.direction.value if hasattr(data, "direction") else ""
                order_po.offset = data.offset.value if hasattr(data, "offset") else ""
                order_po.limit_price = Decimal(str(data.price)) if hasattr(data, "price") else None
                order_po.volume_orign = data.volume if hasattr(data, "volume") else 0
                order_po.volume_left = (
                    data.volume_left
                    if hasattr(data, "volume_left")
                    else data.volume if hasattr(data, "volume") else 0
                )
                order_po.status = data.status if hasattr(data, "status") else ""
                order_po.price_type = data.price_type if hasattr(data, "price_type") else "LIMIT"
                order_po.exchange_order_id = (
                    data.order_id if hasattr(data, "exchange_order_id") else None
                )
                order_po.status_msg = data.status_msg if hasattr(data, "status_msg") else None
                order_po.update_date_time = (
                    data.update_time if hasattr(data, "update_time") else None
                )
                insert_time = data.insert_time if hasattr(data, "insert_time") else None
                order_po.insert_date_time = (
                    insert_time or order_po.update_date_time or datetime.now()
                )

                session.add(order_po)
                logger.debug(f"订单数据已持久化: {order_id}")
        except Exception as e:
            logger.exception(f"持久化订单数据失败: {e}")

    def _persist_trade(self, data: TradeData) -> None:
        """持久化成交数据到PG"""
        try:
            from decimal import Decimal

            from src.models.po import TradePo
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            trade_id = data.trade_id if hasattr(data, "trade_id") else None
            if not trade_id:
                return

            with db.get_session() as session:
                existing = session.query(TradePo).filter_by(trade_id=trade_id).first()
                if existing:
                    return

                trade_po = TradePo(
                    account_id=self.account_id,
                    trade_id=trade_id,
                    order_id=data.order_id if hasattr(data, "order_id") else "",
                    symbol=data.symbol if hasattr(data, "symbol") else "",
                    direction=data.direction.value if hasattr(data, "direction") else "",
                    offset=data.offset.value if hasattr(data, "offset") else "",
                    price=Decimal(str(data.price)) if hasattr(data, "price") else Decimal("0"),
                    volume=data.volume if hasattr(data, "volume") else 0,
                    trade_date_time=data.trade_time if hasattr(data, "trade_time") else 0,
                    order_price=(
                        Decimal(str(data.order_price))
                        if hasattr(data, "order_price") and data.order_price is not None
                        else None
                    ),
                )
                session.add(trade_po)
                logger.debug(f"成交数据已持久化: {trade_id}")
        except Exception as e:
            logger.exception(f"持久化成交数据失败: {e}")

    def _persist_position(self, data) -> None:
        """持久化持仓数据到PG"""
        try:
            from decimal import Decimal

            from src.models.po import PositionPo
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            symbol = data.symbol if hasattr(data, "symbol") else None
            if not symbol:
                return

            with db.get_session() as session:
                position_po = (
                    session.query(PositionPo)
                    .filter_by(account_id=self.account_id, symbol=symbol, strategy_id=None)
                    .first()
                )
                if not position_po:
                    position_po = PositionPo(
                        account_id=self.account_id,
                        symbol=symbol,
                        exchange=data.exchange if hasattr(data, "exchange") else "",
                    )

                position_po.pos_long_td = data.pos_long_td if hasattr(data, "pos_long_td") else 0
                position_po.pos_long_yd = data.pos_long_yd if hasattr(data, "pos_long_yd") else 0
                position_po.pos_short_td = data.pos_short_td if hasattr(data, "pos_short_td") else 0
                position_po.pos_short_yd = data.pos_short_yd if hasattr(data, "pos_short_yd") else 0
                position_po.hold_price_long = (
                    Decimal(str(data.hold_price_long))
                    if hasattr(data, "hold_price_long")
                    else Decimal("0")
                )
                position_po.hold_price_short = (
                    Decimal(str(data.hold_price_short))
                    if hasattr(data, "hold_price_short")
                    else Decimal("0")
                )
                position_po.hold_profit_long = (
                    Decimal(str(data.hold_profit_long))
                    if hasattr(data, "hold_profit_long")
                    else Decimal("0")
                )
                position_po.hold_profit_short = (
                    Decimal(str(data.hold_profit_short))
                    if hasattr(data, "hold_profit_short")
                    else Decimal("0")
                )
                # margin字段在模型中，计算方式：多头保证金+空头保证金
                margin_long = (
                    Decimal(str(data.margin_long)) if hasattr(data, "margin_long") else Decimal("0")
                )
                margin_short = (
                    Decimal(str(data.margin_short))
                    if hasattr(data, "margin_short")
                    else Decimal("0")
                )
                position_po.margin = margin_long + margin_short
                position_po.updated_at = datetime.now()

                session.add(position_po)
                logger.debug(f"持仓数据已持久化: {symbol}")
        except Exception as e:
            logger.exception(f"持久化持仓数据失败: {e}")

    def _cache_account_data(self, data) -> None:
        """缓存账户数据，等待批量写入"""
        try:
            account_data = data.model_dump() if hasattr(data, "model_dump") else data
            self._cached_account = account_data
            logger.debug(f"账户数据已缓存: {self.account_id}")
        except Exception as e:
            logger.exception(f"缓存账户数据失败: {e}")

    def _cache_position_data(self, data) -> None:
        """缓存持仓数据，等待批量写入"""
        try:
            position_data = data.model_dump() if hasattr(data, "model_dump") else data
            symbol = position_data.get("symbol")
            if symbol:
                self._pending_positions[symbol] = position_data
                logger.debug(f"持仓数据已缓存: {symbol}")
        except Exception as e:
            logger.exception(f"缓存持仓数据失败: {e}")

    async def _periodic_persist(self) -> None:
        """定时批量持久化任务"""
        while self._running:
            try:
                await asyncio.sleep(self._persist_interval)
                await self._batch_persist()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"定时持久化任务出错: {e}")

    async def _batch_persist(self) -> None:
        """批量持久化到PG"""
        if not self._cached_account and not self._pending_positions:
            return

        try:
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            with db.get_session() as session:
                # 批量写入账户
                if self._cached_account:
                    self._do_persist_account(session, self.account_id, self._cached_account)

                # 批量写入持仓
                for symbol, data in self._pending_positions.items():
                    self._do_persist_position(session, self.account_id, symbol, data)

                session.commit()

            # 清空待写入队列
            count_accounts = 1
            count_positions = len(self._pending_positions)
            self._cached_account = None
            self._pending_positions.clear()

            logger.debug(f"批量持久化完成: {count_accounts} 账户, {count_positions} 持仓")
        except Exception as e:
            logger.exception(f"批量持久化失败: {e}")

    def _do_persist_account(self, session, account_id: str, data: dict) -> None:
        """执行账户数据持久化（内部方法）"""
        from decimal import Decimal

        from src.models.po import AccountPo

        account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
        if not account_po:
            account_po = AccountPo(account_id=account_id)

        account_po.balance = Decimal(str(data.get("balance") or 0))
        account_po.available = Decimal(str(data.get("available") or 0))
        account_po.margin = Decimal(str(data.get("margin") or 0))
        account_po.position_profit = Decimal(str(data.get("hold_profit") or 0))
        account_po.close_profit = Decimal(str(data.get("close_profit") or 0))
        account_po.risk_ratio = Decimal(str(data.get("risk_ratio") or 0))
        account_po.updated_at = datetime.now()

        session.add(account_po)

    def _do_persist_position(self, session, account_id: str, symbol: str, data: dict) -> None:
        """执行持仓数据持久化（内部方法）"""
        from decimal import Decimal

        from src.models.po import PositionPo

        position_po = (
            session.query(PositionPo)
            .filter_by(account_id=account_id, symbol=symbol, strategy_id=None)
            .first()
        )
        if not position_po:
            position_po = PositionPo(
                account_id=account_id,
                symbol=symbol,
                exchange=data.get("exchange", ""),
            )

        position_po.pos_long_td = data.get("pos_long_td") or 0
        position_po.pos_long_yd = data.get("pos_long_yd") or 0
        position_po.pos_short_td = data.get("pos_short_td") or 0
        position_po.pos_short_yd = data.get("pos_short_yd") or 0
        position_po.hold_price_long = Decimal(str(data.get("hold_price_long") or 0))
        position_po.hold_price_short = Decimal(str(data.get("hold_price_short") or 0))
        position_po.hold_profit_long = Decimal(str(data.get("hold_profit_long") or 0))
        position_po.hold_profit_short = Decimal(str(data.get("hold_profit_short") or 0))
        margin_long = Decimal(str(data.get("margin_long") or 0))
        margin_short = Decimal(str(data.get("margin_short") or 0))
        position_po.margin = margin_long + margin_short
        position_po.updated_at = datetime.now()

        session.add(position_po)



    def _register_event_handlers(self) -> None:
        """
        注册事件处理器（推送到Manager）

        """
        # 注册到 AsyncEventEngine
        event_engine: AsyncEventEngine = ctx.get_event_engine()
        event_engine.register(EventTypes.ACCOUNT_UPDATE, self._on_account_update)
        event_engine.register(EventTypes.ACCOUNT_READY, self._on_account_ready)
        event_engine.register(EventTypes.ORDER_UPDATE, self._on_order_update)
        event_engine.register(EventTypes.TRADE_UPDATE, self._on_trade_update)
        event_engine.register(EventTypes.POSITION_UPDATE, self._on_position_update)
        event_engine.register(EventTypes.TICK_UPDATE, self._on_tick_update)
        logger.info(f"Trader [{self.account_id}] 事件处理器已注册")

    async def stop(self) -> None:
        """停止Trader"""
        self._running = False
        logger.info(f"Trader [{self.account_id}] 停止中...")

        # 停止Tick批量推送任务
        if self._tick_push_task:
            self._tick_push_task.cancel()
            try:
                await self._tick_push_task
            except asyncio.CancelledError:
                pass
            logger.info(f"Trader [{self.account_id}] Tick批量推送任务已停止")

        # 推送剩余Tick
        if self._pending_ticks and self.socket_server:
            ticks = self._pending_ticks
            self._pending_ticks = []
            account_dict = None
            if self.trading_engine and self.trading_engine.account:
                account = self.trading_engine.account
                account_dict = account.model_dump() if hasattr(account, "model_dump") else account
            payload = {"ticks": ticks}
            if account_dict:
                payload["account"] = account_dict
            try:
                await self.socket_server.send_push("tick_batch", payload)
                logger.info(f"Trader [{self.account_id}] 剩余Tick已推送: {len(ticks)} 条")
            except Exception as e:
                logger.warning(f"推送剩余Tick失败: {e}")

        # 停止批量持久化任务
        if self._persist_task:
            self._persist_task.cancel()
            try:
                await self._persist_task
            except asyncio.CancelledError:
                pass
            logger.info(f"Trader [{self.account_id}] 批量持久化任务已停止")

        # 强制持久化剩余数据
        await self._batch_persist()
        logger.info(f"Trader [{self.account_id}] 剩余数据已强制持久化")

        # 停止任务调度器
        if self.task_scheduler:
            self.task_scheduler.shutdown()

        # 关闭交易引擎
        if self.trading_engine:
            await self.trading_engine.close()

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
