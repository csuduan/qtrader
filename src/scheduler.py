"""
定时任务调度器模块
使用APScheduler管理定时任务
"""
import time
from datetime import datetime
from typing import Callable, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config_loader import AppConfig
from src.database import get_session
from src.job_mgr import JobManager
from src.models.po import JobPo as JobModel
from src.switch_mgr import SwitchPosManager
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TaskScheduler:
    """任务调度器类"""

    def __init__(self, config: AppConfig, trading_engine):
        """
        初始化任务调度器

        Args:
            config: 应用配置
            trading_engine: 交易引擎实例（兼容单账户和多账户模式）
        """
        self.config = config
        self.trading_engine = trading_engine
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.position_manager = SwitchPosManager(config, trading_engine)
        self.job_manager = JobManager(config, trading_engine, self.position_manager)