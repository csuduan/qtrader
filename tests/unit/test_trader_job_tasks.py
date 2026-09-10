"""
Trader 侧 JobManager 任务方法单元测试

覆盖盘前/盘后连接、持仓导出 CSV、结算快照、收盘处理、开盘检查等
定时任务入口。引擎与数据库全部 mock。
"""

import csv
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qtrader.app_context import AppContext, get_app_context
from qtrader.trader.job_mgr import JobManager


@pytest.fixture
def engine() -> MagicMock:
    e = MagicMock()
    e.connected = True
    e.connect = AsyncMock(return_value=True)
    e.disconnect = AsyncMock(return_value=True)
    e.positions = {}
    e.account = None
    return e


@pytest.fixture
def config() -> MagicMock:
    c = MagicMock()
    c.account_id = "DQ"
    c.strategies = {}
    return c


@pytest.fixture
def job(engine, config) -> JobManager:
    return JobManager(config, engine, MagicMock())


@pytest.fixture
def app_paths(tmp_path, monkeypatch):
    """把配置里的导出/参数目录指到临时目录"""
    paths = SimpleNamespace(
        export=str(tmp_path / "export"),
        switch_pos="",
        params=str(tmp_path / "params"),
    )
    loader = MagicMock()
    loader._load_app_config.return_value = SimpleNamespace(paths=paths)
    with patch("qtrader.trader.job_mgr.get_config_loader", return_value=loader):
        yield paths


@pytest.mark.unit
class TestMarketConnect:
    """盘前连接 / 盘后断开"""

    @pytest.mark.asyncio
    async def test_pre_market_connect_when_disconnected(self, engine, job):
        engine.connected = False
        await job.pre_market_connect()
        engine.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pre_market_connect_skips_when_connected(self, engine, job):
        await job.pre_market_connect()
        engine.connect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_pre_market_connect_swallows_exception(self, engine, job):
        engine.connected = False
        engine.connect = AsyncMock(side_effect=RuntimeError("boom"))
        await job.pre_market_connect()  # 不应抛出

    @pytest.mark.asyncio
    async def test_post_market_disconnect_when_connected(self, engine, job):
        await job.post_market_disconnect()
        engine.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_post_market_disconnect_skips(self, engine, job):
        engine.connected = False
        await job.post_market_disconnect()
        engine.disconnect.assert_not_awaited()


@pytest.mark.unit
class TestExportPositions:
    """持仓导出 CSV（多空拆行、GBK 编码）"""

    def test_no_positions_skips(self, job, app_paths):
        job._export_positions_to_csv()  # 不应抛错，也不建文件

    def test_long_and_short_split_rows(self, engine, job, app_paths):
        from qtrader.models.object import PositionData

        long_pos = PositionData(symbol="IM2603", exchange="CFFEX", pos_long_td=2, pos_long_yd=0)
        short_pos = PositionData(
            symbol="SHFE.rb2505", exchange="SHFE", pos_short_td=1, pos_short_yd=0
        )
        engine.positions = {"IM2603": long_pos, "SHFE.rb2505": short_pos}

        job._export_positions_to_csv()

        from pathlib import Path

        files = list(Path(app_paths.export).glob("position-DQ-*.csv"))
        assert len(files) == 1
        with open(files[0], encoding="gbk") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2  # 多头一条 + 空头一条
        by_symbol = {r["合约代码"]: r for r in rows}
        assert by_symbol["IM2603"]["方向"] == "Buy"
        assert by_symbol["IM2603"]["今仓"] == "2"
        assert by_symbol["SHFE.rb2505"]["方向"] == "Sell"
        assert by_symbol["SHFE.rb2505"]["今仓"] == "1"


@pytest.mark.unit
class TestRotationAndScan:
    """换仓与订单扫描任务"""

    @pytest.mark.asyncio
    async def test_auto_rotation(self, job):
        job.position_manager = MagicMock()
        job.position_manager.execute_position_rotation = AsyncMock()

        await job.auto_rotation("IM2609")

        job.position_manager.execute_position_rotation.assert_awaited_once_with("IM2609")

    @pytest.mark.asyncio
    async def test_auto_rotation_swallows_exception(self, job):
        job.position_manager = MagicMock()
        job.position_manager.execute_position_rotation = AsyncMock(side_effect=RuntimeError("boom"))
        await job.auto_rotation()  # 不应抛出

    @pytest.mark.asyncio
    async def test_scan_orders(self, job):
        job.position_manager = MagicMock()
        job.position_manager.scan_and_process_orders = MagicMock()

        await job.scan_orders()

        job.position_manager.scan_and_process_orders.assert_called_once()


@pytest.mark.unit
class TestResetStrategies:
    """策略重置任务"""

    @pytest.mark.asyncio
    async def test_without_strategy_manager(self, job):
        ctx = get_app_context()
        ctx.set(AppContext.KEY_STRATEGY_MANAGER, None)
        await job.reset_strategies()  # 不应抛出

    @pytest.mark.asyncio
    async def test_calls_reset(self, job):
        sm = MagicMock()
        sm.reset_strategies = AsyncMock()
        ctx = get_app_context()
        old = ctx.get(AppContext.KEY_STRATEGY_MANAGER)
        ctx.set(AppContext.KEY_STRATEGY_MANAGER, sm)
        try:
            await job.reset_strategies()
            sm.reset_strategies.assert_awaited_once()
        finally:
            ctx.set(AppContext.KEY_STRATEGY_MANAGER, old)


@pytest.mark.unit
class TestDailySettlement:
    """每日结算快照任务"""

    @pytest.mark.asyncio
    async def test_not_connected_skips(self, engine, job):
        engine.connected = False
        with patch("qtrader.trader.dao.settlement_dao.SettlementDao") as dao:
            await job.save_daily_settlement()
            dao.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_account_skips(self, engine, job):
        engine.account = None
        with patch("qtrader.trader.dao.settlement_dao.SettlementDao") as dao:
            await job.save_daily_settlement()
            dao.assert_not_called()

    @pytest.mark.asyncio
    async def test_saves_settlement_and_positions(self, engine, job):
        from qtrader.models.object import AccountData

        engine.account = AccountData(account_id="DQ", balance=1000.0)
        engine.positions = {}

        with patch("qtrader.trader.dao.settlement_dao.SettlementDao") as dao_cls:
            dao = dao_cls.return_value
            await job.save_daily_settlement()

            dao.save_settlement_snapshot.assert_called_once()
            account_id = dao.save_settlement_snapshot.call_args.args[0]
            assert account_id == "DQ"


@pytest.mark.unit
class TestOpeningCheck:
    """开盘检查任务"""

    @pytest.mark.asyncio
    async def test_disconnected_engine_sends_alarm(self, engine, job, app_paths):
        engine.connected = False
        socket_server = MagicMock()
        socket_server.send_push = AsyncMock()
        job.socket_server = socket_server

        await job.opening_check()

        socket_server.send_push.assert_awaited()
        push_type, payload = socket_server.send_push.await_args.args
        assert push_type == "alarm"
        assert "交易接口未连接" in payload["title"]

    @pytest.mark.asyncio
    async def test_connected_engine_no_alarm(self, engine, job, app_paths):
        socket_server = MagicMock()
        socket_server.send_push = AsyncMock()
        job.socket_server = socket_server

        await job.opening_check()

        socket_server.send_push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_param_file_alarms(self, engine, config, job, app_paths):
        from pathlib import Path

        config.strategies = {"rsi_001": SimpleNamespace(enabled=True, params_file="missing.json")}
        Path(app_paths.params).mkdir(parents=True, exist_ok=True)
        socket_server = MagicMock()
        socket_server.send_push = AsyncMock()
        job.socket_server = socket_server

        await job.opening_check()

        calls = [c.args[1] for c in socket_server.send_push.await_args_list]
        assert any("参数文件缺失" in p["title"] for p in calls)

    @pytest.mark.asyncio
    async def test_check_param_files(self, config, job, app_paths):
        from pathlib import Path

        params_dir = Path(app_paths.params)
        params_dir.mkdir(parents=True, exist_ok=True)
        (params_dir / "ok.json").write_text("{}")
        config.strategies = {
            "rsi_001": SimpleNamespace(enabled=True, params_file="ok.json"),
            "rsi_002": SimpleNamespace(enabled=True, params_file="gone.json"),
            "rsi_003": SimpleNamespace(enabled=False, params_file="disabled.json"),
        }

        missing = await job._check_param_files()

        assert missing == ["rsi_002: gone.json"]


@pytest.mark.unit
class TestClosingProcess:
    """收盘处理任务"""

    @pytest.mark.asyncio
    async def test_without_strategy_manager(self, job, app_paths):
        ctx = get_app_context()
        ctx.set(AppContext.KEY_STRATEGY_MANAGER, None)
        await job.closing_process()  # 导出为空持仓 → 不抛出

    @pytest.mark.asyncio
    async def test_settles_and_persists(self, job, app_paths):
        sm = MagicMock()
        sm.strategies = {}
        ctx = get_app_context()
        old = ctx.get(AppContext.KEY_STRATEGY_MANAGER)
        ctx.set(AppContext.KEY_STRATEGY_MANAGER, sm)
        try:
            with patch("qtrader.trader.job_mgr.StrategyPositionService") as svc_cls:
                await job.closing_process()

                sm.settle_positions.assert_called_once()
                svc_cls.assert_called_once()
        finally:
            ctx.set(AppContext.KEY_STRATEGY_MANAGER, old)
