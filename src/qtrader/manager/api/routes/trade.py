"""
成交相关API路由
"""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from qtrader.manager.api.dependencies import get_trading_manager
from qtrader.manager.api.responses import error_response, success_response
from qtrader.manager.api.schemas import TradeRes
from qtrader.manager.manager import TradingManager
from qtrader.models.object import TradeData
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/trade", tags=["成交"])


async def _query_trades_from_db(
    account_id: str | None,
    date: str,
) -> list[dict[str, Any]]:
    """从PG查询历史成交记录

    Args:
        account_id: 账户ID（可选，None则查全部）
        date: 查询日期 YYYY-MM-DD

    Returns:
        成交记录字典列表
    """
    from sqlalchemy import select

    from qtrader.models.po import TradePo
    from qtrader.utils.async_database import get_async_database

    db = get_async_database()
    if not db:
        return []

    # 将日期转为当日时间范围（与DAO落库口径一致：naive datetime）
    try:
        start_dt = datetime.strptime(date, "%Y-%m-%d")
        end_dt = datetime(start_dt.year, start_dt.month, start_dt.day, 23, 59, 59)
    except ValueError:
        return []

    async with db.get_session() as session:
        stmt = select(TradePo).filter(
            TradePo.trade_date_time >= start_dt,
            TradePo.trade_date_time <= end_dt,
        )
        if account_id:
            stmt = stmt.filter(TradePo.account_id == account_id)

        trade_pos = (
            (await session.execute(stmt.order_by(TradePo.trade_date_time.desc()))).scalars().all()
        )

        result = [
            {
                "account_id": t.account_id,
                "trade_id": t.trade_id,
                "order_id": t.order_id or "",
                "symbol": t.symbol,
                "direction": t.direction,
                "offset": t.offset,
                "price": float(t.price) if t.price else 0,
                "volume": t.volume or 0,
                "trade_date_time": t.trade_date_time or datetime.now(),
                "created_at": t.created_at or datetime.now(),
            }
            for t in trade_pos
        ]
        return result


@router.get("")
async def get_trades(
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
    date: str | None = Query(None, description="查询日期（YYYY-MM-DD格式），默认为今日"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    获取成交记录

    - 当日成交记录从内存缓存查询（由Trader实时推送维护）
    - 历史成交记录从数据库查询
    """
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        query_date = date or today

        if query_date == today:
            # 当天：从内存缓存查询
            trades_list: list[TradeData] = await trading_manager.get_trades(account_id=account_id)
            trades_list.sort(key=lambda x: x.trade_time or 0, reverse=True)

            data = []
            for trade in trades_list:
                trade_time_ts = 0
                if trade.trade_time:
                    if isinstance(trade.trade_time, datetime):
                        trade_time_ts = int(trade.trade_time.timestamp())
                    elif isinstance(trade.trade_time, (int, float)):
                        trade_time_ts = int(trade.trade_time)

                data.append(
                    TradeRes(
                        id=0,
                        account_id=trade.account_id,
                        trade_id=trade.trade_id,
                        order_id=trade.order_id,
                        symbol=trade.symbol,
                        direction=(
                            trade.direction.value
                            if hasattr(trade.direction, "value")
                            else str(trade.direction)
                        ),
                        offset=(
                            trade.offset.value
                            if hasattr(trade.offset, "value")
                            else str(trade.offset)
                        ),
                        price=float(trade.price),
                        volume=trade.volume,
                        trade_date_time=(
                            datetime.fromtimestamp(trade_time_ts)
                            if trade_time_ts
                            else datetime.now()
                        ),
                        created_at=datetime.now(),
                    )
                )
        else:
            # 历史：从PG查询
            db_trades = await _query_trades_from_db(account_id, query_date)
            data = [
                TradeRes(
                    id=0,
                    account_id=t["account_id"],
                    trade_id=t["trade_id"],
                    order_id=t["order_id"],
                    symbol=t["symbol"],
                    direction=t["direction"],
                    offset=t["offset"],
                    price=float(t["price"]),
                    volume=t["volume"],
                    trade_date_time=t["trade_date_time"],
                    created_at=t["created_at"],
                )
                for t in db_trades
            ]

        return success_response(data=data, message="获取成功")
    except Exception as e:
        logger.exception("获取成交记录失败")
        return error_response(code=500, message=f"获取成交记录失败: {e}")


@router.get("/order/{order_id}")
async def get_trades_by_order(
    order_id: str,
    account_id: str | None = Query(None, description="账户ID（多账号模式）"),
    trading_manager: TradingManager = Depends(get_trading_manager),
) -> Response:
    """
    获取指定委托单的成交记录

    - **order_id**: 委托单ID
    - **account_id**: 可选，指定账户ID筛选（多账号模式）
    """
    try:
        all_trades = await trading_manager.get_trades(account_id)

        order_trades = [
            TradeRes(
                id=0,
                account_id=trade.account_id,
                trade_id=trade.trade_id,
                order_id=trade.order_id,
                symbol=trade.symbol,
                direction=(
                    trade.direction.value
                    if hasattr(trade.direction, "value")
                    else str(trade.direction)
                ),
                offset=(
                    trade.offset.value if hasattr(trade.offset, "value") else str(trade.offset)
                ),
                price=float(trade.price),
                volume=trade.volume,
                trade_date_time=trade.trade_time or datetime.now(),
                created_at=datetime.now(),
            )
            for trade in all_trades
            if trade.order_id == order_id
        ]

        return success_response(data=order_trades, message="获取成功")
    except Exception as e:
        logger.exception("获取委托单成交记录失败")
        return error_response(code=500, message=f"获取委托单成交记录失败: {e}")
