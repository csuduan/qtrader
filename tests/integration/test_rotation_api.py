"""
换仓指令 API 集成测试

覆盖路由 qtrader.manager.api.routes.rotation（前缀 /api/rotation）。
走完整 FastAPI 栈，TradingManager 全程 mock；数据库回退分支用临时 SQLite
承载 RotationInstructionPo，保证断言确定性。
"""

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from qtrader.models.po import Base, RotationInstructionPo

ACCOUNT = "DQ"
BASE = "/api/rotation"


def make_fake_db(tmp_path):
    """构造仅包含换仓指令表的临时 SQLite 数据库（get_session 语义与生产一致）"""
    engine = create_engine(f"sqlite:///{tmp_path}/rotation.db")
    Base.metadata.create_all(engine, tables=[RotationInstructionPo.__table__])
    session_local = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @contextmanager
    def get_session():
        session = session_local()
        try:
            yield session
            session.commit()
        finally:
            session.close()

    return SimpleNamespace(get_session=get_session), session_local


def seed_instruction(session_local, **overrides) -> int:
    """写入一条换仓指令并返回其ID"""
    defaults = dict(
        account_id=ACCOUNT,
        strategy_id="StrategyFix_RB",
        symbol="SHFE.rb2505",
        offset="CLOSE",
        direction="SELL",
        volume=5,
        filled_volume=0,
        price=3450.0,
        order_time="09:05:00",
        trading_date=datetime.now().strftime("%Y%m%d"),
        enabled=True,
        status="PENDING",
    )
    defaults.update(overrides)
    with session_local() as session:
        inst = RotationInstructionPo(**defaults)
        session.add(inst)
        session.commit()
        return inst.id


def make_trader_instruction(
    strategy_id: str, status: str = "PENDING", enabled: bool = True
) -> dict:
    """Trader 进程返回的换仓指令条目"""
    return {
        "id": 1,
        "account_id": ACCOUNT,
        "strategy_id": strategy_id,
        "symbol": "SHFE.rb2505",
        "offset": "CLOSE",
        "direction": "SELL",
        "volume": 5,
        "filled_volume": 2,
        "price": 3450.0,
        "enabled": enabled,
        "status": status,
        "started_at": "2026-09-01T09:05:00",
    }


@pytest.mark.integration
class TestGetRotationInstructions:
    """获取换仓指令列表 GET /api/rotation"""

    def test_from_trader_today(self, client, mock_trading_manager):
        mock_trading_manager.get_rotation_instructions = AsyncMock(
            return_value={
                "instructions": [make_trader_instruction("StrategyFix_RB")],
                "rotation_status": {"working": True, "is_manual": False},
            }
        )

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["total"] == 1
        assert data["rotation_status"] == {"working": True, "is_manual": False}
        item = data["instructions"][0]
        assert item["strategy_id"] == "StrategyFix_RB"
        assert item["exchange_id"] == "rb2505"
        assert item["is_deleted"] is False
        mock_trading_manager.get_rotation_instructions.assert_awaited_once_with(
            ACCOUNT, 100, 0, None, None
        )

    def test_from_trader_with_filters_and_pagination(self, client, mock_trading_manager):
        mock_trading_manager.get_rotation_instructions = AsyncMock(
            return_value={
                "instructions": [
                    make_trader_instruction("s1", status="PENDING"),
                    make_trader_instruction("s2", status="COMPLETED"),
                    make_trader_instruction("s3", status="COMPLETED"),
                ],
                "rotation_status": {"working": False, "is_manual": False},
            }
        )

        resp = client.get(
            BASE,
            params={
                "account_id": ACCOUNT,
                "status": "COMPLETED",
                "enabled": True,
                "limit": 1,
                "offset": 1,
            },
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert len(data["instructions"]) == 1
        assert data["instructions"][0]["strategy_id"] == "s3"
        assert data["limit"] == 1
        assert data["offset"] == 1

    def test_trader_error_falls_back_to_db(self, client, mock_trading_manager, tmp_path):
        db, session_local = make_fake_db(tmp_path)
        seed_instruction(
            session_local,
            strategy_id="s_old_completed",
            status="COMPLETED",
            created_at=datetime(2026, 9, 1, 10, 0, 0),
        )
        seed_instruction(
            session_local,
            strategy_id="s_new_pending",
            status="PENDING",
            created_at=datetime(2026, 9, 1, 11, 0, 0),
        )
        seed_instruction(
            session_local,
            strategy_id="s_deleted",
            is_deleted=True,
            created_at=datetime(2026, 9, 1, 12, 0, 0),
        )
        mock_trading_manager.get_rotation_instructions = AsyncMock(
            side_effect=RuntimeError("trader down")
        )

        with patch("qtrader.manager.api.routes.rotation.get_database", return_value=db):
            resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["total"] == 2
        # created_at 倒序，最新在前
        assert data["instructions"][0]["strategy_id"] == "s_new_pending"
        assert data["instructions"][1]["strategy_id"] == "s_old_completed"
        assert data["instructions"][0]["exchange_id"] == "rb2505"
        assert data["instructions"][0]["pending_volume"] == 0
        assert data["rotation_status"] == {"working": False, "is_manual": False}

    def test_historical_date_bypasses_trader(self, client, mock_trading_manager, tmp_path):
        db, session_local = make_fake_db(tmp_path)
        seed_instruction(session_local, trading_date="20250115", strategy_id="s_history")
        seed_instruction(
            session_local, trading_date="20250115", strategy_id="s_history_deleted", is_deleted=True
        )
        mock_trading_manager.get_rotation_instructions = AsyncMock()

        with patch("qtrader.manager.api.routes.rotation.get_database", return_value=db):
            resp = client.get(BASE, params={"account_id": ACCOUNT, "trading_date": "20250115"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["instructions"][0]["strategy_id"] == "s_history"
        mock_trading_manager.get_rotation_instructions.assert_not_awaited()

    def test_no_trader_no_db(self, client, mock_trading_manager):
        """Trader 返回空且测试环境无数据库时，返回明确错误"""
        mock_trading_manager.get_rotation_instructions = AsyncMock(return_value=None)

        resp = client.get(BASE, params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "数据库未初始化"


@pytest.mark.integration
class TestGetRotationInstruction:
    """获取指定换仓指令 GET /api/rotation/{instruction_id}"""

    def test_detail_no_db(self, client):
        resp = client.get(f"{BASE}/1", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "数据库未初始化"

    def test_detail_not_found(self, client, tmp_path):
        db, _ = make_fake_db(tmp_path)

        with patch("qtrader.manager.api.routes.rotation.get_database", return_value=db):
            resp = client.get(f"{BASE}/999", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert body["message"] == "换仓指令不存在"

    def test_detail_found(self, client, tmp_path):
        db, session_local = make_fake_db(tmp_path)
        inst_id = seed_instruction(session_local, filled_volume=2, price=3450.0)

        with patch("qtrader.manager.api.routes.rotation.get_database", return_value=db):
            resp = client.get(f"{BASE}/{inst_id}", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["id"] == inst_id
        assert data["account_id"] == ACCOUNT
        assert data["symbol"] == "SHFE.rb2505"
        assert data["exchange_id"] == "rb2505"
        assert data["volume"] == 5
        assert data["filled_volume"] == 2
        assert data["price"] == 3450.0
        assert data["status"] == "PENDING"


@pytest.mark.integration
class TestCreateRotationInstruction:
    """创建换仓指令 POST /api/rotation"""

    def test_create_success(self, client, mock_trading_manager):
        mock_trading_manager.create_rotation_instruction = AsyncMock(
            return_value={"id": 7, "status": "PENDING"}
        )

        payload = {
            "account_id": ACCOUNT,
            "strategy_id": "StrategyFix_RB",
            "symbol": "SHFE.rb2505",
            "exchange_id": "SHFE",
            "offset": "CLOSE",
            "direction": "SELL",
            "volume": 5,
        }
        resp = client.post(BASE, json=payload)

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "创建成功"
        assert body["data"]["id"] == 7
        mock_trading_manager.create_rotation_instruction.assert_awaited_once()
        args = mock_trading_manager.create_rotation_instruction.await_args.args
        assert args[0] == ACCOUNT
        assert args[1]["strategy_id"] == "StrategyFix_RB"
        assert args[1]["volume"] == 5

    def test_create_returns_none(self, client, mock_trading_manager):
        mock_trading_manager.create_rotation_instruction = AsyncMock(return_value=None)

        resp = client.post(
            BASE,
            json={
                "account_id": ACCOUNT,
                "strategy_id": "StrategyFix_RB",
                "symbol": "SHFE.rb2505",
                "exchange_id": "SHFE",
                "offset": "CLOSE",
                "direction": "SELL",
                "volume": 5,
            },
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "创建换仓指令失败"

    def test_create_validation_error(self, client):
        resp = client.post(BASE, json={"account_id": ACCOUNT, "symbol": "SHFE.rb2505"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400


@pytest.mark.integration
class TestUpdateRotationInstruction:
    """更新换仓指令 PUT /api/rotation/{instruction_id}"""

    def test_update_success(self, client, mock_trading_manager):
        mock_trading_manager.update_rotation_instruction = AsyncMock(
            return_value={"id": 5, "enabled": False}
        )

        resp = client.put(f"{BASE}/5", params={"account_id": ACCOUNT}, json={"enabled": False})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "更新成功"
        assert body["data"] == {"id": 5, "enabled": False}
        mock_trading_manager.update_rotation_instruction.assert_awaited_once_with(
            ACCOUNT, 5, {"enabled": False}
        )

    def test_update_backend_error(self, client, mock_trading_manager):
        mock_trading_manager.update_rotation_instruction = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        resp = client.put(f"{BASE}/5", params={"account_id": ACCOUNT}, json={"status": "PENDING"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "更新换仓指令失败" in body["message"]


@pytest.mark.integration
class TestDeleteRotationInstruction:
    """删除换仓指令 DELETE /api/rotation/{instruction_id}"""

    def test_delete_success(self, client, mock_trading_manager):
        mock_trading_manager.delete_rotation_instruction = AsyncMock(return_value=True)

        resp = client.delete(f"{BASE}/5", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "删除成功"
        mock_trading_manager.delete_rotation_instruction.assert_awaited_once_with(ACCOUNT, 5)

    def test_delete_not_found(self, client, mock_trading_manager):
        mock_trading_manager.delete_rotation_instruction = AsyncMock(return_value=False)

        resp = client.delete(f"{BASE}/5", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert body["message"] == "换仓指令不存在"


@pytest.mark.integration
class TestClearRotationInstructions:
    """清除已完成换仓指令 POST /api/rotation/clear"""

    def test_clear_success(self, client, mock_trading_manager):
        mock_trading_manager.clear_rotation_instructions = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/clear", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "清除成功"
        mock_trading_manager.clear_rotation_instructions.assert_awaited_once_with(ACCOUNT)

    def test_clear_failed(self, client, mock_trading_manager):
        mock_trading_manager.clear_rotation_instructions = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/clear", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "清除失败"


@pytest.mark.integration
class TestImportRotationInstructions:
    """批量导入换仓指令 POST /api/rotation/import"""

    def test_import_success(self, client, mock_trading_manager):
        mock_trading_manager.import_rotation_instructions = AsyncMock(
            return_value={"imported": 2, "skipped": 0}
        )
        csv_text = "DQ,策略1,SHFE.rb2505,CLOSE,SELL,2,09:05:00\nDQ,策略2,SHFE.hc2505,CLOSE,BUY,1"

        resp = client.post(
            f"{BASE}/import",
            data={"mode": "replace", "account_id": ACCOUNT},
            files={"file": ("20250115_rotation.csv", csv_text.encode("gbk"), "text/csv")},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "导入完成"
        assert body["data"]["imported"] == 2
        mock_trading_manager.import_rotation_instructions.assert_awaited_once_with(
            ACCOUNT, csv_text, "20250115_rotation.csv", "replace"
        )

    def test_import_returns_none(self, client, mock_trading_manager):
        mock_trading_manager.import_rotation_instructions = AsyncMock(return_value=None)

        resp = client.post(
            f"{BASE}/import",
            data={"account_id": ACCOUNT},
            files={"file": ("rotation.csv", b"DQ,s1,SHFE.rb2505,CLOSE,SELL,1", "text/csv")},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "导入失败"

    def test_import_invalid_gbk_content(self, client, mock_trading_manager):
        """无法按 GBK 解码的文件内容返回导入失败而非崩溃"""
        mock_trading_manager.import_rotation_instructions = AsyncMock(return_value=None)
        resp = client.post(
            f"{BASE}/import",
            data={"account_id": ACCOUNT},
            files={"file": ("rotation.csv", b"\xff\xff\xff", "text/csv")},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert "导入换仓指令失败" in body["message"]
        mock_trading_manager.import_rotation_instructions.assert_not_awaited()


@pytest.mark.integration
class TestBatchExecuteInstructions:
    """批量执行换仓指令 POST /api/rotation/batch/execute"""

    def test_execute_success(self, client, mock_trading_manager):
        mock_trading_manager.batch_execute_instructions = AsyncMock(
            return_value={"success": 2, "failed": 1}
        )

        resp = client.post(
            f"{BASE}/batch/execute", params={"account_id": ACCOUNT}, json={"ids": [1, 2, 3]}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "执行完成：成功 2 条，失败 1 条"
        assert body["data"] == {"success": 2, "failed": 1}
        mock_trading_manager.batch_execute_instructions.assert_awaited_once_with(ACCOUNT, [1, 2, 3])

    def test_execute_none_found(self, client, mock_trading_manager):
        mock_trading_manager.batch_execute_instructions = AsyncMock(return_value=None)

        resp = client.post(
            f"{BASE}/batch/execute", params={"account_id": ACCOUNT}, json={"ids": []}
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert body["message"] == "未找到任何换仓指令"


@pytest.mark.integration
class TestBatchDeleteInstructions:
    """批量删除换仓指令 POST /api/rotation/batch/delete"""

    def test_delete_success(self, client, mock_trading_manager):
        mock_trading_manager.batch_delete_instructions = AsyncMock(return_value={"deleted": 2})

        resp = client.post(
            f"{BASE}/batch/delete", params={"account_id": ACCOUNT}, json={"ids": [1, 2]}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "删除成功"
        assert body["data"] == {"deleted": 2}
        mock_trading_manager.batch_delete_instructions.assert_awaited_once_with(ACCOUNT, [1, 2])

    def test_delete_failed(self, client, mock_trading_manager):
        mock_trading_manager.batch_delete_instructions = AsyncMock(return_value=None)

        resp = client.post(
            f"{BASE}/batch/delete", params={"account_id": ACCOUNT}, json={"ids": [1]}
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 9999
        assert body["message"] == "删除失败"


@pytest.mark.integration
class TestRotationControl:
    """换仓流程控制 POST /api/rotation/start|stop|close-all"""

    def test_start_success(self, client, mock_trading_manager):
        mock_trading_manager.execute_rotation = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/start", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "换仓流程已在后台启动"
        assert body["data"] == {}
        mock_trading_manager.execute_rotation.assert_awaited_once_with(ACCOUNT)

    def test_start_failed(self, client, mock_trading_manager):
        mock_trading_manager.execute_rotation = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/start", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "启动换仓流程失败"

    def test_stop_success(self, client, mock_trading_manager):
        mock_trading_manager.stop_rotation = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/stop", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "换仓流程已停止"

    def test_stop_failed(self, client, mock_trading_manager):
        mock_trading_manager.stop_rotation = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/stop", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert resp.json()["message"] == "停止换仓流程失败"

    def test_close_all_success(self, client, mock_trading_manager):
        mock_trading_manager.close_all_positions = AsyncMock(return_value=True)

        resp = client.post(f"{BASE}/close-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "一键平仓已在后台启动"
        mock_trading_manager.close_all_positions.assert_awaited_once_with(ACCOUNT)

    def test_close_all_failed(self, client, mock_trading_manager):
        mock_trading_manager.close_all_positions = AsyncMock(return_value=False)

        resp = client.post(f"{BASE}/close-all", params={"account_id": ACCOUNT})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert body["message"] == "一键平仓失败"
