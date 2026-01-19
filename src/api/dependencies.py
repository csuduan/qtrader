"""公共依赖注入和工具函数"""
from typing import Optional

from fastapi import Depends, HTTPException, status, Query

from src.database import get_session
from src.trading_engine import TradingEngine


def get_trading_engine(account_id: Optional[str] = Query(None, description="账户ID")) -> TradingEngine:
    """
    获取交易引擎实例（依赖注入）
    
    Args:
        account_id: 账户ID，不指定则返回第一个启用的账户
    """
    from src.context import get_trading_engine as get_global_engine

    engine = get_global_engine()
    if not engine:
        from src.account_manager import get_account_manager
        manager = get_account_manager()
        
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="账户管理器未初始化"
            )

        engines = manager.get_all_engines()
        if not engines:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="没有可用的账户"
            )

        if account_id:
            engine = manager.get_engine(account_id)
            if not engine:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"账户 {account_id} 不存在"
                )
        else:
            engine = next(iter(engines.values()), None)

    if not engine:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="交易引擎未初始化"
        )
    return engine


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
