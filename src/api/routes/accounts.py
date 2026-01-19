"""
多账户管理API路由
提供账户列表、连接、断开、状态查询等功能
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_trading_engine, require_connected
from src.api.responses import success_response, error_response
from src.api.schemas import AccountRes
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/accounts", tags=["多账户"])


@router.get("")
async def get_accounts():
    """
    获取所有账户列表
    """
    from src.account_manager import get_account_manager

    manager = get_account_manager()
    if not manager:
        return error_response(code=500, message="账户管理器未初始化")

    all_status = manager.get_all_account_status()

    return success_response(
        data=all_status,
        message="获取成功"
    )


@router.get("/{account_id}/status")
async def get_account_status(account_id: str):
    """
    获取指定账户的状态
    """
    from src.account_manager import get_account_manager

    manager = get_account_manager()
    if not manager:
        return error_response(code=500, message="账户管理器未初始化")

    status = manager.get_account_status(account_id)
    if not status:
        return error_response(code=404, message=f"账户 {account_id} 不存在")

    return success_response(
        data=status,
        message="获取成功"
    )


@router.post("/{account_id}/connect")
async def connect_account(account_id: str):
    """
    连接指定账户
    """
    from src.account_manager import get_account_manager

    manager = get_account_manager()
    if not manager:
        return error_response(code=500, message="账户管理器未初始化")

    if manager.connect_account(account_id):
        return success_response(message="账户连接成功")
    else:
        return error_response(code=500, message="账户连接失败")


@router.post("/{account_id}/disconnect")
async def disconnect_account(account_id: str):
    """
    断开指定账户
    """
    from src.account_manager import get_account_manager

    manager = get_account_manager()
    if not manager:
        return error_response(code=500, message="账户管理器未初始化")

    if manager.disconnect_account(account_id):
        return success_response(message="账户断开成功")
    else:
        return error_response(code=500, message="账户断开失败")
