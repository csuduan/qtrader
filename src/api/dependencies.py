"""公共依赖注入和工具函数"""
from typing import Optional

from fastapi import Depends, HTTPException, status

from src.database import get_session
from src.trading_engine import TradingEngine
from src.strategy.strategy_manager import StrategyManager


def get_trading_engine() -> TradingEngine:
    """获取交易引擎实例（依赖注入）"""
    from src.context import get_trading_engine as get_global_engine

    engine = get_global_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="交易引擎未初始化"
        )
    return engine

def get_strategy_manager() -> StrategyManager:
    """获取策略管理器实例（依赖注入）"""
    from src.context import get_strategy_manager as get_global_manager

    manager = get_global_manager()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="策略管理器未初始化"
        )
    return manager


def require_connected(engine: TradingEngine = Depends(get_trading_engine)) -> TradingEngine:
    """要求交易引擎已连接"""
    if not engine.connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="交易引擎未连接"
        )
    return engine


def require_not_paused(engine: TradingEngine = Depends(get_trading_engine)) -> TradingEngine:
    """要求交易未暂停"""
    if engine.paused:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="交易已暂停"
        )
    return engine


def get_db_session():
    """获取数据库会话（依赖注入）"""
    session = get_session()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="数据库服务不可用"
        )
    return session


def get_account_id(engine: TradingEngine = Depends(get_trading_engine)) -> str:
    """获取当前账户ID"""
    account_id = engine.config.account_id
    if not account_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="账户信息不存在"
        )
    return account_id
