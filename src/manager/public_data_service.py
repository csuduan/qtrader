"""
公共数据服务
负责管理跨账户共享的公共数据，主要是合约信息

职责：
1. 从共享数据库读写合约信息
2. 内存缓存最新合约数据
3. 提供合约信息查询接口
4. 合并来自不同数据源的合约数据（tq、ctp等）
"""

from datetime import datetime
from typing import Dict, List, Optional

from src.utils.logger import get_logger
from src.utils.shared_database import SharedDatabase

logger = get_logger(__name__)


class ContractInfo:
    """合约信息（内存表示）"""

    __slots__ = (
        "symbol",
        "exchange_id",
        "instrument_name",
        "product_type",
        "volume_multiple",
        "price_tick",
        "min_volume",
        "option_strike",
        "option_underlying",
        "option_type",
        "update_date",
        "data_source",
        "is_active",
    )

    def __init__(
        self,
        symbol: str,
        exchange_id: str,
        instrument_name: Optional[str] = None,
        product_type: str = "FUTURES",
        volume_multiple: int = 1,
        price_tick: float = 0.01,
        min_volume: int = 1,
        option_strike: Optional[float] = None,
        option_underlying: Optional[str] = None,
        option_type: Optional[str] = None,
        update_date: Optional[str] = None,
        data_source: Optional[str] = None,
        is_active: bool = True,
    ):
        self.symbol = symbol
        self.exchange_id = exchange_id
        self.instrument_name = instrument_name
        self.product_type = product_type
        self.volume_multiple = volume_multiple
        self.price_tick = price_tick
        self.min_volume = min_volume
        self.option_strike = option_strike
        self.option_underlying = option_underlying
        self.option_type = option_type
        self.update_date = update_date or datetime.now().strftime("%Y-%m-%d")
        self.data_source = data_source
        self.is_active = is_active

    def to_dict(self) -> dict:
        """转换为字典（用于IPC传输）"""
        return {
            "symbol": self.symbol,
            "exchange_id": self.exchange_id,
            "instrument_name": self.instrument_name,
            "product_type": self.product_type,
            "volume_multiple": self.volume_multiple,
            "price_tick": self.price_tick,
            "min_volume": self.min_volume,
            "option_strike": self.option_strike,
            "option_underlying": self.option_underlying,
            "option_type": self.option_type,
            "update_date": self.update_date,
            "data_source": self.data_source,
            "is_active": self.is_active,
        }


class PublicDataService:
    """
    公共数据服务

    管理跨Trader共享的数据，目前主要是合约信息。
    Manager进程持有此服务，负责写入和分发数据。
    Trader进程通过IPC消息接收数据。
    """

    def __init__(self, shared_db: SharedDatabase):
        """
        初始化公共数据服务

        Args:
            shared_db: 共享数据库实例
        """
        self.shared_db = shared_db
        # 内存缓存：{symbol: ContractInfo}
        self._contracts: Dict[str, ContractInfo] = {}
        # 按数据源分组：{data_source: {symbol: ContractInfo}}
        self._contracts_by_source: Dict[str, Dict[str, ContractInfo]] = {}
        # 最近更新时间
        self._last_updated: Optional[datetime] = None
        logger.info("PublicDataService 初始化完成")

    # ==================== 合约数据写入 ====================

    def upsert_contracts(self, contracts: List[dict], data_source: str) -> int:
        """
        批量写入/更新合约信息（来自某个数据源）

        Args:
            contracts: 合约信息字典列表
            data_source: 数据来源标识（如 "tq"、"ctp"）

        Returns:
            写入的合约数量
        """
        from src.models.po import ContractPo

        update_date = datetime.now().strftime("%Y-%m-%d")
        count = 0

        # 按 symbol 去重（保留最后一个）
        seen = {}
        for contract_dict in contracts:
            symbol = contract_dict.get("symbol")
            if symbol:
                seen[symbol] = contract_dict
        unique_contracts = list(seen.values())

        if len(unique_contracts) < len(contracts):
            logger.warning(f"合约列表去重: {len(contracts)} -> {len(unique_contracts)}")

        with self.shared_db.get_session() as session:
            for contract_dict in unique_contracts:
                symbol = contract_dict.get("symbol")
                if not symbol:
                    continue

                # 查找已有记录
                existing = session.query(ContractPo).filter(ContractPo.symbol == symbol).first()

                if existing:
                    # 更新现有记录
                    existing.exchange_id = contract_dict.get("exchange_id", existing.exchange_id)
                    existing.instrument_name = contract_dict.get(
                        "instrument_name", existing.instrument_name
                    )
                    existing.product_type = contract_dict.get(
                        "product_type", existing.product_type
                    )
                    existing.volume_multiple = contract_dict.get(
                        "volume_multiple", existing.volume_multiple
                    )
                    existing.price_tick = contract_dict.get("price_tick", existing.price_tick)
                    existing.min_volume = contract_dict.get("min_volume", existing.min_volume)
                    existing.option_strike = contract_dict.get("option_strike")
                    existing.option_underlying = contract_dict.get("option_underlying")
                    existing.option_type = contract_dict.get("option_type")
                    existing.update_date = update_date
                    existing.data_source = data_source
                    existing.is_active = contract_dict.get("is_active", True)
                else:
                    # 新增记录
                    po = ContractPo(
                        symbol=symbol,
                        exchange_id=contract_dict.get("exchange_id", ""),
                        instrument_name=contract_dict.get("instrument_name"),
                        product_type=contract_dict.get("product_type", "FUTURES"),
                        volume_multiple=contract_dict.get("volume_multiple", 1),
                        price_tick=contract_dict.get("price_tick", 0.01),
                        min_volume=contract_dict.get("min_volume", 1),
                        option_strike=contract_dict.get("option_strike"),
                        option_underlying=contract_dict.get("option_underlying"),
                        option_type=contract_dict.get("option_type"),
                        update_date=update_date,
                        data_source=data_source,
                        is_active=contract_dict.get("is_active", True),
                    )
                    session.add(po)

                # 同步到内存缓存
                info = ContractInfo(
                    symbol=symbol,
                    exchange_id=contract_dict.get("exchange_id", ""),
                    instrument_name=contract_dict.get("instrument_name"),
                    product_type=contract_dict.get("product_type", "FUTURES"),
                    volume_multiple=contract_dict.get("volume_multiple", 1),
                    price_tick=float(contract_dict.get("price_tick", 0.01)),
                    min_volume=contract_dict.get("min_volume", 1),
                    option_strike=contract_dict.get("option_strike"),
                    option_underlying=contract_dict.get("option_underlying"),
                    option_type=contract_dict.get("option_type"),
                    update_date=update_date,
                    data_source=data_source,
                    is_active=contract_dict.get("is_active", True),
                )
                self._contracts[symbol] = info
                if data_source not in self._contracts_by_source:
                    self._contracts_by_source[data_source] = {}
                self._contracts_by_source[data_source][symbol] = info
                count += 1

        self._last_updated = datetime.now()
        logger.info(f"PublicDataService: 写入 {count} 个合约 (来源: {data_source})")
        return count

    # ==================== 合约数据读取 ====================

    def get_contracts(
        self,
        exchange_id: Optional[str] = None,
        product_type: Optional[str] = None,
        data_source: Optional[str] = None,
        active_only: bool = False,
    ) -> List[ContractInfo]:
        """
        获取合约信息列表（从内存缓存）

        Args:
            exchange_id: 按交易所筛选
            product_type: 按产品类型筛选
            data_source: 按数据源筛选
            active_only: 只返回活跃合约

        Returns:
            合约信息列表
        """
        contracts = list(self._contracts.values())

        if exchange_id:
            contracts = [c for c in contracts if c.exchange_id == exchange_id.upper()]
        if product_type:
            contracts = [c for c in contracts if c.product_type == product_type.upper()]
        if data_source:
            contracts = [c for c in contracts if c.data_source == data_source]
        if active_only:
            contracts = [c for c in contracts if c.is_active]

        return contracts

    def get_contracts_for_push(self, data_source: Optional[str] = None) -> List[dict]:
        """
        获取用于推送给Trader的合约数据

        Args:
            data_source: 指定数据源，None表示返回所有

        Returns:
            合约信息字典列表（可直接序列化通过IPC传输）
        """
        contracts = self.get_contracts(data_source=data_source)
        return [c.to_dict() for c in contracts]

    def load_from_database(self, date_filter: Optional[str] = None) -> int:
        """
        从共享数据库加载合约信息到内存缓存

        Args:
            date_filter: 日期过滤 (YYYY-MM-DD)，None表示加载当天

        Returns:
            加载的合约数量
        """
        from src.models.po import ContractPo

        filter_date = date_filter or datetime.now().strftime("%Y-%m-%d")
        count = 0

        try:
            with self.shared_db.get_session() as session:
                query = session.query(ContractPo).filter(ContractPo.update_date == filter_date)
                contract_pos = query.all()

                for po in contract_pos:
                    info = ContractInfo(
                        symbol=po.symbol,  # type: ignore[arg-type]
                        exchange_id=po.exchange_id,  # type: ignore[arg-type]
                        instrument_name=po.instrument_name,  # type: ignore[arg-type]
                        product_type=po.product_type,  # type: ignore[arg-type]
                        volume_multiple=po.volume_multiple,  # type: ignore[arg-type]
                        price_tick=float(po.price_tick),
                        min_volume=po.min_volume,  # type: ignore[arg-type]
                        option_strike=float(po.option_strike) if po.option_strike else None,
                        option_underlying=po.option_underlying,  # type: ignore[arg-type]
                        option_type=po.option_type,  # type: ignore[arg-type]
                        update_date=po.update_date,  # type: ignore[arg-type]
                        data_source=po.data_source,  # type: ignore[arg-type]
                        is_active=bool(po.is_active),
                    )
                    self._contracts[po.symbol] = info  # type: ignore[index]
                    source = po.data_source or "unknown"
                    if source not in self._contracts_by_source:
                        self._contracts_by_source[source] = {}
                    self._contracts_by_source[source][po.symbol] = info  # type: ignore[index]
                    count += 1

            if count > 0:
                self._last_updated = datetime.now()
            logger.info(f"PublicDataService: 从数据库加载了 {count} 个合约 (日期: {filter_date})")
        except Exception as e:
            logger.exception(f"PublicDataService: 从数据库加载合约失败: {e}")

        return count

    @property
    def contract_count(self) -> int:
        """返回内存中的合约数量"""
        return len(self._contracts)

    @property
    def last_updated(self) -> Optional[datetime]:
        """返回最近更新时间"""
        return self._last_updated

    def has_contracts(self) -> bool:
        """是否有可用的合约数据"""
        return len(self._contracts) > 0

    def has_fresh_contracts(self) -> bool:
        """检查内存中的合约数据是否为今天的数据"""
        if not self._contracts:
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        sample = next(iter(self._contracts.values()))
        return sample.update_date == today
