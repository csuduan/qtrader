"""
策略基类
定义策略的接口和基本功能
"""

from typing import TYPE_CHECKING, List, Optional

from src.models.object import (
    BarData,
    Offset,
    OrderData,
    TickData,
    TradeData,
)
from src.trader.order_cmd import OrderCmd
from src.utils.logger import get_logger
from src.utils.config_loader import StrategyConfig
import pandas as pd

if TYPE_CHECKING:
    from src.trader.core.strategy_manager import StrategyManager

logger = get_logger(__name__)


class BaseStrategy:
    """策略基类"""

    # 订阅bar列表（格式："symbol-interval"）
    def __init__(self, strategy_id: str,strategy_config:StrategyConfig):
        self.strategy_id = strategy_id
        self.config: StrategyConfig = strategy_config
        self.active: bool = False
        self.inited: bool = False
        self.enabled: bool = True
        self.bar_subscriptions: List[str] = [] 
        # 策略管理器引用
        self.strategy_manager: Optional["StrategyManager"] = None

    def init(self,) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        return True

    def get_params(self) -> dict:
        """获取策略参数"""
        return {}

    def start(self) -> bool:
        """启动策略"""
        if not self.inited:
            self.init()
        self.active = True
        logger.info(f"策略 [{self.strategy_id}] 启动")
        return True

    def stop(self) -> bool:
        """停止策略"""
        self.active = False
        logger.info(f"策略 [{self.strategy_id}] 停止")
        return True

    # ==================== 事件回调 ====================
    def on_tick(self, tick: TickData):
        """Tick行情回调"""
        pass

    def on_bar(self, bar: BarData):
        """Bar行情回调"""
        pass

    def on_order(self, order: OrderData):
        """订单状态回调"""
        pass

    def on_trade(self, trade: TradeData):
        """成交回调"""
        pass

    # ==================== 交易接口 ====================
    def send_order_cmd(self,order_cmd:OrderCmd):
        self.order_cmds[order_cmd.cmd_id] = order_cmd

        """发送报单指令"""
        if not self.strategy_manager:
            logger.error("策略管理器未初始化，无法发送报单指令")
            return
        if not self.active:
            logger.warning(f"策略 [{self.strategy_id}] 未启动，无法发送报单指令")
            return
        self.strategy_manager.send_order_cmd(self.strategy_id,order_cmd)
    
    def cancel_order_cmd(self,order_cmd:OrderCmd):
        """取消报单指令"""
        if not self.strategy_manager:
            logger.error("策略管理器未初始化，无法取消报单指令")
            return
        if not self.active:
            logger.warning(f"策略 [{self.strategy_id}] 未启动，无法取消报单指令")
            return
        self.strategy_manager.cancel_order_cmd(self.strategy_id,order_cmd)
