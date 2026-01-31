"""
策略管理API路由
提供策略CRUD、启停、参数配置接口
所有操作通过TradingManager路由到Trader
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from src.manager.api.dependencies import get_trading_manager
from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import StrategyConfig, StrategyRes
from src.manager.core.trading_manager import TradingManager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/strategies", tags=["策略管理"])


@router.get("")
async def list_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取策略列表

    Args:
        account_id: 账户ID

    Returns:
        List[StrategyRes]: 策略状态列表
    """
    try:
        strategies = await trading_manager.list_strategies(account_id)
        return success_response(data=strategies)
    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        return error_response(message=f"获取策略列表失败: {str(e)}")


@router.get("/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取指定策略状态

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        StrategyRes: 策略状态
    """
    try:
        result = await trading_manager.get_strategy(account_id, strategy_id)
        if result is None:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")
        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取策略状态失败: {e}")
        return error_response(message=f"获取策略状态失败: {str(e)}")


@router.post("/{strategy_id}/start")
async def start_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动指定策略

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.start_strategy(account_id, strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 启动成功")
        else:
            raise HTTPException(status_code=400, detail=f"启动策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动策略失败: {e}")
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/{strategy_id}/stop")
async def stop_strategy(
    strategy_id: str,
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止指定策略

    Args:
        strategy_id: 策略ID
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.stop_strategy(account_id, strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 停止成功")
        else:
            raise HTTPException(status_code=400, detail=f"停止策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        return error_response(message=f"停止策略失败: {str(e)}")


@router.post("/start-all")
async def start_all_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    启动所有已启用的策略

    Args:
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.start_all_strategies(account_id)
        if success:
            return success_response(message="已启动所有策略")
        else:
            return error_response(message="启动策略失败")
    except Exception as e:
        logger.error(f"启动策略失败: {e}")
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/stop-all")
async def stop_all_strategies(
    account_id: str = Query(..., description="账户ID"),
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    停止所有策略

    Args:
        account_id: 账户ID

    Returns:
        操作结果
    """
    try:
        success = await trading_manager.stop_all_strategies(account_id)
        if success:
            return success_response(message="已停止所有策略")
        else:
            return error_response(message="停止策略失败")
    except Exception as e:
        logger.error(f"停止策略失败: {e}")
        return error_response(message=f"停止策略失败: {str(e)}")
