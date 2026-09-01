"""
风控模块
实现交易风险控制功能
"""

import threading
from datetime import datetime, time

from qtrader.utils.config_loader import RiskControlConfig
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class RiskControl:
    """风控管理类"""

    def __init__(self, config: RiskControlConfig, account_id: str | None = None):
        """
        初始化风控模块

        Args:
            config: 风控配置
            account_id: 账户ID，用于持久化计数器到数据库
        """
        self.config = config
        self.account_id = account_id
        self.daily_order_count = 0
        self.daily_cancel_count = 0
        self._last_reset_date: datetime | None = None
        # 计数器延迟保存定时器（合并高频写入，避免每次下单/撤单都同步写库）
        self._save_timer: threading.Timer | None = None

        # 从数据库加载当日计数（如果配置了账户ID）
        if account_id:
            self._load_counters()

        logger.info(
            f"风控模块初始化完成 - 最大报单次数: {config.max_daily_orders}, "
            f"最大撤单次数: {config.max_daily_cancels}, "
            f"最大报单手数: {config.max_order_volume}"
        )

    def _load_counters(self) -> None:
        """从数据库加载当日计数器"""
        try:
            from qtrader.models.po import SystemParamPo
            from qtrader.utils.database import session_scope

            with session_scope() as session:
                today = datetime.now().strftime("%Y-%m-%d")
                order_record = (
                    session.query(SystemParamPo)
                    .filter(
                        SystemParamPo.account_id == self.account_id,
                        SystemParamPo.param_key == "risk_control.daily_order_count",
                        SystemParamPo.group == f"risk_control_{today}",
                    )
                    .first()
                )
                cancel_record = (
                    session.query(SystemParamPo)
                    .filter(
                        SystemParamPo.account_id == self.account_id,
                        SystemParamPo.param_key == "risk_control.daily_cancel_count",
                        SystemParamPo.group == f"risk_control_{today}",
                    )
                    .first()
                )

                if order_record:
                    self.daily_order_count = int(order_record.param_value or 0)
                if cancel_record:
                    self.daily_cancel_count = int(cancel_record.param_value or 0)

                self._last_reset_date = datetime.now()
                logger.info(
                    f"从数据库加载风控计数器: 报单={self.daily_order_count}, "
                    f"撤单={self.daily_cancel_count}"
                )
        except Exception as e:
            logger.warning(f"加载风控计数器失败: {e}")
            self.daily_order_count = 0
            self.daily_cancel_count = 0
            self._last_reset_date = None

    # 计数器延迟保存间隔（秒）
    _SAVE_DELAY = 5.0

    def _schedule_save_counters(self) -> None:
        """延迟保存计数器：5秒内的连续变更合并为一次写库，避免下单热路径同步IO"""
        if not self.account_id:
            return
        if self._save_timer and self._save_timer.is_alive():
            return
        self._save_timer = threading.Timer(self._SAVE_DELAY, self._save_counters)
        self._save_timer.daemon = True
        self._save_timer.start()

    def flush_counters(self) -> None:
        """停止前落库：取消延迟保存定时器并立即写入计数器"""
        if self._save_timer:
            self._save_timer.cancel()
            self._save_timer = None
        self._save_counters()

    def _save_counters(self) -> None:
        """保存计数器到数据库"""
        if not self.account_id:
            return

        try:
            from qtrader.models.po import SystemParamPo
            from qtrader.utils.database import session_scope

            today = datetime.now().strftime("%Y-%m-%d")
            group = f"risk_control_{today}"

            with session_scope() as session:
                for key, value in [
                    ("risk_control.daily_order_count", self.daily_order_count),
                    ("risk_control.daily_cancel_count", self.daily_cancel_count),
                ]:
                    record = (
                        session.query(SystemParamPo)
                        .filter(
                            SystemParamPo.account_id == self.account_id,
                            SystemParamPo.param_key == key,
                        )
                        .first()
                    )
                    if record:
                        record.param_value = str(value)  # type: ignore[assignment]
                        record.group = group  # type: ignore[assignment]
                    else:
                        session.add(
                            SystemParamPo(
                                account_id=self.account_id,
                                param_key=key,
                                param_value=str(value),
                                param_type="int",
                                group=group,
                            )
                        )
        except Exception as e:
            logger.warning(f"保存风控计数器失败: {e}")

    def _reset_if_new_day(self) -> None:
        """如果是新的一天，重置计数器"""
        now = datetime.now()

        if self._last_reset_date is None or self._last_reset_date.date() != now.date():
            self.daily_order_count = 0
            self.daily_cancel_count = 0
            self._last_reset_date = now
            logger.info("新的一天，风控计数器已重置")
            self._schedule_save_counters()

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
            logger.warning(f"风控拒绝: 已达到单日最大报单次数 {self.config.max_daily_orders}")
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
            logger.warning(f"风控拒绝: 已达到单日最大撤单次数 {self.config.max_daily_cancels}")
            return False

        return True

    def on_order_inserted(self) -> None:
        """报单成功后的回调"""
        self.daily_order_count += 1
        logger.debug(f"报单计数更新: {self.daily_order_count}/{self.config.max_daily_orders}")
        self._schedule_save_counters()

    def on_order_cancelled(self) -> None:
        """撤单成功后的回调"""
        self.daily_cancel_count += 1
        logger.debug(f"撤单计数更新: {self.daily_cancel_count}/{self.config.max_daily_cancels}")
        self._schedule_save_counters()

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
