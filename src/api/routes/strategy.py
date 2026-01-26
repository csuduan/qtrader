"""
策略管理API路由
提供策略CRUD、启停、参数配置接口
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends

from src.api.responses import success_response, error_response
from src.api.dependencies import get_trading_engine,get_strategy_manager
from src.api.schemas import StrategyRes, StrategyConfig
from src.models.object import StrategyType
from src.strategy.strategy_manager import StrategyManager

router = APIRouter(prefix="/api/strategies", tags=["策略管理"])


@router.get("")
async def list_strategies(strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    获取策略列表

    Returns:
        List[StrategyRes]: 策略状态列表
    """
    try:
        strategies = strategy_manager.strategies
        result = []
        for strategy in strategies.values():
            strategy_res = StrategyRes(
                strategy_id=strategy.strategy_id,
                active=strategy.active,
                config=_build_strategy_config(strategy)
            )
            result.append(strategy_res)
        return success_response(data=result)
    except Exception as e:
        return error_response(message=f"获取策略列表失败: {str(e)}")


def _build_strategy_config(strategy) -> StrategyConfig:
    """
    构建策略配置对象（符合前端期望的格式）

    Args:
        strategy: 策略实例

    Returns:
        StrategyConfig: 策略配置
    """
    config = strategy.config.copy()

    return StrategyConfig(
        enabled=config.get("enabled", True),
        strategy_type=config.get("type", "bar"),
        symbol=config.get("symbol", ""),
        exchange=config.get("exchange", ""),
        volume_per_trade=config.get("volume_per_trade", config.get("volume", 1)),
        max_position=config.get("max_position", 5),
        bar=config.get("bar"),
        params_file=config.get("params_file"),
        take_profit_pct=config.get("take_profit_pct", config.get("TpRet")),
        stop_loss_pct=config.get("stop_loss_pct", config.get("SlRet")),
        fee_rate=config.get("fee_rate"),
        trade_start_time=config.get("trade_start_time", config.get("StartTime")),
        trade_end_time=config.get("trade_end_time", config.get("EndTime")),
        force_exit_time=config.get("force_exit_time", config.get("ForceExitTime")),
        one_trade_per_day=config.get("one_trade_per_day"),
        # RSI策略参数
        rsi_period=config.get("rsi_period"),
        rsi_long_threshold=config.get("rsi_long_threshold"),
        rsi_short_threshold=config.get("rsi_short_threshold"),
        short_kline_period=config.get("short_kline_period"),
        long_kline_period=config.get("long_kline_period"),
        dir_threshold=config.get("dir_threshold", config.get("DirThr")),
        used_signal=config.get("used_signal", config.get("UsedSignal")),
    )


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str, strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    获取指定策略状态

    Args:
        strategy_id: 策略ID

    Returns:
        StrategyRes: 策略状态
    """
    try:
        if strategy_id not in strategy_manager.strategies:
            raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_id}")

        strategy = strategy_manager.strategies[strategy_id]
        result = StrategyRes(
            strategy_id=strategy.strategy_id,
            active=strategy.active,
            config=_build_strategy_config(strategy)
        )
        return success_response(data=result)
    except HTTPException:
        raise
    except Exception as e:
        return error_response(message=f"获取策略状态失败: {str(e)}")


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str, strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    启动指定策略

    Args:
        strategy_id: 策略ID

    Returns:
        操作结果
    """
    try:
        success = strategy_manager.start_strategy(strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 启动成功")
        else:
            raise HTTPException(status_code=400, detail=f"启动策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str, strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    停止指定策略

    Args:
        strategy_id: 策略ID

    Returns:
        操作结果
    """
    try:
        success = strategy_manager.stop_strategy(strategy_id)
        if success:
            return success_response(message=f"策略 {strategy_id} 停止成功")
        else:
            raise HTTPException(status_code=400, detail=f"停止策略失败: {strategy_id}")
    except HTTPException:
        raise
    except Exception as e:
        return error_response(message=f"停止策略失败: {str(e)}")


@router.post("/start-all")
async def start_all_strategies(strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    启动所有已启用的策略

    Returns:
        操作结果
    """
    try:
        strategy_manager.start_all()
        return success_response(message="已启动所有策略")
    except Exception as e:
        return error_response(message=f"启动策略失败: {str(e)}")


@router.post("/stop-all")
async def stop_all_strategies(strategy_manager: StrategyManager = Depends(get_strategy_manager)):
    """
    停止所有策略

    Returns:
        操作结果
    """
    try:
        strategy_manager.stop_all()
        return success_response(message="已停止所有策略")
    except Exception as e:
        return error_response(message=f"停止策略失败: {str(e)}")
