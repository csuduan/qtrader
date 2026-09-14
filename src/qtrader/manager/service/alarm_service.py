"""
告警服务模块
统一管理通知告警和异常告警
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from qtrader.models.object import AlarmType
from qtrader.utils.logger import get_logger
from qtrader.utils.wecomm import is_dnd_now, send_wechat

if TYPE_CHECKING:
    from qtrader.manager.trading_manager import TradingManager

logger = get_logger(__name__)


@dataclass
class SuppressionStatus:
    """压制状态（仅存内存）"""

    indicator: str  # 指标名称: 1min/5min/1hour
    suppressed_at: datetime  # 压制开始时间
    alarm_id: int  # 触发的告警ID
    is_active: bool = True  # 是否有效


class AlarmService:
    """告警服务：统一管理通知告警和异常告警"""

    def __init__(self, trading_manager: "TradingManager"):
        self.trading_manager = trading_manager
        # 压制状态缓存（仅存内存）: {account_id: {indicator: SuppressionStatus}}
        self._suppression_cache: dict[str, dict[str, SuppressionStatus]] = {}

    @logger.catch(message="检查异常阈值失败")
    async def check_exception_thresholds(self) -> None:
        """
        定时检查异常阈值（每分钟执行）

        流程：查询各账户各指标异常数 -> 检查阈值 -> 未压制则触发告警 -> 设置压制状态
        """
        from sqlalchemy import func, select

        from qtrader.models.po import AlarmPo
        from qtrader.utils.async_database import get_async_session

        app_config = self.trading_manager.app_config
        if not app_config or not app_config.alert.exception.enabled:
            return

        async with get_async_session() as session:
            now = datetime.now()
            for account_id in self.trading_manager.account_configs_map:
                for indicator_config in app_config.alert.exception.indicators:
                    indicator = indicator_config.name
                    threshold = indicator_config.threshold
                    window = indicator_config.window
                    # 查询数据库统计窗口内异常数
                    window_start = now - timedelta(seconds=window)
                    base_filter = (
                        AlarmPo.account_id == account_id,
                        AlarmPo.created_at >= window_start,
                        AlarmPo.alarm_type == AlarmType.EXCEPTION,
                        AlarmPo.source != "EXCEPTION_MONITOR",  # 排除阈值告警本身
                    )
                    count = (
                        await session.execute(
                            select(func.count()).select_from(AlarmPo).filter(*base_filter)
                        )
                    ).scalar_one()
                    if count >= threshold:
                        if self._is_suppressed(account_id, indicator):
                            logger.debug(f"[{account_id}] {indicator} 异常告警已压制")
                            continue
                        # 查询最近一次异常作为详情
                        last_alarm = await session.scalar(
                            select(AlarmPo).filter(*base_filter).order_by(AlarmPo.created_at.desc())
                        )
                        source_data = {"title": last_alarm.title if last_alarm else "未知异常"}
                        await self._trigger_exception_alarm(
                            account_id, indicator, count, threshold, source_data
                        )

    async def _trigger_exception_alarm(
        self,
        account_id: str,
        indicator: str,
        count: int,
        threshold: int,
        source_data: dict[str, Any],
    ) -> None:
        """触发异常告警并设置压制"""
        app_config = self.trading_manager.app_config

        title = f"【异常】【{account_id}】{indicator}异常次数超过{threshold}"
        detail = (
            f"最近{indicator}内发生{count}次异常，请检查。"
            f"最近一次异常：{source_data.get('title', '')}"
        )

        # 免打扰检查
        if self._is_dnd(app_config.alert.exception.dnd_start, app_config.alert.exception.dnd_end):
            logger.debug("免打扰时段，跳过异常告警通知")
        else:
            try:
                send_wechat(f"{title}\n{detail}")
            except Exception as e:
                logger.error("发送异常告警通知失败: {!r}", e)

        # 设置压制状态（仅内存，不推送给前端）
        self._set_suppression(account_id, indicator)

    def _set_suppression(self, account_id: str, indicator: str) -> None:
        """设置压制状态（仅内存）"""
        if account_id not in self._suppression_cache:
            self._suppression_cache[account_id] = {}

        self._suppression_cache[account_id][indicator] = SuppressionStatus(
            indicator=indicator,
            suppressed_at=datetime.now(),
            alarm_id=0,
            is_active=True,
        )

        logger.info(f"设置异常告警压制: [{account_id}] {indicator}")

    def _is_suppressed(self, account_id: str, indicator: str) -> bool:
        """检查是否已压制"""
        if account_id not in self._suppression_cache:
            return False
        suppression = self._suppression_cache[account_id].get(indicator)
        if not suppression:
            return False
        return suppression.is_active

    def clear_suppression(self, account_id: str, indicator: str | None = None) -> None:
        """
        清除压制状态

        Args:
            account_id: 账户ID
            indicator: 指标类型，None表示清除该账户所有压制
        """
        if account_id not in self._suppression_cache:
            return

        if indicator:
            suppression = self._suppression_cache[account_id].get(indicator)
            if suppression:
                suppression.is_active = False
                logger.info(f"清除异常告警压制: [{account_id}] {indicator}")
        else:
            for ind in self._suppression_cache[account_id]:
                self._suppression_cache[account_id][ind].is_active = False
            logger.info(f"清除异常告警压制: [{account_id}] 所有指标")

    def clear_all_suppression(self) -> None:
        """清除所有压制状态（Manager重启时调用）"""
        for account_id in list(self._suppression_cache.keys()):
            self.clear_suppression(account_id)
        self._suppression_cache.clear()
        logger.info("已清除所有异常告警压制状态")

    def get_suppression_status(
        self, account_id: str | None = None
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """
        获取压制状态

        Returns:
            {"DQ": {"1min": {"suppressed": true, "since": "..."}, ...}}
        """
        result: dict[str, dict[str, dict[str, Any]]] = {}
        accounts = [account_id] if account_id else list(self._suppression_cache.keys())

        for acc in accounts:
            if acc not in self._suppression_cache:
                continue
            result[acc] = {}
            for indicator, status in self._suppression_cache[acc].items():
                result[acc][indicator] = {
                    "suppressed": status.is_active,
                    "since": status.suppressed_at.isoformat() if status.is_active else None,
                    "alarm_id": status.alarm_id if status.is_active else None,
                }
        return result

    def _is_dnd(self, start: int, end: int) -> bool:
        """检查是否免打扰时段"""
        return is_dnd_now(start, end)

    def notify_alarm(
        self,
        account_id: str,
        source: str,
        title: str,
        detail: str,
    ) -> None:
        """
        通知告警 - 仅发送微信通知，不保存到数据库（日志已自动保存）

        Args:
            account_id: 账户ID
            source: 告警来源
            title: 告警标题（不需要包含类型前缀）
            detail: 告警详情
        """
        app_config = self.trading_manager.app_config
        if not app_config:
            return

        config = app_config.alert.notification
        full_title = f"【通知】【{account_id}】{title}"
        logger.info(f"告警通知: {full_title}")

        # 发送微信通知
        try:
            # 开启通知且不在免打扰时间
            if config.enabled and not self._is_dnd(config.dnd_start, config.dnd_end):
                send_wechat(f"{full_title}\n{detail}")
        except Exception as e:
            logger.error("发送告警通知失败: {!r}", e)
