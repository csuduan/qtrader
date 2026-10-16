"""
TargetPosManager 单元测试

覆盖：
- CSV 解析（strategy/stragegy 表头、账户过滤、非法行）
- 聚合（同symbol同侧跨策略合并、多策略 + 拼接）
- 查询时比对（开/平方向、只比对出现侧、目标0平仓、偏差0已到位、文件按修改时间合并、交易日匹配）
- 导出换仓指令文件（目录/文件名约定、gbk编码、平仓在前、零偏差不导出、开关拦截）
- 导入目标仓位文件（保存到目标目录、文件名校验、开关拦截）
"""

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qtrader.trader.target_pos_mgr import TargetPosManager


def build_manager(
    account_id: str = "DQ",
    target_dir: str = "",
    switch_dir: str = "",
    trading_date: str = "20260811",
) -> TargetPosManager:
    """构造一个不依赖数据库/配置文件的 TargetPosManager"""
    mgr = TargetPosManager.__new__(TargetPosManager)
    mgr.account_id = account_id
    mgr.config = MagicMock()
    mgr.config.enable_target_pos_rotation = True
    te = MagicMock()
    te.std_symbol = lambda s: s  # 测试中不改变合约名
    te.trading_day = datetime.strptime(trading_date, "%Y%m%d")
    mgr.trading_engine = te
    mgr.target_pos_dir = target_dir
    mgr.switch_pos_dir = switch_dir
    return mgr


def make_position(long_vol: int = 0, short_vol: int = 0, symbol: str = ""):
    pos = MagicMock()
    pos.pos_long = long_vol
    pos.pos_short = short_vol
    pos.symbol = symbol
    return pos


def set_positions(mgr, current_map):
    """用 current_map(symbol->position) 设置 trading_engine.positions"""
    positions = {}
    for symbol, pos in current_map.items():
        if not hasattr(pos, "symbol") or not pos.symbol:
            pos.symbol = symbol
        positions[symbol] = pos
    mgr.trading_engine.positions = positions


def make_position_symbol(symbol: str, long_vol: int = 0, short_vol: int = 0):
    return make_position(long_vol=long_vol, short_vol=short_vol, symbol=symbol)


# ==================== CSV 解析 ====================


def test_parse_csv_accepts_both_headers():
    mgr = build_manager()
    csv_text = (
        "account,stragegy,symbol,direction,volume\n"
        "DQ,StrategyFix_A,A2611,Sell,2\n"
        "DQ,StrategyFix_B,AL2609,Buy,6\n"
    )
    rows = mgr._parse_csv(csv_text)
    assert len(rows) == 2
    assert rows[0] == {
        "strategy_id": "StrategyFix_A",
        "symbol": "A2611",
        "direction": "SELL",
        "volume": 2,
    }
    assert rows[1]["direction"] == "BUY"


def test_parse_csv_filters_other_account_and_bad_direction():
    mgr = build_manager()
    csv_text = (
        "account,strategy,symbol,direction,volume\n"
        "RF,StrategyFix_A,A2611,Buy,2\n"  # 其他账户 → 跳过
        "DQ,StrategyFix_B,AL2609,Up,6\n"  # 非法方向 → 跳过
        "DQ,StrategyFix_C,AG2605,Buy,3\n"
    )
    rows = mgr._parse_csv(csv_text)
    assert len(rows) == 1
    assert rows[0]["strategy_id"] == "StrategyFix_C"


def test_aggregate_sums_same_side_and_joins_strategies():
    rows = [
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "BUY", "volume": 2},
        {"strategy_id": "S2", "symbol": "rb2609", "direction": "BUY", "volume": 3},
        {"strategy_id": "S1", "symbol": "rb2609", "direction": "SELL", "volume": 4},
    ]
    grouped = TargetPosManager._aggregate_rows(rows, "f.csv")
    assert grouped["rb2609"]["LONG"]["target_volume"] == 5
    assert grouped["rb2609"]["LONG"]["strategy_id"] == "S1+S2"
    assert grouped["rb2609"]["SHORT"]["target_volume"] == 4
    assert grouped["rb2609"]["SHORT"]["source"] == "f.csv"


# ==================== 查询时比对 ====================


def write_target_file(target_dir: Path, name: str, csv_text: str, mtime: float | None = None):
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / name
    path.write_text(csv_text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_comparison_open_long_and_short_from_zero(tmp_path):
    write_target_file(
        tmp_path,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\n" "DQ,S1,rb2609,Buy,5\n" "DQ,S1,rb2609,Sell,6\n",
    )
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {})
    result = mgr.get_position_comparison()

    assert result["trading_date"] == "20260811"
    by_side = {c["side"]: c for c in result["comparisons"]}
    assert by_side["LONG"]["deviation"] == 5
    assert by_side["LONG"]["direction"] == "BUY" and by_side["LONG"]["offset"] == "OPEN"
    assert by_side["LONG"]["volume"] == 5
    assert by_side["SHORT"]["deviation"] == 6
    assert by_side["SHORT"]["direction"] == "SELL" and by_side["SHORT"]["offset"] == "OPEN"


def test_comparison_only_specified_side(tmp_path):
    """账户 rb2609 持 6多+6空，目标文件只有 Buy 3 → 多头平3手，空头仅显示持仓"""
    write_target_file(
        tmp_path,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,3\n",
    )
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {"rb2609": make_position(long_vol=6, short_vol=6)})
    result = mgr.get_position_comparison()

    by_side = {c["side"]: c for c in result["comparisons"]}
    assert by_side["LONG"]["offset"] == "CLOSE" and by_side["LONG"]["direction"] == "SELL"
    assert by_side["LONG"]["deviation"] == -3 and by_side["LONG"]["volume"] == 3
    assert by_side["SHORT"]["target_volume"] is None
    assert by_side["SHORT"]["current_volume"] == 6
    assert by_side["SHORT"]["deviation"] is None


def test_comparison_shows_position_without_target(tmp_path):
    """持仓存在但目标文件未提及该 symbol，仍显示持仓行且目标手数为 None"""
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {"ag2606": make_position(long_vol=4, short_vol=0)})
    result = mgr.get_position_comparison()

    assert len(result["comparisons"]) == 1
    c = result["comparisons"][0]
    assert c["symbol"] == "ag2606"
    assert c["side"] == "LONG"
    assert c["target_volume"] is None
    assert c["current_volume"] == 4
    assert c["deviation"] is None
    assert c["direction"] is None
    assert c["volume"] is None


def test_comparison_target_zero_closes_side(tmp_path):
    """显式写出某侧目标 0 才会平掉该侧"""
    write_target_file(
        tmp_path,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\n" "DQ,S1,rb2609,Sell,3\n" "DQ,S1,rb2609,Buy,0\n",
    )
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {"rb2609": make_position(long_vol=5)})
    result = mgr.get_position_comparison()

    by_side = {c["side"]: c for c in result["comparisons"]}
    assert by_side["LONG"]["target_volume"] == 0
    assert by_side["LONG"]["deviation"] == -5 and by_side["LONG"]["volume"] == 5
    assert by_side["SHORT"]["deviation"] == 3


def test_comparison_at_target_marks_zero_volume(tmp_path):
    """已到位的行 volume=0，仍返回供页面显示"""
    write_target_file(
        tmp_path,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,4\n",
    )
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {"rb2609": make_position(long_vol=4)})
    result = mgr.get_position_comparison()

    assert len(result["comparisons"]) == 1
    c = result["comparisons"][0]
    assert c["deviation"] == 0 and c["volume"] == 0


def test_comparison_merges_files_by_mtime(tmp_path):
    """同 (symbol, side) 目标以修改时间更新的文件为准，不同 symbol 合并"""
    old = "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,1\nDQ,S2,ag2606,Buy,2\n"
    new = "account,strategy,symbol,direction,volume\nDQ,S3,rb2609,Buy,7\n"
    write_target_file(tmp_path, "TargetPos-DQ-20260811-N.csv", old, mtime=1000)
    write_target_file(tmp_path, "TargetPos-DQ-20260811-D.csv", new, mtime=2000)
    mgr = build_manager(target_dir=str(tmp_path))
    set_positions(mgr, {})

    targets = mgr._load_today_targets("20260811")
    assert targets["rb2609"]["LONG"]["target_volume"] == 7
    assert targets["rb2609"]["LONG"]["strategy_id"] == "S3"
    assert targets["ag2606"]["LONG"]["target_volume"] == 2


def test_comparison_matches_trading_date_not_calendar(tmp_path):
    """夜盘时段（交易日为次日）只匹配交易日文件，不匹配日历日文件"""
    header = "account,strategy,symbol,direction,volume\n"
    write_target_file(tmp_path, "TargetPos-DQ-20260810.csv", header + "DQ,S1,rb2609,Buy,1\n")
    write_target_file(tmp_path, "TargetPos-DQ-20260811-N.csv", header + "DQ,S1,rb2609,Buy,9\n")
    mgr = build_manager(target_dir=str(tmp_path), trading_date="20260811")
    set_positions(mgr, {})

    targets = mgr._load_today_targets("20260811")
    assert list(targets.keys()) == ["rb2609"]
    assert targets["rb2609"]["LONG"]["target_volume"] == 9


def test_comparison_ignores_other_account_files(tmp_path):
    write_target_file(
        tmp_path,
        "TargetPos-RF-20260811.csv",
        "account,strategy,symbol,direction,volume\nRF,S1,rb2609,Buy,1\n",
    )
    # 账户ID为DQ2的文件名包含子串DQ，前缀匹配下不应被误读（行内账户留空以验证扫描层的过滤）
    write_target_file(
        tmp_path,
        "TargetPos-DQ2-20260811.csv",
        "account,strategy,symbol,direction,volume\n,S1,rb2609,Buy,1\n",
    )
    mgr = build_manager(target_dir=str(tmp_path))
    result = mgr.get_position_comparison()
    assert result["comparisons"] == []


# ==================== 导出换仓指令文件 ====================


def test_export_writes_instruction_file(tmp_path):
    """导出到 switch_pos/<当日>/，文件名含当日日期与账户ID，gbk 可读，平仓在前"""
    target_dir = tmp_path / "target_pos"
    switch_dir = tmp_path / "switch_pos"
    write_target_file(
        target_dir,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\n"
        "DQ,S1,rb2609,Buy,5\n"  # 持仓0 → 开多5
        "DQ,S1,cu2609,Sell,0\n",  # 空头持仓2 → 平空2
    )
    mgr = build_manager(target_dir=str(target_dir), switch_dir=str(switch_dir))
    set_positions(mgr, {"cu2609": make_position(short_vol=2)})

    result = mgr.export_instructions()

    assert result["exported"] == 2
    date_dir = Path(switch_dir) / datetime.now().strftime("%Y%m%d")
    path = date_dir / result["file_name"]
    assert path.exists()
    assert datetime.now().strftime("%Y%m%d") in result["file_name"]
    assert "DQ" in result["file_name"]

    content = path.read_text(encoding="gbk")
    lines = content.strip().split("\n")
    assert lines[0] == "account,strategy,symbol,offset,direction,volume"
    assert lines[1] == "DQ,S1,cu2609,Close,Buy,2"  # 平仓在前
    assert lines[2] == "DQ,S1,rb2609,Open,Buy,5"


def test_export_skips_zero_deviation(tmp_path):
    target_dir = tmp_path / "target_pos"
    write_target_file(
        target_dir,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,4\n",
    )
    mgr = build_manager(target_dir=str(target_dir), switch_dir=str(tmp_path / "switch_pos"))
    set_positions(mgr, {"rb2609": make_position(long_vol=4)})

    result = mgr.export_instructions()

    assert result["exported"] == 0
    assert result["file_name"] is None
    assert not list((tmp_path / "switch_pos").rglob("*.csv"))


# ==================== 导出目标仓位 ====================


def test_export_target_positions_all_positions(tmp_path):
    """按当前持仓导出目标仓位文件，默认包含所有持仓多空两侧"""
    mgr = build_manager(target_dir=str(tmp_path / "target_pos"))
    mgr.trading_engine.positions = {
        "rb2609": make_position_symbol("rb2609", long_vol=5, short_vol=2),
        "cu2609": make_position_symbol("cu2609", long_vol=0, short_vol=3),
    }

    result = mgr.export_target_positions()

    assert result["exported"] == 3
    target_dir = tmp_path / "target_pos"
    path = target_dir / result["file_name"]
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "DQ,manual,rb2609,Buy,5" in content
    assert "DQ,manual,rb2609,Sell,2" in content
    assert "DQ,manual,cu2609,Sell,3" in content


def test_export_target_positions_empty_when_no_positions(tmp_path):
    mgr = build_manager(target_dir=str(tmp_path / "target_pos"))
    mgr.trading_engine.positions = {}

    result = mgr.export_target_positions()

    assert result["exported"] == 0
    assert result["file_name"] is None


# ==================== 导入目标仓位文件 ====================


def test_import_saves_file_to_target_dir(tmp_path):
    mgr = build_manager(target_dir=str(tmp_path / "target_pos"))
    csv_text = "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,3\n"

    result = mgr.import_target_file(csv_text, "TargetPos-DQ-20260811.csv")

    assert result == {"saved": True, "file_name": "TargetPos-DQ-20260811.csv"}
    saved = tmp_path / "target_pos" / "TargetPos-DQ-20260811.csv"
    assert saved.read_text(encoding="utf-8") == csv_text


def test_import_rejects_filename_without_date(tmp_path):
    mgr = build_manager(target_dir=str(tmp_path))
    with pytest.raises(ValueError, match="交易日"):
        mgr.import_target_file("a,b\n", "positions.csv")


def test_import_rejects_filename_without_account(tmp_path):
    mgr = build_manager(target_dir=str(tmp_path))
    with pytest.raises(ValueError, match="账户ID"):
        mgr.import_target_file("a,b\n", "TargetPos-20260811.csv")


# ==================== 手动修改目标手数 ====================


def test_update_target_volume_creates_edit_file(tmp_path):
    """修改已有目标会生成 edit 文件，覆盖原目标"""
    target_dir = tmp_path / "target_pos"
    write_target_file(
        target_dir,
        "TargetPos-DQ-20260811.csv",
        "account,strategy,symbol,direction,volume\nDQ,S1,rb2609,Buy,4\n",
    )
    mgr = build_manager(target_dir=str(target_dir))

    result = mgr.update_target_volume("rb2609", "LONG", 2)

    assert result["saved"] is True
    assert result["file_name"] == "TargetPos-DQ-20260811-edit.csv"
    edit_path = target_dir / "TargetPos-DQ-20260811-edit.csv"
    assert edit_path.exists()
    assert "DQ,manual,rb2609,Buy,2" in edit_path.read_text(encoding="utf-8")


def test_update_target_volume_adds_new_target(tmp_path):
    """为没有目标的持仓侧新增目标"""
    mgr = build_manager(target_dir=str(tmp_path / "target_pos"))
    result = mgr.update_target_volume("ag2606", "SHORT", 3)

    assert result["saved"] is True
    edit_path = tmp_path / "target_pos" / "TargetPos-DQ-20260811-edit.csv"
    assert edit_path.exists()
    assert "DQ,manual,ag2606,Sell,3" in edit_path.read_text(encoding="utf-8")


def test_update_target_volume_deletes_row_and_file(tmp_path):
    """清空目标手数会删除对应行；文件为空则删除文件"""
    target_dir = tmp_path / "target_pos"
    write_target_file(
        target_dir,
        "TargetPos-DQ-20260811-edit.csv",
        "account,strategy,symbol,direction,volume\nDQ,manual,rb2609,Buy,4\n",
    )
    mgr = build_manager(target_dir=str(target_dir))

    result = mgr.update_target_volume("rb2609", "LONG", None)

    assert result["deleted"] is True
    assert not (target_dir / "TargetPos-DQ-20260811-edit.csv").exists()


def test_update_target_volume_changes_only_matched_side(tmp_path):
    """修改多头时不影响同合约空头目标"""
    target_dir = tmp_path / "target_pos"
    write_target_file(
        target_dir,
        "TargetPos-DQ-20260811-edit.csv",
        "account,strategy,symbol,direction,volume\n"
        "DQ,manual,rb2609,Buy,4\n"
        "DQ,manual,rb2609,Sell,2\n",
    )
    mgr = build_manager(target_dir=str(target_dir))

    mgr.update_target_volume("rb2609", "LONG", 1)

    content = (target_dir / "TargetPos-DQ-20260811-edit.csv").read_text(encoding="utf-8")
    assert "DQ,manual,rb2609,Buy,1" in content
    assert "DQ,manual,rb2609,Sell,2" in content
