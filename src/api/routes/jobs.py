"""
定时任务配置相关API路由
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from src.api.dependencies import get_db_session
from src.api.responses import success_response, error_response
from src.models.po import JobPo
from src.utils.logger import get_logger

logger = get_logger(__name__)


class JobToggleRequest(BaseModel):
    """任务状态切换请求"""
    enabled: bool


class JobOperateRequest(BaseModel):
    """任务操作请求"""
    action: str


router = APIRouter(prefix="/api/jobs", tags=["定时任务"])


@router.get("")
async def get_jobs(
    group: Optional[str] = Query(None, description="任务分组"),
    enabled: Optional[bool] = Query(None, description="是否启用"),
    session=Depends(get_db_session),
):
    """
    获取定时任务列表

    - **group**: 任务分组筛选
    - **enabled**: 是否启用筛选
    """
    from src.context import get_task_scheduler
    from src.scheduler import TaskScheduler
    query = session.query(JobPo)

    if group:
        query = query.filter_by(job_group=group)

    if enabled is not None:
        query = query.filter_by(enabled=enabled)
    
    scheduler: TaskScheduler = get_task_scheduler()
    if not scheduler:
        return error_response(code=500, message="任务调度器未初始化")
    jobs = scheduler.get_jobs()   
    return success_response(data={"tasks": [job for id,job in jobs.items()], "count": len(jobs)}, message="获取成功")


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    session=Depends(get_db_session),
):
    """
    获取指定定时任务

    - **job_id**: 任务ID
    """
    job = session.query(JobPo).filter_by(job_id=job_id).first()

    if not job:
        return error_response(code=404, message="任务不存在")

    return success_response(
        data={
            "job_id": job.job_id,
            "job_name": job.job_name,
            "job_group": job.job_group,
            "job_description": job.job_description,
            "cron_expression": job.cron_expression,
            "last_trigger_time": job.last_trigger_time.isoformat() if job.last_trigger_time else None,
            "next_trigger_time": job.next_trigger_time.isoformat() if job.next_trigger_time else None,
            "enabled": job.enabled,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
        },
        message="获取成功"
    )


@router.put("/{job_id}/toggle")
async def toggle_job(
    job_id: str,
    request: JobToggleRequest,
    session=Depends(get_db_session),
):
    """
    切换任务启用/禁用状态

    - **job_id**: 任务ID
    - **request**: 包含enabled的请求体
    """
    from src.context import get_task_scheduler

    # 更新调度器中的任务状态
    scheduler = get_task_scheduler()
    if scheduler:
        scheduler.update_job_status(job_id, request.enabled)

    # 如果启用，重新加载任务配置
    if request.enabled:
        logger.info(f"任务 {job.job_name} 已启用")
    else:
        logger.info(f"任务 {job.job_name} 已禁用")

    return success_response(
        data={
            "job_id": job.job_id,
            "enabled": job.enabled
        },
        message=f"任务已{'启用' if request.enabled else '禁用'}"
    )


@router.post("/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    session=Depends(get_db_session),
):
    """
    立即触发定时任务

    - **job_id**: 任务ID
    """
    from src.context import get_task_scheduler
    from src.utils.logger import get_logger

    logger = get_logger(__name__)

    job = session.query(JobPo).filter_by(job_id=job_id).first()

    if not job:
        return error_response(code=404, message="任务不存在")

    try:
        # 获取 scheduler 实例
        scheduler = get_task_scheduler()

        if not scheduler:
            return error_response(code=500, message="任务调度器未初始化")

        # 立即触发任务
        success = scheduler.trigger_job(job_id)

        if not success:
            return error_response(code=500, message="触发任务失败")

        logger.info(f"手动触发任务: {job.job_name} ({job_id})")
        return success_response(
            data={"job_id": job_id, "job_name": job.job_name},
            message=f"任务 {job.job_name} 已触发"
        )
    except Exception as e:
        logger.error(f"触发任务失败: {e}", exc_info=True)
        return error_response(code=500, message=f"触发任务失败: {str(e)}")


@router.post("/{job_id}/operate")
async def operate_job(
    job_id: str,
    request: JobOperateRequest,
    session=Depends(get_db_session),
):
    """
    操作定时任务（暂停/恢复/触发）

    - **job_id**: 任务ID
    - **request**: 包含action的请求体
    """
    from src.context import get_task_scheduler

    job = session.query(JobPo).filter_by(job_id=job_id).first()

    if not job:
        return error_response(code=404, message="任务不存在")

    try:
        scheduler = get_task_scheduler()
        if not scheduler:
            return error_response(code=500, message="任务调度器未初始化")

        success = scheduler.operate_job(job_id, request.action)
        if not success:
            return error_response(code=500, message="操作任务失败")

        action_text = {
            "pause": "暂停",
            "resume": "恢复",
            "trigger": "触发"
        }.get(request.action, request.action)

        logger.info(f"操作任务: {job.job_name} ({job_id}) - {action_text}")
        return success_response(message=f"任务 {job.job_name} 已{action_text}")
    except Exception as e:
        logger.error(f"操作任务失败: {e}", exc_info=True)
        return error_response(code=500, message=f"操作任务失败: {str(e)}")
