"""
定时任务调度器模块
使用APScheduler管理定时任务，直接从config.yaml加载配置
"""

import asyncio
import inspect
from datetime import datetime
from typing import Callable, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel

from src.trader.job_mgr import JobManager
from src.trader.switch_mgr import SwitchPosManager
from src.utils.config_loader import SchedulerConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class Job(BaseModel):
    """定时任务"""

    job_id: str = None
    job_name: str = None
    job_group: str = None
    job_description: str = None
    cron_expression: str = None
    job_method: str = None
    last_trigger_time: datetime | None = None
    next_trigger_time: datetime | None = None
    enabled: bool | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskScheduler:
    """任务调度器类"""

    def __init__(self, config: SchedulerConfig, job_manager: JobManager):
        """
        初始化任务调度器

        Args:
            config: 应用配置
            trading_engine: 交易引擎实例
        """
        self.config = config
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self.job_manager = job_manager
        # 内存中的任务配置
        self._jobs: dict[str, Job] = {}

        # 从配置文件加载任务
        self._load_jobs_from_config()

        logger.info("任务调度器初始化完成")

    def _load_jobs_from_config(self) -> None:
        if not self.config or not self.config.jobs:
            logger.warning("配置文件中没有任务配置")
            return

        for job_config in self.config.jobs:
            job = Job(
                job_id=job_config.job_id,
                job_name=job_config.job_name,
                job_group=job_config.job_group,
                job_description=job_config.job_description,
                cron_expression=job_config.cron_expression,
                job_method=job_config.job_method,
                enabled=job_config.enabled,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            self._jobs[job.job_id] = job
            self._setup_job(job)

        logger.info(f"已从配置文件加载 {len(self._jobs)} 个任务")

    def _setup_job(self, job: Job) -> None:
        """设置单个任务"""
        job_method = job.job_method
        if not job_method:
            logger.warning(f"任务 {job.job_name} 缺少执行方法，跳过")
            return

        # 获取执行函数
        job_func = self._get_job_function(job_method)
        if not job_func:
            logger.error(f"任务 {job.job_name} 的执行方法 {job_method} 不存在，跳过")
            return

        # 包装任务函数，在执行后更新触发时间
        def wrap_job_func(func: Callable, job: Job) -> Callable:
            def wrapped():
                try:
                    # 检测是否为协程函数
                    if inspect.iscoroutinefunction(func):
                        # 异步函数：在事件循环中执行
                        from src.app_context import get_app_context

                        ctx = get_app_context()
                        loop = ctx.get_event_loop()

                        if loop and loop.is_running():
                            # 使用 run_coroutine_threadsafe 在线程中安全地调度协程
                            future = asyncio.run_coroutine_threadsafe(func(), loop)
                            # 等待结果，设置5分钟超时
                            try:
                                future.result(timeout=300)
                            except asyncio.TimeoutError:
                                logger.error(f"异步任务执行超时（300秒）: {job.job_name}")
                            except Exception as e:
                                logger.error(f"异步任务执行失败: {job.job_name}, {e}")
                        else:
                            logger.error(f"事件循环未运行，无法执行异步任务: {job.job_name}")
                    else:
                        # 同步函数：直接调用
                        func()
                finally:
                    job.last_trigger_time = datetime.now()

            return wrapped

        wrapped_func = wrap_job_func(job_func, job)

        # 解析CRON表达式
        trigger = self._parse_cron_expression(job.cron_expression)
        if not trigger:
            logger.error(f"任务 {job.job_name} 的CRON表达式无效: {job.cron_expression}")
            return

        # 添加任务到调度器
        try:
            self.scheduler.add_job(
                wrapped_func,
                trigger,
                id=job.job_id,
                name=job.job_name,
                replace_existing=True,
            )
            if not job.enabled:
                self.scheduler.pause_job(job.job_id)
            logger.info(
                f"已添加任务: {job.job_name}, 方法: {job_method}, CRON: {job.cron_expression}, 状态: {'暂停' if not job.enabled else '运行'}"
            )
        except Exception as e:
            logger.error(f"添加任务 {job.job_name} 失败: {e}")

    def _get_job_function(self, job_method: str) -> Callable:
        """
        获取任务执行函数

        Args:
            job_method: 方法名（如 _pre_market_connect）

        Returns:
            Callable: 执行函数
        """
        # 去掉前缀下划线
        method_name = job_method.lstrip("_")

        # 优先从 JobManager 获取
        job_func = getattr(self.job_manager, method_name, None)
        if job_func and callable(job_func):
            return job_func

        logger.warning(f"未找到任务方法: {job_method}")
        return None

    def _parse_cron_expression(self, cron_expression: str):
        """
        解析CRON表达式

        Args:
            cron_expression: CRON表达式字符串

        Returns:
            CronTrigger: APScheduler触发器
        """
        try:
            cron_parts = cron_expression.split()
            if len(cron_parts) == 6:
                # 6字段格式：秒 分 时 日 月 周
                return CronTrigger(
                    second=cron_parts[0],
                    minute=cron_parts[1],
                    hour=cron_parts[2],
                    day=cron_parts[3],
                    month=cron_parts[4],
                    day_of_week=cron_parts[5],
                    timezone="Asia/Shanghai",
                )
            else:
                # 5字段格式：分 时 日 月 周
                return CronTrigger.from_crontab(cron_expression, timezone="Asia/Shanghai")
        except Exception as e:
            logger.error(f"解析CRON表达式失败: {cron_expression}, {e}")
            return None

    def _reset_strategies(self) -> None:
        """重置所有策略（开盘前调用）"""
        from src.app_context import get_app_context

        ctx = get_app_context()
        strategy_manager = ctx.get_strategy_manager()
        if strategy_manager:
            strategy_manager.reset_all_for_new_day()

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

    def get_jobs(self) -> dict[str, Job]:
        """
        获取所有任务信息

        Returns:
            List[dict]: 任务信息列表
        """
        return self._jobs

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

            # 立即执行任务
            self.scheduler.add_job(
                job.func,
                trigger="date",
                id=f"{job_id}_manual_{int(datetime.now().timestamp())}",
                name=f"{job.name} (手动)",
            )

            logger.info(f"已手动触发任务: {job.name} ({job_id})")
            return True
        except Exception as e:
            logger.error(f"触发任务失败: {job_id}, 错误: {e}")
            return False

    def operate_job(self, job_id: str, action: str) -> bool:
        """
        操作定时任务（暂停/恢复/触发）

        Args:
            job_id: 任务ID
            action: 操作类型（pause/resume/trigger）

        Returns:
            bool: 是否操作成功
        """
        try:
            job_config = self._jobs.get(job_id)
            if not job_config:
                logger.error(f"任务不存在: {job_id}")
                return False

            apscheduler_job = self.scheduler.get_job(job_id)
            if not apscheduler_job:
                logger.error(f"调度器中找不到任务: {job_id}")
                return False

            if action == "pause":
                apscheduler_job.pause()
                job_config.enabled = False
                logger.info(f"暂停任务: {job_config.job_name} ({job_id})")
                return True
            elif action == "resume":
                apscheduler_job.resume()
                job_config.enabled = True
                logger.info(f"恢复任务: {job_config.job_name} ({job_id})")
                return True
            elif action == "trigger":
                return self.trigger_job(job_id)
            else:
                logger.error(f"未知操作: {action}")
                return False
        except Exception as e:
            logger.error(f"操作任务失败: {job_id}, 错误: {e}")
            return False

    def update_job_status(self, job_id: str, enabled: bool) -> bool:
        """
        更新任务启用状态（内存中）

        Args:
            job_id: 任务ID
            enabled: 是否启用

        Returns:
            bool: 是否更新成功
        """
        if job_id not in self._jobs:
            logger.error(f"任务不存在: {job_id}")
            return False

        self._jobs[job_id].enabled = enabled
        if enabled:
            self.scheduler.resume_job(job_id)
        else:
            self.scheduler.pause_job(job_id)

        logger.info(
            f"任务 {self._jobs[job_id].job_name} ({job_id}) 已{'启用' if enabled else '禁用'}"
        )
        return True
