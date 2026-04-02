"""
Trader交易执行器
运行在子进程中，负责交易执行、策略运行、行情处理
"""

import asyncio
import signal
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from datetime import datetime

from src.app_context import AppContext, get_app_context
from src.models.object import OrderData,TradeData
from src.trader.alarm_handler import TraderAlarmHandler
from src.trader.job_mgr import JobManager
from src.trader.strategy import BaseParam, BaseStrategy
from src.trader.strategy_manager import StrategyManager
from src.trader.switch_mgr import SwitchPosManager
from src.trader.trading_engine import TradingEngine
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
        self._td_connected: bool = False  # 上一次TD连接状态

        # 公共数据初始化状态
        # Manager 启动后会通过 init_public_data 消息推送合约信息
        self._public_data_initialized: bool = False
        # 用于等待 Manager 推送公共数据的 Future
        self._init_data_future: Optional[asyncio.Future] = None

        # 批量持久化相关
        self._pending_accounts: Dict[str, Any] = {}
        self._pending_positions: Dict[str, Any] = {}  # key: symbol
        self._persist_interval: float = 30.0  # 30秒批量写一次
        self._persist_task: Optional[asyncio.Task] = None

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
        logger.info(f"Trader [{self.account_id}] 批量持久化任务已启动(间隔{self._persist_interval}秒)")

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
            existing = session.query(SystemParamPo).filter(
                SystemParamPo.account_id == self.account_id
            ).first()

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

    def get_task_scheduler(self) -> Optional[TaskScheduler]:
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
            logger.warning(
                f"Trader [{self.account_id}] 等待公共数据超时，将自行从网关加载合约信息"
            )
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
        """账户更新事件处理器
        """
        try:
            # 缓存账户数据，等待批量写入
            self._cache_account_data(data)
            account_dict = data.model_dump() if hasattr(data, "model_dump") else data
            await self.socket_server.send_push("account", account_dict)
            # 推送给manager
        except Exception as e:
            logger.exception(f"账户更新处理失败: {e}")

    async def _on_account_ready(self,data):
        """发送账户就绪通知
        """
        try:
            if self.socket_server:
                await self.socket_server.send_push("trader_ready", {
                    "account_id": self.account_id,
                    "timestamp": datetime.now().isoformat(),
                })
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
                await self.socket_server.send_push("trader_ready", {
                    "account_id": self.account_id,
                    "timestamp": datetime.now().isoformat(),
                })
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

                account_po.balance = Decimal(str(data.balance)) if hasattr(data, 'balance') else Decimal("0")
                account_po.available = Decimal(str(data.available)) if hasattr(data, 'available') else Decimal("0")
                account_po.margin = Decimal(str(data.margin)) if hasattr(data, 'margin') else Decimal("0")
                account_po.position_profit = Decimal(str(data.hold_profit)) if hasattr(data, 'hold_profit') else Decimal("0")
                account_po.close_profit = Decimal(str(data.close_profit)) if hasattr(data, 'close_profit') else Decimal("0")
                account_po.risk_ratio = Decimal(str(data.risk_ratio)) if hasattr(data, 'risk_ratio') else Decimal("0")
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
                order_id = data.order_id if hasattr(data, 'order_id') else None
                if not order_id:
                    return

                order_po = session.query(OrderPo).filter_by(account_id=self.account_id, order_id=order_id).first()
                if not order_po:
                    order_po = OrderPo(account_id=self.account_id, order_id=order_id)

                order_po.symbol = data.symbol if hasattr(data, 'symbol') else ""
                order_po.direction = data.direction.value if hasattr(data, 'direction') else ""
                order_po.offset = data.offset.value if hasattr(data, 'offset') else ""
                order_po.limit_price = Decimal(str(data.price)) if hasattr(data, 'price') else None
                order_po.volume_orign = data.volume if hasattr(data, 'volume') else 0
                order_po.volume_left = data.volume_left if hasattr(data, 'volume_left') else data.volume if hasattr(data, 'volume') else 0
                order_po.status = data.status if hasattr(data, 'status') else ""
                order_po.price_type = data.price_type if hasattr(data, 'price_type') else "LIMIT"
                order_po.exchange_order_id = data.order_id if hasattr(data, 'exchange_order_id') else None
                order_po.status_msg = data.status_msg if hasattr(data, 'status_msg') else None
                order_po.update_date_time = data.update_time if hasattr(data, 'update_time') else None
                order_po.insert_date_time = data.insert_time if hasattr(data, 'insert_time') else None

                session.add(order_po)
                logger.debug(f"订单数据已持久化: {order_id}")
        except Exception as e:
            logger.exception(f"持久化订单数据失败: {e}")

    def _persist_trade(self, data:TradeData) -> None:
        """持久化成交数据到PG"""
        try:
            from decimal import Decimal
            from src.models.po import TradePo
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            trade_id = data.trade_id if hasattr(data, 'trade_id') else None
            if not trade_id:
                return

            with db.get_session() as session:
                existing = session.query(TradePo).filter_by(trade_id=trade_id).first()
                if existing:
                    return

                trade_po = TradePo(
                    account_id=self.account_id,
                    trade_id=trade_id,
                    order_id=data.order_id if hasattr(data, 'order_id') else "",
                    symbol=data.symbol if hasattr(data, 'symbol') else "",
                    direction=data.direction.value if hasattr(data, 'direction') else "",
                    offset=data.offset.value if hasattr(data, 'offset') else "",
                    price=Decimal(str(data.price)) if hasattr(data, 'price') else Decimal("0"),
                    volume=data.volume if hasattr(data, 'volume') else 0,
                    trade_date_time=data.trade_time if hasattr(data, 'trade_time') else 0,
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

            symbol = data.symbol if hasattr(data, 'symbol') else None
            if not symbol:
                return

            with db.get_session() as session:
                position_po = session.query(PositionPo).filter_by(
                    account_id=self.account_id, symbol=symbol, strategy_id=None
                ).first()
                if not position_po:
                    position_po = PositionPo(
                        account_id=self.account_id,
                        symbol=symbol,
                        exchange=data.exchange if hasattr(data, 'exchange') else "",
                    )

                position_po.pos_long_td = data.pos_long_td if hasattr(data, 'pos_long_td') else 0
                position_po.pos_long_yd = data.pos_long_yd if hasattr(data, 'pos_long_yd') else 0
                position_po.pos_short_td = data.pos_short_td if hasattr(data, 'pos_short_td') else 0
                position_po.pos_short_yd = data.pos_short_yd if hasattr(data, 'pos_short_yd') else 0
                position_po.hold_price_long = Decimal(str(data.hold_price_long)) if hasattr(data, 'hold_price_long') else Decimal("0")
                position_po.hold_price_short = Decimal(str(data.hold_price_short)) if hasattr(data, 'hold_price_short') else Decimal("0")
                position_po.hold_profit_long = Decimal(str(data.hold_profit_long)) if hasattr(data, 'hold_profit_long') else Decimal("0")
                position_po.hold_profit_short = Decimal(str(data.hold_profit_short)) if hasattr(data, 'hold_profit_short') else Decimal("0")
                # margin字段在模型中，计算方式：多头保证金+空头保证金
                margin_long = Decimal(str(data.margin_long)) if hasattr(data, 'margin_long') else Decimal("0")
                margin_short = Decimal(str(data.margin_short)) if hasattr(data, 'margin_short') else Decimal("0")
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
            self._pending_accounts[self.account_id] = account_data
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
        if not self._pending_accounts and not self._pending_positions:
            return

        try:
            from src.utils.database import get_database

            db = get_database()
            if not db:
                return

            with db.get_session() as session:
                # 批量写入账户
                for account_id, data in self._pending_accounts.items():
                    self._do_persist_account(session, account_id, data)

                # 批量写入持仓
                for symbol, data in self._pending_positions.items():
                    self._do_persist_position(session, self.account_id, symbol, data)

                session.commit()

            # 清空待写入队列
            count_accounts = len(self._pending_accounts)
            count_positions = len(self._pending_positions)
            self._pending_accounts.clear()
            self._pending_positions.clear()

            logger.debug(f"批量持久化完成: {count_accounts} 账户, {count_positions} 持仓")
        except Exception as e:
            logger.exception(f"批量持久化失败: {e}")

    def _do_persist_account(self, session, account_id: str, data: Dict) -> None:
        """执行账户数据持久化（内部方法）"""
        from decimal import Decimal
        from src.models.po import AccountPo

        account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
        if not account_po:
            account_po = AccountPo(account_id=account_id)

        account_po.balance = Decimal(str(data.get("balance", 0)))
        account_po.available = Decimal(str(data.get("available", 0)))
        account_po.margin = Decimal(str(data.get("margin", 0)))
        account_po.position_profit = Decimal(str(data.get("hold_profit", 0)))
        account_po.close_profit = Decimal(str(data.get("close_profit", 0)))
        account_po.risk_ratio = Decimal(str(data.get("risk_ratio", 0)))
        account_po.updated_at = datetime.now()

        session.add(account_po)

    def _do_persist_position(self, session, account_id: str, symbol: str, data: Dict) -> None:
        """执行持仓数据持久化（内部方法）"""
        from decimal import Decimal
        from src.models.po import PositionPo

        position_po = session.query(PositionPo).filter_by(
            account_id=account_id, symbol=symbol, strategy_id=None
        ).first()
        if not position_po:
            position_po = PositionPo(
                account_id=account_id,
                symbol=symbol,
                exchange=data.get("exchange", ""),
            )

        position_po.pos_long_td = data.get("pos_long_td", 0)
        position_po.pos_long_yd = data.get("pos_long_yd", 0)
        position_po.pos_short_td = data.get("pos_short_td", 0)
        position_po.pos_short_yd = data.get("pos_short_yd", 0)
        position_po.hold_price_long = Decimal(str(data.get("hold_price_long", 0)))
        position_po.hold_price_short = Decimal(str(data.get("hold_price_short", 0)))
        position_po.hold_profit_long = Decimal(str(data.get("hold_profit_long", 0)))
        position_po.hold_profit_short = Decimal(str(data.get("hold_profit_short", 0)))
        margin_long = Decimal(str(data.get("margin_long", 0)))
        margin_short = Decimal(str(data.get("margin_short", 0)))
        position_po.margin = margin_long + margin_short
        position_po.updated_at = datetime.now()

        session.add(position_po)

    async def _on_tick_update(self, data):
        """行情更新事件处理器"""
        if self.socket_server:
            # 行情数据不实时推送，按需订阅
            await self.socket_server.send_push("tick", data.model_dump())
            pass

    async def _on_alarm_update(self, data):
        """告警事件处理器 - 转发给Manager"""
        try:
            if self.socket_server:
                alarm_dict = (
                    data if isinstance(data, dict)
                    else (data.model_dump() if hasattr(data, "model_dump") else data)
                )
                await self.socket_server.send_push("alarm", alarm_dict)
        except Exception as e:
            logger.exception(f"告警转发失败: {e}")

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
        event_engine.register(EventTypes.ALARM_UPDATE, self._on_alarm_update)
        logger.info(f"Trader [{self.account_id}] 事件处理器已注册")

    async def stop(self) -> None:
        """停止Trader"""
        self._running = False
        logger.info(f"Trader [{self.account_id}] 停止中...")

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

    @request("get_account_details")
    async def _req_get_account_details(self, data: dict) -> dict:
        """
        获取账户完整数据

        返回包括：账户信息、持仓列表、挂单列表、成交列表、行情列表
        """
        if self.trading_engine is None:
            return {
                "account": None,
                "positions": [],
                "orders": [],
                "trades": [],
                "quotes": [],
            }

        # 获取账户数据
        account = self.trading_engine.account

        # 获取持仓列表
        positions = self.trading_engine.positions

        # 获取挂单列表（状态为ALIVE/PENDING的订单）
        orders = self.trading_engine.orders
        active_orders = [o for o in orders.values() if o.status in ("ALIVE", "PENDING")]

        # 获取成交列表（今日）
        trades = self.trading_engine.trades

        # 获取行情列表
        quotes = self.trading_engine.quotes

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
        if self.trading_engine is None or self.trading_engine.gateway is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎或 Gateway 未初始化")
            return []

        try:
            contracts = self.trading_engine.gateway.get_contracts()
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

    @request("cancel_order_cmd")
    async def _req_cancel_order_cmd(self, data: dict) -> dict:
        """
        处理取消报单指令请求

        Args:
            data: {"cmd_id": 指令ID}

        Returns:
            {"success": bool, "message": str}
        """
        if self.trading_engine is None:
            return {"success": False, "message": "交易引擎未初始化"}

        cmd_id = data.get("cmd_id")
        if not cmd_id:
            return {"success": False, "message": "缺少指令ID"}

        try:
            result = await self.trading_engine.cancel_order_cmd(cmd_id)
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
        if self.strategy_manager is None:
            return []
        from src.manager.api.schemas import StrategyPositionRes, StrategyRes

        # 获取最新行情数据
        quotes = self.trading_engine.quotes if self.trading_engine else {}

        result = []
        for strategy in self.strategy_manager.strategies.values():
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
                            close_profit=(pos.close_profit_long or 0) + (pos.close_profit_short or 0),
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
    async def _req_get_strategy(self, data: dict) -> Optional[dict]:
        """处理获取指定策略状态请求"""
        if self.strategy_manager is None:
            return None
        from src.manager.api.schemas import StrategyPositionRes, StrategyRes

        strategy_id = data.get("strategy_id")
        if strategy_id and strategy_id in self.strategy_manager.strategies:
            strategy = self.strategy_manager.strategies[strategy_id]
            params = strategy.get_params()
            base_fields = set[str](BaseParam.model_fields.keys())
            ext_params = [p for p in params if p["key"] not in base_fields]
            base_params = [p for p in params if p["key"] in base_fields]

            # 获取最新行情数据
            quotes = self.trading_engine.quotes if self.trading_engine else {}

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
                            close_profit=(pos.close_profit_long or 0) + (pos.close_profit_short or 0),
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

    @request("clear_strategy_signal")
    async def _req_clear_strategy_signal(self, data: dict) -> dict:
        """处理清除策略信号请求"""
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
            account_positions = self.trading_engine.positions
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
        if self.strategy_manager is None:
            return {"success": False, "message": "策略管理器未初始化"}

        strategy_id = data.get("strategy_id")
        if not strategy_id:
            return {"success": False, "message": "缺少 strategy_id"}

        strategy = self.strategy_manager.strategies.get(strategy_id)
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
                    from src.trader.dao.position_dao import StrategyPositionService

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

        try:
            strategy = self.strategy_manager.strategies.get(strategy_id)
            if not strategy:
                return {"success": False, "message": f"策略 {strategy_id} 不存在"}
            self.strategy_manager.init_strategy(strategy)
            logger.info(f"策略 [{strategy_id}] 初始化成功")
            return {"success": True, "message": "策略初始化成功"}
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

            await strategy.send_order_cmds([order_cmd])
            logger.info(
                f"策略 [{strategy_id}] 已发送报单指令: {order_cmd.symbol} {order_cmd.direction} {order_cmd.offset} {order_cmd.volume}手"
            )
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
            "rotation_status": rotation_status,
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
            query = session.query(SystemParamPo).filter(
                (SystemParamPo.account_id == self.account_id)
                | (SystemParamPo.account_id.is_(None))
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
    async def _req_get_system_param(self, data: dict) -> Optional[dict]:
        """处理获取单个系统参数请求"""
        from src.models.po import SystemParamPo
        from src.utils.database import get_database

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
    async def _req_get_system_params_by_group(self, data: dict) -> Optional[dict]:
        """处理根据分组获取系统参数请求"""
        from src.models.po import SystemParamPo
        from src.utils.database import get_database

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
        self.trading_engine.paused = True
        return True

    @request("resume_trading")
    async def _req_resume_trading(self, data: dict) -> dict:
        """处理恢复交易请求"""
        self.trading_engine.paused = False
        return True

    @request("update_alert_wechat")
    async def _req_update_alert_wechat(self, data: dict) -> dict:
        """处理更新微信告警配置请求（已废弃，请使用 update_alert_config）"""
        alert_wechat = data.get("alert_wechat", False)
        self.account_config.alert.immediate = alert_wechat
        self.account_config.alert.threshold = alert_wechat
        logger.warning(f"Trader [{self.account_id}] update_alert_wechat 已废弃，请使用 update_alert_config")
        logger.info(f"Trader [{self.account_id}] 告警配置已更新: immediate={alert_wechat}, threshold={alert_wechat}")
        return {"alert_wechat": alert_wechat}

    @request("get_alert_wechat")
    async def _req_get_alert_wechat(self, data: dict) -> dict:
        """处理获取微信告警配置请求（已废弃，请使用 get_alert_config）"""
        logger.warning(f"Trader [{self.account_id}] get_alert_wechat 已废弃，请使用 get_alert_config")
        legacy_value = self.account_config.alert.immediate or self.account_config.alert.threshold
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
            self.account_config.alert.immediate = immediate
        if threshold is not None:
            self.account_config.alert.threshold = threshold
        if threshold_count is not None:
            self.account_config.alert.threshold_count = threshold_count
        if threshold_window is not None:
            self.account_config.alert.threshold_window = threshold_window
        if dnd_start is not None:
            self.account_config.alert.dnd_start = dnd_start
        if dnd_end is not None:
            self.account_config.alert.dnd_end = dnd_end

        logger.info(
            f"Trader [{self.account_id}] 告警配置已更新: "
            f"immediate={self.account_config.alert.immediate}, "
            f"threshold={self.account_config.alert.threshold}, "
            f"threshold_count={self.account_config.alert.threshold_count}, "
            f"threshold_window={self.account_config.alert.threshold_window}, "
            f"dnd={self.account_config.alert.dnd_start}-{self.account_config.alert.dnd_end}"
        )
        return {
            "immediate": self.account_config.alert.immediate,
            "threshold": self.account_config.alert.threshold,
            "threshold_count": self.account_config.alert.threshold_count,
            "threshold_window": self.account_config.alert.threshold_window,
            "dnd_start": self.account_config.alert.dnd_start,
            "dnd_end": self.account_config.alert.dnd_end,
        }

    @request("get_alert_config")
    async def _req_get_alert_config(self, data: dict) -> dict:
        """处理获取告警配置请求"""
        return {
            "immediate": self.account_config.alert.immediate,
            "threshold": self.account_config.alert.threshold,
            "threshold_count": self.account_config.alert.threshold_count,
            "threshold_window": self.account_config.alert.threshold_window,
            "dnd_start": self.account_config.alert.dnd_start,
            "dnd_end": self.account_config.alert.dnd_end,
        }

    @request("refresh_contracts")
    async def _req_refresh_contracts(self, data: dict) -> dict:
        """
        处理强制刷新合约信息请求

        Returns:
            {"success": bool, "message": str}
        """
        if self.trading_engine is None:
            logger.error(f"Trader [{self.account_id}] 交易引擎未初始化")
            return {"success": False, "message": "交易引擎未初始化"}

        try:
            success = self.trading_engine.refresh_contracts()
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
            self._public_data_initialized = True
            if self._init_data_future and not self._init_data_future.done():
                self._init_data_future.set_result(True)
            return {"success": True, "message": "无合约数据", "count": 0}

        try:
            # 将合约数据加载到 Gateway
            if self.trading_engine and self.trading_engine.gateway:
                count = self.trading_engine.gateway.load_contracts_from_init_data(contracts)
                self._public_data_initialized = True
                # 唤醒等待中的 _wait_for_init_data
                if self._init_data_future and not self._init_data_future.done():
                    self._init_data_future.set_result(True)
                logger.info(
                    f"Trader [{self.account_id}] 已从 Manager 加载 {count} 个合约信息"
                )
                return {"success": True, "message": "合约数据已加载", "count": count}
            else:
                logger.warning(
                    f"Trader [{self.account_id}] 交易引擎或 Gateway 未初始化，无法加载合约数据"
                )
                return {"success": False, "message": "交易引擎未初始化", "count": 0}
        except Exception as e:
            logger.exception(f"Trader [{self.account_id}] 加载公共数据失败: {e}")
            return {"success": False, "message": f"加载失败: {str(e)}", "count": 0}
