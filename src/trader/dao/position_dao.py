"""
策略持仓持久化服务
负责策略持仓的保存、加载、查询等操作
使用 PositionData 和 PositionPo
"""

from typing import List, Optional

from src.models.object import PositionData,Exchange
from src.models.po import PositionPo
from src.utils.database import session_scope
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StrategyPositionService:
    """策略持仓服务"""

    def __init__(self):
        """初始化服务"""
        pass

    def save_position(self, position: PositionData) -> bool:
        """
        保存策略持仓到数据库

        Args:
            position: 策略持仓对象（包含 strategy_id）

        Returns:
            bool: 是否成功
        """
        try:
            with session_scope() as session:
                # 查找是否已存在记录
                existing = (
                    session.query(PositionPo)
                    .filter(
                        PositionPo.account_id == position.extras.get("account_id", ""),
                        PositionPo.strategy_id == position.strategy_id,
                        PositionPo.symbol == position.symbol,
                    )
                    .first()
                )

                if existing:
                    # 更新现有记录
                    existing.pos_long_td = position.pos_long_td or 0
                    existing.pos_long_yd = position.pos_long_yd or 0
                    existing.pos_short_td = position.pos_short_td or 0
                    existing.pos_short_yd = position.pos_short_yd or 0
                    existing.hold_price_long = position.hold_price_long or 0
                    existing.hold_price_short = position.hold_price_short or 0
                    existing.close_profit_long = position.close_profit_long or 0
                    existing.close_profit_short = position.close_profit_short or 0
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

    def load_positions(
        self, account_id: str, strategy_id: str
    ) -> List[PositionData]:
        """
        从数据库加载策略的所有持仓

        Args:
            account_id: 账户ID
            strategy_id: 策略ID

        Returns:
            List[PositionData]: 持仓列表
        """
        positions = []
        try:
            with session_scope() as session:
                records = (
                    session.query(PositionPo)
                    .filter(
                        PositionPo.account_id == account_id,
                        PositionPo.strategy_id == strategy_id,
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
                        position = PositionData(
                            symbol=record.symbol,
                            exchange=Exchange.from_str(record.exchange),
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

                logger.debug(
                    f"加载策略持仓: {account_id}/{strategy_id}, 共 {len(positions)} 条"
                )

        except Exception as e:
            logger.exception(f"加载策略持仓失败: {e}")

        return positions

    def load_position(
        self, account_id: str, strategy_id: str, symbol: str
    ) -> Optional[PositionData]:
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
            with session_scope() as session:
                record = (
                    session.query(PositionPo)
                    .filter(
                        PositionPo.account_id == account_id,
                        PositionPo.strategy_id == strategy_id,
                        PositionPo.symbol == symbol,
                    )
                    .first()
                )

                if record and (
                    record.pos_long_td
                    + record.pos_long_yd
                    + record.pos_short_td
                    + record.pos_short_yd
                ) > 0:
                    return PositionData(
                        symbol=record.symbol,
                        exchange=Exchange.from_str(record.exchange),
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
                query = session.query(PositionPo).filter(
                    PositionPo.account_id == account_id,
                    PositionPo.strategy_id == strategy_id,
                )

                if symbol:
                    query = query.filter(PositionPo.symbol == symbol)

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
                session.query(PositionPo).filter(
                    PositionPo.account_id == account_id,
                    PositionPo.strategy_id.is_not(None),  # 只删除策略持仓
                ).delete(synchronize_session=False)

                logger.info(f"清空账户所有策略持仓: {account_id}")
                return True

        except Exception as e:
            logger.exception(f"清空账户策略持仓失败: {e}")
            return False
