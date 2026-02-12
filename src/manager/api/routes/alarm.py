"""
告警相关API路由
"""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.manager.api.responses import error_response, success_response
from src.manager.api.schemas import AlarmRes, AlarmStatsRes
from src.models.po import AlarmPo
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/alarm", tags=["告警"])


class AlarmConfirmReq(BaseModel):
    """告警确认请求"""

    account_id: Optional[str] = None


def get_db(request: Request):
    """从 app.state 获取数据库实例"""
    db = request.app.state.db
    if db is None:
        raise RuntimeError("数据库未初始化，请检查应用启动配置")
    return db


@router.get("/list")
async def get_today_alarms(
    request: Request,
    status_filter: Optional[str] = Query(
        None, description="状态筛选: UNCONFIRMED未处理/CONFIRMED已处理，不传则返回全部"
    ),
):
    """
    获取当日告警列表

    支持按状态筛选：未处理/已处理/全部
    """
    db = get_db(request)
    session: Session = db.get_session_sync()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        query = session.query(AlarmPo).filter(AlarmPo.alarm_date == today)

        if status_filter:
            query = query.filter(AlarmPo.status == status_filter)

        alarms = query.order_by(AlarmPo.created_at.desc()).all()
        data = [AlarmRes.model_validate(alarm) for alarm in alarms]

        return success_response(data=data, message="获取成功")
    except Exception as e:
        logger.error(f"获取告警列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取告警列表失败: {str(e)}")
    finally:
        session.close()


@router.get("/stats")
async def get_alarm_stats(request: Request):
    """
    获取告警统计信息

    返回今日总告警数、未处理告警数、最近1小时告警数、最近5分钟告警数
    """
    db = get_db(request)
    session: Session = db.get_session_sync()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        five_minutes_ago = now - timedelta(minutes=5)

        # 今日总告警数
        today_total = (
            session.query(func.count(AlarmPo.id))
            .filter(AlarmPo.alarm_date == today)
            .scalar()
            or 0
        )

        # 未处理告警数
        unconfirmed = (
            session.query(func.count(AlarmPo.id))
            .filter(and_(AlarmPo.alarm_date == today, AlarmPo.status == "UNCONFIRMED"))
            .scalar()
            or 0
        )

        # 最近1小时告警数
        last_hour = (
            session.query(func.count(AlarmPo.id))
            .filter(AlarmPo.created_at >= one_hour_ago)
            .scalar()
            or 0
        )

        # 最近5分钟告警数
        last_five_minutes = (
            session.query(func.count(AlarmPo.id))
            .filter(AlarmPo.created_at >= five_minutes_ago)
            .scalar()
            or 0
        )

        data = AlarmStatsRes(
            today_total=today_total,
            unconfirmed=unconfirmed,
            last_hour=last_hour,
            last_five_minutes=last_five_minutes,
        )

        return success_response(data=data, message="获取成功")
    except Exception as e:
        logger.exception(f"获取告警统计失败: {e}")
        return error_response(code=500, message=f"获取告警统计失败: {str(e)}")
    finally:
        session.close()


@router.post("/confirm/{alarm_id}")
async def confirm_alarm(
    alarm_id: int,
    req: Optional[AlarmConfirmReq] = None,
    request: Request = None,
):
    """
    确认告警

    将告警状态从 UNCONFIRMED 改为 CONFIRMED
    """
    db = get_db(request)
    session: Session = db.get_session_sync()
    try:
        alarm = session.query(AlarmPo).filter(AlarmPo.id == alarm_id).first()
        if not alarm:
            return error_response(code=404, message="告警不存在")

        alarm.status = "CONFIRMED"
        session.commit()

        data = AlarmRes.model_validate(alarm)
        return success_response(data=data, message="确认成功")
    except Exception as e:
        session.rollback()
        logger.exception(f"确认告警失败: {e}")
        return error_response(code=500, message=f"确认告警失败: {str(e)}")
    finally:
        session.close()


@router.post("/confirm_all")
async def confirm_all_alarms(
    req: Optional[AlarmConfirmReq] = None,
    request: Request = None,
):
    """
    批量确认所有未处理的告警

    将所有状态为 UNCONFIRMED 的告警改为 CONFIRMED
    支持按账户ID筛选
    只处理当日的告警

    返回确认的告警数量
    """
    db = get_db(request)
    session: Session = db.get_session_sync()
    try:
        today = datetime.now().strftime("%Y-%m-%d")

        # 构建查询条件：只处理当日未确认的告警
        query = session.query(AlarmPo).filter(
            AlarmPo.status == "UNCONFIRMED",
            AlarmPo.alarm_date == today
        )

        # 如果提供了账户ID，按账户筛选
        account_id = None
        if req and req.account_id:
            account_id = req.account_id
            query = query.filter(AlarmPo.account_id == account_id)

        # 批量更新
        confirmed_count = query.update({"status": "CONFIRMED"}, synchronize_session=False)
        session.commit()

        return success_response(
            data={"confirmed_count": confirmed_count}, message=f"已确认 {confirmed_count} 条告警"
        )
    except Exception as e:
        session.rollback()
        logger.exception(f"批量确认告警失败: {e}")
        return error_response(code=500, message=f"批量确认告警失败: {str(e)}")
    finally:
        session.close()
