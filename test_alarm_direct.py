"""
直接测试告警功能
"""
from src.utils.logger import get_logger

logger = get_logger(__name__)

logger.error("测试告警功能 - 模拟系统错误")
