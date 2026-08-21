"""
目标仓位比对管理器

扫描每个账户的目标仓位文件（TargetPos-<account>-<YYYYMMDD>[-N|-D].csv），
查询时与当前账户持仓实时比对并计算偏差；可按偏差导出换仓指令文件到
switch_pos 目录（格式与手工指令文件一致），由指令换仓流程扫描导入执行。

文件名日期为交易日，可选 -N（夜盘）/ -D（日盘）盘次标志：
夜盘文件在交易日的前一日晚间投放（夜盘属于次一交易日），
比对以网关返回的交易所交易日为准（夜盘时段为次一交易日）。

比对针对整个账户：文件中的 strategy_id 仅用于显示/标注，不参与仓位匹配。
同一 (symbol, side) 的目标以修改时间更新的文件为准。
"""

import base64
import csv
import re
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from qtrader.models.object import PositionData
from qtrader.trader.trading_engine import TradingEngine
from qtrader.utils.config_loader import AccountConfig, AppConfig, get_config_loader
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 目标仓位文件中方向到多/空侧的映射
_DIRECTION_SIDE = {"BUY": "LONG", "Buy": "LONG", "SELL": "SHORT", "Sell": "SHORT"}

# 指令换仓文件的 offset/direction 写法（与手工指令文件一致）
_OFFSET_TEXT = {"OPEN": "Open", "CLOSE": "Close"}
_DIRECTION_TEXT = {"BUY": "Buy", "SELL": "Sell"}


class TargetPosManager:
    """目标仓位比对管理器"""

    def __init__(self, config: AccountConfig, trading_engine: TradingEngine):
        """
        初始化目标仓位管理器

        Args:
            config: 账户配置
            trading_engine: 交易引擎实例
        """
        self.config: AccountConfig = config
        self.trading_engine: TradingEngine = trading_engine
        self.account_id: str = config.account_id  # type: ignore[assignment]

        app_config: AppConfig = get_config_loader()._load_app_config()
        self.target_pos_dir: str = app_config.paths.target_pos
        self.switch_pos_dir: str = app_config.paths.switch_pos

    # ==================== 文件导入 ====================

    def import_target_file(self, csv_text: str, filename: str) -> dict:
        """
        手动导入目标仓位文件：保存到目标仓位目录，供比对扫描读取

        文件名需包含8位交易日与本账户ID（如 TargetPos-DQ-20260811.csv）。

        Args:
            csv_text: CSV 文本内容
            filename: 文件名

        Returns:
            导入结果字典
        """
        if not re.search(r"\d{8}", filename or ""):
            raise ValueError(f"文件名无法提取交易日（需包含8位日期）: {filename}")
        if self.account_id not in (filename or ""):
            raise ValueError(f"文件名需包含账户ID（如 TargetPos-{self.account_id}-YYYYMMDD.csv）")

        target_dir = Path(self.target_pos_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / filename).write_text(csv_text, encoding="utf-8")
        logger.info(f"[{self.account_id}] 目标仓位文件已保存: {filename}")
        return {"saved": True, "file_name": filename}

    # ==================== 查询比对 ====================

    def get_position_comparison(self) -> dict[str, Any]:
        """
        扫描今日目标仓位文件，与当前账户持仓实时比对

        显示目标仓位与当前持仓的并集：
        - 只有目标没有持仓：current_volume=0
        - 只有持仓没有目标：target_volume=None，偏差与操作建议显示为空

        Returns:
            {"trading_date": 交易日, "comparisons": [比对行...]}
        """
        trading_date = self._trading_date()
        targets = self._load_today_targets(trading_date)
        positions = self._load_positions_by_symbol_side()

        all_symbols = sorted(set(targets.keys()) | set(positions.keys()))
        comparisons: list[dict[str, Any]] = []
        for symbol in all_symbols:
            for side in ("LONG", "SHORT"):
                target_info = targets.get(symbol, {}).get(side)
                current_volume = positions.get(symbol, {}).get(side, 0)

                # 两侧都没有数据时跳过
                if target_info is None and current_volume == 0:
                    continue

                if target_info is not None:
                    target_volume = target_info["target_volume"]
                    deviation = target_volume - current_volume
                    if deviation > 0:
                        direction = "BUY" if side == "LONG" else "SELL"
                        offset = "OPEN"
                    elif deviation < 0:
                        direction = "SELL" if side == "LONG" else "BUY"
                        offset = "CLOSE"
                    else:
                        direction = "BUY" if side == "LONG" else "SELL"
                        offset = "OPEN"
                    comparisons.append(
                        {
                            "account_id": self.account_id,
                            "symbol": symbol,
                            "side": side,
                            "strategy_id": target_info["strategy_id"],
                            "target_volume": target_volume,
                            "current_volume": current_volume,
                            "deviation": deviation,
                            "direction": direction,
                            "offset": offset,
                            "volume": abs(deviation),
                            "source": target_info["source"],
                        }
                    )
                else:
                    comparisons.append(
                        {
                            "account_id": self.account_id,
                            "symbol": symbol,
                            "side": side,
                            "strategy_id": None,
                            "target_volume": None,
                            "current_volume": current_volume,
                            "deviation": None,
                            "direction": None,
                            "offset": None,
                            "volume": None,
                            "source": None,
                        }
                    )
        return {"trading_date": trading_date, "comparisons": comparisons}

    # ==================== 导出换仓指令 ====================

    def export_instructions(self) -> dict[str, Any]:
        """
        按当前偏差生成换仓指令文件，写入指令换仓扫描目录

        只导出偏差不为 0 的行，平仓在前开仓在后（释放保证金）。
        指令换仓的扫描任务会自动导入该文件并执行。

        Returns:
            {"exported": 条数, "file_name": 文件名, "file_path": 目录}
        """
        result = self.get_position_comparison()
        rows = [r for r in result["comparisons"] if r["volume"] > 0]
        if not rows:
            logger.info(f"[{self.account_id}] 目标仓位与持仓无偏差，未生成指令文件")
            return {"exported": 0, "file_name": None, "file_path": None}

        # 平仓在前、开仓在后
        rows.sort(key=lambda r: 0 if r["offset"] == "CLOSE" else 1)

        now = datetime.now()
        # 目录与文件名遵循指令换仓扫描约定：switch_pos/<当日>/，文件名含当日日期与账户ID
        date_dir = Path(self.switch_pos_dir) / now.strftime("%Y%m%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"SwitchPos-{self.account_id}-{now:%Y%m%d}-{now:%H%M%S}.csv"

        lines = ["account,strategy,symbol,offset,direction,volume"]
        for r in rows:
            lines.append(
                f"{self.account_id},{r['strategy_id']},{r['symbol']},"
                f"{_OFFSET_TEXT[r['offset']]},{_DIRECTION_TEXT[r['direction']]},{r['volume']}"
            )
        file_path = date_dir / file_name
        # 指令换仓扫描按 gbk 读取文件
        file_path.write_text("\n".join(lines) + "\n", encoding="gbk")
        content_base64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        logger.info(f"[{self.account_id}] 已导出换仓指令文件 {file_name}，共 {len(rows)} 条")
        return {
            "exported": len(rows),
            "file_name": file_name,
            "file_path": str(date_dir),
            "content_base64": content_base64,
            "encoding": "gbk",
        }

    # ==================== 导出目标仓位 ====================

    def export_target_positions(self, strategy_id: str = "manual") -> dict[str, Any]:
        """
        将当前账户所有持仓导出为目标仓位文件

        默认导出全部持仓（多空两侧分别生成一行），
        写入 target_pos 目录，供后续比对/生成换仓指令。

        Args:
            strategy_id: 导出时使用的策略ID（默认 manual）

        Returns:
            {"exported": 条数, "file_name": 文件名, "file_path": 目录}
        """
        positions = self.trading_engine.positions or {}
        if not positions:
            return {"exported": 0, "file_name": None, "file_path": None}

        lines = ["account,strategy,symbol,direction,volume"]
        exported = 0
        trading_date = self._trading_date()
        for pos in positions.values():
            symbol = getattr(pos, "symbol", "") or ""
            if not symbol:
                continue
            symbol = self.trading_engine.std_symbol(symbol.split(".")[0])
            long_vol = pos.pos_long or 0
            short_vol = pos.pos_short or 0
            if long_vol > 0:
                lines.append(f"{self.account_id},{strategy_id},{symbol},Buy,{long_vol}")
                exported += 1
            if short_vol > 0:
                lines.append(f"{self.account_id},{strategy_id},{symbol},Sell,{short_vol}")
                exported += 1

        if exported == 0:
            return {"exported": 0, "file_name": None, "file_path": None}

        target_dir = Path(self.target_pos_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        file_name = f"TargetPos-{self.account_id}-{trading_date}-{now:%H%M%S}.csv"
        file_path = target_dir / file_name
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        content_base64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
        logger.info(f"[{self.account_id}] 已导出目标仓位文件 {file_name}，共 {exported} 条")
        return {
            "exported": exported,
            "file_name": file_name,
            "file_path": str(target_dir),
            "content_base64": content_base64,
            "encoding": "utf-8",
        }

    # ==================== 手动修改目标手数 ====================

    def update_target_volume(
        self, symbol: str, side: str, target_volume: int | None
    ) -> dict[str, Any]:
        """
        手动修改（或删除）某合约某侧的目标手数

        修改结果写入独立的目标仓位文件（TargetPos-<账户>-<交易日>-edit.csv），
        该文件以最新修改时间参与 _load_today_targets 的合并，从而覆盖策略文件中的同名目标。
        当 target_volume 为 None 时，删除该 (symbol, side) 对应的目标行；
        若文件因此为空，则直接删除该文件。

        Args:
            symbol: 合约代码（已标准化）
            side: 侧，"LONG" 或 "SHORT"
            target_volume: 目标手数；None 表示删除目标

        Returns:
            更新结果字典
        """
        if side not in ("LONG", "SHORT"):
            raise ValueError("side 必须是 LONG 或 SHORT")

        trading_date = self._trading_date()
        target_dir = Path(self.target_pos_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"TargetPos-{self.account_id}-{trading_date}-edit.csv"
        file_path = target_dir / file_name

        direction = "Buy" if side == "LONG" else "Sell"

        rows: list[dict[str, str]] = []
        if file_path.exists():
            text = self._read_file(file_path)
            reader = csv.DictReader(StringIO(text))
            for row in reader:
                rows.append(
                    {
                        "account": (row.get("account") or self.account_id).strip(),
                        "strategy": (
                            row.get("strategy") or row.get("stragegy") or "manual"
                        ).strip(),
                        "symbol": (row.get("symbol") or "").strip(),
                        "direction": (row.get("direction") or "").strip(),
                        "volume": (row.get("volume") or "0").strip(),
                    }
                )

        updated = False
        new_rows: list[dict[str, str]] = []
        for row in rows:
            row_side = _DIRECTION_SIDE.get(row["direction"])
            row_symbol = self.trading_engine.std_symbol(row["symbol"].split(".")[0])
            if row_symbol == symbol and row_side == side:
                if target_volume is not None:
                    row["volume"] = str(int(target_volume))
                    new_rows.append(row)
                updated = True
            else:
                new_rows.append(row)

        if not updated and target_volume is not None:
            new_rows.append(
                {
                    "account": self.account_id,
                    "strategy": "manual",
                    "symbol": symbol,
                    "direction": direction,
                    "volume": str(int(target_volume)),
                }
            )

        if not new_rows:
            if file_path.exists():
                file_path.unlink()
            return {"saved": True, "file_name": None, "deleted": True}

        lines = ["account,strategy,symbol,direction,volume"]
        for row in new_rows:
            lines.append(
                f"{row['account']},{row['strategy']},{row['symbol']},{row['direction']},{row['volume']}"
            )
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        logger.info(
            f"[{self.account_id}] 已更新目标仓位 {symbol} {side}={target_volume} -> {file_name}"
        )
        return {"saved": True, "file_name": file_name}

    # ==================== 文件解析 ====================

    def _load_today_targets(self, trading_date: str) -> dict[str, dict[str, dict[str, Any]]]:
        """加载今日所有目标仓位文件，按 (symbol, side) 合并（修改时间新的文件优先）"""
        targets: dict[str, dict[str, dict[str, Any]]] = {}
        target_dir = Path(self.target_pos_dir)
        if not target_dir.exists():
            return targets

        csv_files = [
            f
            for f in target_dir.glob("*.csv")
            if trading_date in f.name and self.account_id in f.name
        ]
        for csv_file in sorted(csv_files, key=lambda f: f.stat().st_mtime):
            try:
                rows = self._parse_csv(self._read_file(csv_file))
                for symbol, info in self._aggregate_rows(rows, csv_file.name).items():
                    for side, side_info in info.items():
                        targets.setdefault(symbol, {})[side] = side_info
            except Exception as e:
                logger.exception(f"[{self.account_id}] 解析目标仓位文件 {csv_file.name} 失败: {e}")
        return targets

    def _parse_csv(self, csv_text: str) -> list[dict[str, Any]]:
        """解析目标仓位 CSV，兼容 strategy/stragegy 表头"""
        reader = csv.DictReader(StringIO(csv_text))
        rows: list[dict[str, Any]] = []
        for line_num, row in enumerate(reader, start=2):
            # 兼容表头拼写错误 stragegy
            strategy_id = (row.get("strategy") or row.get("stragegy") or "").strip()
            account_id = (row.get("account") or "").strip()
            symbol_raw = (row.get("symbol") or "").strip()
            direction = (row.get("direction") or "").strip()
            volume_str = (row.get("volume") or "0").strip()

            if not strategy_id or not symbol_raw:
                logger.warning(f"第{line_num}行缺少策略或合约，跳过: {row}")
                continue
            if account_id and account_id != self.account_id:
                logger.warning(f"第{line_num}行账户 {account_id} 与本账户不符，跳过")
                continue
            if direction not in _DIRECTION_SIDE:
                logger.warning(f"第{line_num}行方向 {direction} 非法，跳过")
                continue
            try:
                volume = int(float(volume_str))
            except ValueError:
                logger.warning(f"第{line_num}行手数 {volume_str} 非法，跳过")
                continue

            symbol = self.trading_engine.std_symbol(symbol_raw.split(".")[0])
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "direction": direction.upper(),
                    "volume": volume,
                }
            )
        return rows

    @staticmethod
    def _aggregate_rows(
        rows: list[dict[str, Any]], source: str
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """按 symbol 聚合目标多/空手数，返回 symbol -> side -> {target_volume, strategy_id, source}"""
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            side = _DIRECTION_SIDE[row["direction"]]
            group = grouped.setdefault(row["symbol"], {})
            if side in group:
                group[side]["target_volume"] += row["volume"]
                # 多策略用 + 拼接（避免逗号破坏指令CSV格式）
                if row["strategy_id"] not in group[side]["strategy_id"]:
                    group[side]["strategy_id"] += f"+{row['strategy_id']}"
            else:
                group[side] = {
                    "target_volume": row["volume"],
                    "strategy_id": row["strategy_id"],
                    "source": source,
                }
        return grouped

    # ==================== 辅助方法 ====================

    def _load_positions_by_symbol_side(self) -> dict[str, dict[str, int]]:
        """将当前账户持仓按 symbol -> side 整理"""
        result: dict[str, dict[str, int]] = {}
        positions = self.trading_engine.positions or {}
        for pos in positions.values():
            symbol = getattr(pos, "symbol", "") or ""
            if not symbol:
                continue
            symbol = self.trading_engine.std_symbol(symbol.split(".")[0])
            long_vol = pos.pos_long or 0
            short_vol = pos.pos_short or 0
            if long_vol == 0 and short_vol == 0:
                continue
            result[symbol] = {"LONG": long_vol, "SHORT": short_vol}
        return result

    def _get_account_position(self, symbol: str) -> PositionData | None:
        """从网关内存获取账户级持仓，按标准代码匹配。

        不走数据库（账户持仓异步落库会滞后）。匹配顺序：
        1) 精确 key；
        2) 标准代码（std_symbol）一致；
        3) 基础代码（去交易所、小写）一致。
        覆盖大小写/带不带交易所后缀等差异。
        """
        positions = self.trading_engine.positions or {}
        if not positions:
            return None

        # 1) 精确 key
        pos = positions.get(symbol)
        if pos:
            return pos

        target_std = self.trading_engine.std_symbol(symbol)
        target_base = symbol.split(".")[0].lower()

        # 2)/3) 标准代码 / 基础代码匹配
        for key, p in positions.items():
            if key == symbol:
                return p
            key_std = self.trading_engine.std_symbol(key)
            if target_std and key_std and key_std == target_std:
                return p
            if key.split(".")[0].lower() == target_base:
                return p
            p_symbol = getattr(p, "symbol", "") or ""
            if p_symbol == symbol or p_symbol.split(".")[0].lower() == target_base:
                return p
        return None

    def _side_position_volume(self, symbol: str, side: str) -> int:
        """取账户级某合约指定侧的持仓手数"""
        pos = self._get_account_position(symbol)
        if not pos:
            return 0
        if side == "LONG":
            return pos.pos_long or 0
        return pos.pos_short or 0

    @staticmethod
    def _read_file(path: Path) -> str:
        """读取文件（utf-8 优先，回退 gbk）"""
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="gbk")

    def _trading_date(self) -> str:
        """当前交易日（交易所口径，夜盘时段为次一交易日）"""
        return self.trading_engine.trading_day.strftime("%Y%m%d")
