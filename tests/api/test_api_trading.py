"""
API 交易测试（真实后端写路径，DQ 模拟盘）

组合流程验证：HTTP → 路由 → Manager → Unix Socket IPC → Trader → 网关 → 模拟盘
→ 回报 → 数据可见。受交易时段影响（守卫自动 skip），仅在 DQ 模拟盘账户执行。
"""

import time

import pytest

from tests.api.conftest import E2E_ACCOUNT_ID, E2E_SYMBOL, require_trading_session

pytestmark = pytest.mark.api


def test_order_cmd_full_flow(require_dq_connected):
    """报单指令组合流程：发送 → 轮询终态 ALL_COMPLETED → 成交记录可见

    1 手开仓、价格 0（市价=对手价追价），由 OrderCmd 状态机自动拆单/追价。
    """
    client = require_dq_connected
    require_trading_session()

    # 发送报单指令
    resp = client.post(
        "/api/order-cmd",
        params={"account_id": E2E_ACCOUNT_ID},
        json={
            "symbol": E2E_SYMBOL,
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 0,
            "source": "api-e2e",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0, f"发送报单指令失败: {body.get('message')}"
    cmd_id = body["data"]["cmd_id"]

    # 轮询已完成列表直至 ALL_COMPLETED（OrderCmd 超时上限 120s，轮询 90s）
    deadline = time.time() + 90
    finished_cmd = None
    while time.time() < deadline:
        resp = client.get(
            "/api/order-cmd",
            params={"account_id": E2E_ACCOUNT_ID, "status": "finished"},
        )
        for cmd in resp.json().get("data", []):
            if cmd["cmd_id"] == cmd_id:
                finished_cmd = cmd
                if cmd.get("finish_reason") == "ALL_COMPLETED":
                    break
        if finished_cmd and finished_cmd.get("finish_reason") == "ALL_COMPLETED":
            break
        time.sleep(2)

    assert finished_cmd is not None, "指令未进入已完成列表"
    assert (
        finished_cmd["finish_reason"] == "ALL_COMPLETED"
    ), f"指令未全部成交: {finished_cmd['finish_reason']}"
    assert finished_cmd["filled_volume"] == 1

    # 成交记录可见（symbol 不带交易所前缀，如 rb2701）
    bare_symbol = E2E_SYMBOL.split(".")[-1]
    resp = client.get("/api/trade", params={"account_id": E2E_ACCOUNT_ID})
    trades = resp.json()["data"]
    assert any(
        t["symbol"] == bare_symbol for t in trades
    ), f"成交记录中未找到 {bare_symbol}: {sorted({t['symbol'] for t in trades})}"


def test_place_and_cancel_order(require_dq_connected):
    """挂单撤销：偏离价报单挂出 → 撤单 → 挂单列表不再出现"""
    client = require_dq_connected
    require_trading_session()

    # 先订阅行情，取对手价造一个必然挂出的偏离价（account_id 在 body）
    resp = client.post(
        "/api/quote/subscribe",
        json={"account_id": E2E_ACCOUNT_ID, "symbol": E2E_SYMBOL},
    )
    assert resp.status_code == 200

    resp = client.get("/api/quote", params={"account_id": E2E_ACCOUNT_ID})
    bare_symbol = E2E_SYMBOL.split(".")[-1]
    quotes = {q["symbol"]: q for q in resp.json()["data"]}
    quote = quotes.get(bare_symbol)
    if not quote or not quote.get("bid_price1"):
        pytest.skip("无行情数据（快期模拟盘行情可能未推送），跳过挂单撤销用例")

    # 买价下浮 2% 限价挂出（必然不成交）
    hang_price = round(quote["bid_price1"] * 0.98, 1)
    resp = client.post(
        "/api/order",
        json={
            "account_id": E2E_ACCOUNT_ID,
            "symbol": E2E_SYMBOL,
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": hang_price,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0, f"报单失败: {body.get('message')}"
    order_id = body["data"]["order_id"]

    # 挂单出现在委托列表（status=ALIVE 必填，走 Trader 实时缓存）
    resp = client.get("/api/order", params={"account_id": E2E_ACCOUNT_ID, "status": "ALIVE"})
    assert any(o["order_id"] == order_id for o in resp.json()["data"]), "挂单未出现在委托列表"

    # 撤单
    resp = client.delete(f"/api/order/{order_id}", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200

    # 轮询确认挂单消失（撤单回报异步到达）
    deadline = time.time() + 15
    gone = False
    while time.time() < deadline:
        resp = client.get("/api/order", params={"account_id": E2E_ACCOUNT_ID, "status": "ALIVE"})
        alive = [o for o in resp.json()["data"] if o["order_id"] == order_id]
        if not alive:
            gone = True
            break
        time.sleep(1)
    assert gone, "撤单后挂单仍在委托列表"


def test_order_error_message_propagates(require_dq_connected):
    """错误链路透传：Trader 处理失败时，错误响应应含真实失败原因而非笼统提示

    验证 Manager → IPC → Trader 的异常传播链（RemoteHandlerError）。
    """
    client = require_dq_connected
    require_trading_session()

    resp = client.post(
        "/api/order",
        json={
            "account_id": E2E_ACCOUNT_ID,
            "symbol": "FOO.xxx_not_exist",
            "direction": "BUY",
            "offset": "OPEN",
            "volume": 1,
            "price": 0,
        },
    )
    body = resp.json()
    assert body["code"] != 0, "无效合约报单应失败"
    # 错误信息应包含具体原因（如合约不存在/查询失败），而非仅"下单失败"
    assert len(body["message"]) > len("下单失败"), f"错误信息缺少真实原因: {body['message']}"
