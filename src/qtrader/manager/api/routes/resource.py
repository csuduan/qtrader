"""
服务器资源监控路由
提供 CPU、内存、磁盘等实时指标查询
"""

from datetime import datetime

import psutil
from fastapi import APIRouter, Response

from qtrader.manager.api.responses import success_response
from qtrader.manager.api.schemas import ResourceHistory, ResourceSnapshot
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/resource", tags=["资源监控"])


async def get_resource_snapshot() -> ResourceSnapshot:
    """获取当前服务器资源快照"""
    now = datetime.now()

    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)

    # Memory
    mem = psutil.virtual_memory()
    memory_used_gb = round(mem.used / (1024**3), 2)
    memory_total_gb = round(mem.total / (1024**3), 2)
    memory_percent = round(mem.percent, 2)

    # Disk（取根目录）
    disk = psutil.disk_usage("/")
    disk_used_gb = round(disk.used / (1024**3), 2)
    disk_total_gb = round(disk.total / (1024**3), 2)
    disk_percent = round(disk.percent, 2)

    # Process count
    process_count = len(psutil.pids())

    # Boot time
    boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()

    return ResourceSnapshot(
        timestamp=now.isoformat(),
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        memory_used_gb=memory_used_gb,
        memory_total_gb=memory_total_gb,
        disk_percent=disk_percent,
        disk_used_gb=disk_used_gb,
        disk_total_gb=disk_total_gb,
        process_count=process_count,
        boot_time=boot_time,
    )


@router.get("/current")
async def resource_current() -> Response:
    """获取当前服务器资源快照"""
    try:
        snapshot = await get_resource_snapshot()
        return success_response(snapshot.model_dump())
    except Exception:
        logger.exception("获取资源快照失败")
        return success_response(message="获取资源快照失败")


@router.get("/history")
async def resource_history(points: int = 60) -> Response:
    """获取最近的服务器资源历史数据"""
    try:
        from qtrader.app_context import get_app_context

        ctx = get_app_context()
        manager = ctx.get_trading_manager()
        if not manager:
            return success_response(message="管理器未启动")

        history_data = manager.get_resource_history(points)
        return success_response(
            ResourceHistory(points=history_data, interval_seconds=5).model_dump()
        )
    except Exception:
        logger.exception("获取资源历史数据失败")
        return success_response(message="获取资源历史数据失败")
