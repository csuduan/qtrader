"""
运维类 API 集成测试

覆盖路由模块：
- qtrader.manager.api.routes.log（/api/log，读取磁盘日志文件）
- qtrader.manager.api.routes.jobs（/api/jobs，经 TradingManager 转发到 Trader）
- qtrader.manager.api.routes.resource（/api/resource，psutil 采样 + 内存历史）
- qtrader.manager.api.routes.system_params（/api/system-params，经 TradingManager 转发）

日志目录用 tmp_path 隔离；jobs/resource/system_params 通过覆盖
mock_trading_manager 的对应方法构造确定返回值。

client / mock_trading_manager 夹具来自 conftest.py。
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.app_context import AppContext
from qtrader.utils.scheduler import Job


def make_job(job_id: str = "job_open", enabled: bool = True) -> Job:
    """构造定时任务对象（真实 Pydantic 模型）"""
    return Job(
        job_id=job_id,
        job_name=f"任务-{job_id}",
        job_group="trading",
        cron_expression="0 9 * * 1-5",
        enabled=enabled,
    )


def make_resource_point(ts: str = "2026-09-01T10:00:00") -> dict:
    """构造资源采样点（与 Manager.get_resource_history 返回的 dict 结构一致）"""
    return {
        "timestamp": ts,
        "cpu_percent": 12.5,
        "memory_percent": 45.0,
        "memory_used_gb": 7.2,
        "memory_total_gb": 16.0,
        "disk_percent": 60.0,
        "disk_used_gb": 120.0,
        "disk_total_gb": 200.0,
    }


def make_param_dict(key: str = "risk_ratio", value: str = "0.8") -> dict:
    """构造系统参数（与 Trader 侧 IPC 返回的 dict 结构一致）"""
    return {
        "id": 1,
        "param_key": key,
        "param_value": value,
        "param_type": "string",
        "description": "风控阈值",
        "group": "risk",
        "updated_at": "2026-09-01T10:00:00",
    }


# ============ 日志查看 API ============


@pytest.fixture
def log_dir(tmp_path):
    """将 log 路由的日志目录指到 tmp_path，并预置账户日志目录"""
    config_loader = MagicMock()
    config_loader._load_app_config.return_value = SimpleNamespace(
        paths=SimpleNamespace(logs=str(tmp_path))
    )
    account_dir = tmp_path / "DQ"
    account_dir.mkdir()
    with patch("qtrader.manager.api.routes.log.get_config_loader", return_value=config_loader):
        yield tmp_path


@pytest.mark.integration
class TestLogReadAPI:
    """日志读取端点（GET /api/log）"""

    def test_read_log_tail(self, client, log_dir):
        content = "line1\nline2\nline3\n"
        (log_dir / "DQ" / "trader-DQ_app.log").write_text(content, encoding="utf-8")

        resp = client.get("/api/log", params={"account_id": "DQ", "filename": "app"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["lines"] == ["line1", "line2", "line3"]
        assert body["data"]["offset"] == len(content)
        assert body["data"]["has_more"] is False
        assert body["data"]["file_size"] == len(content)

    def test_read_log_incremental(self, client, log_dir):
        """从指定 offset 增量读取（limit 截断 + has_more）"""
        (log_dir / "DQ" / "trader-DQ_app.log").write_text("l1\nl2\nl3\n", encoding="utf-8")

        resp = client.get(
            "/api/log", params={"account_id": "DQ", "filename": "app", "offset": 3, "limit": 1}
        )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["lines"] == ["l2"]
        assert data["offset"] == 6
        assert data["has_more"] is True

    def test_read_log_rejects_unsafe_account_id(self, client, log_dir):
        """账户ID含非法字符（防路径穿越）被拒绝"""
        resp = client.get("/api/log", params={"account_id": "../etc"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "非法的账户ID" in resp.json()["message"]

    def test_read_log_rejects_unsafe_filename(self, client, log_dir):
        resp = client.get("/api/log", params={"account_id": "DQ", "filename": "a/b"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "非法的日志文件名" in resp.json()["message"]

    def test_read_log_dir_missing(self, client, log_dir):
        resp = client.get("/api/log", params={"account_id": "GHOST", "filename": "app"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "日志目录不存在"
        assert body["data"] == {"lines": [], "offset": 0, "has_more": False}

    def test_read_log_file_missing(self, client, log_dir):
        """账户日志目录存在但没有匹配文件"""
        resp = client.get("/api/log", params={"account_id": "DQ", "filename": "error"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "日志文件不存在"
        assert body["data"]["lines"] == []

    def test_read_log_glob_fallback(self, client, log_dir):
        """标准文件名不存在时按关键词模糊匹配账户目录内文件"""
        (log_dir / "DQ" / "trader-DQ_app-20260901.log").write_text("fallback\n", encoding="utf-8")

        resp = client.get("/api/log", params={"account_id": "DQ", "filename": "app"})

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["lines"] == ["fallback"]


@pytest.mark.integration
class TestLogFilesAPI:
    """日志文件列表端点（GET /api/log/files）"""

    def test_list_log_files(self, client, log_dir):
        (log_dir / "DQ" / "trader-DQ_app.log").write_text("a\n", encoding="utf-8")
        (log_dir / "DQ" / "trader-DQ_error.log").write_text("b\nb\n", encoding="utf-8")

        resp = client.get("/api/log/files", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        files = body["data"]["files"]
        assert [f["name"] for f in files] == ["trader-DQ_app.log", "trader-DQ_error.log"]
        assert files[0]["size"] == 2
        assert files[1]["size"] == 4
        # mtime 为可解析的 ISO 时间
        datetime.fromisoformat(files[0]["mtime"])

    def test_list_log_files_dir_missing(self, client, log_dir):
        resp = client.get("/api/log/files", params={"account_id": "GHOST"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "日志目录不存在"
        assert body["data"] == {"files": []}

    def test_list_log_files_unsafe_account_id(self, client, log_dir):
        resp = client.get("/api/log/files", params={"account_id": "D;Q"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400


@pytest.mark.integration
class TestLogDownloadAPI:
    """日志下载端点（GET /api/log/download）"""

    def test_download_log(self, client, log_dir):
        content = "hello log\nsecond line\n"
        (log_dir / "DQ" / "trader-DQ_app.log").write_text(content, encoding="utf-8")

        resp = client.get("/api/log/download", params={"account_id": "DQ", "filename": "app"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["filename"] == "trader-DQ_app.log"
        assert body["data"]["content"] == content
        assert body["data"]["size"] == len(content)

    def test_download_log_missing(self, client, log_dir):
        resp = client.get("/api/log/download", params={"account_id": "DQ", "filename": "app"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "日志文件不存在" in resp.json()["message"]

    def test_download_log_unsafe_filename(self, client, log_dir):
        resp = client.get("/api/log/download", params={"account_id": "DQ", "filename": "../secret"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 400


# ============ 定时任务 API ============


@pytest.mark.integration
class TestJobsListAPI:
    """任务列表端点（GET /api/jobs）"""

    def test_get_jobs(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.get_jobs = AsyncMock(return_value=[make_job("job_open"), make_job("job_close")])
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.get("/api/jobs", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] == 2
        assert body["data"]["tasks"][0]["job_id"] == "job_open"
        assert body["data"]["tasks"][0]["cron_expression"] == "0 9 * * 1-5"

    def test_get_jobs_account_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.get("/api/jobs", params={"account_id": "GHOST"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404
        assert "GHOST" in resp.json()["message"]


@pytest.mark.integration
class TestJobsToggleAPI:
    """任务启停端点（PUT /api/jobs/{job_id}/toggle）"""

    def test_toggle_job(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.toggle_job = AsyncMock(return_value=True)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.put(
            "/api/jobs/job_open/toggle", params={"account_id": "DQ"}, json={"enabled": False}
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"job_id": "job_open", "enabled": False}
        assert body["message"] == "任务状态已更新"
        trader.toggle_job.assert_awaited_once_with("job_open", False)

    def test_toggle_job_failure(self, client, mock_trading_manager):
        trader = MagicMock()
        trader.toggle_job = AsyncMock(return_value=False)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)

        resp = client.put(
            "/api/jobs/job_open/toggle", params={"account_id": "DQ"}, json={"enabled": True}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "更新任务状态失败" in resp.json()["message"]

    def test_toggle_job_account_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.put(
            "/api/jobs/job_open/toggle", params={"account_id": "GHOST"}, json={"enabled": True}
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404


@pytest.mark.integration
class TestJobsTriggerAndOperateAPI:
    """任务触发与操作端点（POST /api/jobs/{job_id}/trigger|operate）"""

    def _make_trader(self, mock_trading_manager):
        trader = MagicMock()
        trader.trigger_job = AsyncMock(return_value=True)
        trader.pause_job = AsyncMock(return_value=True)
        trader.resume_job = AsyncMock(return_value=True)
        mock_trading_manager.get_trader = MagicMock(return_value=trader)
        return trader

    def test_trigger_job(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)

        resp = client.post("/api/jobs/job_open/trigger", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {"job_id": "job_open"}
        assert body["message"] == "任务已触发"
        trader.trigger_job.assert_awaited_once_with("job_open")

    def test_trigger_job_failure(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)
        trader.trigger_job = AsyncMock(return_value=False)

        resp = client.post("/api/jobs/job_open/trigger", params={"account_id": "DQ"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "触发任务失败" in resp.json()["message"]

    def test_trigger_job_account_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_trader = MagicMock(return_value=None)

        resp = client.post("/api/jobs/job_open/trigger", params={"account_id": "GHOST"})

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_operate_pause(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)

        resp = client.post(
            "/api/jobs/job_open/operate",
            params={"account_id": "DQ"},
            json={"action": "PAUSE"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "任务已暂停"
        trader.pause_job.assert_awaited_once_with("job_open")

    def test_operate_resume(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)

        resp = client.post(
            "/api/jobs/job_open/operate",
            params={"account_id": "DQ"},
            json={"action": "resume"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "任务已恢复"
        trader.resume_job.assert_awaited_once_with("job_open")

    def test_operate_trigger(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)

        resp = client.post(
            "/api/jobs/job_open/operate",
            params={"account_id": "DQ"},
            json={"action": "trigger"},
        )

        assert resp.status_code == 200
        assert resp.json()["message"] == "任务已触发"
        trader.trigger_job.assert_awaited_once_with("job_open")

    def test_operate_unsupported_action(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)

        resp = client.post(
            "/api/jobs/job_open/operate",
            params={"account_id": "DQ"},
            json={"action": "explode"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 400
        assert "不支持的操作" in resp.json()["message"]
        trader.pause_job.assert_not_awaited()

    def test_operate_failure(self, client, mock_trading_manager):
        trader = self._make_trader(mock_trading_manager)
        trader.pause_job = AsyncMock(return_value=False)

        resp = client.post(
            "/api/jobs/job_open/operate",
            params={"account_id": "DQ"},
            json={"action": "pause"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 500
        assert "操作任务失败" in resp.json()["message"]


# ============ 服务器资源监控 API ============


@pytest.mark.integration
class TestResourceAPI:
    """资源监控端点（/api/resource）"""

    def test_current_snapshot(self, client):
        """真实 psutil 采样：字段齐全且数值合理"""
        resp = client.get("/api/resource/current")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        for field in (
            "timestamp",
            "cpu_percent",
            "memory_percent",
            "memory_used_gb",
            "memory_total_gb",
            "disk_percent",
            "disk_used_gb",
            "disk_total_gb",
            "process_count",
            "boot_time",
        ):
            assert field in data
        assert data["memory_total_gb"] > 0
        assert data["disk_total_gb"] > 0
        assert data["process_count"] >= 1
        assert 0 <= data["memory_percent"] <= 100
        # 时间字段为可解析的 ISO 格式
        datetime.fromisoformat(data["timestamp"])
        datetime.fromisoformat(data["boot_time"])

    def test_current_snapshot_error_returns_code0_message(self, client, mock_trading_manager):
        """采样异常时仍返回 HTTP 200 + code 0（沿用路由现状），仅 message 提示失败"""
        with patch(
            "qtrader.manager.api.routes.resource.get_resource_snapshot",
            AsyncMock(side_effect=RuntimeError("psutil boom")),
        ):
            resp = client.get("/api/resource/current")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "获取资源快照失败"
        assert body["data"] is None

    def test_history(self, client, mock_trading_manager):
        mock_trading_manager.get_resource_history = MagicMock(
            return_value=[
                make_resource_point("2026-09-01T10:00:00"),
                make_resource_point("2026-09-01T10:00:05"),
            ]
        )

        resp = client.get("/api/resource/history", params={"points": 2})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["interval_seconds"] == 5
        assert len(data["points"]) == 2
        assert data["points"][0]["cpu_percent"] == 12.5
        mock_trading_manager.get_resource_history.assert_called_once_with(2)

    def test_history_manager_not_started(self, client):
        with patch.object(AppContext, "get_trading_manager", return_value=None):
            resp = client.get("/api/resource/history")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "管理器未启动"
        assert body["data"] is None


# ============ 系统参数 API ============


@pytest.mark.integration
class TestSystemParamsAPI:
    """系统参数端点（/api/system-params）"""

    def test_list_params(self, client, mock_trading_manager):
        """list 端点返回统一信封包装的 Manager 结果"""
        params = [make_param_dict("risk_ratio", "0.8"), make_param_dict("max_volume", "10")]
        mock_trading_manager.list_system_params = AsyncMock(return_value=params)

        resp = client.get("/api/system-params", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == params
        mock_trading_manager.list_system_params.assert_awaited_once_with("DQ", None)

    def test_list_params_with_group(self, client, mock_trading_manager):
        params = [make_param_dict("risk_ratio")]
        mock_trading_manager.list_system_params = AsyncMock(return_value=params)

        resp = client.get("/api/system-params", params={"account_id": "DQ", "group": "risk"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == params
        mock_trading_manager.list_system_params.assert_awaited_once_with("DQ", "risk")

    def test_list_params_error(self, client, mock_trading_manager):
        mock_trading_manager.list_system_params = AsyncMock(side_effect=RuntimeError("ipc timeout"))

        resp = client.get("/api/system-params", params={"account_id": "DQ"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 500
        assert "获取系统参数失败" in body["message"]

    def test_get_param(self, client, mock_trading_manager):
        param = make_param_dict("risk_ratio", "0.9")
        mock_trading_manager.get_system_param = AsyncMock(return_value=param)

        resp = client.get("/api/system-params/risk_ratio", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == param
        mock_trading_manager.get_system_param.assert_awaited_once_with("DQ", "risk_ratio")

    def test_get_param_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_system_param = AsyncMock(return_value=None)

        resp = client.get("/api/system-params/ghost_key", params={"account_id": "DQ"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert "ghost_key" in body["message"]

    def test_update_param(self, client, mock_trading_manager):
        updated = make_param_dict("risk_ratio", "0.95")
        mock_trading_manager.update_system_param = AsyncMock(return_value=updated)

        resp = client.put(
            "/api/system-params/risk_ratio",
            params={"account_id": "DQ"},
            json={"param_key": "risk_ratio", "param_value": "0.95"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "参数更新成功"
        assert body["data"] == updated
        mock_trading_manager.update_system_param.assert_awaited_once_with(
            "DQ", "risk_ratio", "0.95"
        )

    def test_update_param_not_found(self, client, mock_trading_manager):
        mock_trading_manager.update_system_param = AsyncMock(return_value=None)

        resp = client.put(
            "/api/system-params/ghost_key",
            params={"account_id": "DQ"},
            json={"param_key": "ghost_key", "param_value": "1"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 404

    def test_update_param_missing_value_rejected(self, client):
        """请求体缺少 param_value 时被 Pydantic 拒绝"""
        resp = client.put(
            "/api/system-params/risk_ratio",
            params={"account_id": "DQ"},
            json={"param_key": "risk_ratio"},
        )

        assert resp.status_code == 400
        assert resp.json()["code"] == 400

    def test_get_params_by_group(self, client, mock_trading_manager):
        group_data = {"risk_ratio": "0.8", "max_volume": "10"}
        mock_trading_manager.get_system_params_by_group = AsyncMock(return_value=group_data)

        resp = client.get("/api/system-params/group/risk", params={"account_id": "DQ"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == group_data
        mock_trading_manager.get_system_params_by_group.assert_awaited_once_with("DQ", "risk")

    def test_get_params_by_group_not_found(self, client, mock_trading_manager):
        mock_trading_manager.get_system_params_by_group = AsyncMock(return_value=None)

        resp = client.get("/api/system-params/group/ghost", params={"account_id": "DQ"})

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 404
        assert "ghost" in body["message"]
