"""
告警日志处理器
监听ERROR级别日志并自动创建告警记录
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.app_context import get_app_context
from src.models.po import AlarmPo
from src.utils.database import get_session
from src.utils.event_engine import EventTypes
from src.utils.logger import get_logger

logger = get_logger(__name__)


import re


def extract_account_id_from_message(message: str) -> Optional[str]:
    """
    从日志消息中提取账户ID

    常见的账户ID格式：
    -  trader-XXXX
    -  账户ID: XXXX
    -  account_id: XXXX
    """
    if not message:
        return None

    # 匹配常见的账户ID模式
    patterns = [
        r'账户\[?([^\]]+)\]?',  # 账户[DQ] 或 账户DQ
        r'account_id[:=]\s*(\w+)',  # account_id: DQ 或 account_id=DQ
        r'trader[-_](\w+)',  # trader-DQ 或 trader_DQ
        r'account[:=]\s*(\w+)',  # account: DQ
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def create_alarm_from_log(
    log_message: str,
    module: Optional[str] = None,
    function: Optional[str] = None,
    extra: Optional[dict] = None
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
    session = None
    try:
        session = get_session()
        if not session:
            logger.warning("获取数据库会话失败，告警未保存到数据库")
            return False

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        # 尝试从 extra 或消息中提取账户ID
        account_id = None
        if extra and isinstance(extra, dict):
            account_id = extra.get('account_id')
        if not account_id:
            account_id = extract_account_id_from_message(log_message)
        if not account_id:
            account_id = "SYSTEM"

        # 格式化标题：【即时告警】【账户ID】模块错误
        title = f"【即时告警】【{account_id}】{module or '未知模块'}错误"

        alarm = AlarmPo(
            account_id=account_id,
            alarm_date=today,
            alarm_time=time_str,
            source="LOG",
            title=title,
            detail=log_message,
            status="UNCONFIRMED",
        )

        session.add(alarm)
        session.commit()

        logger.info(f"告警已创建: {alarm.title}")

        # 触发告警更新事件
        ctx = get_app_context()
        event_engine = ctx.get_event_engine()
        if event_engine:
            alarm_dict = {
                "id": alarm.id,
                "account_id": alarm.account_id,
                "alarm_date": alarm.alarm_date,
                "alarm_time": alarm.alarm_time,
                "source": alarm.source,
                "title": alarm.title,
                "detail": alarm.detail,
                "status": alarm.status,
                "created_at": alarm.created_at.isoformat(),
            }
            event_engine.put(EventTypes.ALARM_UPDATE, alarm_dict)

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

    def __call__(self, message):
        """
        处理日志记录

        Args:
            message: loguru消息对象
        """
        try:
            # 避免处理自己产生的错误日志（防止无限循环）
            # 检查消息来源
            try:
                record = message.record if hasattr(message, "record") else message
            except:
                record = message

            # 获取模块名
            module = ""
            try:
                if isinstance(record, dict):
                    module = record.get("name", "")
                else:
                    module = getattr(record, "name", "")
            except:
                pass

            # 跳过alarm_handler自身的错误
            if "alarm_handler" in str(module):
                return

            # 排除Manager模块的异常（只处理Trader推送过来的告警）
            if "manager" in str(module).lower():
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
            except:
                pass

            if level != "ERROR":
                return

            # 获取日志消息
            log_message = ""
            try:
                if isinstance(record, dict):
                    log_message = record.get("message", "")
                else:
                    # loguru 使用 _message 属性存储原始消息
                    log_message = str(record) if hasattr(record, "__str__") else ""
            except:
                log_message = str(record) if record else ""

            # 获取函数名
            function = None
            try:
                if isinstance(record, dict):
                    function = record.get("function")
                else:
                    function = getattr(record, "function", None)
            except:
                pass

            # 获取 extra 数据
            extra = None
            try:
                if isinstance(record, dict):
                    extra = record.get("extra")
                else:
                    extra = getattr(record, "extra", None)
            except:
                pass

            create_alarm_from_log(log_message, module, function, extra)

        except Exception as e:
            # 避免告警处理器自身出错导致日志系统异常
            import traceback

            print(f"告警处理器异常: {e}")
            traceback.print_exc()


alarm_handler = AlarmHandler()
