"""
告警相关API路由
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select, update

from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.api.schemas import AlarmRes, AlarmStatsRes
from qtrader.models.po import AlarmPo
from qtrader.utils.async_database import get_async_database
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/alarm", tags=["告警"])


class AlarmConfirmReq(BaseModel):
    """告警确认请求"""

    account_id: str | None = None


@router.get("/list")
async def get_today_alarms(
    request: Request,
    account_id: str | None = Query(None, description="账户ID，不传则返回所有账户"),
    status_filter: str | None = Query(
        None, description="状态筛选: UNCONFIRMED未处理/CONFIRMED已处理，不传则返回全部"
    ),
):
    """
    获取当日告警列表

    支持按账户和状态筛选：未处理/已处理/全部
    """
    try:
        db = get_async_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        async with db.get_session() as session:
            today = datetime.now().strftime("%Y-%m-%d")
            stmt = select(AlarmPo).filter(AlarmPo.alarm_date == today)

            # 按账户筛选
            if account_id:
                stmt = stmt.filter(AlarmPo.account_id == account_id)

            if status_filter:
                stmt = stmt.filter(AlarmPo.status == status_filter)

            alarms = (
                (await session.execute(stmt.order_by(AlarmPo.created_at.desc()))).scalars().all()
            )

        data = [AlarmRes.model_validate(alarm) for alarm in alarms]

        return success_response(data=data, message="获取成功")
    except Exception as e:
        logger.error(f"获取告警列表失败: {e}", exc_info=True)
        return error_response(code=500, message=f"获取告警列表失败: {str(e)}")


@router.get("/stats")
async def get_alarm_stats(
    request: Request,
    account_id: str | None = Query(None, description="账户ID，不传则统计所有账户"),
):
    """
    获取告警统计信息

    返回今日总告警数、未处理告警数、最近1小时告警数、最近5分钟告警数
    支持按账户筛选
    """
    try:
        db = get_async_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        async with db.get_session() as session:
            today = datetime.now().strftime("%Y-%m-%d")
            now = datetime.now()
            one_hour_ago = now - timedelta(hours=1)
            five_minutes_ago = now - timedelta(minutes=5)

            # 构建基础查询
            def build_base_stmt():
                stmt = select(func.count(AlarmPo.id))
                if account_id:
                    stmt = stmt.filter(AlarmPo.account_id == account_id)
                return stmt

            # 今日总告警数
            today_total = (
                await session.scalar(build_base_stmt().filter(AlarmPo.alarm_date == today)) or 0
            )

            # 未处理告警数
            unconfirmed = (
                await session.scalar(
                    build_base_stmt().filter(
                        and_(AlarmPo.alarm_date == today, AlarmPo.status == "UNCONFIRMED")
                    )
                )
                or 0
            )

            # 最近1小时告警数
            last_hour = (
                await session.scalar(build_base_stmt().filter(AlarmPo.created_at >= one_hour_ago))
                or 0
            )

            # 最近5分钟告警数
            last_five_minutes = (
                await session.scalar(
                    build_base_stmt().filter(AlarmPo.created_at >= five_minutes_ago)
                )
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


@router.post("/confirm/{alarm_id}")
async def confirm_alarm(
    alarm_id: int,
    req: AlarmConfirmReq | None = None,
    request: Request = None,
):
    """
    确认告警

    将告警状态从 UNCONFIRMED 改为 CONFIRMED
    """
    try:
        db = get_async_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        async with db.get_session() as session:
            alarm = (
                await session.execute(select(AlarmPo).filter(AlarmPo.id == alarm_id))
            ).scalar_one_or_none()
            if not alarm:
                return error_response(code=404, message="告警不存在")

            alarm.status = "CONFIRMED"

        data = AlarmRes.model_validate(alarm)
        return success_response(data=data, message="确认成功")
    except Exception as e:
        logger.exception(f"确认告警失败: {e}")
        return error_response(code=500, message=f"确认告警失败: {str(e)}")


@router.post("/confirm_all")
async def confirm_all_alarms(
    req: AlarmConfirmReq | None = None,
    request: Request = None,
):
    """
    批量确认所有未处理的告警

    将所有状态为 UNCONFIRMED 的告警改为 CONFIRMED
    支持按账户ID筛选
    只处理当日的告警

    返回确认的告警数量
    """
    try:
        db = get_async_database()
        if not db:
            return error_response(code=500, message="数据库未初始化")

        async with db.get_session() as session:
            today = datetime.now().strftime("%Y-%m-%d")

            # 构建更新条件：只处理当日未确认的告警
            conditions = [AlarmPo.status == "UNCONFIRMED", AlarmPo.alarm_date == today]

            # 如果提供了账户ID，按账户筛选
            if req and req.account_id:
                conditions.append(AlarmPo.account_id == req.account_id)

            # 批量更新
            result = await session.execute(
                update(AlarmPo).where(*conditions).values(status="CONFIRMED")
            )
            confirmed_count = result.rowcount or 0

        return success_response(
            data={"confirmed_count": confirmed_count}, message=f"已确认 {confirmed_count} 条告警"
        )
    except Exception as e:
        logger.exception(f"批量确认告警失败: {e}")
        return error_response(code=500, message=f"批量确认告警失败: {str(e)}")


@router.get("/suppression")
async def get_suppression_status(
    request: Request,
    account_id: str | None = Query(None, description="账户ID，不传则返回所有账户"),
):
    """
    获取异常告警压制状态

    返回各账户各指标的压制状态
    """
    try:
        from qtrader.app_context import get_app_context

        ctx = get_app_context()
        alarm_service = ctx.get_alarm_service()

        if not alarm_service:
            return error_response(code=500, message="告警服务未初始化")

        status = alarm_service.get_suppression_status(account_id)
        return success_response(data=status, message="获取成功")
    except Exception as e:
        logger.exception(f"获取压制状态失败: {e}")
        return error_response(code=500, message=f"获取压制状态失败: {str(e)}")


@router.post("/suppression/clear/{account_id}")
async def clear_suppression(
    account_id: str,
    indicator: str | None = Query(
        None, description="指标类型(1min/5min/1hour)，不传则清除该账户所有压制"
    ),
):
    """
    清除指定账户的异常告警压制状态

    Args:
        account_id: 账户ID
        indicator: 指标类型，不传则清除该账户所有压制
    """
    try:
        from qtrader.app_context import get_app_context

        ctx = get_app_context()
        alarm_service = ctx.get_alarm_service()

        if not alarm_service:
            return error_response(code=500, message="告警服务未初始化")

        alarm_service.clear_suppression(account_id, indicator)

        if indicator:
            return success_response(message=f"已清除 [{account_id}] {indicator} 的压制状态")
        else:
            return success_response(message=f"已清除 [{account_id}] 所有压制状态")
    except Exception as e:
        logger.exception(f"清除压制状态失败: {e}")
        return error_response(code=500, message=f"清除压制状态失败: {str(e)}")


@router.post("/suppression/clear_all")
async def clear_all_suppression():
    """清除所有异常告警压制状态（管理员用）"""
    try:
        from qtrader.app_context import get_app_context

        ctx = get_app_context()
        alarm_service = ctx.get_alarm_service()

        if not alarm_service:
            return error_response(code=500, message="告警服务未初始化")

        alarm_service.clear_all_suppression()
        return success_response(message="已清除所有压制状态")
    except Exception as e:
        logger.exception(f"清除所有压制状态失败: {e}")
        return error_response(code=500, message=f"清除所有压制状态失败: {str(e)}")
