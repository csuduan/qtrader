"""
Trader端告警处理器
监听ERROR级别日志并自动创建告警记录，推送给Manager
"""

from datetime import datetime
from typing import Optional

from src.models.object import AlarmData
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TraderAlarmHandler:
    """
    Trader端告警处理器

    捕获ERROR级别日志，包装成AlarmData推送给Manager
    """

    def __init__(self, account_id: str, socket_server):
        """
        初始化告警处理器

        Args:
            account_id: 账户ID
            socket_server: Socket服务器实例，用于推送告警
        """
        self.account_id = account_id
        self.socket_server = socket_server

    async def __call__(self, message) -> None:
        """
        处理日志记录

        Args:
            message: loguru消息对象
        """
        try:
            # 避免处理自己产生的错误日志
            record = message.record if hasattr(message, "record") else message

            # 获取模块名
            module = ""
            try:
                if isinstance(record, dict):
                    module = record.get("name", "")
                else:
                    module = getattr(record, "name", "")
            except Exception:
                pass

            # 跳过alarm_handler自身的错误
            if "alarm_handler" in str(module):
                return

            # 获取日志级别
            level = None
            try:
                if isinstance(record, dict):
                    level_obj = record.get("level")
                else:
                    level_obj = getattr(record, "level", None)

                if level_obj:
                    if isinstance(level_obj, tuple) and len(level_obj) > 0:
                        level = level_obj[0]
                    elif hasattr(level_obj, "name"):
                        level = level_obj.name
                    else:
                        level_str = str(level_obj)
                        level = "ERROR" if "ERROR" in level_str else None
            except Exception:
                pass

            if level != "ERROR":
                return

            # 获取日志消息
            log_message = ""
            try:
                if isinstance(record, dict):
                    log_message = record.get("message", "")
                else:
                    log_message = str(record) if hasattr(record, "__str__") else ""
            except Exception:
                log_message = str(record) if record else ""

            if not log_message:
                return

            # 构造告警数据
            now = datetime.now()
            alarm_data = AlarmData(
                account_id=self.account_id,
                alarm_date=now.strftime("%Y-%m-%d"),
                alarm_time=now.strftime("%H:%M:%S"),
                source="TRADER",
                title=f"Trader错误: {module or '未知模块'}",
                detail=log_message,
                status="UNCONFIRMED",
                created_at=now,
            )

            # 推送给Manager
            if self.socket_server:
                await self.socket_server.send_push("alarm", alarm_data.model_dump())
                logger.info(f"告警已推送到Manager: {alarm_data.title}")
            else:
                logger.warning("Socket服务器未初始化，告警未推送")

        except Exception as e:
            # 避免告警处理器自身出错导致日志系统异常
            import traceback

            print(f"Trader告警处理器异常: {e}")
            traceback.print_exc()
