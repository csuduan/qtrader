"""
告警相关API路由
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import AlarmRes
from src.models.po import AlarmPo
from src.manager.core.trading_manager import TradingManager
from src.manager.api.dependencies import get_trading_manager
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/alarm", tags=["告警"])


@router.get("/list")
async def get_today_alarms(
    status_filter: Optional[str] = Query(
        None, description="状态筛选: UNCONFIRMED未处理/CONFIRMED已处理，不传则返回全部"
    ),
    trading_manager:TradingManager = Depends(get_trading_manager),
):
    """
    获取当日告警列表

    支持按状态筛选：未处理/已处理/全部
    - **account_id**: 账户ID（多账号模式）
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        return success_response(data=[], message="获取成功")
    except Exception as e:
        logger.error(f"获取告警列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取告警列表失败: {str(e)}")


@router.get("/stats")
async def get_alarm_stats(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    获取告警统计信息

    返回今日总告警数、未处理告警数、最近1小时告警数、最近5分钟告警数
    - **account_id**: 账户ID（多账号模式）
    """
    try:
        now = datetime.now()
        return success_response(data=None, message="获取成功")
    except Exception as e:
        logger.exception(f"获取告警统计失败: {e}")
        return error_response(code=500, message=f"获取告警统计失败: {str(e)}")