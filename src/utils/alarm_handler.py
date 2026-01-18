"""
告警日志处理器
监听ERROR级别日志并自动创建告警记录
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.database import get_session
from src.models.po import AlarmPo
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_alarm_from_log(
    log_message: str,
    module: Optional[str] = None,
    function: Optional[str] = None
) -> bool:
    """
    从日志记录创建告警

    Args:
        log_message: 日志消息
        module: 模块名
        function: 函数名

    Returns:
        是否创建成功
    """
    try:
        session = get_session()
        if not session:
            logger.error("获取数据库会话失败")
            return False

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        alarm = AlarmPo(
            account_id="SYSTEM",
            alarm_date=today,
            alarm_time=time_str,
            source="LOG",
            title=f"系统错误: {module or '未知模块'}",
            detail=log_message,
            status="UNCONFIRMED"
        )

        session.add(alarm)
        session.commit()

        logger.info(f"告警已创建: {alarm.title}")
        return True
    except Exception as e:
        logger.error(f"创建告警失败: {e}", exc_info=True)
        return False
    finally:
        if session:
            session.close()


class AlarmHandler:
    """
    告警处理器
    用于捕获ERROR级别日志并创建告警记录
    """

    def __init__(self):
        self.alarm_interval = 300

    def __call__(self, record):
        """
        处理日志记录

        Args:
            record: 日志记录对象
        """
        if record["level"].name == "ERROR":
            log_message = record["message"]
            module = record.get("name")
            function = record.get("function")

            create_alarm_from_log(log_message, module, function)


alarm_handler = AlarmHandler()
