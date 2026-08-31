"""
K线数据相关API路由
查询由 Manager 数据服务（ManagerDataFeed）落库的K线数据，支持手动同步
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.manager import TradingManager
from qtrader.trader.dao.bar_dao import BarDao
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/bars", tags=["K线数据"])


@router.get("")
async def get_bars(
    symbol: str = Query(..., description="合约代码，如IM2609"),
    interval: str = Query(default="M1", description="K线周期，如M1/M5"),
    start: datetime = Query(..., description="起始时间（ISO格式）"),
    end: datetime = Query(..., description="结束时间（ISO格式）"),
    limit: int = Query(default=500, ge=1, le=5000, description="最大返回条数"),
):
    """
    查询K线数据（bars_history + bars_today 合并去重，当日表优先）

    Returns:
        按时间升序的bar列表：[{datetime, open, high, low, close, volume, source}]
    """
    try:
        bars = await asyncio.to_thread(BarDao().query_bars, symbol, interval, start, end, limit)
        return success_response(data=bars, message=f"获取成功，共{len(bars)}根")
    except Exception as e:
        logger.exception(f"查询K线失败: {symbol} {interval}: {e}")
        return error_response(code=500, message=f"查询K线失败: {str(e)}")


@router.post("/sync")
async def sync_bars(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """
    手动同步K线数据（故障恢复）

    触发数据服务全量同步：补齐新订阅合约 + 全量K线落库（覆盖修正当日及历史）
    """
    try:
        data_feed = trading_manager.data_feed
        if not data_feed:
            return error_response(code=503, message="数据服务未启动（未配置tq_data账号）")
        message = await asyncio.to_thread(data_feed.request_resync)
        return success_response(data={"message": message}, message="同步已触发")
    except Exception as e:
        logger.exception(f"手动同步K线失败: {e}")
        return error_response(code=500, message=f"手动同步K线失败: {str(e)}")


@router.get("/feed/status")
async def get_feed_status(
    trading_manager: TradingManager = Depends(get_trading_manager),
):
    """查询数据服务状态"""
    data_feed = trading_manager.data_feed
    if not data_feed:
        return success_response(data={"enabled": False, "connected": False})
    return success_response(
        data={
            "enabled": True,
            "connected": data_feed.connected,
            "subscriptions": [
                {"symbol": symbol, "interval": interval}
                for symbol, interval in data_feed._klines.keys()
            ],
        }
    )
