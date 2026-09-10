"""
BaseGateway 单元测试

覆盖抽象基类的具体实现：初始化状态、connected 判定、std_symbol 标准化、
合约加载（Manager 推送/数据库PO）、事件转发。
"""

from datetime import datetime
from typing import Optional
from unittest.mock import MagicMock

import pytest

from qtrader.models.object import (
    AccountData,
    CancelRequest,
    ContractData,
    Exchange,
    OrderData,
    OrderRequest,
    TickData,
)
from qtrader.trader.gateway.base_gateway import BaseGateway
from qtrader.utils.async_event_engine import EventTypes


class MockConcreteGateway(BaseGateway):
    """实现全部抽象方法的最小具体网关"""

    gateway_name = "MockGateway"

    async def connect(self) -> bool:
        self.md_connected = True
        self.td_connected = True
        return True

    async def disconnect(self) -> bool:
        self.md_connected = False
        self.td_connected = False
        return True

    def get_trading_day(self) -> Optional[str]:
        return "20260903"

    def subscribe(self, symbols: list[str]) -> bool:
        return True

    def subscribe_bars(self, symbol: str, interval: str) -> bool:
        return True

    def send_order(self, req: OrderRequest) -> Optional[OrderData]:
        return None

    def cancel_order(self, req: CancelRequest) -> bool:
        return True

    def get_account(self) -> Optional[AccountData]:
        return None

    def get_positions(self) -> dict:
        return {}

    def get_orders(self) -> dict:
        return {}

    def get_trades(self) -> dict:
        return {}

    def get_contracts(self) -> dict:
        return self.contracts

    def get_quotes(self) -> dict:
        return {}

    def refresh_contracts(self) -> bool:
        return True

    def get_kline(self, symbol: str, interval: str):
        return None


@pytest.fixture
def gateway():
    gw = MockConcreteGateway()
    gw._event_engine = MagicMock()
    return gw


def make_contract_dict(symbol="SHFE.rb2505", **overrides) -> dict:
    """构造 Manager 推送格式的合约字典"""
    data = {
        "symbol": symbol,
        "exchange_id": symbol.split(".")[0],
        "instrument_name": "螺纹钢",
        "volume_multiple": 10,
        "price_tick": 1.0,
        "min_volume": 1,
    }
    data.update(overrides)
    return data


@pytest.mark.unit
class TestBaseGatewayInit:
    """初始化状态"""

    def test_init_state(self, gateway):
        assert gateway.connected is False
        assert gateway.trading_day is None
        assert gateway.contracts == {}
        assert gateway._contracts_update_date is None

    def test_gateway_name_attribute(self, gateway):
        assert gateway.gateway_name == "MockGateway"

    def test_connected_requires_both_channels(self, gateway):
        gateway.md_connected = True
        assert gateway.connected is False
        gateway.td_connected = True
        assert gateway.connected is True


@pytest.mark.unit
class TestStdSymbol:
    """合约代码标准化"""

    def test_exchange_first_format(self, gateway):
        assert gateway.std_symbol("SHFE.rb2505") == "rb2505"

    def test_exchange_last_format(self, gateway):
        assert gateway.std_symbol("rb2505.SHFE") == "rb2505"

    def test_bare_symbol_with_contract_cache(self, gateway):
        gateway.contracts["RB2505"] = ContractData(
            symbol="rb2505", exchange=Exchange.SHFE, name="螺纹钢"
        )
        assert gateway.std_symbol("RB2505") == "rb2505"

    def test_bare_symbol_without_cache_returns_as_is(self, gateway):
        assert gateway.std_symbol("rb2505") == "rb2505"

    def test_czce_uppercased(self, gateway):
        assert gateway.std_symbol("CZCE.ta505") == "TA505"

    def test_other_exchanges_lowercased(self, gateway):
        assert gateway.std_symbol("DCE.M2505") == "m2505"

    def test_empty_returns_none(self, gateway):
        assert gateway.std_symbol("") is None
        assert gateway.std_symbol(None) is None


@pytest.mark.unit
class TestLoadContractsFromInitData:
    """Manager 公共数据合约加载"""

    def test_loads_contract(self, gateway):
        count = gateway.load_contracts_from_init_data([make_contract_dict()])
        assert count == 1
        contract = gateway.contracts["rb2505"]
        assert contract.exchange == Exchange.SHFE
        assert contract.multiple == 10
        assert contract.pricetick == 1.0

    def test_bare_symbol_dict(self, gateway):
        count = gateway.load_contracts_from_init_data(
            [make_contract_dict(symbol="rb2505", exchange_id="SHFE")]
        )
        assert count == 1
        assert "rb2505" in gateway.contracts

    def test_skips_unknown_exchange(self, gateway):
        count = gateway.load_contracts_from_init_data(
            [make_contract_dict(symbol="XXX.rb2505", exchange_id="XXX")]
        )
        assert count == 0
        assert gateway.contracts == {}

    def test_updates_cache_date(self, gateway):
        gateway.load_contracts_from_init_data([make_contract_dict()])
        assert gateway._contracts_update_date == datetime.now().strftime("%Y-%m-%d")


@pytest.mark.unit
class TestEmitEvent:
    """事件转发"""

    def test_emit_event_forwards_to_engine(self, gateway):
        tick = TickData.model_construct(symbol="rb2505")
        gateway.emit_event(EventTypes.TICK_UPDATE, tick)
        gateway._event_engine.put.assert_called_once_with(EventTypes.TICK_UPDATE, tick)
