"""
公共依赖注入和工具函数
支持多账号架构
"""

from typing import Optional

from fastapi import Depends, HTTPException, status

from src.app_context import get_app_context
from src.manager.core.trading_manager import TradingManager

def get_trading_manager() -> TradingManager:
    """获取交易管理器（依赖注入）"""
    ctx = get_app_context()
    manager:TradingManager = ctx.get_trading_manager()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="交易管理器未初始化"
        )
    return manager
