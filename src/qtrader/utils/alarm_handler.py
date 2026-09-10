"""
告警日志处理器
监听ERROR级别日志并自动创建告警记录
"""

import re
from datetime import datetime

from qtrader.models.po import AlarmPo
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


def extract_account_id_from_message(message: str) -> str | None:
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
        r"账户\[?([^\]]+)\]?",  # 账户[DQ] 或 账户DQ
        r"account_id[:=]\s*(\w+)",  # account_id: DQ 或 account_id=DQ
        r"trader[-_](\w+)",  # trader-DQ 或 trader_DQ
        r"account[:=]\s*(\w+)",  # account: DQ
    ]

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


async def create_alarm_from_log(
    log_message: str,
    module: str | None = None,
    function: str | None = None,
    extra: dict | None = None,
) -> bool:
    """
    从日志记录创建告警（异步落库）

    Args:
        log_message: 日志消息
        module: 模块名
        function: 函数名

    Returns:
        是否创建成功
    """
    from qtrader.utils.async_database import get_async_session

    try:
        async with get_async_session() as session:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M:%S")

            # 尝试从 extra 或消息中提取账户ID
            account_id = None
            if extra and isinstance(extra, dict):
                account_id = extra.get("account_id")
            if not account_id:
                account_id = extract_account_id_from_message(log_message)
            if not account_id:
                account_id = "SYSTEM"

            # 格式化标题：【异常】【账户ID】模块错误
            title = f"【异常】【{account_id}】{module or '未知模块'}错误"

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

            logger.info(f"告警已创建: {alarm.title}")

            return True
    except Exception as e:
        logger.error(f"创建告警失败: {e}", exc_info=True)
        return False


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
            except Exception:
                record = message

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
                    # loguru 使用 _message 属性存储原始消息
                    log_message = str(record) if hasattr(record, "__str__") else ""
            except Exception:
                log_message = str(record) if record else ""

            # 获取函数名
            function = None
            try:
                if isinstance(record, dict):
                    function = record.get("function")
                else:
                    function = getattr(record, "function", None)
            except Exception:
                pass

            # 获取 extra 数据
            extra = None
            try:
                if isinstance(record, dict):
                    extra = record.get("extra")
                else:
                    extra = getattr(record, "extra", None)
            except Exception:
                pass

            # sink 是同步回调，通过 submit_loop 投递到主事件循环异步落库；
            # 循环未运行时（启动早期/退出阶段）降级为仅记日志
            from qtrader.utils.executors import submit_loop

            future = submit_loop(create_alarm_from_log(log_message, module, function, extra))
            if future is None:
                logger.warning(f"事件循环未运行，告警仅记录日志: {log_message}")

        except Exception as e:
            # 避免告警处理器自身出错导致日志系统异常
            import traceback

            logger.error(f"告警处理器异常: {e}")
            traceback.print_exc()


alarm_handler = AlarmHandler()
