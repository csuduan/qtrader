"""
策略持仓持久化服务
负责策略持仓的保存、加载、查询等操作
"""

from typing import List, Optional

from src.models.object import StrategyPosition
from src.models.po import StrategyPositionPo
from src.utils.database import session_scope
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StrategyPositionService:
    """策略持仓服务"""

    def __init__(self):
        """初始化服务"""
        pass

    def save_position(self, position: StrategyPosition) -> bool:
        """
        保存策略持仓到数据库

        Args:
            position: 策略持仓对象

        Returns:
            bool: 是否成功
        """
        try:
            with session_scope() as session:
                # 查找是否已存在记录
                existing = (
                    session.query(StrategyPositionPo)
                    .filter(
                        StrategyPositionPo.account_id == position.account_id,
                        StrategyPositionPo.strategy_id == position.strategy_id,
                        StrategyPositionPo.symbol == position.symbol,
                    )
                    .first()
                )

                if existing:
                    # 更新现有记录
                    existing.pos_long_td = position.pos_long_td
                    existing.pos_long_yd = position.pos_long_yd
                    existing.pos_short_td = position.pos_short_td
                    existing.pos_short_yd = position.pos_short_yd
                    existing.avg_price_long = position.avg_price_long
                    existing.avg_price_short = position.avg_price_short
                    existing.position_profit = position.position_profit
                    existing.close_profit = position.close_profit
                    logger.debug(
                        f"更新策略持仓: {position.account_id}/{position.strategy_id}/{position.symbol}"
                    )
                else:
                    # 创建新记录
                    po = StrategyPositionPo(
                        account_id=position.account_id or "",
                        strategy_id=position.strategy_id,
                        symbol=position.symbol,
                        pos_long_td=position.pos_long_td,
                        pos_long_yd=position.pos_long_yd,
                        pos_short_td=position.pos_short_td,
                        pos_short_yd=position.pos_short_yd,
                        avg_price_long=position.avg_price_long,
                        avg_price_short=position.avg_price_short,
                        position_profit=position.position_profit,
                        close_profit=position.close_profit,
                    )
                    session.add(po)
                    logger.debug(
                        f"创建策略持仓: {position.account_id}/{position.strategy_id}/{position.symbol}"
                    )

            return True

        except Exception as e:
            logger.exception(f"保存策略持仓失败: {e}")
            return False

    def load_positions(
        self, account_id: str, strategy_id: str
    ) -> List[StrategyPosition]:
        """
        从数据库加载策略的所有持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID

        Returns:
            List[StrategyPosition]: 持仓列表
        """
        positions = []
        try:
            with session_scope() as session:
                records = (
                    session.query(StrategyPositionPo)
                    .filter(
                        StrategyPositionPo.account_id == account_id,
                        StrategyPositionPo.strategy_id == strategy_id,
                    )
                    .all()
                )

                for record in records:
                    # 只加载有持仓的记录
                    if (
                        record.pos_long_td
                        + record.pos_long_yd
                        + record.pos_short_td
                        + record.pos_short_yd
                    ) > 0:
                        position = StrategyPosition(
                            strategy_id=record.strategy_id,
                            symbol=record.symbol,
                            account_id=record.account_id,
                            pos_long_td=record.pos_long_td or 0,
                            pos_long_yd=record.pos_long_yd or 0,
                            pos_short_td=record.pos_short_td or 0,
                            pos_short_yd=record.pos_short_yd or 0,
                            avg_price_long=float(record.avg_price_long or 0),
                            avg_price_short=float(record.avg_price_short or 0),
                            position_profit=float(record.position_profit or 0),
                            close_profit=float(record.close_profit or 0),
                            created_at=record.created_at,
                            updated_at=record.updated_at,
                        )
                        positions.append(position)

                logger.debug(
                    f"加载策略持仓: {account_id}/{strategy_id}, 共 {len(positions)} 条"
                )

        except Exception as e:
            logger.exception(f"加载策略持仓失败: {e}")

        return positions

    def load_position(
        self, account_id: str, strategy_id: str, symbol: str
    ) -> Optional[StrategyPosition]:
        """
        从数据库加载指定合约的持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID
            symbol: 合约代码

        Returns:
            StrategyPosition: 持仓对象，如果不存在则返回None
        """
        try:
            with session_scope() as session:
                record = (
                    session.query(StrategyPositionPo)
                    .filter(
                        StrategyPositionPo.account_id == account_id,
                        StrategyPositionPo.strategy_id == strategy_id,
                        StrategyPositionPo.symbol == symbol,
                    )
                    .first()
                )

                if record and (
                    record.pos_long_td
                    + record.pos_long_yd
                    + record.pos_short_td
                    + record.pos_short_yd
                ) > 0:
                    return StrategyPosition(
                        strategy_id=record.strategy_id,
                        symbol=record.symbol,
                        account_id=record.account_id,
                        pos_long_td=record.pos_long_td or 0,
                        pos_long_yd=record.pos_long_yd or 0,
                        pos_short_td=record.pos_short_td or 0,
                        pos_short_yd=record.pos_short_yd or 0,
                        avg_price_long=float(record.avg_price_long or 0),
                        avg_price_short=float(record.avg_price_short or 0),
                        position_profit=float(record.position_profit or 0),
                        close_profit=float(record.close_profit or 0),
                        created_at=record.created_at,
                        updated_at=record.updated_at,
                    )

        except Exception as e:
            logger.exception(f"加载策略持仓失败: {e}")

        return None

    def clear_position(
        self, account_id: str, strategy_id: str, symbol: Optional[str] = None
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
            with session_scope() as session:
                query = session.query(StrategyPositionPo).filter(
                    StrategyPositionPo.account_id == account_id,
                    StrategyPositionPo.strategy_id == strategy_id,
                )

                if symbol:
                    query = query.filter(StrategyPositionPo.symbol == symbol)

                query.delete(synchronize_session=False)

                if symbol:
                    logger.info(
                        f"清空策略持仓: {account_id}/{strategy_id}/{symbol}"
                    )
                else:
                    logger.info(f"清空策略所有持仓: {account_id}/{strategy_id}")

                return True

        except Exception as e:
            logger.exception(f"清空策略持仓失败: {e}")
            return False

    def clear_all_positions(self, account_id: str) -> bool:
        """
        清空账户下所有策略持仓

        Args:
            account_id: 账户ID

        Returns:
            bool: 是否成功
        """
        try:
            with session_scope() as session:
                session.query(StrategyPositionPo).filter(
                    StrategyPositionPo.account_id == account_id
                ).delete(synchronize_session=False)

                logger.info(f"清空账户所有策略持仓: {account_id}")
                return True

        except Exception as e:
            logger.exception(f"清空账户策略持仓失败: {e}")
            return False
