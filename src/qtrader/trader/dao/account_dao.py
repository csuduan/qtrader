"""
账户数据持久化DAO
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from qtrader.models.po import AccountPo
from qtrader.utils.database import session_scope
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class AccountDao:
    """账户数据访问对象"""

    def save(self, account_id: str, data) -> None:
        """持久化账户数据"""
        try:
            with session_scope() as session:
                self._save_with_session(session, account_id, data)
        except Exception as e:
            logger.exception(f"持久化账户数据失败: {e}")

    def _save_with_session(self, session, account_id: str, data) -> None:
        """在指定会话中持久化账户数据"""
        account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
        if not account_po:
            account_po = AccountPo(account_id=account_id)

        account_po.balance = (
            Decimal(str(data.balance or 0)) if hasattr(data, "balance") else Decimal("0")
        )
        account_po.available = (
            Decimal(str(data.available or 0)) if hasattr(data, "available") else Decimal("0")
        )
        account_po.margin = (
            Decimal(str(data.margin or 0)) if hasattr(data, "margin") else Decimal("0")
        )
        account_po.float_profit = (
            Decimal(str(data.float_profit or 0)) if hasattr(data, "float_profit") else Decimal("0")
        )
        account_po.position_profit = (
            Decimal(str(data.hold_profit or 0)) if hasattr(data, "hold_profit") else Decimal("0")
        )
        account_po.close_profit = (
            Decimal(str(data.close_profit or 0)) if hasattr(data, "close_profit") else Decimal("0")
        )
        account_po.risk_ratio = (
            Decimal(str(data.risk_ratio or 0)) if hasattr(data, "risk_ratio") else Decimal("0")
        )
        account_po.updated_at = datetime.now()

        session.add(account_po)
        logger.debug(f"账户数据已持久化: {account_id}")

    def save_dict(self, session, account_id: str, data: dict[str, Any]) -> None:
        """在指定会话中通过字典持久化账户数据（用于批量写入）"""
        account_po = session.query(AccountPo).filter_by(account_id=account_id).first()
        if not account_po:
            account_po = AccountPo(account_id=account_id)

        account_po.balance = Decimal(str(data.get("balance") or 0))
        account_po.available = Decimal(str(data.get("available") or 0))
        account_po.margin = Decimal(str(data.get("margin") or 0))
        account_po.float_profit = Decimal(str(data.get("float_profit") or 0))
        account_po.position_profit = Decimal(str(data.get("hold_profit") or 0))
        account_po.close_profit = Decimal(str(data.get("close_profit") or 0))
        account_po.risk_ratio = Decimal(str(data.get("risk_ratio") or 0))
        account_po.updated_at = datetime.now()

        session.add(account_po)
