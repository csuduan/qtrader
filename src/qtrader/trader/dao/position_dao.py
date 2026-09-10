"""
策略持仓持久化服务
负责策略持仓的保存、加载、查询等操作
使用 PositionData 和 PositionPo
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from qtrader.models.object import Exchange, PositionData
from qtrader.models.po import PositionPo
from qtrader.utils.async_database import fetch_all, fetch_one, get_async_session
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class PositionDao:
    """账户级持仓数据访问对象"""

    async def save_dict(
        self, session: AsyncSession, account_id: str, symbol: str, data: dict[str, Any]
    ) -> None:
        """在指定会话中通过字典持久化账户级持仓（用于批量写入）"""
        position_po = await fetch_one(
            session,
            select(PositionPo).filter_by(account_id=account_id, symbol=symbol, strategy_id=None),
        )
        if not position_po:
            position_po = PositionPo(
                account_id=account_id,
                symbol=symbol,
                exchange=data.get("exchange", ""),
            )

        position_po.pos_long_td = data.get("pos_long_td") or 0
        position_po.pos_long_yd = data.get("pos_long_yd") or 0
        position_po.pos_short_td = data.get("pos_short_td") or 0
        position_po.pos_short_yd = data.get("pos_short_yd") or 0
        position_po.hold_price_long = Decimal(str(data.get("hold_price_long") or 0))
        position_po.hold_price_short = Decimal(str(data.get("hold_price_short") or 0))
        position_po.hold_profit_long = Decimal(str(data.get("hold_profit_long") or 0))
        position_po.hold_profit_short = Decimal(str(data.get("hold_profit_short") or 0))
        margin_long = Decimal(str(data.get("margin_long") or 0))
        margin_short = Decimal(str(data.get("margin_short") or 0))
        position_po.margin = margin_long + margin_short
        position_po.updated_at = datetime.now()

        session.add(position_po)


class StrategyPositionService:
    """策略持仓服务"""

    def __init__(self):
        """初始化服务"""
        pass

    async def save_position(self, position: PositionData) -> bool:
        """
        保存策略持仓到数据库

        Args:
            position: 策略持仓对象（包含 strategy_id）

        Returns:
            bool: 是否成功
        """
        try:
            async with get_async_session() as session:
                # 查找是否已存在记录
                existing = await fetch_one(
                    session,
                    select(PositionPo).filter(
                        PositionPo.account_id == position.extras.get("account_id", ""),
                        PositionPo.strategy_id == position.strategy_id,
                        PositionPo.symbol == position.symbol,
                    ),
                )

                if existing:
                    # 更新现有记录
                    existing.pos_long_td = position.pos_long_td or 0  # type: ignore[assignment]
                    existing.pos_long_yd = position.pos_long_yd or 0  # type: ignore[assignment]
                    existing.pos_short_td = position.pos_short_td or 0  # type: ignore[assignment]
                    existing.pos_short_yd = position.pos_short_yd or 0  # type: ignore[assignment]
                    existing.hold_price_long = position.hold_price_long or 0  # type: ignore[assignment]
                    existing.hold_price_short = position.hold_price_short or 0  # type: ignore[assignment]
                    existing.close_profit_long = position.close_profit_long or 0  # type: ignore[assignment]
                    existing.close_profit_short = position.close_profit_short or 0  # type: ignore[assignment]
                    logger.debug(
                        f"更新策略持仓: {position.extras.get('account_id', '')}/{position.strategy_id}/{position.symbol}"
                    )
                else:
                    # 创建新记录
                    po = PositionPo(
                        account_id=position.extras.get("account_id", ""),
                        strategy_id=position.strategy_id,
                        symbol=position.symbol,
                        exchange=position.exchange.value,
                        multiple=position.multiple or 0,
                        pos_long_td=position.pos_long_td or 0,
                        pos_long_yd=position.pos_long_yd or 0,
                        pos_short_td=position.pos_short_td or 0,
                        pos_short_yd=position.pos_short_yd or 0,
                        hold_price_long=position.hold_price_long or 0,
                        hold_price_short=position.hold_price_short or 0,
                        close_profit_long=position.close_profit_long or 0,
                        close_profit_short=position.close_profit_short or 0,
                    )
                    session.add(po)
                    logger.debug(
                        f"创建策略持仓: {position.extras.get('account_id', '')}/{position.strategy_id}/{position.symbol}"
                    )

            return True

        except Exception as e:
            logger.exception(f"保存策略持仓失败: {e}")
            return False

    async def load_positions(self, account_id: str, strategy_id: str) -> list[PositionData]:
        """
        从数据库加载策略的所有持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID

        Returns:
            list[PositionData]: 持仓列表
        """
        positions = []
        try:
            async with get_async_session() as session:
                records = await fetch_all(
                    session,
                    select(PositionPo).filter(
                        PositionPo.account_id == account_id,
                        PositionPo.strategy_id == strategy_id,
                    ),
                )

                for record in records:
                    # 只加载有持仓的记录
                    if (
                        record.pos_long_td
                        + record.pos_long_yd
                        + record.pos_short_td
                        + record.pos_short_yd
                    ) > 0:
                        position = PositionData(
                            symbol=record.symbol,
                            exchange=Exchange.from_str(record.exchange),  # type: ignore[arg-type]
                            multiple=record.multiple or 0,
                            strategy_id=record.strategy_id,
                            pos_long_td=record.pos_long_td or 0,
                            pos_long_yd=record.pos_long_yd or 0,
                            pos_short_td=record.pos_short_td or 0,
                            pos_short_yd=record.pos_short_yd or 0,
                            hold_price_long=float(record.hold_price_long or 0),
                            hold_price_short=float(record.hold_price_short or 0),
                            close_profit_long=float(record.close_profit_long or 0),
                            close_profit_short=float(record.close_profit_short or 0),
                            extras={"account_id": record.account_id},
                        )
                        positions.append(position)

                logger.debug(f"加载策略持仓: {account_id}/{strategy_id}, 共 {len(positions)} 条")

        except Exception as e:
            logger.exception(f"加载策略持仓失败: {e}")

        return positions

    async def load_position(
        self, account_id: str, strategy_id: str, symbol: str
    ) -> PositionData | None:
        """
        从数据库加载指定合约的持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID
            symbol: 合约代码

        Returns:
            PositionData: 持仓对象，如果不存在则返回None
        """
        try:
            async with get_async_session() as session:
                record = await fetch_one(
                    session,
                    select(PositionPo).filter(
                        PositionPo.account_id == account_id,
                        PositionPo.strategy_id == strategy_id,
                        PositionPo.symbol == symbol,
                    ),
                )

                if (
                    record
                    and (
                        record.pos_long_td
                        + record.pos_long_yd
                        + record.pos_short_td
                        + record.pos_short_yd
                    )
                    > 0
                ):
                    return PositionData(
                        symbol=record.symbol,
                        exchange=Exchange.from_str(record.exchange),  # type: ignore[arg-type]
                        strategy_id=record.strategy_id,
                        pos_long_td=record.pos_long_td or 0,
                        pos_long_yd=record.pos_long_yd or 0,
                        pos_short_td=record.pos_short_td or 0,
                        pos_short_yd=record.pos_short_yd or 0,
                        hold_price_long=float(record.hold_price_long or 0),
                        hold_price_short=float(record.hold_price_short or 0),
                        close_profit_long=float(record.close_profit_long or 0),
                        close_profit_short=float(record.close_profit_short or 0),
                        extras={"account_id": record.account_id},
                    )

        except Exception as e:
            logger.exception(f"加载策略持仓失败: {e}")

        return None

    async def clear_position(
        self, account_id: str, strategy_id: str, symbol: str | None = None
    ) -> bool:
        """
        清空策略持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID
            symbol: 合约代码，如果为None则清空所有持仓

        Returns:
            bool: 是否成功
        """
        try:
            async with get_async_session() as session:
                stmt = delete(PositionPo).where(
                    PositionPo.account_id == account_id,
                    PositionPo.strategy_id == strategy_id,
                )

                if symbol:
                    stmt = stmt.where(PositionPo.symbol == symbol)

                await session.execute(stmt)

                if symbol:
                    logger.info(f"清空策略持仓: {account_id}/{strategy_id}/{symbol}")
                else:
                    logger.info(f"清空策略所有持仓: {account_id}/{strategy_id}")

                return True

        except Exception as e:
            logger.exception(f"清空策略持仓失败: {e}")
            return False

    async def clear_all_positions(self, account_id: str) -> bool:
        """
        清空账户下所有策略持仓

        Args:
            account_id: 账户ID

        Returns:
            bool: 是否成功
        """
        try:
            async with get_async_session() as session:
                await session.execute(
                    delete(PositionPo).where(
                        PositionPo.account_id == account_id,
                        PositionPo.strategy_id.is_not(None),  # 只删除策略持仓
                    )
                )

                logger.info(f"清空账户所有策略持仓: {account_id}")
                return True

        except Exception as e:
            logger.exception(f"清空账户策略持仓失败: {e}")
            return False
