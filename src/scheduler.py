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
from src.trading_engine import TradingEngine
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

    def _init_jobs_in_db(self) -> None:
        """初始化任务配置到数据库"""
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        default_jobs = []
        if self.config and self.config.scheduler and self.config.scheduler.jobs:
            default_jobs = [
                {
                    "job_id": job.job_id,
                    "job_name": job.job_name,
                    "job_group": job.job_group,
                    "job_description": job.job_description,
                    "cron_expression": job.cron_expression,
                    "job_method": job.job_method,
                    "enabled": job.enabled,
                }
                for job in self.config.scheduler.jobs
            ]

    def _setup_jobs_from_db(self) -> None:
        """从数据库加载任务配置并设置定时任务"""
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        jobs = session.query(JobModel).all()

        for job in jobs:
            job_method_value = getattr(job, "job_method", None)

            if not job_method_value or job_method_value == "":
                logger.warning(f"任务 {job.job_name} 缺少执行方法，跳过")
                continue

            method_name = job_method_value.strip("_")

            if job_method_name not in ["_pre_market_connect", "_post_market_disconnect", "execute_position_rotation", "_scan_orders", "_post_market_export"]:
                logger.error(f"任务 {job.job_name} 的执行方法 {job_method_name} 不存在，跳过")
                continue

            try:
                job_func = getattr(self.job_manager, method_name, None) if self.job_manager else None
            except AttributeError:
                logger.warning(f"无法获取任务 {job.job_name} 的执行方法")
                continue

            trigger = None
            cron_parts = job.cron_expression.split()

            if len(cron_parts) == 6:
                trigger = CronTrigger(
                    second=cron_parts[0],
                    minute=cron_parts[1],
                    hour=cron_parts[2],
                    day=cron_parts[3],
                    month=cron_parts[4],
                    day_of_week=cron_parts[5],
                    timezone="Asia/Shanghai",
                )
            else:
                trigger = CronTrigger.from_crontab(job.cron_expression, timezone="Asia/Shanghai")

            self.scheduler.add_job(
                wrapped_func,
                trigger,
                id=job.job_id,
                name=job.job_name,
                replace_existing=True,
            )

            job.enabled = False

            if job.enabled:
                self.scheduler.pause_job(job.job_id)
                logger.info(f"已添加任务 {job.job_name}, 方法: {job_method_value}")

    def _update_job_last_trigger_time(self, job_id: str) -> None:
        """更新任务最后触发时间"""
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return

        job = session.query(JobModel).filter_by(job_id=job_id).first()
        if job:
            job.last_trigger_time = datetime.now()
            session.add(job)
            logger.info(f"已更新任务 {job.job.job_name} 最后触发时间")

    def start(self) -> None:
        """启动调度器"""
        try:
            self.scheduler.start()
            logger.info("任务调度器已启动")
        except Exception as e:
            logger.error(f"启动任务调度器失败: {e}")

    def shutdown(self) -> None:
        """关闭调度器"""
        try:
            self.scheduler.shutdown(wait=False)
            logger.info("任务调度器已关闭")
        except Exception as e:
            logger.error(f"关闭任务调度器时出错: {e}")

    def get_jobs(self) -> List[dict]:
        """
        获取所有任务信息

        Returns:
            List[dict]: 任务信息列表
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run_time_val = None
            if job.next_run_time:
                next_run_time_val = job.next_run_time.isoformat()
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run_time_val,
                "enabled": job.next_run_time != None,
            })

        return jobs

    def trigger_job(self, job_id: str) -> bool:
        """
        手动触发定时任务

        Args:
            job_id: 任务ID

        Returns:
            bool: 是否触发成功
        """
        try:
            job = self.scheduler.get_job(job_id)
            if not job:
                logger.error(f"任务不存在: {job_id}")
                return False

            self.scheduler.add_job(
                job.func,
                trigger='date',
                id=f"{job_id}_manual_{int(datetime.now().timestamp())}",
                name=f"{job.name} (手动)",
            )

            logger.info(f"已手动触发任务 {job.name} ({job_id})")
            return True
        except Exception as e:
            logger.error(f"触发任务失败 {job_id}, 错误: {e}")
            return False

    def operate_job(self, job_id: str, action: str) -> bool:
        """
        操作定时任务（暂停/恢复/触发）

        Args:
            job_id: 任务ID
            action: 操作类型

        Returns:
            bool: 是否操作成功
        """
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return False

        job = session.query(JobModel).filter_by(job_id=job_id).first()
        if not job:
            logger.error(f"任务不存在: {job_id}")
            return False

        apscheduler_job = self.scheduler.get_job(job_id)
        if not apscheduler_job:
            logger.error(f"调度器中找不到任务 {job_id}")
            return False

        if action == "pause":
            apscheduler_job.pause()
            job.enabled = False
            job.updated_at = datetime.now()
            session.add(job)
            session.commit()

            logger.info(f"暂停任务 {job.job_name} ({job_id})")
            return True
        elif action == "resume":
            apscheduler_job.resume()
            job.enabled = True
            job.updated_at = datetime.now()
            session.add(job)
            session.commit()

            logger.info(f"恢复任务 {job.job_name} ({job_id})")
            return True
        elif action == "trigger":
            success = self.trigger_job(job_id)
            return success
        else:
            logger.error(f"未知操作: {action}")
            return False

    def update_job_status(self, job_id: str, enabled: bool) -> bool:
        """
        更新任务启用状态到数据库

        Args:
            job_id: 任务ID
            enabled: 是否启用

        Returns:
            bool: 是否更新成功
        """
        session = get_session()
        if not session:
            logger.error("无法获取数据库会话")
            return False

        job = session.query(JobModel).filter_by(job_id=id=job_id).first()
        if not job:
            logger.error(f"任务不存在: {job_id}")
            return False

        job.enabled = enabled
        job.updated_at = datetime.now()
        session.add(job)
        session.commit()

        logger.info(f"任务 {job.job_name} ({job_id}) 已{'启用' if enabled else '禁用'}")
        return True
