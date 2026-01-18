"""
测试告警功能
触发ERROR日志，验证告警是否自动创建
"""
import time
from src.utils.logger import get_logger

logger = get_logger(__name__)

logger.info("开始测试告警功能...")
time.sleep(1)

logger.error("这是一条测试ERROR日志，应该会自动创建告警")
logger.error("测试告警功能 - 模拟系统错误 - 测试模块")

time.sleep(2)
logger.info("测试告警功能完成，请检查告警页面")
