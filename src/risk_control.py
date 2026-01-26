"""
风控模块
实现交易风险控制功能
"""
from datetime import datetime, time
from typing import Optional

from src.config_loader import RiskControlConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class RiskControl:
    """风控管理类"""

    def __init__(self, config: RiskControlConfig):
        """
        初始化风控模块

        Args:
            config: 风控配置
        """
        self.config = config
        self.daily_order_count = 0
        self.daily_cancel_count = 0
        self._last_reset_date: Optional[datetime] = None

        logger.info(
            f"风控模块初始化完成 - 最大报单次数: {config.max_daily_orders}, "
            f"最大撤单次数: {config.max_daily_cancels}, "
            f"最大报单手数: {config.max_order_volume}"
        )

    def _reset_if_new_day(self) -> None:
        """如果是新的一天，重置计数器"""
        now = datetime.now()

        if self._last_reset_date is None or self._last_reset_date.date() != now.date():
            self.daily_order_count = 0
            self.daily_cancel_count = 0
            self._last_reset_date = now
            logger.info("新的一天，风控计数器已重置")

    def check_order(self, volume: int) -> bool:
        """
        检查订单是否符合风控要求

        Args:
            volume: 报单手数

        Returns:
            bool: 是否通过风控检查
        """
        self._reset_if_new_day()

        # 检查单日最大报单次数
        if self.daily_order_count >= self.config.max_daily_orders:
            logger.warning(
                f"风控拒绝: 已达到单日最大报单次数 {self.config.max_daily_orders}"
            )
            return False

        # 检查单笔最大报单手数
        if volume > self.config.max_order_volume:
            logger.warning(
                f"风控拒绝: 报单手数 {volume} 超过单笔最大手数 {self.config.max_order_volume}"
            )
            return False

        return True

    def check_cancel(self) -> bool:
        """
        检查撤单是否符合风控要求

        Returns:
            bool: 是否通过风控检查
        """
        self._reset_if_new_day()

        # 检查单日最大撤单次数
        if self.daily_cancel_count >= self.config.max_daily_cancels:
            logger.warning(
                f"风控拒绝: 已达到单日最大撤单次数 {self.config.max_daily_cancels}"
            )
            return False

        return True

    def on_order_inserted(self) -> None:
        """报单成功后的回调"""
        self.daily_order_count += 1
        logger.debug(f"报单计数更新: {self.daily_order_count}/{self.config.max_daily_orders}")

    def on_order_cancelled(self) -> None:
        """撤单成功后的回调"""
        self.daily_cancel_count += 1
        logger.debug(f"撤单计数更新: {self.daily_cancel_count}/{self.config.max_daily_cancels}")

    def get_status(self) -> dict:
        """
        获取风控状态

        Returns:
            风控状态字典
        """
        self._reset_if_new_day()
        return {
            "daily_order_count": self.daily_order_count,
            "daily_cancel_count": self.daily_cancel_count,
            "max_daily_orders": self.config.max_daily_orders,
            "max_daily_cancels": self.config.max_daily_cancels,
            "max_order_volume": self.config.max_order_volume,
            "max_split_volume": self.config.max_split_volume,
            "order_timeout": self.config.order_timeout,
            "remaining_orders": self.config.max_daily_orders - self.daily_order_count,
            "remaining_cancels": self.config.max_daily_cancels - self.daily_cancel_count,
        }
