"""
交易引擎核心模块
负责连接TqSdk、管理交易会话、处理行情和交易
"""
import asyncio
import math
from datetime import datetime
import time
from typing import Any, Dict, List, Optional
from threading import Thread


# tqsdk已移至TqGateway，TradingEngine通过Gateway操作

from src.config_loader import AppConfig
from src.risk_control import RiskControl
from src.utils.helpers import nanos_to_datetime_str, parse_symbol
from src.utils.logger import get_logger
from src.utils.event import event_engine, EventTypes


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
        # Gateway实例（所有tqsdk操作通过gateway进行）
        self.gateway = None
        self.account: Optional[Any] = None
        self.connected = False
        self.paused = config.trading.paused
        self._running = False
        self._pending_disconnect = False

        # 缓存的统一格式数据（从Gateway转换）
        self.quotes: Dict[str, Any] = {}
        self.positions: Dict[str, Any] = {}
        self.orders: Dict[str, Any] = {}
        self.trades: Dict[str, Any] = {}

        # 风控模块（使用配置文件中的默认值，启动后会从数据库加载）
        self.risk_control = RiskControl(config.risk_control)

        self._hist_subs = set()

        # 事件引擎
        self.event_engine = event_engine

        logger.info(f"交易引擎初始化完成，账户类型: {config.account_type}")
        
        # ==================== Gateway初始化 ====================
        self.gateway = None
        self._init_gateway()

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
        from src.trading_engine_gateway import create_gateway
        
        self.gateway = create_gateway(self)
        logger.info(f"Gateway初始化完成: {self.gateway.gateway_name}")
        
        # 注册回调（Gateway → EventEngine）
        self.gateway.register_callbacks(
            on_tick=self._on_tick_from_gateway,
            on_bar=self._on_bar_from_gateway,
            on_order=self._on_order_from_gateway,
            on_trade=self._on_trade_from_gateway,
            on_position=self._on_position_from_gateway,
            on_account=self._on_account_from_gateway,
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
            logger.info("连接到交易系统（通过Gateway）...")

            if not self.gateway:
                from src.trading_engine_gateway import create_gateway
                self.gateway = create_gateway(self)

            return self.gateway.connect()

        except Exception as e:
            logger.error(f"连接失败: {e}", exc_info=True)
            return False

    def loop_run(self) -> None:
        """主循环运行"""
        while self._running:
            try:
                # 检查是否有待处理的断开连接请求
                if self._pending_disconnect:
                    self._do_disconnect()
                    break

                self.update()
            except Exception as e:
                logger.error(f"主循环更新出错: {e}")
            #sleep(1)


    def disconnect(self) -> None:
        """请求断开TqSdk连接（设置标志位，由主循环执行）"""
        if not self._pending_disconnect and self.connected:
            self._pending_disconnect = True
            logger.info("已设置断开连接请求")

    def _do_disconnect(self) -> None:
        """实际执行断开连接（在主循环中调用）"""
        if self.gateway:
            try:
                self.gateway.disconnect()
                logger.info("已断开连接")

                # 推送账户状态事件
                self._emit_event(EventTypes.ACCOUNT_STATUS, {
                    "account_id": self.config.account_id,
                    "status": "disconnected",
                    "timestamp": datetime.now().isoformat(),
                })

            except Exception as e:
                logger.error(f"断开连接时出错: {e}")
        self.connected = False
        self._pending_disconnect = False
        self._running = False

    def _init_risk_counts_from_orders(self) -> None:
        """根据orders列表初始化当日已发送的报单次数和撤单次数（已由Gateway处理）"""
        pass

    def _init_subscriptions(self) -> None:
        """初始化行情订阅（已由Gateway处理）"""
        pass

    def update(self) -> bool:
        """
        更新交易数据（在主循环中调用）

        数据更新现在由Gateway通过回调处理，此方法仅保持循环运行

        Returns:
            bool: 是否继续运行
        """
        if not self.connected or not self.gateway:
            return False

        try:
            # Gateway通过回调处理数据更新
            # 此方法仅用于保持循环运行和检查连接状态
            return True

        except Exception as e:
            logger.error(f"更新数据时出错: {e}", exc_info=e)
            self._emit_event(EventTypes.SYSTEM_ERROR, {"error": str(e)})
            return False

    def _check_and_save_account(self) -> None:
        """检查并推送账户信息（已由Gateway回调处理）"""
        pass

    def _check_and_save_positions(self) -> None:
        """检查并推送持仓信息（已由Gateway回调处理）"""
        pass

    def _check_and_save_orders(self) -> None:
        """检查并推送委托单信息（已由Gateway回调处理）"""
        pass

    def _check_and_save_trades(self) -> None:
        """检查并推送成交信息（已由Gateway回调处理）"""
        pass

    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
    ) -> Optional[str]:
        """
        下单（通过Gateway）

        Args:
            symbol: 合约代码，支持格式：合约编号(如a2605)、合约编号.交易所(如a2605.DCE)、交易所.合约编号(如DCE.a2605)
            direction: 方向 (BUY/SELL)
            offset: 开平 (OPEN/CLOSE/CLOSETODAY)
            volume: 手数
            price: 0-市价，>0限价

        Returns:
            Optional[str]: 委托单ID，失败返回None
        """
        if not self.connected or not self.gateway:
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
            from src.models.object import OrderRequest, Direction, Offset

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

    def _format_symbol(self, symbol: str) -> Optional[str]:
        """
        格式化合约代码

        Args:
            symbol: 合约代码，支持：
                    - 合约编号，如 a2605
                    - 合约编号.交易所，如 a2605.DCE
                    - 交易所.合约编号，如 DCE.a2605

        Returns:
            Optional[str]: 格式化后的合约代码（交易所.合约编号），失败返回None
        """
        if not symbol:
            return None

        return symbol

    def cancel_order(self, order_id: str) -> bool:
        """
        撤单（通过Gateway）

        Args:
            order_id: 订单ID

        Returns:
            bool: 撤单是否成功
        """
        if self.gateway and self.gateway.connected:
            from src.models.object import CancelRequest
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
            "connected": self.connected,
            "paused": self.paused,
            "account_id": getattr(self.account, "user_id", "") if self.account else "",
            "daily_orders": self.risk_control.daily_order_count,
            "daily_cancels": self.risk_control.daily_cancel_count,
        }

    def subscribe_symbol(self, symbol: str) -> bool:
        """
        订阅合约行情（通过Gateway）

        Args:
            symbol: 合约代码

        Returns:
            bool: 订阅是否成功
        """
        if self.gateway:
            from src.models.object import SubscribeRequest
            req = SubscribeRequest(symbols=[symbol])
            return self.gateway.subscribe(req)
        return False

    def is_subscribed(self, symbol: str) -> bool:
        """
        检查合约是否已订阅

        Args:
            symbol: 合约代码，支持多种格式

        Returns:
            bool: 是否已订阅
        """
        formatted_symbol = self._format_symbol(symbol)
        if not formatted_symbol:
            return False
        return formatted_symbol in self.quotes

    def get_subscribed_symbols(self) -> List[str]:
        """
        获取所有已订阅的合约代码

        Returns:
            List[str]: 已订阅的合约代码列表
        """
        return list(self.quotes.keys())

    def unsubscribe_symbol(self, symbol: str) -> bool:
        """
        取消订阅合约行情（通过Gateway）

        Args:
            symbol: 合约代码

        Returns:
            bool: 取消订阅是否成功
        """
        if self.gateway:
            from src.models.object import SubscribeRequest
            req = SubscribeRequest(symbols=[symbol])
            return self.gateway.unsubscribe(req)
        return False

    def _check_and_emit_tick_updates(self) -> None:
        """检查并推送tick行情更新事件（已由Gateway回调处理）"""
        pass

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

    # ==================== Gateway适配器支持 ====================

    def init_gateway_adapter(self):
        """
        初始化Gateway适配器（新增功能）

        将TqGateway包装在TradingEngine外层，支持多接口切换
        """
        from src.adapters.tq_gateway import TqGateway

        self.gateway_adapter = TqGateway(self)
        logger.info("Gateway适配器初始化完成（TqSdk）")

    def connect_gateway(self) -> bool:
        """通过Gateway适配器连接（新增）"""
        if hasattr(self, 'gateway_adapter'):
            return self.gateway_adapter.connect()
        return self.connect()

    def send_order_via_gateway(self, symbol: str, direction: str, offset: str,
                            volume: int, price: float = 0) -> Optional[str]:
        """通过Gateway适配器下单（新增）"""
        if not hasattr(self, 'gateway_adapter'):
            return self.insert_order(symbol, direction, offset, volume, price)

        from src.models.object import OrderRequest, Direction, Offset
        req = OrderRequest(
            symbol=symbol,
            direction=Direction(direction),
            offset=Offset(offset),
            volume=volume,
            price=price if price > 0 else None
        )
        return self.gateway_adapter.send_order(req)

    def cancel_order_via_gateway(self, order_id: str) -> bool:
        """通过Gateway适配器撤单（新增）"""
        if not hasattr(self, 'gateway_adapter'):
            return self.cancel_order(order_id)

        from src.models.object import CancelRequest
        req = CancelRequest(order_id=order_id)
        return self.gateway_adapter.cancel_order(req)

    # ==================== 策略系统支持 ====================

    def init_strategy_system(self, config_path: str = "config/strategies.yaml"):
        """
        初始化策略系统（新增功能）

        Args:
            config_path: 策略配置文件路径
        """
        from src.strategy.strategy_manager import StrategyManager

        self.strategy_manager = StrategyManager()
        if self.strategy_manager.load_config(config_path):
            logger.info("策略系统初始化完成")
            return True
        return False

    def register_strategy_callbacks(self):
        """注册策略系统到Gateway（新增）"""
        if not hasattr(self, 'strategy_manager'):
            return

        if not hasattr(self, 'gateway_adapter'):
            logger.warning("Gateway适配器未初始化，无法注册策略回调")
            return

        # 注册策略回调
        self.gateway_adapter.register_strategy_callbacks(
            on_tick=lambda tick: self._dispatch_to_strategies('on_tick', tick),
            on_bar=lambda bar: self._dispatch_to_strategies('on_bar', bar)
        )

    def _dispatch_to_strategies(self, method: str, data):
        """分发数据到所有策略（新增）"""
        for name, strategy in self.strategy_manager.strategies.items():
            if strategy.active:
                try:
                    getattr(strategy, method)(data)
                except Exception as e:
                    logger.error(f"策略 {name} {method} 失败: {e}", exc_info=True)

    def start_all_strategies(self):
        """启动所有已启用的策略（新增）"""
        if hasattr(self, 'strategy_manager'):
            self.strategy_manager.start_all()

    def stop_all_strategies(self):
        """停止所有策略（新增）"""
        if hasattr(self, 'strategy_manager'):
            self.strategy_manager.stop_all()

    def get_strategy_status(self) -> list:
        """获取所有策略状态（新增）"""
        if hasattr(self, 'strategy_manager'):
            return self.strategy_manager.get_status()
        return []

    # ==================== Gateway回调方法 ====================
    
    def _on_tick_from_gateway(self, tick):
        """Gateway tick回调 → EventEngine"""
        # 转换为字典格式（保持兼容性）
        tick_dict = {
            "symbol": f"{tick.symbol}.{tick.exchange.value}",
            "last_price": tick.last_price,
            "volume": tick.volume or 0,
            "datetime": tick.datetime.isoformat(),
            "bid_price1": tick.bid_price_1,
            "ask_price1": tick.ask_price_1,
            "bid_volume1": tick.bid_volume_1,
            "ask_volume1": tick.ask_volume_1,
            "open_price": tick.open_price,
            "high_price": tick.high_price,
            "low_price": tick.low_price,
            "limit_up": tick.limit_up,
            "limit_down": tick.limit_down,
        }
        self.event_engine.put(EventTypes.TICK_UPDATE, tick_dict)
    
    def _on_bar_from_gateway(self, bar):
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
    
    def _on_order_from_gateway(self, order):
        """Gateway order回调 → EventEngine"""
        order_dict = {
            "order_id": order.order_id,
            "symbol": f"{order.symbol}.{order.exchange.value}",
            "direction": order.direction.value,
            "offset": order.offset.value,
            "volume_orign": order.volume,
            "volume_left": order.volume_left,
            "limit_price": order.price,
            "price_type": order.price_type.value,
            "status": order.status.value,
            "status_msg": order.status_msg,
            "gateway_order_id": order.gateway_order_id,
            "insert_date_time": int(order.insert_time.timestamp() * 1e9) if order.insert_time else 0,
        }
        self.event_engine.put(EventTypes.ORDER_UPDATE, order_dict)
    
    def _on_trade_from_gateway(self, trade):
        """Gateway trade回调 → EventEngine"""
        trade_dict = {
            "trade_id": trade.trade_id,
            "order_id": trade.order_id,
            "symbol": f"{trade.symbol}.{trade.exchange.value}",
            "direction": trade.direction.value,
            "offset": trade.offset.value,
            "price": trade.price,
            "volume": trade.volume,
            "trade_date_time": int(trade.trade_time.timestamp() * 1e9) if trade.trade_time else 0,
        }
        self.event_engine.put(EventTypes.TRADE_UPDATE, trade_dict)
    
    def _on_position_from_gateway(self, position):
        """Gateway position回调 → EventEngine"""
        pos_dict = {
            "symbol": f"{position.symbol}.{position.exchange.value}",
            "pos_long": position.volume if position.direction.value == "LONG" else 0,
            "pos_short": position.volume if position.direction.value == "SHORT" else 0,
            "open_price_long": position.avg_price if position.direction.value == "LONG" else 0,
            "open_price_short": position.avg_price if position.direction.value == "SHORT" else 0,
            "float_profit": position.hold_profit or 0,
            "margin": position.margin or 0,
        }
        self.event_engine.put(EventTypes.POSITION_UPDATE, pos_dict)
    
    def _on_account_from_gateway(self, account):
        """Gateway account回调 → EventEngine"""
        acc_dict = {
            "account_id": account.account_id,
            "balance": account.balance,
            "available": account.available,
            "frozen": account.frozen or 0,
            "margin": account.margin or 0,
            "float_profit": account.hold_profit or 0,
            "position_profit": account.hold_profit or 0,
            "close_profit": account.close_profit or 0,
            "risk_ratio": account.risk_ratio or 0,
        }
        self.event_engine.put(EventTypes.ACCOUNT_UPDATE, acc_dict)
