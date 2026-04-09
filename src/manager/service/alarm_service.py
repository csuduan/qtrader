"""
告警服务模块
统一管理通知告警和异常告警
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.models.object import AlarmType
from src.utils.logger import get_logger
from src.utils.wecomm import is_dnd_now, send_wechat

if TYPE_CHECKING:
    from src.manager.trading_manager import TradingManager
    from src.models.po import AlarmPo

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
        self._suppression_cache: Dict[str, Dict[str, SuppressionStatus]] = {}

    async def handle_notification(self, data: Dict) -> None:
        """
        处理通知告警

        流程：检查开关 -> 检查免打扰 -> 发送微信 -> 保存数据库 -> 推送WebSocket
        """
        from src.manager.api.responses import success_response

        app_config = self.trading_manager.app_config
        if not app_config or not app_config.alert.notification.enabled:
            return

        # 免打扰检查
        if self._is_dnd(
            app_config.alert.notification.dnd_start, app_config.alert.notification.dnd_end
        ):
            logger.debug("免打扰时段，跳过通知告警")
            return

        account_id = data.get("account_id", "SYSTEM")
        title = f"【通知】【{account_id}】{data.get('title', '')}"
        detail = data.get("detail", "")

        # 发送微信
        try:
            send_wechat(f"{title}\n{detail}")
        except Exception as e:
            logger.error(f"发送通知告警失败: {e}")

        # 保存数据库
        try:
            alarm = self._save_alarm(
                {
                    "account_id": account_id,
                    "title": data.get("title", ""),
                    "detail": detail,
                    "source": data.get("source", "TRADER"),
                },
                alarm_type=AlarmType.NOTIFICATION,
                title=title,
            )
            # 推送WebSocket
            self._emit_alarm_event(alarm)
        except Exception as e:
            logger.error(f"保存通知告警失败: {e}")

    async def handle_exception(self, data: Dict) -> None:
        """
        处理异常日志（仅保存到数据库，统计由定时任务完成）

        流程：保存异常记录 -> 供定时任务统计
        """
        # 异常记录已在 _save_alarm_to_db 中保存
        # 定时任务 check_exception_thresholds 会每分钟查询统计
        pass

    async def check_exception_thresholds(self) -> None:
        """
        定时检查异常阈值（每分钟执行）

        流程：查询各账户各指标异常数 -> 检查阈值 -> 未压制则触发告警 -> 设置压制状态
        """
        from src.models.po import AlarmPo
        from src.utils.database import get_session

        app_config = self.trading_manager.app_config
        if not app_config or not app_config.alert.exception.enabled:
            return

        session = get_session()
        if not session:
            logger.error("无法获取数据库会话，跳过异常阈值检查")
            return

        try:
            now = datetime.now()

            for account_id in self.trading_manager.account_configs_map.keys():
                for indicator_config in app_config.alert.exception.indicators:
                    indicator = indicator_config.name
                    threshold = indicator_config.threshold
                    window = indicator_config.window

                    # 查询数据库统计窗口内异常数
                    window_start = now - timedelta(seconds=window)
                    count = (
                        session.query(AlarmPo)
                        .filter(
                            AlarmPo.account_id == account_id,
                            AlarmPo.created_at >= window_start,
                            AlarmPo.alarm_type == AlarmType.EXCEPTION,
                            AlarmPo.source != "EXCEPTION_MONITOR",  # 排除阈值告警本身
                        )
                        .count()
                    )

                    if count >= threshold:
                        if self._is_suppressed(account_id, indicator):
                            logger.debug(f"[{account_id}] {indicator} 异常告警已压制")
                            continue

                        # 查询最近一次异常作为详情
                        last_alarm = (
                            session.query(AlarmPo)
                            .filter(
                                AlarmPo.account_id == account_id,
                                AlarmPo.created_at >= window_start,
                                AlarmPo.alarm_type == AlarmType.EXCEPTION,
                                AlarmPo.source != "EXCEPTION_MONITOR",
                            )
                            .order_by(AlarmPo.created_at.desc())
                            .first()
                        )

                        source_data = {"title": last_alarm.title if last_alarm else "未知异常"}

                        await self._trigger_exception_alarm(
                            account_id, indicator, count, threshold, source_data
                        )

        except Exception as e:
            logger.exception(f"检查异常阈值失败: {e}")
        finally:
            session.close()

    async def _trigger_exception_alarm(
        self, account_id: str, indicator: str, count: int, threshold: int, source_data: Dict
    ) -> None:
        """触发异常告警并设置压制"""
        app_config = self.trading_manager.app_config

        title = f"【异常】【{account_id}】{indicator}异常次数超过{threshold}"
        detail = (
            f"最近{indicator}内发生{count}次异常，请检查。"
            f"最近一次异常：{source_data.get('title', '')}"
        )

        # 免打扰检查
        if self._is_dnd(
            app_config.alert.exception.dnd_start, app_config.alert.exception.dnd_end
        ):
            logger.debug("免打扰时段，跳过异常告警通知")
        else:
            try:
                send_wechat(f"{title}\n{detail}")
            except Exception as e:
                logger.error(f"发送异常告警通知失败: {e}")

        # 保存告警到数据库
        try:
            alarm = self._save_alarm(
                {
                    "account_id": account_id,
                    "title": title,
                    "detail": detail,
                    "source": "EXCEPTION_MONITOR",
                },
                alarm_type=AlarmType.EXCEPTION,
                indicator=indicator,
            )

            # 设置压制状态（仅内存）
            self._set_suppression(account_id, indicator, int(alarm.id))  # type: ignore[arg-type]

            # 推送WebSocket
            self._emit_alarm_event(alarm)
        except Exception as e:
            logger.error(f"保存异常告警失败: {e}")

    def _set_suppression(self, account_id: str, indicator: str, alarm_id: int) -> None:
        """设置压制状态（仅内存）"""
        if account_id not in self._suppression_cache:
            self._suppression_cache[account_id] = {}

        self._suppression_cache[account_id][indicator] = SuppressionStatus(
            indicator=indicator,
            suppressed_at=datetime.now(),
            alarm_id=alarm_id,
            is_active=True,
        )

        logger.info(f"设置异常告警压制: [{account_id}] {indicator}")

        # 广播压制状态更新
        self._broadcast_suppression_update(account_id, indicator)

    def _is_suppressed(self, account_id: str, indicator: str) -> bool:
        """检查是否已压制"""
        if account_id not in self._suppression_cache:
            return False
        suppression = self._suppression_cache[account_id].get(indicator)
        if not suppression:
            return False
        return suppression.is_active

    def clear_suppression(self, account_id: str, indicator: Optional[str] = None) -> None:
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
                self._broadcast_suppression_update(account_id, indicator)
        else:
            for ind in self._suppression_cache[account_id]:
                self._suppression_cache[account_id][ind].is_active = False
                self._broadcast_suppression_update(account_id, ind)
            logger.info(f"清除异常告警压制: [{account_id}] 所有指标")

    def clear_all_suppression(self) -> None:
        """清除所有压制状态（Manager重启时调用）"""
        for account_id in list(self._suppression_cache.keys()):
            self.clear_suppression(account_id)
        self._suppression_cache.clear()
        logger.info("已清除所有异常告警压制状态")

    def get_suppression_status(self, account_id: Optional[str] = None) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        获取压制状态

        Returns:
            {"DQ": {"1min": {"suppressed": true, "since": "..."}, ...}}
        """
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
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

    def _save_alarm(self, data: Dict, alarm_type: str = "exception", **kwargs) -> "AlarmPo":
        """保存告警到数据库"""
        from src.models.po import AlarmPo
        from src.utils.database import get_session

        session = get_session()
        if not session:
            raise RuntimeError("无法获取数据库会话")

        try:
            now = datetime.now()
            alarm = AlarmPo(
                account_id=data.get("account_id", "SYSTEM"),
                alarm_type=alarm_type,
                indicator=kwargs.get("indicator"),
                alarm_date=now.strftime("%Y-%m-%d"),
                alarm_time=now.strftime("%H:%M:%S"),
                source=data.get("source", "SYSTEM"),
                title=kwargs.get("title", data.get("title", "")),
                detail=data.get("detail"),
                status="UNCONFIRMED",
            )
            session.add(alarm)
            session.commit()
            session.refresh(alarm)
            logger.info(f"告警已保存: {alarm.title}")
            return alarm
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    def _emit_alarm_event(self, alarm: "AlarmPo") -> None:
        """推送告警事件到WebSocket"""
        from src.app_context import get_app_context
        from src.utils.event_engine import EventTypes

        ctx = get_app_context()
        if not ctx:
            return

        event_engine = ctx.get_event_engine()
        if not event_engine:
            return

        alarm_dict = {
            "id": alarm.id,
            "account_id": alarm.account_id,
            "alarm_type": alarm.alarm_type,
            "indicator": alarm.indicator,
            "alarm_date": alarm.alarm_date,
            "alarm_time": alarm.alarm_time,
            "source": alarm.source,
            "title": alarm.title,
            "detail": alarm.detail,
            "status": alarm.status,
            "created_at": alarm.created_at.isoformat() if alarm.created_at else None,
        }
        event_engine.put(EventTypes.ALARM_UPDATE, alarm_dict)

    def _broadcast_suppression_update(self, account_id: str, indicator: str) -> None:
        """广播压制状态更新"""
        from src.app_context import get_app_context

        ctx = get_app_context()
        if not ctx:
            return

        ws_manager = ctx.get_ws_manager()
        if not ws_manager:
            return

        status = self.get_suppression_status(account_id)
        ws_manager.broadcast_suppression_update(account_id, indicator, status)
