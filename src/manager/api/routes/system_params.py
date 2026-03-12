"""
系统参数相关API路由
所有操作通过TradingManager路由到Trader
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import SystemParamRes, SystemParamUpdateReq
from src.manager.manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/system-params", tags=["系统参数"])


@router.get("")
async def list_system_params(
    account_id: str = Query(..., description="账户ID"),
    group: str | None = Query(None, description="参数分组"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取系统参数列表

    Args:
        account_id: 账户ID
        group: 参数分组（可选）

    Returns:
        系统参数列表
    """
    try:
        params = await trading_manager.list_system_params(account_id, group)
        return params
    except Exception as e:
        logger.error(f"获取系统参数失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取系统参数失败: {str(e)}")


@router.get("/{param_key}")
async def get_system_param(
    param_key: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取单个系统参数

    Args:
        param_key: 参数键名
        account_id: 账户ID

    Returns:
        系统参数
    """
    try:
        param = await trading_manager.get_system_param(account_id, param_key)

        if not param:
            return error_response(code=404, message=f"参数 {param_key} 不存在")

        return param

    except Exception as e:
        logger.error(f"获取系统参数失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取系统参数失败: {str(e)}")


@router.put("/{param_key}")
async def update_system_param(
    param_key: str,
    req: SystemParamUpdateReq,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    更新系统参数

    Args:
        param_key: 参数键名
        req: 更新请求
        account_id: 账户ID

    Returns:
        更新结果
    """
    try:
        param = await trading_manager.update_system_param(account_id, param_key, req.param_value)

        if not param:
            return error_response(code=404, message=f"参数 {param_key} 不存在")

        logger.info(f"系统参数已更新: {param_key} = {req.param_value}")

        return success_response(data=param, message="参数更新成功")

    except Exception as e:
        logger.error(f"更新系统参数失败: {e}", exc_info=True)
        return error_response(code=500, message=f"更新系统参数失败: {str(e)}")


@router.get("/group/{group}")
async def get_system_params_by_group(
    group: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    根据分组获取系统参数

    Args:
        group: 参数分组
        account_id: 账户ID

    Returns:
        系统参数字典
    """
    try:
        result = await trading_manager.get_system_params_by_group(account_id, group)

        if result is None:
            return error_response(code=404, message=f"参数组 {group} 不存在")

        return success_response(data=result, message="获取成功")

    except Exception as e:
        logger.error(f"获取系统参数失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取系统参数失败: {str(e)}")
