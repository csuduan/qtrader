"""
目标仓位换仓管理器

根据每个账户的目标仓位文件（TargetPos-<account>-<YYYYMMDD>[-N|-D].csv），
按"目标持仓 vs 当前账户持仓"的差值生成换仓指令并执行。

文件名日期为交易日，可选 -N（夜盘）/ -D（日盘）盘次标志：
夜盘文件在交易日的前一日晚间投放（夜盘属于次一交易日），
扫描/执行均以网关返回的交易所交易日为准（夜盘时段为次一交易日）。

换仓针对整个账户：文件中的 strategy_id 仅用于显示/标注，不参与仓位匹配；
账户持仓由网关维护，成交后自动更新，无需回写策略持仓。

与 SwitchPosManager（基于明确订单指令文件）并存，互不影响。
新模式内置幂等/防重复：
- 文件级：扫描导入按 file_hash 去重，文件变化才重算；手动导入始终强制重算。
- 指令级：instruction_key 唯一，重算按当前账户持仓重新计算差值。
- 执行级：不为 RUNNING 指令重复创建 OrderCmd；重启后按活跃状态恢复。
"""

import asyncio
import csv
import hashlib
import re
import time
import uuid
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any

from qtrader.models.object import (
    Direction,
    Offset,
    OrderCmdFinishReason,
    PositionData,
)
from qtrader.models.po import SwitchPosImportPo, TargetPosInstructionPo
from qtrader.trader.order_cmd import OrderCmd
from qtrader.trader.trading_engine import TradingEngine
from qtrader.utils.config_loader import AccountConfig, AppConfig, get_config_loader
from qtrader.utils.database import session_scope
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 目标仓位文件中方向到多/空侧的映射
_DIRECTION_SIDE = {"BUY": "LONG", "Buy": "LONG", "SELL": "SHORT", "Sell": "SHORT"}


class TargetPosManager:
    """目标仓位换仓管理器"""

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

        self.working: bool = False
        self.is_manual: bool = False
        self._stop_requested: bool = False

    # ==================== 启动/恢复 ====================

    def start(self) -> None:
        """启动目标仓位管理器（重置/恢复未完成指令）"""
        self._reconcile_running_instructions()
        logger.info(f"[{self.account_id}] 目标仓位管理器已启动")

    def _reconcile_running_instructions(self) -> None:
        """启动时恢复：今日 RUNNING 但对应 OrderCmd 已不存在的指令回退状态"""
        try:
            today = self._trading_date()
            with session_scope() as session:
                instructions = (
                    session.query(TargetPosInstructionPo)
                    .filter(
                        TargetPosInstructionPo.account_id == self.account_id,
                        TargetPosInstructionPo.trading_date == today,
                        TargetPosInstructionPo.is_deleted == False,  # noqa: E712
                        TargetPosInstructionPo.status == "RUNNING",
                    )
                    .all()
                )
                for inst in instructions:
                    if inst.current_order_id and self._is_cmd_active(inst.current_order_id):
                        # 仍有活跃报单指令，保持 RUNNING 由监控接管
                        continue
                    if inst.filled_volume >= inst.volume:
                        inst.status = "COMPLETED"
                    else:
                        inst.status = "PENDING"
                        inst.remaining_volume = inst.volume - inst.filled_volume
                        logger.warning(
                            f"[{self.account_id}] 指令 {inst.symbol}/{inst.side} 上次执行未完成，"
                            f"回退为 PENDING（已成交 {inst.filled_volume}/{inst.volume}）"
                        )
                    inst.current_order_id = None
        except Exception as e:
            logger.exception(f"[{self.account_id}] 恢复目标仓位指令失败: {e}")

    # ==================== 文件扫描与导入 ====================

    def scan_and_process_target_files(self) -> None:
        """扫描目标仓位目录并处理当前交易日文件（兼容 -N/-D 盘次标志）

        账户配置 enable_target_pos_rotation=false 时跳过扫描。
        """
        if not self.config.enable_target_pos_rotation:
            logger.debug("目标仓位换仓未开启，跳过扫描目标仓位文件")
            return
        try:
            trading_date = self._trading_date()
            target_dir = Path(self.target_pos_dir)
            if not target_dir.exists():
                return

            csv_files = [
                f
                for f in target_dir.glob("*.csv")
                if trading_date in f.name and self.account_id in f.name
            ]
            if not csv_files:
                return

            for csv_file in sorted(csv_files, key=lambda f: f.name):
                try:
                    content = self._read_file(csv_file)
                    self._import_target_csv(content, csv_file.name, str(csv_file.parent))
                except Exception as e:
                    logger.exception(
                        f"[{self.account_id}] 导入目标仓位文件 {csv_file.name} 失败: {e}"
                    )
        except Exception as e:
            logger.exception(f"[{self.account_id}] 扫描目标仓位文件失败: {e}")

    def import_target_file(self, csv_text: str, filename: str) -> dict:
        """
        手动导入目标仓位文件

        无论文件内容是否变化都重新计算差值并替换旧指令。
        账户配置 enable_target_pos_rotation=false 时拦截导入。

        Args:
            csv_text: CSV 文本内容
            filename: 文件名（需包含 YYYYMMDD 日期，可选 -N/-D 盘次标志）

        Returns:
            导入结果字典
        """
        if not self.config.enable_target_pos_rotation:
            raise ValueError(
                "目标仓位换仓未开启，已拦截导入（账户配置 enable_target_pos_rotation=false）"
            )
        return self._import_target_csv(csv_text, filename, self.target_pos_dir, force=True)

    def _import_target_csv(
        self, csv_text: str, filename: str, file_path: str, force: bool = False
    ) -> dict:
        """解析、计算差值并持久化目标仓位指令

        Args:
            force: 强制重新导入（跳过文件级幂等检查），手动导入使用
        """
        file_hash = hashlib.md5(csv_text.encode("utf-8")).hexdigest()

        trading_date = self._extract_trading_date(filename)
        if not trading_date:
            raise ValueError(f"文件名无法提取交易日（需包含8位日期）: {filename}")

        # 解析 + 计算差值（仅读取账户内存持仓，不占用数据库会话）
        target_rows = self._parse_csv(csv_text)
        plan_id = uuid.uuid4().hex
        instructions = self._compute_instructions(target_rows, trading_date, plan_id, filename)

        with session_scope() as session:
            # 文件级幂等：同名且 hash 一致则跳过（扫描导入；手动导入 force 跳过此检查）
            # 注意：查询与更新必须在同一会话内，否则脱管对象的属性修改不会持久化
            existing = (
                session.query(SwitchPosImportPo)
                .filter_by(account_id=self.account_id, file_name=filename)
                .first()
            )
            if not force and existing and existing.file_hash == file_hash:
                return {"imported": 0, "skipped": True, "reason": "文件未变化"}

            # 取消并软删除本账户今日旧 plan 的指令（文件变化 → 按当前持仓重算）
            self._retire_old_instructions(session, trading_date, plan_id)

            for inst in instructions:
                session.add(inst)

            # 记录/更新导入记录（plan_id/trading_date 仅存于指令表，导入记录只保留审计字段）
            if existing:
                existing.file_hash = file_hash
                existing.file_path = file_path or existing.file_path
            else:
                session.add(
                    SwitchPosImportPo(
                        account_id=self.account_id,
                        file_name=filename,
                        file_path=file_path,
                        file_hash=file_hash,
                        created_at=datetime.now(),
                    )
                )

        logger.info(
            f"[{self.account_id}] 目标仓位文件导入完成: {filename}, 生成 {len(instructions)} 条差值指令"
        )
        return {"imported": len(instructions), "skipped": False, "plan_id": plan_id}

    def _retire_old_instructions(self, session, trading_date: str, new_plan_id: str) -> None:
        """软删除今日旧指令，并撤销仍在执行的报单指令"""
        old_instructions = (
            session.query(TargetPosInstructionPo)
            .filter(
                TargetPosInstructionPo.account_id == self.account_id,
                TargetPosInstructionPo.trading_date == trading_date,
                TargetPosInstructionPo.is_deleted == False,  # noqa: E712
                TargetPosInstructionPo.plan_id != new_plan_id,
            )
            .all()
        )
        executor = self.trading_engine._order_cmd_executor
        for inst in old_instructions:
            if inst.status == "RUNNING" and inst.current_order_id and executor is not None:
                try:
                    executor.close(inst.current_order_id)
                except Exception as e:
                    logger.warning(f"[{self.account_id}] 撤销旧指令报单失败: {e}")
            inst.is_deleted = True

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

    def _compute_instructions(
        self,
        target_rows: list[dict[str, Any]],
        trading_date: str,
        plan_id: str,
        source: str,
    ) -> list[TargetPosInstructionPo]:
        """按 symbol 聚合目标多/空，对照账户持仓计算差值生成指令。

        - 换仓针对整个账户：同一 symbol 的多行（即使 strategy_id 不同）合并计算。
        - strategy_id 仅作显示，记录该 symbol 涉及的策略（多个则逗号拼接）。
        - 语义：只有目标文件中明确出现的侧才调整；未出现的侧保持不动（不会被动平仓）。
        """
        # 按 symbol 聚合目标，并记录每个侧是否被明确指定、涉及的策略
        grouped: dict[str, dict[str, Any]] = {}
        for row in target_rows:
            symbol = row["symbol"]
            group = grouped.setdefault(
                symbol,
                {
                    "target_long": 0,
                    "has_long": False,
                    "target_short": 0,
                    "has_short": False,
                    "strategy_ids": set(),
                },
            )
            group["strategy_ids"].add(row["strategy_id"])
            if row["direction"] == "BUY":
                group["target_long"] += row["volume"]
                group["has_long"] = True
            else:
                group["target_short"] += row["volume"]
                group["has_short"] = True

        instructions: list[TargetPosInstructionPo] = []
        now = datetime.now()
        for symbol, target in grouped.items():
            strategy_id = ",".join(sorted(target["strategy_ids"]))
            current = self._get_account_position(symbol)
            current_long = current.pos_long if current else 0
            current_short = current.pos_short if current else 0

            # 仅处理被明确指定的侧；未指定的侧不动
            side_actions: list[tuple[str, int, int]] = []
            if target["has_long"]:
                side_actions.append(("LONG", target["target_long"], current_long))
            if target["has_short"]:
                side_actions.append(("SHORT", target["target_short"], current_short))

            # 先生成平仓指令，再生成开仓指令（释放保证金）
            close_plans: list[tuple[str, str, str, int, int]] = []
            open_plans: list[tuple[str, str, str, int, int]] = []
            done_plans: list[tuple[str, int]] = []
            for side, target_vol, current_vol in side_actions:
                diff = target_vol - current_vol
                if diff > 0:
                    if side == "LONG":
                        open_plans.append(("BUY", "OPEN", side, target_vol, diff))
                    else:
                        open_plans.append(("SELL", "OPEN", side, target_vol, diff))
                elif diff < 0:
                    if side == "LONG":
                        close_plans.append(("SELL", "CLOSE", side, target_vol, -diff))
                    else:
                        close_plans.append(("BUY", "CLOSE", side, target_vol, -diff))
                else:
                    # 目标已到位：仍生成跟踪行（volume=0/COMPLETED），
                    # 持仓后续偏离目标时执行环节会自动重算并重新执行
                    done_plans.append((side, target_vol))

            for direction, offset, side, target_vol, vol in close_plans + open_plans:
                instruction_key = f"{self.account_id}:{symbol}:{side}:{trading_date}:{plan_id}"
                instructions.append(
                    TargetPosInstructionPo(
                        account_id=self.account_id,
                        strategy_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        target_volume=target_vol,
                        direction=direction,
                        offset=offset,
                        volume=vol,
                        filled_volume=0,
                        remaining_volume=vol,
                        price=0,
                        trading_date=trading_date,
                        plan_id=plan_id,
                        instruction_key=instruction_key,
                        enabled=True,
                        status="PENDING",
                        current_order_id=None,
                        source=source,
                        is_deleted=False,
                        created_at=now,
                        updated_at=now,
                    )
                )

            # 已到位的跟踪行：volume=0、COMPLETED
            for side, target_vol in done_plans:
                instruction_key = f"{self.account_id}:{symbol}:{side}:{trading_date}:{plan_id}"
                instructions.append(
                    TargetPosInstructionPo(
                        account_id=self.account_id,
                        strategy_id=strategy_id,
                        symbol=symbol,
                        side=side,
                        target_volume=target_vol,
                        direction="BUY" if side == "LONG" else "SELL",
                        offset="OPEN",
                        volume=0,
                        filled_volume=0,
                        remaining_volume=0,
                        price=0,
                        trading_date=trading_date,
                        plan_id=plan_id,
                        instruction_key=instruction_key,
                        enabled=True,
                        status="COMPLETED",
                        current_order_id=None,
                        source=source,
                        is_deleted=False,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return instructions

    # ==================== 执行 ====================

    async def execute_target_position(self, is_manual: bool = False) -> None:
        """
        执行目标仓位换仓

        Args:
            is_manual: 是否手动触发（手动触发可重试 FAILED 指令）
        """
        if self.working:
            logger.info(f"[{self.account_id}] 目标仓位换仓任务已在进行中，跳过")
            return
        self.working = True
        self._stop_requested = False
        self.is_manual = is_manual
        logger.info(f"[{self.account_id}] 开始目标仓位换仓, 手动: {is_manual}")

        instructions: list[TargetPosInstructionPo] = []
        try:
            instructions = self._load_today_instructions()
            if not instructions:
                logger.info(f"[{self.account_id}] 无目标仓位指令")
                return
            # 防重复判定 + 按当前持仓重新评估
            runnable: list[TargetPosInstructionPo] = []
            for inst in instructions:
                if not inst.enabled:
                    continue
                if inst.status == "RUNNING":
                    # 仍有活跃报单则仅监控，不重复创建
                    if inst.current_order_id and self._is_cmd_active(inst.current_order_id):
                        continue
                    # 活跃报单已丢失：落到下面按当前持仓重新评估
                # 其余所有指令（PENDING / FAILED / COMPLETED / 报单丢失）：
                # 只要最新偏差不为 0，就重置为 PENDING、刷新换仓前偏差(volume)重新执行；
                # 偏差为 0 则标记 COMPLETED。手动与定时行为一致。
                if not self._recalculate_deviation(inst):
                    continue  # 偏差为 0，方法内已标记 COMPLETED
                runnable.append(inst)

            self._update_instructions(instructions)

            # 为 PENDING 指令创建报单指令
            for inst in runnable:
                await self._launch_order_cmd(inst)

            # 监控所有 RUNNING 指令
            running = [i for i in instructions if i.status == "RUNNING"]
            if running:
                await self._monitor_order_commands(running)
        except Exception as e:
            logger.exception(f"[{self.account_id}] 目标仓位换仓执行失败: {e}")
        finally:
            self._update_instructions(instructions)
            self.working = False
            logger.info(f"[{self.account_id}] 目标仓位换仓任务结束")

    def _recalculate_deviation(self, inst: TargetPosInstructionPo) -> bool:
        """按当前实时持仓重算差值，刷新本次执行的换仓前基准。

        每次"开始换仓"时对待执行指令调用：以点击时刻的内存持仓为新起点，
        重新计算要调整的手数与方向，使"换仓前偏差"(=volume 带符号)反映本次
        执行的真实起点，而非导入时的历史值。

        Args:
            inst: 待执行指令（原地更新 volume/direction/offset/remaining/filled）

        Returns:
            True 表示仍有差值需下单；False 表示已到位（已标记 COMPLETED）。
        """
        current_vol = self._side_position_volume(inst.symbol, inst.side)
        diff = inst.target_volume - current_vol
        if diff > 0:
            inst.direction = "BUY" if inst.side == "LONG" else "SELL"
            inst.offset = "OPEN"
            inst.volume = diff
        elif diff < 0:
            inst.direction = "SELL" if inst.side == "LONG" else "BUY"
            inst.offset = "CLOSE"
            inst.volume = -diff
        else:
            inst.volume = 0
            inst.remaining_volume = 0
            inst.filled_volume = 0
            inst.status = "COMPLETED"
            inst.current_order_id = None
            logger.info(
                f"[{self.account_id}] {inst.symbol}/{inst.side} 已到位"
                f"(目标 {inst.target_volume} = 持仓 {current_vol})，标记完成"
            )
            return False

        inst.filled_volume = 0
        inst.remaining_volume = inst.volume
        inst.current_order_id = None
        inst.error_message = None
        inst.status = "PENDING"
        logger.info(
            f"[{self.account_id}] 重算 {inst.symbol}/{inst.side}："
            f"持仓 {current_vol} → 目标 {inst.target_volume}，"
            f"{inst.direction} {inst.offset} {inst.volume} 手"
        )
        return True

    async def _launch_order_cmd(self, inst: TargetPosInstructionPo) -> None:
        """为单条指令创建并提交 OrderCmd（先落库映射再执行，防丢失）"""
        if inst.current_order_id and self._is_cmd_active(inst.current_order_id):
            return  # 防重复：已有活跃报单指令

        price = float(inst.price) if inst.price and float(inst.price) > 0 else None
        order_cmd = OrderCmd(
            symbol=inst.symbol,
            direction=Direction(inst.direction),
            offset=Offset(inst.offset),
            volume=inst.remaining_volume,
            price=price,
            max_volume_per_order=self._max_split_volume(),
            order_interval=1,
            total_timeout=180,
            order_timeout=10,
            slip=1,
            source=f"目标换仓:{inst.strategy_id}:{inst.symbol}",
        )

        # 先持久化映射，避免提交后崩溃导致状态丢失
        inst.current_order_id = order_cmd.cmd_id
        inst.status = "RUNNING"
        inst.order_placed_time = datetime.now()
        self._update_instructions([inst])

        self.trading_engine.insert_order_cmd(order_cmd)
        logger.info(
            f"[{self.account_id}] 目标指令 {inst.symbol}/{inst.side} "
            f"{inst.direction} {inst.offset} {inst.remaining_volume}手 -> 报单指令 {order_cmd.cmd_id}"
        )

    async def _monitor_order_commands(self, instructions: list[TargetPosInstructionPo]) -> None:
        """轮询报单指令状态并回写"""
        check_interval = 2.0
        max_wait_time = 600
        start_time = time.time()
        stopped = False

        while True:
            if time.time() - start_time > max_wait_time:
                logger.warning(f"[{self.account_id}] 目标仓位换仓监控超时，强制退出")
                break

            if self._stop_requested and not stopped:
                logger.info(f"[{self.account_id}] 收到停止请求，撤销所有目标仓位报单")
                for inst in instructions:
                    if inst.current_order_id:
                        await self.trading_engine.cancel_order_cmd(inst.current_order_id)
                stopped = True
                self._stop_requested = False

            all_finished = True
            for inst in instructions:
                cmd_id = inst.current_order_id
                if not cmd_id:
                    continue
                cmd = self.trading_engine.get_order_cmd(cmd_id)
                if cmd is None:
                    continue
                # 累计成交 = 指令总量 - 当前报单剩余
                inst.filled_volume = max(0, inst.volume - cmd["remaining_volume"])
                inst.remaining_volume = cmd["remaining_volume"]

                if cmd["is_active"]:
                    all_finished = False
                else:
                    finish_reason = cmd.get("finish_reason")
                    if finish_reason == OrderCmdFinishReason.ALL_COMPLETED:
                        inst.status = "COMPLETED"
                    else:
                        inst.status = "FAILED"
                        inst.error_message = finish_reason
                    inst.current_order_id = None

            self._update_instructions(instructions)
            if all_finished:
                logger.info(f"[{self.account_id}] 所有目标仓位报单已完成")
                break
            await asyncio.sleep(check_interval)

    def stop_target_position(self) -> None:
        """请求停止目标仓位换仓"""
        if not self.working:
            logger.info(f"[{self.account_id}] 目标仓位换仓未进行中，无需停止")
            return
        self._stop_requested = True
        logger.info(f"[{self.account_id}] 已请求停止目标仓位换仓")

    # ==================== 辅助方法 ====================

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

    def _is_cmd_active(self, cmd_id: str) -> bool:
        """报单指令是否仍活跃"""
        cmd = self.trading_engine.get_order_cmd(cmd_id)
        return bool(cmd and cmd.get("is_active"))

    def _max_split_volume(self) -> int:
        """从风控配置获取最大拆单手数"""
        try:
            rc = self.config.trading.risk_control if self.config.trading else None
            if rc:
                return rc.max_split_volume
        except Exception:
            pass
        return 5

    def _load_today_instructions(self) -> list[TargetPosInstructionPo]:
        """加载今日本账户未删除的目标仓位指令"""
        today = self._trading_date()
        with session_scope() as session:
            rows = (
                session.query(TargetPosInstructionPo)
                .filter(
                    TargetPosInstructionPo.account_id == self.account_id,
                    TargetPosInstructionPo.trading_date == today,
                    TargetPosInstructionPo.is_deleted == False,  # noqa: E712
                )
                .order_by(TargetPosInstructionPo.id)
                .all()
            )
            # 提前 detach，避免跨 session 使用
            for r in rows:
                session.expunge(r)
            return rows

    def delete_instructions(self, ids: list[int]) -> int:
        """
        软删除指定指令。若指令仍在执行，先撤销其报单指令。

        Args:
            ids: 指令ID列表

        Returns:
            实际删除的条数
        """
        if not ids:
            return 0
        executor = self.trading_engine._order_cmd_executor
        deleted = 0
        try:
            with session_scope() as session:
                rows = (
                    session.query(TargetPosInstructionPo)
                    .filter(
                        TargetPosInstructionPo.id.in_(ids),
                        TargetPosInstructionPo.account_id == self.account_id,
                    )
                    .all()
                )
                for r in rows:
                    # 撤销仍在执行的报单，避免删除后留下孤儿挂单
                    if r.status == "RUNNING" and r.current_order_id and executor is not None:
                        try:
                            executor.close(r.current_order_id)
                        except Exception as e:
                            logger.warning(f"[{self.account_id}] 删除时撤销报单失败: {e}")
                    r.is_deleted = True
                    r.updated_at = datetime.now()
                    deleted += 1
            logger.info(f"[{self.account_id}] 软删除目标仓位指令 {deleted} 条")
        except Exception as e:
            logger.exception(f"[{self.account_id}] 删除目标仓位指令失败: {e}")
        return deleted

    def update_instruction(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        更新单条指令（启用/禁用、目标手数）。

        修改目标手数后按当前持仓重算偏差并重置进度基准
        （filled_volume=0、volume=当前偏差，执行中指令拒绝修改）。

        Args:
            data: {"instruction_id": int, "enabled"?: bool, "status"?: str, "target_volume"?: int}

        Returns:
            更新后的指令字典
        """
        instruction_id = data.get("instruction_id")
        if instruction_id is None:
            raise ValueError("缺少 instruction_id")

        with session_scope() as session:
            inst = (
                session.query(TargetPosInstructionPo)
                .filter_by(id=instruction_id, account_id=self.account_id)
                .first()
            )
            if not inst:
                raise ValueError(f"指令不存在: {instruction_id}")

            if data.get("enabled") is not None:
                inst.enabled = bool(data["enabled"])
            if data.get("status") is not None:
                inst.status = str(data["status"])
            if data.get("target_volume") is not None:
                target_volume = int(data["target_volume"])
                if target_volume < 0:
                    raise ValueError("目标手数不能为负数")
                if (
                    inst.status == "RUNNING"
                    and inst.current_order_id
                    and self._is_cmd_active(inst.current_order_id)
                ):
                    raise ValueError("指令执行中，请先停止换仓后再修改目标手数")
                if inst.target_volume != target_volume:
                    inst.target_volume = target_volume
                    # 目标变化后重置进度基准：分子清零、分母=当前偏差（与换仓开始时一致）
                    self._recalculate_deviation(inst)
            inst.updated_at = datetime.now()

            session.flush()
            session.refresh(inst)
            session.expunge(inst)
            return self._instruction_to_dict(inst)

    def _update_instructions(self, instructions: list[TargetPosInstructionPo]) -> None:
        """持久化指令状态"""
        if not instructions:
            return
        try:
            with session_scope() as session:
                for inst in instructions:
                    inst.updated_at = datetime.now()
                    session.merge(inst)
        except Exception as e:
            logger.exception(f"[{self.account_id}] 更新目标仓位指令失败: {e}")

    def get_today_instructions(self) -> list[dict[str, Any]]:
        """获取今日指令（供 API 返回）"""
        instructions = self._load_today_instructions()
        return [self._instruction_to_dict(inst) for inst in instructions]

    def _instruction_to_dict(self, inst: TargetPosInstructionPo) -> dict[str, Any]:
        """指令转字典（含当前账户持仓与偏差）"""
        pending_volume = 0
        if inst.current_order_id and inst.status == "RUNNING":
            cmd = self.trading_engine.get_order_cmd(inst.current_order_id)
            if cmd:
                pending_volume = cmd.get("pending_volume", 0)

        # 当前账户持仓（按侧取多/空）与当前偏差 = 目标 - 持仓（实时）
        current_volume = self._side_position_volume(inst.symbol, inst.side)
        current_deviation = inst.target_volume - current_volume
        # 换仓前偏差：指令生成时目标与持仓的差值（开仓为正、平仓为负），作为进度基准
        initial_deviation = inst.volume if inst.offset == "OPEN" else -inst.volume

        return {
            "id": inst.id,
            "account_id": inst.account_id,
            "strategy_id": inst.strategy_id,
            "symbol": inst.symbol,
            "side": inst.side,
            "target_volume": inst.target_volume,
            "current_volume": current_volume,
            "initial_deviation": initial_deviation,
            "current_deviation": current_deviation,
            "direction": inst.direction,
            "offset": inst.offset,
            "volume": inst.volume,
            "filled_volume": inst.filled_volume,
            "remaining_volume": inst.remaining_volume,
            "pending_volume": pending_volume,
            "price": float(inst.price) if inst.price else 0,
            "trading_date": inst.trading_date,
            "plan_id": inst.plan_id,
            "enabled": inst.enabled,
            "status": inst.status,
            "current_order_id": inst.current_order_id,
            "order_placed_time": (
                inst.order_placed_time.isoformat() if inst.order_placed_time else None
            ),
            "error_message": inst.error_message,
            "source": inst.source,
            "created_at": inst.created_at.isoformat() if inst.created_at else None,
            "updated_at": inst.updated_at.isoformat() if inst.updated_at else None,
        }

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
        """当前交易日（交易所口径，夜盘时段为次一交易日；网关未就绪回退日历日）"""
        return self.trading_engine.trading_day.strftime("%Y%m%d")

    @staticmethod
    def _extract_trading_date(filename: str) -> str | None:
        """从文件名提取 YYYYMMDD 交易日（兼容 -N/-D 盘次标志）"""
        matches = re.findall(r"\d{8}", filename)
        return matches[0] if matches else None
