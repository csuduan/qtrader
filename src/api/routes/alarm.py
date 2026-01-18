"""
告警相关API路由
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.dependencies import get_trading_engine, get_db_session
from src.api.responses import success_response, error_response
from src.api.schemas import AlarmRes, AlarmStatsRes
from src.models.po import AlarmPo
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/alarm", tags=["告警"])


@router.get("/list")
async def get_today_alarms(
    status_filter: Optional[str] = Query(None, description="状态筛选: UNCONFIRMED未处理/CONFIRMED已处理，不传则返回全部"),
    engine = Depends(get_trading_engine),
    session: Session = Depends(get_db_session)
):
    """
    获取当日告警列表

    支持按状态筛选：未处理/已处理/全部
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        query = session.query(AlarmPo).filter(AlarmPo.alarm_date == today)

        if status_filter:
            query = query.filter(AlarmPo.status == status_filter)

        alarms = query.order_by(AlarmPo.created_at.desc()).all()

        alarm_list = [AlarmRes.model_validate(alarm) for alarm in alarms]

        return success_response(
            data=alarm_list,
            message="获取成功"
        )
    except Exception as e:
        logger.error(f"获取告警列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取告警列表失败: {str(e)}")


@router.get("/stats")
async def get_alarm_stats(engine = Depends(get_trading_engine), session: Session = Depends(get_db_session)):
    """
    获取告警统计信息

    返回今日总告警数、未处理告警数、最近1小时告警数、最近5分钟告警数
    """
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        one_hour_ago = now - timedelta(hours=1)
        five_minutes_ago = now - timedelta(minutes=5)

        today_count = (
            session.query(AlarmPo)
            .filter(AlarmPo.alarm_date == today)
            .count()
        )

        unconfirmed_count = (
            session.query(AlarmPo)
            .filter(AlarmPo.alarm_date == today, AlarmPo.status == "UNCONFIRMED")
            .count()
        )

        last_hour_count = (
            session.query(AlarmPo)
            .filter(AlarmPo.created_at >= one_hour_ago)
            .count()
        )

        last_five_minutes_count = (
            session.query(AlarmPo)
            .filter(AlarmPo.created_at >= five_minutes_ago)
            .count()
        )

        stats = AlarmStatsRes(
            today_total=today_count,
            unconfirmed=unconfirmed_count,
            last_hour=last_hour_count,
            last_five_minutes=last_five_minutes_count
        )

        return success_response(
            data=stats,
            message="获取成功"
        )
    except Exception as e:
        logger.error(f"获取告警统计失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取告警统计失败: {str(e)}")


@router.post("/confirm/{alarm_id}")
async def confirm_alarm(alarm_id: int, session: Session = Depends(get_db_session)):
    """
    标记告警已处理

    Args:
        alarm_id: 告警ID

    Returns:
        操作结果
    """
    try:
        alarm = session.query(AlarmPo).filter(AlarmPo.id == alarm_id).first()

        if not alarm:
            return error_response(code=404, message="告警不存在")

        alarm.status = "CONFIRMED"
        session.commit()

        return success_response(
            data=AlarmRes.model_validate(alarm),
            message="标记成功"
        )
    except Exception as e:
        logger.error(f"标记告警失败: {e}", exc_info=True)
        return error_response(code=500, message=f"标记告警失败: {str(e)}")
