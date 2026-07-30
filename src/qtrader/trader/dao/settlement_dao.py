"""
每日结算快照持久化DAO
保存每日结算后的账户权益与账户级持仓历史
"""

from datetime import date
from decimal import Decimal

from qtrader.models.object import AccountData, PositionData
from qtrader.models.po import AccountHistoryPo, PositionHistoryPo
from qtrader.utils.database import session_scope
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


def _to_decimal(value: float | None) -> Decimal | None:
    """将可选浮点数转换为 Decimal，None 保持 None"""
    return Decimal(str(value)) if value is not None else None


class SettlementDao:
    """每日结算快照数据访问对象"""

    def save_settlement(self, account_id: str, settle_date: date, account: AccountData) -> None:
        """
        保存账户每日结算权益快照（同日重复保存则覆盖）

        Args:
            account_id: 账户ID
            settle_date: 结算日期
            account: 账户数据
        """
        with session_scope() as session:
            po = (
                session.query(AccountHistoryPo)
                .filter_by(account_id=account_id, settle_date=settle_date)
                .first()
            )
            if not po:
                po = AccountHistoryPo(account_id=account_id, settle_date=settle_date)

            po.balance = Decimal(str(account.balance))
            po.available = Decimal(str(account.available))
            po.pre_balance = _to_decimal(account.pre_balance)
            po.static_balance = _to_decimal(account.static_balance)
            po.deposit = _to_decimal(account.deposit)
            po.withdraw = _to_decimal(account.withdraw)
            po.close_profit = _to_decimal(account.close_profit)
            po.hold_profit = _to_decimal(account.hold_profit)
            po.margin = _to_decimal(account.margin)
            po.risk_ratio = _to_decimal(account.risk_ratio)

            session.add(po)
        logger.info(f"结算权益快照已保存: {account_id} {settle_date} 权益={account.balance}")

    def save_positions(
        self, account_id: str, settle_date: date, positions: dict[str, PositionData]
    ) -> None:
        """
        保存账户每日结算持仓快照（先删除当日旧记录再写入，空仓跳过）

        Args:
            account_id: 账户ID
            settle_date: 结算日期
            positions: 账户级持仓字典（symbol -> PositionData）
        """
        with session_scope() as session:
            session.query(PositionHistoryPo).filter_by(
                account_id=account_id, settle_date=settle_date
            ).delete()

            count = 0
            for position in positions.values():
                pos_long = position.pos_long or 0
                pos_short = position.pos_short or 0
                if pos_long == 0 and pos_short == 0:
                    continue

                po = PositionHistoryPo(
                    account_id=account_id,
                    settle_date=settle_date,
                    symbol=position.symbol,
                    exchange=position.exchange.value,
                    pos_long=pos_long,
                    pos_short=pos_short,
                    hold_price_long=_to_decimal(position.hold_price_long),
                    hold_price_short=_to_decimal(position.hold_price_short),
                    hold_profit_long=_to_decimal(position.hold_profit_long),
                    hold_profit_short=_to_decimal(position.hold_profit_short),
                    margin_long=_to_decimal(position.margin_long),
                    margin_short=_to_decimal(position.margin_short),
                    last_price=_to_decimal(position.last_price),
                )
                session.add(po)
                count += 1
        logger.info(f"结算持仓快照已保存: {account_id} {settle_date} 共{count}条")

    def query_settlements(
        self, account_ids: list[str] | None, start_date: date, end_date: date
    ) -> list[AccountHistoryPo]:
        """
        按日期范围查询结算权益快照

        Args:
            account_ids: 账户ID列表，None 表示全部账户
            start_date: 开始日期（含）
            end_date: 结束日期（含）

        Returns:
            按 account_id、settle_date 排序的快照列表
        """
        with session_scope() as session:
            query = session.query(AccountHistoryPo).filter(
                AccountHistoryPo.settle_date >= start_date,
                AccountHistoryPo.settle_date <= end_date,
            )
            if account_ids:
                query = query.filter(AccountHistoryPo.account_id.in_(account_ids))
            records = query.order_by(
                AccountHistoryPo.account_id, AccountHistoryPo.settle_date
            ).all()
            session.expunge_all()
            return records
