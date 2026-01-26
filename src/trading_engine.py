"""
交易引擎核心模块
负责连接API、管理交易会话、处理行情和交易
"""
import asyncio
import math
from datetime import datetime
import time
from typing import Any, Dict, List, Optional,Union
from threading import Thread


from src.config_loader import AppConfig
from src.risk_control import RiskControl
from src.utils.logger import get_logger
from src.utils.event import event_engine, EventTypes
from src.models.object import OrderRequest, Direction, Offset, CancelRequest
from src.models.object import TradeData



logger = get_logger(__name__)

class TradingEngine:
    """交易引擎类"""

    def __init__(self, config: AppConfig):
        """
        初始化交易引擎

        Args:
            config: 应用配置对象
        """
        self.config = config
        self.account_id = config.account_id

        self.gateway = None
        self.paused = config.trading.paused

        # 缓存的统一格式数据（从Gateway转换）
        # self.quotes: Dict[str, Any] = {}
        # self.positions: Dict[str, Any] = {}
        # self.orders: Dict[str, Any] = {}
        # self.trades: Dict[str, Any] = {}

        # 风控模块（使用配置文件中的默认值，启动后会从数据库加载）
        self.risk_control = RiskControl(config.risk_control)
        # 事件引擎
        self.event_engine = event_engine
        logger.info(f"交易引擎初始化完成，账户类型: {config.account_type}")
        
        # Gateway初始化 
        self._init_gateway()
        # 加载风控数据
        self.reload_risk_control_config()


    @property
    def connected(self) -> bool:
        return self.gateway.connected    
    
    @property
    def trades(self):
        return self.gateway.get_trades()
    
    @property
    def account(self):
        return self.gateway.get_account()
    
    @property
    def orders(self):
        return self.gateway.get_orders()
    
    @property
    def positions(self):
        return self.gateway.get_positions()
    
    @property
    def quotes(self):
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
        gateway_type = getattr(self.config, 'gateway_type', 'TQSDK')  
        logger.info(f"创建Gateway，类型: {gateway_type}")  
        if gateway_type == 'CTP':
            from src.adapters.ctp_gateway import CtpGateway
            self.gateway = CtpGateway(self)
            logger.info("CTP Gateway创建成功(框架实现，需CTP SDK)")
        else: # 默认TQSDK
            from src.adapters.tq_gateway import TqGateway
            self.gateway = TqGateway(self)
            logger.info("TqSdk Gateway创建成功")

        
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

    def connect(self) -> bool:
        """
        连接到交易系统（通过Gateway）

        Returns:
            bool: 连接是否成功
        """
        try:
            logger.info("连接到交易系统...")
            return self.gateway.connect()

        except Exception as e:
            logger.exception(f"连接失败: {e}")
            return False
    
    def disconnect(self) -> bool:
        """
        断开与交易系统的连接（通过Gateway）

        Returns:
            bool: 断开是否成功
        """
        try:
            logger.info("断开与交易系统的连接...")
            return self.gateway.disconnect()

        except Exception as e:
            logger.exception(f"断开连接失败: {e}")
            return False


    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
    ) -> Optional[str]:
        """
        下单

        Args:
            symbol: 合约代码，支持格式：合约编号(如a2605)、合约编号.交易所(如a2605.DCE)、交易所.合约编号(如DCE.a2605)
            direction: 方向 (BUY/SELL)
            offset: 开平 (OPEN/CLOSE/CLOSETODAY)
            volume: 手数
            price: 0-市价，>0限价

        Returns:
            Optional[str]: 委托单ID，失败返回None
        """
        if not self.gateway.connected:
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

            req = OrderRequest(
                symbol=symbol,
                direction=Direction(direction),
                offset=Offset(offset),
                volume=volume,
                price=price if price > 0 else None
            )

            order_id = self.gateway.send_order(req)

            if order_id:
                logger.bind(tags=["trade"]).info(
                    f"下单: {symbol} {direction} {offset} {volume}手 @{price if price > 0 else 'MARKET'}, 委托单ID: {order_id}"
                )
                # 更新风控计数
                self.risk_control.on_order_inserted()

            return order_id

        except Exception as e:
            raise Exception(f"下单失败: {e}")


    def cancel_order(self, order_id: str) -> bool:
        """
        撤单（通过Gateway）

        Args:
            order_id: 订单ID

        Returns:
            bool: 撤单是否成功
        """
        if self.gateway and self.gateway.connected:
            req = CancelRequest(order_id=order_id)
            return self.gateway.cancel_order(req)

        logger.warning("Gateway未初始化或未连接")
        return False

    def pause(self) -> None:
        """暂停交易"""
        self.paused = True
        logger.info("交易已暂停")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "paused",
            "timestamp": datetime.now().isoformat(),
        })

    def resume(self) -> None:
        """恢复交易"""
        self.paused = False
        logger.info("交易已恢复")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "running",
            "timestamp": datetime.now().isoformat(),
        })

    def get_status(self) -> Dict[str, Any]:
        """
        获取引擎状态

        Returns:
            状态字典
        """
        return {
            "connected": self.gateway.connected,
            "paused": self.paused,
            "account_id": getattr(self.account, "user_id", "") if self.account else "",
            "daily_orders": self.risk_control.daily_order_count,
            "daily_cancels": self.risk_control.daily_cancel_count,
        }

    def subscribe_symbol(self, symbol: Union[str, List[str]]) -> bool:
        """
        订阅合约行情（通过Gateway）

        Args:
            symbol: 合约代码

        Returns:
            bool: 订阅是否成功
        """
        if self.gateway:
            return self.gateway.subscribe(symbol)
        return False



    def _emit_event(self, event_type: str, data: Any) -> None:
        """
        推送事件到事件引擎
        Args:
            event_type: 事件类型
            data: 事件数据
        """
        try:
            self.event_engine.put(event_type, data)
        except Exception as e:
            logger.error(f"推送事件失败 [{event_type}]: {e}")

    
    def _on_tick(self, tick):
        """Gateway tick回调 → EventEngine"""
        self.event_engine.put(EventTypes.TICK_UPDATE, tick)
    
    def _on_bar(self, bar):
        """Gateway bar回调 → EventEngine"""
        bar_dict = {
            "symbol": f"{bar.symbol}.{bar.exchange.value}",
            "interval": bar.interval.value,
            "datetime": bar.datetime.isoformat(),
            "open_price": bar.open_price,
            "high_price": bar.high_price,
            "low_price": bar.low_price,
            "close_price": bar.close_price,
            "volume": bar.volume or 0,
        }
        self.event_engine.put(EventTypes.KLINE_UPDATE, bar_dict)
    
    def _on_order(self, order):
        """Gateway order回调 → EventEngine"""
        self.event_engine.put(EventTypes.ORDER_UPDATE, order)
    
    def _on_trade(self, trade):
        """Gateway trade回调 → EventEngine"""
        self.event_engine.put(EventTypes.TRADE_UPDATE, trade)
    
    def _on_position(self, position):
        """Gateway position回调 → EventEngine"""
        self.event_engine.put(EventTypes.POSITION_UPDATE, position)
    
    def _on_account(self, account):
        """Gateway account回调 → EventEngine"""
        self.event_engine.put(EventTypes.ACCOUNT_UPDATE, account)
