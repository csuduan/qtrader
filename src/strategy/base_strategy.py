"""
策略基类
定义策略的接口和基本功能
"""
from typing import TYPE_CHECKING, Optional

from src.models.object import (
    TickData,
    BarData,
    OrderData,
    TradeData,
    Offset,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.strategy.strategy_manager import StrategyManager

logger = get_logger(__name__)


class BaseStrategy:
    """策略基类"""

    def __init__(self, strategy_id: str, config: dict):
        self.strategy_id = strategy_id
        self.config = config
        self.active: bool = False
        self.inited: bool = False

        # 策略管理器引用（代替直接的 trading_engine）
        self.strategy_manager: Optional["StrategyManager"] = None

    # ==================== 生命周期 ====================

    def init(self) -> bool:
        """策略初始化"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        return True

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

    def reload(self) -> bool:
        """重新加载策略参数"""
        logger.info(f"策略 [{self.strategy_id}] 重新加载参数...")
        return True

    def reset_for_new_day(self) -> bool:
        """
        每日开盘重置策略状态

        子类可以重写此方法实现具体的重置逻辑
        """
        logger.info(f"策略 [{self.strategy_id}] 每日重置")
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

    def buy(self, symbol: str, volume: int, price: Optional[float] = None,
            offset: Offset = Offset.OPEN) -> Optional[str]:
        """
        买入 - 通过策略管理器

        Args:
            symbol: 合约代码
            volume: 手数
            price: 价格（None为市价）
            offset: 开平标识

        Returns:
            委托单ID
        """
        if not self.active or not self.strategy_manager:
            logger.warning(f"策略 [{self.strategy_id}] 未激活或策略管理器未设置")
            return None

        try:
            return self.strategy_manager.buy(
                strategy_id=self.strategy_id,
                symbol=symbol,
                volume=volume,
                price=price,
                offset=offset
            )
        except Exception as e:
            logger.error(f"策略 [{self.strategy_id}] 买入失败: {e}")
            return None

    def sell(self, symbol: str, volume: int, price: Optional[float] = None,
             offset: Offset = Offset.CLOSE) -> Optional[str]:
        """
        卖出 - 通过策略管理器

        Args:
            symbol: 合约代码
            volume: 手数
            price: 价格（None为市价）
            offset: 开平标识

        Returns:
            委托单ID
        """
        if not self.active or not self.strategy_manager:
            logger.warning(f"策略 [{self.strategy_id}] 未激活或策略管理器未设置")
            return None

        try:
            return self.strategy_manager.sell(
                strategy_id=self.strategy_id,
                symbol=symbol,
                volume=volume,
                price=price,
                offset=offset
            )
        except Exception as e:
            logger.error(f"策略 [{self.strategy_id}] 卖出失败: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """
        撤单 - 通过策略管理器

        Args:
            order_id: 订单ID

        Returns:
            是否成功
        """
        if not self.active or not self.strategy_manager:
            logger.warning(f"策略 [{self.strategy_id}] 未激活或策略管理器未设置")
            return False

        try:
            return self.strategy_manager.cancel_order(
                strategy_id=self.strategy_id,
                order_id=order_id
            )
        except Exception as e:
            logger.error(f"策略 [{self.strategy_id}] 撤单失败: {e}")
            return False
