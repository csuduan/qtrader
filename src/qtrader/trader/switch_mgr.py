"""
订单文件扫描器和持仓管理器
扫描指定目录中的CSV订单文件并执行交易指令
执行换仓逻辑
"""

import asyncio
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from qtrader.models.object import Direction, Offset, OrderCmdFinishReason
from qtrader.models.po import RotationInstructionPo
from qtrader.models.po import SwitchPosImportPo as OrderFile
from qtrader.trader.order_cmd import OrderCmd
from qtrader.trader.trading_engine import TradingEngine
from qtrader.utils.async_database import fetch_all, fetch_one, get_async_session
from qtrader.utils.config_loader import AccountConfig, get_config_loader
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class OrderInstruction:
    """订单指令类"""

    def __init__(
        self,
        symbol: str,
        exchange_id: str,
        offset: str,
        direction: str,
        volume: int,
        price: float,
        order_time: str | None,
    ):
        self.symbol = symbol  # 合约代码，如 "SHFE.rb2505"
        self.exchange_id = exchange_id  # 交易所代码，如 "SHFE"
        self.offset = offset  # 开平类型: OPEN/CLOSE/CLOSETODAY
        self.direction = direction  # 买卖方向: BUY/SELL
        self.volume = volume  # 手数
        self.price = price  # 价格（0表示使用对手价）
        self.order_time = order_time  # 报单时间（格式HH:MM:SS，空则不限制）

    def __repr__(self) -> str:
        return (
            f"OrderInstruction(symbol={self.symbol}, direction={self.direction}, "
            f"offset={self.offset}, volume={self.volume}, price={self.price})"
        )


class SwitchPosManager:
    """换仓管理器，负责换仓逻辑"""

    def __init__(self, config: AccountConfig, trading_engine: TradingEngine):
        """
        初始化持仓管理器

        Args:
            config: 应用配置（AppConfig 或 AccountConfig）
            trading_engine: 交易引擎实例
        """
        self.config: AccountConfig = config
        self.trading_engine: TradingEngine = trading_engine
        # 从全局配置获取路径
        app_config = get_config_loader()._load_app_config()
        self.switchPos_files_dir = app_config.paths.switch_pos
        self.working = False
        self.running_instructions: list[RotationInstructionPo] | None = None
        self.is_manual = False
        self.all_instructions: list[RotationInstructionPo] = []
        self._stop_requested = False

    async def start(self) -> None:
        """启动换仓管理器"""
        # 加载所有换仓指令
        await self.load_rotation_instructions()

    def stop_rotation(self) -> None:
        """请求停止换仓"""
        if not self.working:
            logger.info("换仓未在进行中，无需停止")
            return
        self._stop_requested = True
        logger.info("已请求停止换仓")

    def get_today_instructions(self) -> list[RotationInstructionPo]:
        """获取今日换仓指令"""
        today = datetime.now().strftime("%Y%m%d")
        return [x for x in self.all_instructions if x.trading_date == today]

    async def update_instruction(self, data: dict[str, Any]) -> "RotationInstructionPo":
        """更新换仓指令"""
        instruction_id = data.get("instruction_id")
        if not instruction_id:
            raise ValueError("缺少指令ID")

        instruction = next((x for x in self.all_instructions if x.id == instruction_id), None)
        if not instruction:
            raise ValueError("指令不存在")

        if data.get("enabled") is not None:
            instruction.enabled = data["enabled"]
        if data.get("status") is not None:
            instruction.status = data["status"]
        if data.get("filled_volume") is not None:
            instruction.filled_volume = data["filled_volume"]
        if data.get("direction") is not None:
            instruction.direction = data["direction"]
        if data.get("offset") is not None:
            instruction.offset = data["offset"]
        if data.get("volume") is not None:
            instruction.volume = data["volume"]
            # 同步调整剩余手数
            instruction.remaining_volume = max(0, instruction.volume - instruction.filled_volume)
        instruction.updated_at = datetime.now()

        # 更新数据库
        async with get_async_session() as session:
            await session.merge(instruction)

        return instruction

    async def delete_instruction(self, ids: list[int]) -> None:
        """删除换仓指令"""
        self.all_instructions = [x for x in self.all_instructions if x.id not in ids]
        # 更新数据库
        async with get_async_session() as session:
            await session.execute(
                update(RotationInstructionPo)
                .where(RotationInstructionPo.id.in_(ids))
                .values(is_deleted=True)
            )

    async def load_rotation_instructions(self) -> None:
        """加载所有换仓指令"""
        try:
            # 从数据库加载今日换仓指令
            async with get_async_session() as session:
                today = datetime.now().strftime("%Y%m%d")
                self.all_instructions = await fetch_all(
                    session,
                    select(RotationInstructionPo).filter(
                        RotationInstructionPo.trading_date == today,
                        RotationInstructionPo.is_deleted == False,  # noqa: E712
                        RotationInstructionPo.account_id == self.config.account_id,
                    ),
                )

            # 订阅所有指令中的合约
            symbols = list({instruction.symbol for instruction in self.all_instructions})
            logger.info(f"换仓指令合约列表: {symbols}")
            self.trading_engine.subscribe_symbol(symbols)
        except Exception:
            logger.exception("获取所有指令列表时出错")
        logger.info(f"加载换仓指令完成，共 {len(self.all_instructions)} 条")

    async def import_csv(
        self, csv_text: str, filename: str, mode: str = "replace"
    ) -> dict[str, Any]:
        """
        导入换仓指令文件

        Args:
            csv_text: 换仓指令文件内容
            filename: 文件名（用于提取交易日）
            mode: 导入模式（replace/append）
        """
        lines = csv_text.strip().split("\n")
        if len(lines) < 2:
            raise ValueError("CSV文件为空或格式错误")

        header = lines[0].strip().split(",")
        logger.info(f"准备导入换仓文件，文件名: {filename}, 模式: {mode}, 列: {header}")

        imported_count = 0
        failed_count = 0
        errors = []

        trading_date = None
        if filename:
            matchs = re.findall(r"\d{8}", filename)
            if matchs:
                trading_date = matchs[0]
                logger.info(f"从文件名提取交易日: {trading_date}")
            else:
                raise ValueError(f"文件名格式错误，无法提取交易日: {filename}")

        add_instruction = []
        for line_num, line in enumerate(lines[1:], start=2):
            try:
                values = line.strip().split(",")
                if len(values) < 6:
                    logger.warning(f"第{line_num}行数据不完整，跳过: {line}")
                    failed_count += 1
                    continue

                account_id = values[0].strip()
                strategy_id = values[1].strip()
                instrument_str = self.trading_engine.std_symbol(values[2].strip().split(".")[0])
                offset_str = values[3].strip()
                direction_str = values[4].strip()
                volume_str = values[5].strip()
                order_time_str = values[6].strip() if len(values) > 6 else None

                if not account_id or not strategy_id or not instrument_str:
                    logger.warning(f"第{line_num}行缺少必要字段，跳过")
                    failed_count += 1
                    continue

                if self.config.account_id != account_id:
                    logger.warning(
                        f"第{line_num}行账户ID {account_id} 与配置账户ID {self.config.account_id} 不一致，跳过"
                    )
                    failed_count += 1
                    continue

                instrument_str = instrument_str.strip()
                symbol = instrument_str

                offset_map = {
                    "Open": "OPEN",
                    "Close": "CLOSE",
                    "开仓": "OPEN",
                    "平仓": "CLOSE",
                }
                direction_map = {
                    "Buy": "BUY",
                    "Sell": "SELL",
                    "买入": "BUY",
                    "卖出": "SELL",
                }

                offset = offset_map.get(offset_str, offset_str.upper())
                direction = direction_map.get(direction_str, direction_str.upper())

                try:
                    volume = int(volume_str)
                except ValueError:
                    logger.warning(f"第{line_num}行手数格式错误: {volume_str}")
                    failed_count += 1
                    continue

                if volume <= 0:
                    logger.warning(f"第{line_num}行手数必须大于0")
                    failed_count += 1
                    continue

                instruction = RotationInstructionPo(
                    account_id=account_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    offset=offset,
                    direction=direction,
                    volume=volume,
                    filled_volume=0,
                    price=0,
                    order_time=order_time_str,
                    trading_date=trading_date,
                    enabled=True,
                    status="PENDING",
                    attempt_count=0,
                    remaining_attempts=0,
                    remaining_volume=volume,
                    current_order_id=None,
                    order_placed_time=None,
                    last_attempt_time=None,
                    error_message=None,
                    source=filename,
                    is_deleted=False,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                add_instruction.append(instruction)
                imported_count += 1

            except Exception as e:
                logger.exception("第{}行解析失败: , 内容: {}", line_num, line)
                failed_count += 1
                errors.append({"row": line_num, "error": str(e), "content": line})
                continue

        async with get_async_session() as session:
            if mode == "replace":
                # 先删除本账户已存在的记录
                await session.execute(
                    update(RotationInstructionPo)
                    .where(
                        RotationInstructionPo.trading_date == trading_date,
                        RotationInstructionPo.account_id == self.config.account_id,
                    )
                    .values(is_deleted=True)
                )
            session.add_all(add_instruction)

        # 重新加载数据
        await self.load_rotation_instructions()
        logger.info(f"CSV导入完成，成功: {imported_count}, 失败: {failed_count}")
        data = {
            "imported": imported_count,
            "failed": failed_count,
            "errors": errors[:10],
        }
        return data

    async def _is_file_stable(
        self, csv_file: Path, size_window: float = 3.0, min_age: float = 5.0
    ) -> bool:
        """
        检查文件是否已写入完成（不再变化）

        判定条件（同时满足）：
        1. size_window 秒观察窗口内文件大小无变化
        2. 文件修改时间与当前时间差的绝对值不小于 min_age 秒
           （进入观察窗口前快检一次，观察结束后复检一次，观察期内被触碰视为未稳定）

        Args:
            csv_file: 待检查的文件
            size_window: 大小稳定性观察窗口（秒）
            min_age: 修改时间与当前时间的最小偏差（秒）

        Returns:
            bool: True-文件已稳定；False-仍在变化、时间戳过新或获取状态失败
        """
        try:
            stat_before = csv_file.stat()
            # 时间戳过新（含轻微未来偏差，共享目录时钟不一致场景）直接跳过，不进入观察窗口
            if abs(time.time() - stat_before.st_mtime) < min_age:
                logger.debug(
                    f"文件 {csv_file.name} 修改时间与当前偏差不足{min_age}秒，跳过本次扫描"
                )
                return False
            await asyncio.sleep(size_window)
            stat_after = csv_file.stat()
            if stat_before.st_size != stat_after.st_size:
                logger.warning(f"文件 {csv_file.name} 正在写入，跳过本次扫描")
                return False
            if abs(time.time() - stat_after.st_mtime) < min_age:
                logger.warning(f"文件 {csv_file.name} 观察期内被修改，跳过本次扫描")
                return False
            return True
        except OSError as e:
            logger.warning(f"获取文件 {csv_file.name} 状态失败: {e}")
            return False

    @logger.catch(message="扫描订单文件时出错")
    async def scan_and_process_orders(self) -> None:
        """扫描并处理交易指令文件"""
        today_dir = Path(self.switchPos_files_dir) / datetime.now().strftime("%Y%m%d")
        today_str = datetime.now().strftime("%Y%m%d")
        csv_files = [
            f
            for f in today_dir.glob("*.csv")
            if today_str in f.name and self.config.account_id and self.config.account_id in f.name
        ]
        if not csv_files:
            return
        csv_files = sorted(
            csv_files,
            key=lambda f: f.stat().st_mtime if f.is_file() else 0,
            reverse=True,
        )

        # 筛出尚未导入的文件（会话即开即关，不跨越下方的文件等待）
        async with get_async_session() as session:
            pending_files = []
            for f in csv_files:
                existing = await fetch_one(
                    session,
                    select(OrderFile).filter_by(
                        account_id=self.config.account_id, file_name=f.name
                    ),
                )
                if not existing:
                    pending_files.append(f)
        if not pending_files:
            return

        # 预检文件稳定性与内容（含大小观察窗口等待），不占用数据库会话
        ready_files: list[tuple[Path, str]] = []
        for csv_file in pending_files:
            if not await self._is_file_stable(csv_file):
                continue
            try:
                content = csv_file.read_text(encoding="gbk")
            except Exception:
                logger.exception("读取文件 {} 失败", csv_file.name)
                continue

            # 内容为空说明写入方尚未写入，跳过本轮，下轮扫描重试
            if not content.strip():
                logger.warning(f"文件 {csv_file.name} 内容为空，可能正在写入，跳过本次扫描")
                continue

            ready_files.append((csv_file, content))
        if not ready_files:
            return

        # 导入文件；失败时不写导入记录，等待下轮扫描重试
        async with get_async_session() as session:
            for csv_file, content in ready_files:
                try:
                    await self.import_csv(content, csv_file.name, mode="replace")
                except Exception:
                    logger.exception("导入文件 {} 时出错", csv_file.name)
                    continue

                # 导入成功后写入导入记录
                record = OrderFile(
                    account_id=self.config.account_id,
                    file_name=csv_file.name,
                    file_path=str(csv_file.parent),
                    file_hash=hashlib.md5(content.encode("utf-8")).hexdigest(),
                    created_at=datetime.now(),
                )
                session.add(record)
                logger.info(f"文件 {csv_file.name} 导入记录已保存")

    async def execute_position_rotation(
        self, trading_type: str = "", is_manual: bool = False
    ) -> None:
        """
        执行换仓逻辑（使用OrderCmd）

        Args:
            trading_type: 交易类型
            is_manual: 是否手动换仓
        """
        if self.working:
            logger.info("换仓任务已在进行中，跳过")
            return
        self.working = True
        self._stop_requested = False
        self.is_manual = is_manual
        logger.info(f"开始换仓, 手动: {is_manual}")

        todo_instructions = [
            x
            for x in self.get_today_instructions()
            if x.status != "COMPLETED"
            and x.enabled
            and x.is_deleted == False  # noqa: E712
            and x.account_id == self.config.account_id
        ]
        if not todo_instructions:
            logger.info("今日无换仓指令")
            self.working = False
            return
        logger.info(f"获取到 {len(todo_instructions)} 条可执行换仓指令")

        try:
            # 重置所有指令状态
            for instruction in todo_instructions:
                if instruction.filled_volume >= instruction.volume:
                    instruction.status = "COMPLETED"

                if instruction.status != "COMPLETED":
                    instruction.status = "PENDING"
                    instruction.error_message = None
                    instruction.current_order_id = None

            # 为每个指令创建OrderCmd
            # 平仓/平今排在前面，优先释放保证金与持仓
            todo_instructions.sort(key=lambda inst: 0 if inst.offset != "OPEN" else 1)

            # 单笔最大拆单手数（未配置风控时用默认值5）
            max_split_volume = (
                self.config.trading.risk_control.max_split_volume
                if self.config.trading and self.config.trading.risk_control
                else 5
            )

            for instruction in todo_instructions:
                if instruction.status != "PENDING":
                    continue

                # 检查是否满足换仓时间
                if not self._check_instruction(instruction, is_manual):
                    continue

                # 创建报单指令
                price = (
                    float(instruction.price)
                    if instruction.price and instruction.price > 0
                    else None
                )
                order_cmd: OrderCmd = OrderCmd(
                    symbol=instruction.symbol,
                    direction=Direction(instruction.direction),
                    offset=Offset(instruction.offset),
                    volume=instruction.remaining_volume,
                    price=price,
                    max_volume_per_order=max_split_volume,
                    order_interval=1,
                    total_timeout=180,  # 总超时为单笔超时的10倍
                    order_timeout=10,
                    slip=1,
                    source=f"换仓:{instruction.symbol}",
                    on_change=self._on_cmd_changed,
                )
                self.trading_engine.insert_order_cmd(order_cmd)
                if order_cmd:
                    instruction.current_order_id = order_cmd.cmd_id
                    instruction.status = "RUNNING"
                    instruction.order_placed_time = datetime.now()
                    logger.info(f"为指令 {instruction.symbol} 创建报单指令: {order_cmd.cmd_id}")

            # 监控OrderCmd执行状态
            await self._monitor_order_commands(todo_instructions)

        except Exception:
            logger.exception("换仓执行时出错")
        finally:
            snapshots = [self._snapshot_instruction(inst) for inst in todo_instructions]
            await self._update_instructions(snapshots)
            self.working = False
            logger.info("换仓任务结束")

    def _on_cmd_changed(self, order_cmd: OrderCmd) -> None:
        """处理订单状态变化"""
        if not order_cmd.is_finished:
            return

        pass

    async def _monitor_order_commands(
        self,
        instructions: list[RotationInstructionPo],
    ) -> None:
        """
        监控OrderCmd执行状态

        Args:
            instructions: 所有换仓指令
        """
        active_instructions = [inst for inst in instructions if inst.status == "RUNNING"]
        if not active_instructions:
            logger.info("没有活动的报单指令")
            return

        logger.info(f"开始监控 {len(active_instructions)} 个报单指令...")
        check_interval = 2.0  # 每2秒检查一次
        max_wait_time = 600  # 最大等待时间10分钟
        start_time = time.time()
        stopped = False

        while True:
            # 检查总超时
            if time.time() - start_time > max_wait_time:
                logger.warning("换仓监控超时，强制退出")
                break

            # 检查停止请求
            if self._stop_requested and not stopped:
                logger.info("收到停止换仓请求，正在取消所有报单指令...")
                for instruction in active_instructions:
                    cmd_id = instruction.current_order_id
                    if cmd_id:
                        await self.trading_engine.cancel_order_cmd(cmd_id)
                stopped = True
                self._stop_requested = False

            # 检查所有指令状态
            all_finished = True
            for instruction in active_instructions:
                cmd_id = instruction.current_order_id
                if not cmd_id:
                    continue

                # 获取OrderCmd状态
                cmd = self.trading_engine.get_order_cmd(cmd_id)
                if cmd is None:
                    logger.warning(f"未找到OrderCmd: {cmd_id}")
                    continue

                # 实时更新成交手数
                # OrderCmd 的 filled_volume 只代表本次执行的成交
                # 通过 instruction.volume - OrderCmd.remaining_volume 计算累计成交
                instruction.filled_volume = instruction.volume - cmd["remaining_volume"]
                instruction.remaining_volume = cmd["remaining_volume"]

                if cmd["is_active"]:
                    # 指令仍在运行
                    all_finished = False
                else:
                    # 指令已结束
                    finish_reason = cmd.get("finish_reason")
                    if finish_reason == OrderCmdFinishReason.ALL_COMPLETED:
                        instruction.status = "COMPLETED"
                    else:
                        instruction.status = "FAILED"
                        instruction.error_message = finish_reason
                    instruction.current_order_id = None

            # 每次循环都更新数据库，确保前端能实时看到进度
            snapshots = [self._snapshot_instruction(inst) for inst in active_instructions]
            await self._update_instructions(snapshots)

            # 检查是否全部完成
            if all_finished:
                logger.info("所有报单指令已完成")
                break

            await asyncio.sleep(check_interval)

        # 清理已完成的OrderCmd
        # self.trading_engine.cleanup_finished_order_cmds()

    @staticmethod
    def _snapshot_instruction(instruction: RotationInstructionPo) -> dict[str, Any]:
        """
        提取指令待更新字段的快照

        监控循环会持续改写 PO 对象，写库时直接 merge PO 会并发读写同一对象，
        先提取快照，写库只处理不可变数据。
        """
        return {
            "id": instruction.id,
            "status": instruction.status,
            "filled_volume": instruction.filled_volume,
            "remaining_volume": instruction.remaining_volume,
            "error_message": instruction.error_message,
            "current_order_id": instruction.current_order_id,
            "order_placed_time": instruction.order_placed_time,
            "updated_at": datetime.now(),
        }

    @logger.catch(message="更新指令状态时出错")
    async def _update_instructions(self, snapshots: list[dict[str, Any]]) -> None:
        """
        更新指令状态（接收 _snapshot_instruction 生成的快照，按 id 批量更新）

        Args:
            snapshots: 指令字段快照列表
        """
        if not snapshots:
            return

        async with get_async_session() as session:
            for snap in snapshots:
                values = {k: v for k, v in snap.items() if k != "id"}
                await session.execute(
                    update(RotationInstructionPo)
                    .where(RotationInstructionPo.id == snap["id"])
                    .values(**values)
                )

    def _check_instruction(
        self, instruction: RotationInstructionPo, is_manual: bool = False
    ) -> bool:
        """
        检查指令是否可以执行

        Args:
            instruction: 待检查的指令
            is_manual: 是否手动换仓

        Returns:
            是否可以执行
        """
        try:
            if not instruction.enabled:
                return False

            if instruction.status in ("COMPLETED", "FAILED"):
                return False

            if instruction.remaining_volume <= 0:
                return False

            if not is_manual:
                # 不满足换仓时间
                now_time = datetime.now().strftime("%H:%M:%S")
                if instruction.order_time and instruction.order_time > now_time:
                    return False

        except Exception:
            logger.exception("检查指令状态时出错")

        return True

    @logger.catch(message="更新指令状态时出错")
    async def _update_instruction(self, instruction: RotationInstructionPo) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        async with get_async_session() as session:
            await session.merge(instruction)
