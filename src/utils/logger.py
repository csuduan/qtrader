"""
日志工具模块
基于loguru实现日志记录功能

当前日志文件：{app_name}_app.log
轮转后的历史文件：{app_name}_app_YYYYMMDD.log
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger


def setup_logger(
    app_name: str,
    log_dir: str = "./data/logs",
    log_level: str = "INFO",
    rotation: str = "00:00",  # 每天午夜轮转
    retention: str = "30 days",  # 保留30天
    compression: str = "zip",  # 压缩旧日志
) -> None:
    """
    配置loguru日志系统

    日志文件名格式：
    - 当前日志：{app_name}_app.log
    - 历史日志：{app_name}_app_YYYYMMDD.log（轮转后自动添加日期）

    Args:
        app_name: 应用名称，用于日志文件名
        log_dir: 日志目录
        log_level: 日志级别
        rotation: 日志轮转设置
        retention: 日志保留时间
        compression: 日志压缩方式
    """
    # 确保日志目录存在
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    # 移除默认的handler
    logger.remove()

    # 添加控制台输出handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>",
        level=log_level,
        colorize=True,
    )

    # 添加通用日志文件handler
    logger.add(
        f"{log_dir}/{app_name}_app.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level=log_level,
        rotation=rotation,
        retention=retention,
        compression=compression,
        encoding="utf-8",
        enqueue=False,  # 禁用队列，立即写入
    )

    # 添加错误日志文件handler
    logger.add(
        f"{log_dir}/{app_name}_error.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="ERROR",
        rotation=rotation,
        retention=retention,
        compression=compression,
        encoding="utf-8",
    )

    logger.opt(exception=True)
    logger.info(f"日志系统初始化完成，日志目录: {log_dir}")


def enable_alarm_handler():
    """
    启用告警日志处理器
    监听ERROR级别日志并自动创建告警
    """
    from src.utils.alarm_handler import alarm_handler

    logger.add(lambda record: alarm_handler(record), level="ERROR", enqueue=False)
    logger.info("告警日志处理器已启用")


def get_logger(name: Optional[str] = None):
    """
    获取logger实例

    Args:
        name: logger名称

    Returns:
        logger实例
    """
    if name:
        return logger.bind(name=name)
    return logger
