"""
定时任务配置相关API路由
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from src.app_context import get_app_context
from src.manager.api.responses import error_response, success_response
from src.models.po import JobPo
from src.scheduler import TaskScheduler
from src.manager.core.trading_manager import TradingManager
from src.manager.api.dependencies import get_trading_manager
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
    account_id: str = Query(..., description="账户ID"),
    trading_manager:TradingManager = Depends(get_trading_manager),
):
    """
    获取定时任务列表

    - **account_id**: 账户ID
    - **group**: 任务分组筛选
    - **enabled**: 是否启用筛选
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")
    jobs = await trader.get_jobs()
    # jobs 是 List[Job]
    return success_response(data={"tasks": jobs, "count": len(jobs)}, message="获取成功")


@router.put("/{job_id}/toggle")
async def toggle_job(
    job_id: str,
    request: JobToggleRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager:TradingManager = Depends(get_trading_manager),
):
    """
    切换任务启用/禁用状态

    - **account_id**: 账户ID
    - **job_id**: 任务ID
    - **request**: 包含enabled的请求体
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")
    success = await trader.toggle_job(job_id, request.enabled)
    if success:
        return success_response(data={"job_id": job_id, "enabled": request.enabled}, message="任务状态已更新")
    return error_response(code=500, message="更新任务状态失败")


@router.post("/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager:TradingManager = Depends(get_trading_manager),
):
    """
    立即触发定时任务

    - **account_id**: 账户ID
    - **job_id**: 任务ID
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")
    success = await trader.trigger_job(job_id)
    if success:
        return success_response(data={"job_id": job_id}, message="任务已触发")
    return error_response(code=500, message="触发任务失败")


@router.post("/{job_id}/operate")
async def operate_job(
    job_id: str,
    request: JobOperateRequest,
    account_id: str = Query(..., description="账户ID"),
    trading_manager:TradingManager = Depends(get_trading_manager),
):
    """
    操作定时任务（暂停/恢复/触发）

    - **account_id**: 账户ID
    - **job_id**: 任务ID
    - **request**: 包含action的请求体
    """
    trader = trading_manager.get_trader(account_id)
    if not trader:
        return error_response(code=404, message=f"账户 [{account_id}] 不存在")

    action = request.action.lower()
    if action == "pause":
        success = await trader.pause_job(job_id)
    elif action == "resume":
        success = await trader.resume_job(job_id)
    elif action == "trigger":
        success = await trader.trigger_job(job_id)
    else:
        return error_response(code=400, message=f"不支持的操作: {action}")

    if success:
        action_text = "暂停" if action == "pause" else "恢复" if action == "resume" else "触发"
        return success_response(data={"job_id": job_id}, message=f"任务已{action_text}")
    return error_response(code=500, message=f"操作任务失败: {action}")
