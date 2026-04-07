"""
公共依赖注入和工具函数
支持多账号架构
"""

from typing import Optional

from fastapi import Depends, HTTPException, status

from src.app_context import get_app_context
from src.manager.manager import TradingManager

# 从auth模块导入认证依赖，统一暴露
from src.manager.api.routes.auth import get_current_user, require_admin


def get_trading_manager() -> TradingManager:
    """获取交易管理器（依赖注入）"""
    ctx = get_app_context()
    manager: TradingManager = ctx.get_trading_manager()
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="交易管理器未初始化"
        )
    return manager
