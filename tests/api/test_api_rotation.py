"""
API 换仓测试（真实后端）

覆盖导入换仓文件、开始/停止换仓的核心流程。
写路径（start/stop）需 DQ 连接；导入与列表查询仅需后端在线。

数据回退：用例创建的指令通过 batch/delete 批量软删除。

已知问题（测试如实记录现状，非测试缺陷）：
- POST /api/rotation（单条创建）与 DELETE /api/rotation/{id}（单条删除）
  的 Trader 侧 IPC handler 未注册（trader/req/rotation.py 仅 7 个 handler），
  请求以 "Unknown request type" 失败。前端实际走导入与批量删除路径。
- CSV 导入第一行固定按表头跳过（switch_mgr.import_csv 的 lines[1:] 遍历），
  本文件的 _csv_content 生成占位表头行绕开该行为。
"""

import pytest

from tests.api.conftest import E2E_ACCOUNT_ID

pytestmark = pytest.mark.api


def _csv_content(rows: list[tuple]) -> bytes:
    """构造换仓 CSV 内容（gbk 编码）

    列序: 账户ID,策略ID,合约,开平,方向,手数[,下单时间]
    注意：解析器将第一行固定按表头跳过，故首行为占位表头。
    合约仅取 "." 前段（std_symbol），须用 rb2705.SHFE / 裸 rb2705 格式，
    不能用 SHFE.rb2705（会被解析成 "SHFE"）。
    文件名须含 8 位日期（yyyyMMdd），由后端提取为 trading_date。
    """
    lines = ["account_id,strategy_id,symbol,offset,direction,volume"]
    for strategy_id, symbol, offset, direction, volume in rows:
        lines.append(f"{E2E_ACCOUNT_ID},{strategy_id},{symbol},{offset},{direction},{volume}")
    return "\n".join(lines).encode("gbk")


def _import_file(api_client, filename: str, content: bytes, mode: str = "append"):
    return api_client.post(
        "/api/rotation/import",
        files={"file": (filename, content, "text/csv")},
        data={"mode": mode, "account_id": E2E_ACCOUNT_ID},
    )


def _import_ok(api_client, filename: str, rows: list[tuple], mode: str = "append") -> dict:
    """导入并断言成功，返回响应 data"""
    resp = _import_file(api_client, filename, _csv_content(rows), mode=mode)
    body = resp.json()
    assert body["code"] == 0, f"导入失败: {body}"
    return body["data"]


@pytest.fixture()
def cleanup_rotation(api_client):
    """用例后清理：批量软删除本账户全部指令"""
    yield
    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    ids = [i["id"] for i in resp.json().get("data", {}).get("instructions", [])]
    if ids:
        api_client.post(
            "/api/rotation/batch/delete",
            params={"account_id": E2E_ACCOUNT_ID},
            json={"ids": ids},
        )


# ==================== 导入换仓文件 ====================


def test_import_rotation_csv(api_client, cleanup_rotation):
    """导入合法换仓 CSV → imported 统计正确，列表可见"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    data = _import_ok(
        api_client,
        f"{trading_date}_itest.csv",
        [
            ("ITEST_S1", "rb2705.SHFE", "Open", "Buy", 1),
            ("ITEST_S1", "rb2705.SHFE", "Close", "Sell", 1),
        ],
    )
    assert data["imported"] == 2, f"应导入2条: {data}"
    assert data["failed"] == 0

    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "rotation_status" in data
    symbols = [i["symbol"] for i in data["instructions"]]
    assert any("rb2705" in s for s in symbols)


def test_import_rotation_csv_replace_mode(api_client, cleanup_rotation):
    """replace 模式：替换同交易日旧指令而非追加"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    r1 = _import_ok(
        api_client,
        f"{trading_date}_a.csv",
        [("ITEST_R1", "rb2705.SHFE", "Open", "Buy", 1), ("ITEST_R1", "rb2705.SHFE", "Open", "Buy", 2)],
    )
    assert r1["imported"] == 2

    r2 = _import_ok(
        api_client,
        f"{trading_date}_b.csv",
        [("ITEST_R2", "rb2705.SHFE", "Close", "Sell", 2), ("ITEST_R2", "rb2705.SHFE", "Close", "Sell", 3)],
        mode="replace",
    )
    assert r2["imported"] == 2

    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    strategies = [i["strategy_id"] for i in resp.json()["data"]["instructions"]]
    assert "ITEST_R1" not in strategies, "replace 后旧指令应被软删除"
    assert "ITEST_R2" in strategies


def test_import_rotation_csv_bad_filename(api_client, cleanup_rotation):
    """文件名不含 8 位日期 → 导入失败"""
    resp = _import_file(
        api_client,
        "badname.csv",
        _csv_content([("ITEST_X1", "rb2705.SHFE", "Open", "Buy", 1), ("ITEST_X1", "rb2705.SHFE", "Open", "Buy", 1)]),
    )
    body = resp.json()
    assert body["code"] != 0
    assert "导入失败" in body["message"] or "文件名" in body["message"]


def test_import_rotation_csv_wrong_account_row_skipped(api_client, cleanup_rotation):
    """CSV 行账户ID与本账户不一致 → 该行计入 failed"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    lines = [
        "account_id,strategy_id,symbol,offset,direction,volume",
        "OTHER_ACC,ITEST_W1,rb2705,Open,Buy,1",
        "OTHER_ACC,ITEST_W1,rb2705,Open,Buy,2",
    ]
    resp = _import_file(api_client, f"{trading_date}_w.csv", "\n".join(lines).encode("gbk"))
    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["imported"] == 0
    assert data["failed"] == 2


def test_import_rotation_csv_bad_volume_row(api_client, cleanup_rotation):
    """CSV 行手数非法（0/非整数）→ 计入 failed"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    lines = [
        "account_id,strategy_id,symbol,offset,direction,volume",
        f"{E2E_ACCOUNT_ID},ITEST_V1,rb2705,Open,Buy,0",  # 手数必须大于0
        f"{E2E_ACCOUNT_ID},ITEST_V1,rb2705,Open,Buy,abc",  # 非整数
    ]
    resp = _import_file(api_client, f"{trading_date}_v.csv", "\n".join(lines).encode("gbk"))
    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["imported"] == 0
    assert data["failed"] == 2


# ==================== 指令管理与删除 ====================


def test_batch_delete_rotation(api_client, cleanup_rotation):
    """批量删除：导入 → batch/delete → 列表不可见"""
    import datetime as dt

    trading_date = dt.date.today().strftime("%Y%m%d")
    data = _import_ok(
        api_client,
        f"{trading_date}_d.csv",
        [("ITEST_D1", "rb2705.SHFE", "Open", "Buy", 1), ("ITEST_D1", "rb2705.SHFE", "Open", "Buy", 2)],
    )
    assert data["imported"] == 2

    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    ids = [i["id"] for i in resp.json()["data"]["instructions"]]
    assert ids

    resp = api_client.post(
        "/api/rotation/batch/delete",
        params={"account_id": E2E_ACCOUNT_ID},
        json={"ids": ids},
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == 0

    resp = api_client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    remaining = {i["id"] for i in resp.json()["data"]["instructions"]}
    assert not (set(ids) & remaining), "删除后指令不应再出现在列表"


def test_create_rotation_single_handler_missing(api_client):
    """单条创建端点的 Trader handler 未注册（已知问题）→ 请求失败并透传错误"""
    import datetime as dt

    payload = {
        "account_id": E2E_ACCOUNT_ID,
        "strategy_id": "ITEST_SINGLE",
        "symbol": "SHFE.rb2705",
        "exchange_id": "SHFE",
        "offset": "OPEN",
        "direction": "BUY",
        "volume": 1,
        "price": 0,
        "trading_date": dt.date.today().strftime("%Y%m%d"),
    }
    resp = api_client.post("/api/rotation", json=payload)
    body = resp.json()
    # handler 未注册：Manager 侧 result=None → "创建换仓指令失败"
    assert body["code"] != 0
    assert "创建换仓指令失败" in body["message"]


def test_get_rotation_not_found(api_client):
    """查询不存在的指令 → 路由层 404（HTTP 400 + body code=404 的项目约定）"""
    resp = api_client.get(
        "/api/rotation/99999999", params={"account_id": E2E_ACCOUNT_ID}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 404
    assert "不存在" in body["message"]


# ==================== 开始/停止换仓 ====================


def test_start_stop_rotation(require_dq_connected, cleanup_rotation):
    """开始换仓（空指令列表为合法空跑）→ 状态可查 → 停止"""
    client = require_dq_connected

    resp = client.post("/api/rotation/start", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0, f"启动失败: {body['message']}"

    resp = client.get("/api/rotation", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    assert "rotation_status" in resp.json()["data"]

    resp = client.post("/api/rotation/stop", params={"account_id": E2E_ACCOUNT_ID})
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


def test_start_rotation_unknown_account(api_client):
    """不存在的账户启动换仓 → 500"""
    resp = api_client.post("/api/rotation/start", params={"account_id": "NO_SUCH_ACC"})
    body = resp.json()
    assert body["code"] == 500
