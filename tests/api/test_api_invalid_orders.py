"""
API 无效单测试（真实后端）

覆盖直接下单与指令下单的无效输入处理：
- 参数校验层拦截（Pydantic/路由校验，HTTP 400，不触达 Trader）
- Trader 层真实失败（无效合约/风控超限，错误信息透传）

无效单不产生真实委托，无需交易时段与 DQ 连接。
"""

import pytest

from tests.api.conftest import E2E_ACCOUNT_ID

pytestmark = pytest.mark.api


def _order_body(**overrides) -> dict:
    """合法下单请求体基线，按用例覆盖字段"""
    body = {
        "account_id": E2E_ACCOUNT_ID,
        "symbol": "SHFE.rb2701",
        "direction": "BUY",
        "offset": "OPEN",
        "volume": 1,
        "price": 0,
    }
    body.update(overrides)
    return body


# ==================== 直接下单：参数校验层拦截 ====================


@pytest.mark.parametrize(
    "bad_body, expect_msg",
    [
        (_order_body(volume=0), None),  # Pydantic gt=0
        (_order_body(volume=-1), None),
        (_order_body(direction="XX"), "买卖方向"),
        (_order_body(offset="XX"), "开平标志"),
        (_order_body(symbol=""), None),
    ],
)
def test_direct_order_invalid_params_rejected(api_client, bad_body, expect_msg):
    """直接下单无效参数 → 400，错误信息可读"""
    resp = api_client.post("/api/order", json=bad_body)
    body = resp.json()
    assert resp.status_code == 400
    assert body["code"] != 0
    if expect_msg:
        assert expect_msg in body["message"]


def test_direct_order_unknown_account_rejected(api_client):
    """不存在的账户 → 400 + 账户不存在提示"""
    resp = api_client.post("/api/order", json=_order_body(account_id="NO_SUCH_ACC"))
    body = resp.json()
    assert resp.status_code == 400
    assert body["code"] != 0
    assert "不存在" in body["message"] or "账户" in body["message"]


# ==================== 直接下单：Trader 层真实失败 ====================


def test_direct_order_unknown_symbol_trader_error(require_dq_connected):
    """无效合约（路由校验通过，Trader 层失败）→ 错误信息含真实原因"""
    resp = require_dq_connected.post("/api/order", json=_order_body(symbol="FOO.no_such_contract"))
    body = resp.json()
    assert body["code"] != 0
    assert "下单失败" in body["message"]
    # 错误透传链验证：message 应含具体原因而非笼统提示
    assert len(body["message"]) > len("下单失败")


def test_direct_order_over_risk_limit_rejected(require_dq_connected):
    """手数超风控限制（max_order_volume=50）→ 风控拦截"""
    resp = require_dq_connected.post("/api/order", json=_order_body(volume=9999))
    body = resp.json()
    assert body["code"] != 0
    assert "风控" in body["message"], f"应被风控拦截: {body['message']}"


# ==================== 指令下单：参数校验层拦截 ====================


@pytest.mark.parametrize(
    "bad_body, expect_msg",
    [
        ({"direction": "SELL", "offset": "OPEN", "volume": 1}, "缺少必要参数"),  # 缺 symbol
        (
            {"symbol": "SHFE.rb2701", "offset": "OPEN", "volume": 1},
            "缺少必要参数",
        ),  # 缺 direction
        (
            {"symbol": "SHFE.rb2701", "direction": "BUY", "volume": 1},
            "缺少必要参数",
        ),  # 缺 offset
        (
            {"symbol": "SHFE.rb2701", "direction": "BUY", "offset": "OPEN"},
            "缺少必要参数",
        ),  # 缺 volume
        (
            {"symbol": "SHFE.rb2701", "direction": "XX", "offset": "OPEN", "volume": 1},
            "direction",
        ),
        (
            {"symbol": "SHFE.rb2701", "direction": "BUY", "offset": "XX", "volume": 1},
            "offset",
        ),
        (
            {"symbol": "SHFE.rb2701", "direction": "BUY", "offset": "OPEN", "volume": 0},
            "volume",
        ),
        (
            {"symbol": "SHFE.rb2701", "direction": "BUY", "offset": "OPEN", "volume": -1},
            "volume",
        ),
        (
            {
                "symbol": "SHFE.rb2701",
                "direction": "BUY",
                "offset": "OPEN",
                "volume": "abc",
            },
            "volume",
        ),
    ],
)
def test_order_cmd_invalid_params_rejected(api_client, bad_body, expect_msg):
    """指令下单无效参数 → 400 + 错误信息"""
    resp = api_client.post("/api/order-cmd", params={"account_id": E2E_ACCOUNT_ID}, json=bad_body)
    body = resp.json()
    assert resp.status_code == 400
    assert body["code"] != 0
    assert expect_msg in body["message"]


def test_order_cmd_missing_account_id_rejected(api_client):
    """指令下单缺 account_id → 400"""
    resp = api_client.post("/api/order-cmd", json=_order_body())
    body = resp.json()
    assert resp.status_code == 422 or body["code"] != 0


def test_order_cmd_unknown_symbol_finishes_rejected(require_dq_connected):
    """无效合约指令：创建被接受（code=0，指令层不校验合约），执行期以
    "报单被拒: 未获取到合约信息" 结束——如实记录现状

    现状说明：POST /api/order-cmd 对合约存在性零校验，无效合约生成一条
    必然失败的指令。改进方向是在创建期拒绝（需后端配合，另行处理）。
    """
    import time

    client = require_dq_connected
    resp = client.post(
        "/api/order-cmd",
        params={"account_id": E2E_ACCOUNT_ID},
        json={
            "symbol": "FOO.no_such_contract_itest",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 0,
        },
    )
    body = resp.json()
    assert body["code"] == 0, f"指令创建应被接受（现状）: {body}"
    cmd_id = body["data"]["cmd_id"]

    # 轮询已完成列表，确认指令以被拒结束（OrderCmd 状态机自动流转）
    deadline = time.time() + 30
    reason = None
    while time.time() < deadline:
        resp = client.get(
            "/api/order-cmd", params={"account_id": E2E_ACCOUNT_ID, "status": "finished"}
        )
        for cmd in resp.json().get("data", []):
            if cmd["cmd_id"] == cmd_id:
                reason = cmd.get("finish_reason") or ""
                break
        if reason:
            break
        time.sleep(1)

    assert reason is not None, "指令应在 30s 内进入已完成列表"
    assert "未获取到合约信息" in reason, f"结束原因应含合约错误: {reason}"


# ==================== 读路径补充：持仓/成交/合约 ====================


def test_get_contract_list(api_client):
    """合约列表：结构 + 关键字段"""
    resp = api_client.get("/api/contract/list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    contracts = body["data"]
    assert isinstance(contracts, list)
    if contracts:
        c = contracts[0]
        for field in ("symbol", "exchange_id", "name", "price_tick", "is_main"):
            assert field in c


def test_get_contract_list_filter_main(api_client):
    """is_main 筛选：true 只返回主力且带 is_main 字段，false 只返回非主力"""
    resp = api_client.get("/api/contract/list", params={"is_main": True})
    assert resp.status_code == 200
    mains = resp.json()["data"]
    assert all(c["is_main"] is True for c in mains), "is_main=true 应只返回主力合约"

    resp = api_client.get("/api/contract/list", params={"is_main": False})
    assert resp.status_code == 200
    others = resp.json()["data"]
    assert all(c["is_main"] is False for c in others), "is_main=false 应只返回非主力合约"


def test_get_contract_exchanges(api_client):
    """交易所列表"""
    resp = api_client.get("/api/contract/exchanges")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    exchanges = body["data"]
    assert isinstance(exchanges, list)
    if exchanges:
        assert "exchange_id" in exchanges[0]


def test_get_positions_structure(api_client):
    """持仓列表字段结构"""
    resp = api_client.get("/api/position", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)
    if body["data"]:
        for field in ("symbol", "pos_long", "pos_short", "hold_price_long"):
            assert field in body["data"][0]


def test_get_trades_by_date(api_client):
    """当日成交记录（date 参数 YYYY-MM-DD）"""
    import datetime as dt

    today = dt.date.today().isoformat()
    resp = api_client.get("/api/trade", params={"account_id": E2E_ACCOUNT_ID, "date": today})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert isinstance(body["data"], list)
    if body["data"]:
        for field in ("trade_id", "symbol", "price", "volume", "trade_date_time"):
            assert field in body["data"][0]
