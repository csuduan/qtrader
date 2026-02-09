"""
交易引擎核心模块（异步版本）
负责连接API、管理交易会话、处理行情和交易
"""

import asyncio
import math
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from src.app_context import get_app_context
from src.models.object import (
    AccountData,
    CancelRequest,
    Direction,
    Offset,
    OrderData,
    OrderRequest,
    OrderStatus,
    PositionData,
    TradeData,
)
from src.trader.core.risk_control import RiskControl
from src.trader.order_cmd import OrderCmd, OrderCmdStatus, SplitStrategyType
from src.trader.order_cmd_executor import OrderCmdExecutor
from src.utils.async_event_engine import AsyncEventEngine
from src.utils.config_loader import AccountConfig, AppConfig
from src.utils.event_engine import EventTypes
from src.utils.logger import get_logger
from src.utils.wecomm import send_wechat

logger = get_logger(__name__)
ctx = get_app_context()


class TradingEngine:
    """交易引擎类（异步版本）"""

    def __init__(
        self,
        config: AccountConfig,  # config 可以是 AppConfig 或 AccountConfig
    ):
        """
        初始化交易引擎

        Args:
            config: 配置对象（AppConfig 或 AccountConfig）
            event_engine: 事件引擎实例（可选，如果不提供则创建新的）
        """
        self.config: AccountConfig = config
        self.account_id = config.account_id  # type: ignore[attr-defined]
        logger.info(
            f"TradingEngine __init__, account_id: {self.account_id}, config_id: {id(config)}"
        )

        from src.trader.adapters.base_gateway import BaseGateway

        self.gateway: Optional[BaseGateway] = None
        self.paused = config.trading.paused if config.trading else False

        # 风控模块（使用配置文件中的默认值，启动后会从数据库加载）
        risk_config = config.trading.risk_control if config.trading else None
        if risk_config:
            self.risk_control = RiskControl(risk_config)
        else:
            from src.utils.config_loader import RiskControlConfig
            self.risk_control = RiskControl(RiskControlConfig())

        # 异步事件引擎
        self.event_engine: Optional[AsyncEventEngine] = None

        # 报单指令管理
        self._order_cmds: Dict[str, OrderCmd] = {}

        # 报单指令执行器
        self._order_cmd_executor: Optional[OrderCmdExecutor] = None

        logger.info(f"交易引擎初始化完成，账户类型: {config.account_type}")  # type: ignore[attr-defined]

        # Gateway初始化
        self._init_gateway()
        # 加载风控数据
        self.reload_risk_control_config()  # type: ignore[attr-defined]

    async def start(self):
        """
        启动交易引擎（异步版本）
        """
        if self.gateway is None:
            logger.error("Gateway未初始化，无法启动交易引擎")
            return

        # 启动执行器
        from src.trader.order_cmd_executor import OrderCmdExecutor

        if self._order_cmd_executor is None:
            self._order_cmd_executor = OrderCmdExecutor(self.event_engine, self)
            self._order_cmd_executor.start()
            logger.info("报单指令执行器已启动")

        # 后台连接Gateway
        await self.connect()
        logger.info(f"交易引擎 [{self.account_id}] 已启动")

    @property
    def connected(self) -> bool:
        if self.gateway is None:
            return False
        return self.gateway.connected

    @property
    def trades(self):
        if self.gateway is None:
            return {}
        return self.gateway.get_trades()

    @property
    def account(self):
        if self.gateway is None:
            return None
        account = self.gateway.get_account()
        if account is None:
            return None
        account.gateway_connected = self.gateway.connected
        user_id = None
        if self.config.gateway and self.config.gateway.broker:
            user_id = self.config.gateway.broker.user_id
        account.user_id = user_id or "--"
        account.risk_status = self.risk_control.get_status()
        account.trade_paused = self.paused
        return account

    @property
    def orders(self):
        if self.gateway is None:
            return {}
        return self.gateway.get_orders()

    @property
    def trading_day(self) -> datetime:
        if self.gateway is None:
            return datetime.now()
        trading_day = self.gateway.get_trading_day()
        if trading_day is None:
            return datetime.now()
        return datetime.strptime(trading_day, "%Y%m%d")

    @property
    def positions(self):
        if self.gateway is None:
            return {}
        return self.gateway.get_positions()

    @property
    def quotes(self):
        if self.gateway is None:
            return {}
        return self.gateway.get_quotes()

    def reload_risk_control_config(self):
        """
        从数据库重新加载风控配置
        """
        try:
            from src.param_loader import load_risk_control_config

            new_config = load_risk_control_config()
            self.risk_control.config = new_config
            logger.info("风控配置已从数据库重新加载")
        except Exception as e:
            logger.error(f"重新加载风控配置失败: {e}", exc_info=True)

    def _init_gateway(self):
        """
        初始化Gateway（根据配置类型）

        Gateway类型配置（config.gateway_type）：
        - "TQSDK": 使用TqSdk接口
        - "CTP": 使用CTP接口（需要CTP SDK）
        """
        # 获取Gateway类型配置（新增到config_loader.py）
        gateway_config = self.config.gateway
        gateway_config.account_id = self.account_id
        gateway_type = gateway_config.type
        logger.info(f"创建Gateway，类型: {gateway_type}")
        if gateway_type == "CTP":
            from src.trader.adapters.ctp_gateway import CtpGateway

            self.gateway = CtpGateway(gateway_config)
            logger.info("CTP Gateway创建成功(框架实现，需CTP SDK)")
        else:  # 默认TQSDK
            from src.trader.adapters.tq_gateway import TqGateway

            self.gateway = TqGateway(gateway_config)
            logger.info("TqSdk Gateway创建成功")

        # 初始化异步事件引擎
        self.event_engine = ctx.get_event_engine()
        if self.event_engine is None or not isinstance(self.event_engine, AsyncEventEngine):
            # 创建新的异步事件引擎
            self.event_engine = AsyncEventEngine(f"TradingEngine_{self.account_id}")
            self.event_engine.start()
            ctx.set(ctx.KEY_EVENT_ENGINE, self.event_engine)

        # 注册回调（Gateway → EventEngine）
        self.gateway.register_callbacks(
            on_tick=self._on_tick,
            on_bar=self._on_bar,
            on_order=self._on_order,
            on_trade=self._on_trade,
            on_position=self._on_position,
            on_account=self._on_account,
        )

    def _load_risk_control_config(self):
        """
        加载风控配置

        优先从数据库加载，如果数据库中没有，则使用配置文件中的默认值

        Returns:
            RiskControlConfig: 风控配置对象
        """
        try:
            from src.param_loader import load_risk_control_config

            return load_risk_control_config()
        except Exception as e:
            logger.warning(f"从数据库加载风控配置失败: {e}，使用配置文件默认值")
            return self.config.risk_control

    async def connect(self) -> bool:
        """
        连接到交易系统（通过Gateway）

        Returns:
            bool: 连接是否成功
        """
        try:
            logger.info("连接到交易系统...")
            if self.gateway is None:
                return False
            asyncio.create_task(self.gateway.connect())
            return True

        except Exception as e:
            logger.exception(f"连接失败: {e}")
            return False

    async def disconnect(self) -> bool:
        """
        断开与交易系统的连接（通过Gateway）

        Returns:
            bool: 断开是否成功
        """
        try:
            logger.info("断开与交易系统的连接...")
            if self.gateway is None:
                return False
            return await self.gateway.disconnect()

        except Exception as e:
            logger.exception(f"断开连接失败: {e}")
            return False

    async def insert_order(
        self,
        symbol: str,
        direction: Union[str, Direction],
        offset: Union[str, Offset],
        volume: int,
        price: float = 0,
    ) -> Optional[OrderData]:
        """
        下单（异步版本）

        Args:
            symbol: 合约代码，支持格式：合约编号(如a2605)、合约编号.交易所(如a2605.DCE)、交易所.合约编号(如DCE.a2605)
            direction: 方向 (BUY/SELL)
            offset: 开平 (OPEN/CLOSE/CLOSETODAY)
            volume: 手数
            price: 0-市价，>0限价

        Returns:
            Optional[OrderData]: 委托单数据，失败返回None
        """
        if self.gateway is None or not self.gateway.connected:
            logger.error("交易引擎未连接，无法下单")
            raise Exception("交易引擎未连接，无法下单")

        if self.paused:
            logger.warning("交易已暂停，无法下单")
            raise Exception("交易已暂停，无法下单")

        # 风控检查
        if not self.risk_control.check_order(volume):
            logger.error(f"风控检查失败: 手数 {volume} 超过限制")
            raise Exception(f"风控检查失败: 手数 {volume} 超过限制")

        try:
            if self.gateway is None:
                raise Exception("Gateway未初始化")

            # 转换为枚举类型
            if isinstance(direction, str):
                direction = Direction(direction)
            if isinstance(offset, str):
                offset = Offset(offset)

            req = OrderRequest(
                symbol=symbol,
                direction=direction,
                offset=offset,
                volume=volume,
                price=price if price > 0 else None,
            )

            order_data = await self.gateway.send_order(req)

            if order_data is not None:
                logger.bind(tags=["trade"]).info(
                    f"下单: {symbol} {direction} {offset} {volume}手 @{price if price > 0 else 'MARKET'}, 委托单ID: {order_data.order_id}"
                )
                order_data.insert_time = datetime.now()
                # 更新风控计数
                self.risk_control.on_order_inserted()

            return order_data

        except Exception as e:
            raise Exception(f"下单失败: {e}")

    async def cancel_order(self, order_id: str) -> bool:
        """
        撤单（通过Gateway，异步版本）

        Args:
            order_id: 订单ID

        Returns:
            bool: 撤单是否成功
        """
        if self.gateway and self.gateway.connected:
            req = CancelRequest(order_id=order_id)
            return await self.gateway.cancel_order(req)

        logger.warning("Gateway未初始化或未连接")
        return False

    def pause(self) -> None:
        """暂停交易"""
        self.paused = True
        logger.info("交易已暂停")

        # 获取当前账户数据，添加 trade_paused 字段后推送
        account_data = self.account
        if account_data:
            update_data = account_data.model_dump()
            update_data["trade_paused"] = True
            self._emit_event(EventTypes.ACCOUNT_UPDATE, update_data)
        else:
            # 如果没有账户数据，发送最小化的状态更新
            self._emit_event(
                EventTypes.ACCOUNT_STATUS,
                {
                    "account_id": self.account_id,  # type: ignore[attr-defined]
                    "status": "paused",
                    "trade_paused": True,
                    "timestamp": datetime.now().isoformat(),
                },
            )

    def resume(self) -> None:
        """恢复交易"""
        self.paused = False
        logger.info("交易已恢复")

        # 获取当前账户数据，添加 trade_paused 字段后推送
        account_data = self.account
        if account_data:
            update_data = account_data.model_dump()
            update_data["trade_paused"] = False
            self._emit_event(EventTypes.ACCOUNT_UPDATE, update_data)
        else:
            # 如果没有账户数据，发送最小化的状态更新
            self._emit_event(
                EventTypes.ACCOUNT_STATUS,
                {
                    "account_id": self.account_id,  # type: ignore[attr-defined]
                    "status": "running",
                    "trade_paused": False,
                    "timestamp": datetime.now().isoformat(),
                },
            )

    def get_position(self, symbol: str) -> Optional[PositionData]:
        """
        获取合约持仓数据（通过Gateway）

        Args:
            symbol: 合约代码

        Returns:
            Optional[PositionData]: 持仓数据，失败返回None
        """
        if self.gateway:
            return self.gateway.get_positions().get(symbol, None)
        return None

    def get_status(self) -> Dict[str, Any]:
        """
        获取引擎状态

        Returns:
            状态字典
        """
        return {
            "connected": self.gateway.connected if self.gateway else False,
            "paused": self.paused,
            "account_id": getattr(self.account, "user_id", "") if self.account else "",
            "daily_orders": self.risk_control.daily_order_count,
            "daily_cancels": self.risk_control.daily_cancel_count,
        }

    def get_kline(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """
        获取合约K线数据（通过Gateway）

        Args:
            symbol: 合约代码
            interval: K线周期

        Returns:
            Optional[pd.DataFrame]: K线数据框（如果成功），否则None
        """
        if self.gateway:
            return self.gateway.get_kline(symbol, interval)
        return None

    async def subscribe_symbol(self, symbol: Union[str, List[str]]) -> bool:
        """
        订阅合约行情（通过Gateway，异步版本）

        Args:
            symbol: 合约代码

        Returns:
            bool: 订阅是否成功
        """
        if self.gateway:
            await self.gateway.subscribe(symbol)
        return True

    async def subscribe_bars(self, symbol: str, interval: str) -> bool:
        """
        订阅合约行情（通过Gateway，异步版本）

        Args:
            symbol: 合约代码

        Returns:
            bool: 订阅是否成功
        """
        if self.gateway:
            await self.gateway.subscribe_bars(symbol, interval)
        return True

    def _emit_event(self, event_type: str, data: Any) -> None:
        """
        推送事件到事件引擎
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        try:
            if self.event_engine:
                self.event_engine.put(event_type, data)
        except Exception as e:
            logger.error(f"推送事件失败 [{event_type}]: {e}")

    def _emit_cmd_update_event(self, cmd: OrderCmd) -> None:
        """发送报单指令更新事件"""
        try:
            if self.event_engine:
                self.event_engine.put(EventTypes.ORDER_CMD_UPDATE, cmd)
        except Exception as e:
            logger.error(f"发送报单指令更新事件失败: {e}")

    async def _on_tick(self, tick):
        """Gateway tick回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.TICK_UPDATE, tick)

    async def _on_bar(self, bar):
        """Gateway bar回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.KLINE_UPDATE, bar)

    async def _on_order(self, order: OrderData):
        """Gateway order回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.ORDER_UPDATE, order)
        if order.status == OrderStatus.REJECTED and self.config.alert_wechat:
            send_wechat(f"账户[{self.account_id}]告警：{order.status_msg}")

    async def _on_trade(self, trade):
        """Gateway trade回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.TRADE_UPDATE, trade)

    async def _on_position(self, position):
        """Gateway position回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.POSITION_UPDATE, position)

    async def _on_account(self, account):
        """Gateway account回调 → EventEngine（异步版本）"""
        if self.event_engine:
            await self.event_engine.put_async(EventTypes.ACCOUNT_UPDATE, account)

    async def insert_order_cmd(self, cmd: OrderCmd) -> Optional[str]:
        """
        创建报单指令

        Args:
            symbol: 合约代码
            direction: 方向 BUY/SELL
            offset: 开平 OPEN/CLOSE
            volume: 总手数
            price: 限价（None=市价）
            split_strategy: 拆单策略 SIMPLE/TWAP
            max_volume_per_order: 单次最大报单手数
            order_interval: 报单间隔（秒）
            twap_duration: TWAP执行时长（秒）
            total_timeout: 总超时时间（秒）
            max_retries: 最大重试次数
            order_timeout: 单笔挂单超时时间（秒）

        Returns:
            指令ID
        """
        # 保存引用
        self._order_cmds[cmd.cmd_id] = cmd
        # 注册到执行器（注册即启动）
        if self._order_cmd_executor:
            await self._order_cmd_executor.register(cmd)

        if "策略-" in cmd.source and self.config.alert_wechat:
            send_wechat(
                f"账户[{self.account_id}提醒]：创建新的报单指令{cmd.cmd_id} {cmd.symbol} {cmd.offset} {cmd.direction} {cmd.volume}手"
            )

        logger.info(f"创建报单指令: {cmd.cmd_id} {cmd.symbol} {cmd.direction} {cmd.volume}手")
        return cmd.cmd_id

    async def cancel_order_cmd(self, cmd_id: str) -> bool:
        """
        取消报单指令（异步版本，使用后台任务）

        Args:
            cmd_id: 指令ID

        Returns:
            是否成功（立即返回，实际执行在后台）
        """
        if self._order_cmd_executor:
            # 使用 asyncio.create_task 在后台执行
            asyncio.create_task(self._order_cmd_executor.close(cmd_id))
            return True
        return False

    def get_order_cmd(self, cmd_id: str) -> Optional[dict]:
        """
        获取报单指令状态

        Args:
            cmd_id: 指令ID

        Returns:
            指令状态字典
        """
        cmd = self._order_cmds.get(cmd_id)
        if not cmd:
            return None

        return cmd.to_dict()

    def get_all_order_cmds(self) -> List[dict]:
        """
        获取所有报单指令状态

        Returns:
            指令状态字典列表
        """
        return [cmd.to_dict() for cmd in self._order_cmds.values()]

    def cleanup_finished_order_cmds(self):
        """
        清理已完成的报单指令
        """
        finished_cmds = [
            cmd_id
            for cmd_id, cmd in self._order_cmds.items()
            if cmd.is_finished
        ]
        for cmd_id in finished_cmds:
            # 从执行器注销
            if self._order_cmd_executor:
                self._order_cmd_executor.unregister(cmd_id)
            self._order_cmds.pop(cmd_id, None)
        if finished_cmds:
            logger.info(f"清理已完成指令: {len(finished_cmds)}个")
