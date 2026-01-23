"""
成交相关API路由
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import get_db_session, get_trading_engine
from src.api.responses import success_response, error_response
from src.api.schemas import TradeRes
from src.models.po import TradePo
from src.trading_engine import TradingEngine

router = APIRouter(prefix="/api/trade", tags=["成交"])


@router.get("")
async def get_trades(
    limit: int = Query(100, ge=1, le=1000, description="返回记录数量"),
    offset: int = Query(0, ge=0, description="偏移量"),
    date: Optional[str] = Query(None, description="查询日期（YYYY-MM-DD格式），默认为今日"),
    from_db: bool = Query(False, description="强制从数据库查询（覆盖日期判断）"),
    session  = Depends(get_db_session),
    engine:TradingEngine = Depends(get_trading_engine),
):
    """
    获取成交记录

    返回最近的成交记录，支持分页
    - 今日成交记录自动从内存查询
    - 历史成交记录自动从数据库查询
    - 设置from_db=true可强制从数据库查询
    """
    from datetime import date as date_type
    from datetime import timedelta

    today = date_type.today()
    query_date = None

    if date:
        try:
            query_date = date_type.fromisoformat(date)
        except ValueError:
            return error_response(code=400, message="日期格式错误，请使用YYYY-MM-DD格式")

    # 判断查询来源
    if from_db:
        query_from_db = True
    elif query_date is None:
        # 未指定日期，默认查询今日数据，从内存获取
        query_from_db = False
    elif query_date == today:
        # 查询今日数据，从内存获取
        query_from_db = False
    else:
        # 查询历史数据，从数据库获取
        query_from_db = True

    if query_from_db:
        # 从数据库查询
        account_id = engine.account.get("account_id", "") if engine.account else ""
        query = session.query(TradePo).filter_by(account_id=account_id)

        # 如果指定了日期，添加日期过滤
        if query_date:
            start_datetime = datetime.combine(query_date, datetime.min.time())
            end_datetime = start_datetime + timedelta(days=1)
            query = query.filter(
                TradePo.created_at >= start_datetime,
                TradePo.created_at < end_datetime
            )

        trades = query.order_by(TradePo.created_at.desc()).limit(limit).offset(offset).all()

        return success_response(
            data=[TradeRes.model_validate(trade) for trade in trades],
            message="获取成功"
        )
    else:
        # 从内存查询
        if not engine or not engine.trades:
            return success_response(
                data=[],
                message="获取成功"
            )

        trades = engine.trades
        end_index = offset + limit
        #paginated_trades = trades[offset:end_index]
        paginated_trades = trades

        return success_response(
            data=[
                TradeRes(
                    id=0,
                    account_id=engine.account.get("account_id", "") if engine.account else "",
                    trade_id=trade.get("trade_id", ""),
                    order_id=trade.get("order_id", ""),
                    symbol=trade.get("instrument_id", ""),
                    direction=trade.get("direction", ""),
                    offset=trade.get("offset", ""),
                    price=float(trade.get("price", 0)),
                    volume=trade.get("volume", 0),
                    trade_date_time=datetime.fromtimestamp(trade.trade_date_time/1_000_000_000),
                    created_at=datetime.now(),
                )
                for id,trade in paginated_trades.items()
            ],
            message="获取成功"
        )


@router.get("/{trade_id}")
async def get_trade_by_id(
    trade_id: str,
    from_db: bool = Query(False, description="是否从数据库查询（默认从TradingEngine获取当日数据）"),
    session = Depends(get_db_session),
    engine = Depends(get_trading_engine),
):
    """
    获取指定成交详情

    - **trade_id**: 成交ID
    - **from_db**: 是否从数据库查询（默认从TradingEngine获取当日数据）
    """
    if from_db:
        account_id = engine.account.get("account_id", "") if engine.account else ""
        trade = session.query(TradePo).filter_by(
            account_id=account_id, trade_id=trade_id
        ).first()

        if not trade:
            return error_response(code=404, message="成交记录不存在")

        return success_response(
            data=TradeRes.model_validate(trade),
            message="获取成功"
        )
    else:
        if not engine or not engine.trades:
            return error_response(code=404, message="成交记录不存在")

        trade = next((trade for trade in engine.trades if trade.get("trade_id") == trade_id), None)

        if not trade:
            return error_response(code=404, message="成交记录不存在")

        return success_response(
            data=TradeRes(
                id=0,
                account_id=engine.account.get("account_id", "") if engine.account else "",
                trade_id=trade.get("trade_id", ""),
                order_id=trade.get("order_id", ""),
                symbol=trade.get("symbol", ""),
                direction=trade.get("direction", ""),
                offset=trade.get("offset", ""),
                price=float(trade.get("price", 0)),
                volume=trade.get("volume", 0),
                trade_date_time=trade.get("trade_date_time", 0),
                created_at=datetime.now(),
            ),
            message="获取成功"
        )


@router.get("/order/{order_id}")
async def get_trades_by_order(
    order_id: str,
    session = Depends(get_db_session),
    engine = Depends(get_trading_engine),
):
    """
    获取指定委托单的成交记录

    - **order_id**: 委托单ID
    """
    account_id = engine.account.get("account_id", "") if engine.account else ""

    trades = session.query(TradePo).filter_by(
        account_id=account_id, order_id=order_id
    ).order_by(TradePo.trade_date_time.desc()).all()

    return success_response(
        data=[TradeRes.model_validate(trade) for trade in trades],
        message="获取成功"
    )
