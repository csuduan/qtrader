"""
订单文件扫描器和持仓管理器
扫描指定目录中的CSV订单文件并执行交易指令
执行换仓逻辑
"""

import csv
import os
import shutil
import time
import asyncio
from datetime import datetime
from gc import enable
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import True_
from sqlalchemy.orm import Session as SQLASession

from src.models.object import OrderCmdFinishReason
from src.models.po import RotationInstructionPo
from src.models.po import SwitchPosImportPo as OrderFile
from src.trader.trading_engine import TradingEngine
from src.trader.order_cmd import OrderCmd, SplitStrategyType
from src.utils.config_loader import AppConfig, TraderConfig
from src.utils.database import get_session
from src.utils.helpers import parse_symbol
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Type alias for Session that can be None
OptionalSession = Optional[SQLASession]


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
        order_time: Optional[str],
    ):
        self.symbol = symbol  # 合约代码，如 "SHFE.rb2505"
        self.exchange_id = exchange_id  # 交易所代码，如 "SHFE"
        self.offset = offset  # 开平类型: OPEN/CLOSE/CLOSETODAY
        self.direction = direction  # 买卖方向: BUY/SELL
        self.volume = volume  # 手数
        self.price = price  # 价格（0表示使用对手价）
        self.order_time = order_time  # 报单时间（格式HH:MM:SS，空则不限制）

    def __repr__(self):
        return (
            f"OrderInstruction(symbol={self.symbol}, direction={self.direction}, "
            f"offset={self.offset}, volume={self.volume}, price={self.price})"
        )


class SwitchPosManager:
    """换仓管理器，负责换仓逻辑"""

    def __init__(self, config: Any, trading_engine: TradingEngine):
        """
        初始化持仓管理器

        Args:
            config: 应用配置（AppConfig 或 AccountConfig）
            trading_engine: 交易引擎实例
        """
        self.config: TraderConfig = config
        self.trading_engine = trading_engine
        self.switchPos_files_dir = config.paths.switchPos_files
        self.working = False
        self.running_instructions: Optional[List[RotationInstructionPo]] = None
        self.is_manual = False

    def start(self):
        """启动换仓管理器"""
        pass

    def import_csv(self, csv_text: str, filename: str, mode: str = "replace"):
        """
        导入换仓指令文件

        Args:
            file_path: 换仓指令文件路径
        """
        try:
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
                import re

                matchs = re.findall(r"\d{8}", filename)
                if matchs:
                    trading_date = matchs[0]
                    logger.info(f"从文件名提取交易日: {trading_date}")
                else:
                    raise ValueError(f"文件名格式错误，无法提取交易日: {filename}")

            session = get_session()
            if session is None:
                logger.error("无法获取数据库会话")
                raise RuntimeError("无法获取数据库会话")
            for line_num, line in enumerate(lines[1:], start=2):
                try:
                    values = line.strip().split(",")
                    if len(values) < 6:
                        logger.warning(f"第{line_num}行数据不完整，跳过: {line}")
                        failed_count += 1
                        continue

                    account_id = values[0].strip()
                    strategy_id = values[1].strip()
                    instrument_str = values[2].strip()
                    offset_str = values[3].strip()
                    direction_str = values[4].strip()
                    volume_str = values[5].strip()
                    order_time_str = values[6].strip() if len(values) > 6 else None

                    if not account_id or not strategy_id or not instrument_str:
                        logger.warning(f"第{line_num}行缺少必要字段，跳过")
                        failed_count += 1
                        continue

                    instrument_str = instrument_str.replace(" ", "")

                    if "." not in instrument_str:
                        logger.warning(f"第{line_num}行合约格式错误: {instrument_str}")
                        failed_count += 1
                        continue
                    symbol = instrument_str

                    offset_map = {"Open": "OPEN", "Close": "CLOSE", "开仓": "OPEN", "平仓": "CLOSE"}
                    direction_map = {"Buy": "BUY", "Sell": "SELL", "买入": "BUY", "卖出": "SELL"}

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

                    if mode == "replace" and trading_date:
                        # 替换模式下，将相同交易日的旧记录设为已删除
                        session.query(RotationInstructionPo).filter_by(
                            trading_date=trading_date
                        ).update({"is_deleted": True})

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

                    session.add(instruction)
                    imported_count += 1

                except Exception as e:
                    logger.error(f"第{line_num}行解析失败: {e}, 内容: {line}")
                    failed_count += 1
                    errors.append({"row": line_num, "error": str(e), "content": line})
                    session.rollback()
                    continue

            session.commit()
            logger.info(f"CSV导入完成，成功: {imported_count}, 失败: {failed_count}")

            # 对导入的合约进行订阅
            self.subscribe_today_symbols()

            data = {"imported": imported_count, "failed": failed_count, "errors": errors[:10]}
            return data
        except Exception as e:
            raise Exception(f"导入文件失败{e}")

    def subscribe_today_symbols(self) -> None:
        """订阅今日换仓记录中的所有合约"""
        try:
            session = get_session()
            if not session:
                logger.error("无法获取数据库会话")
                return

            today = datetime.now().strftime("%Y%m%d")
            instructions = (
                session.query(RotationInstructionPo)
                .filter(
                    RotationInstructionPo.trading_date == today,
                    RotationInstructionPo.is_deleted == False,
                    RotationInstructionPo.enabled == True,
                )
                .all()
            )

            if not instructions:
                logger.info("今日无换仓记录，无需订阅合约")
                return

            symbols = [instruction.symbol for instruction in instructions]
            self.trading_engine.subscribe_symbol(symbols)
            logger.info(f"换仓管理器订阅换仓合约完成")

        except Exception as e:
            logger.error(f"订阅今日换仓合约时出错: {e}")
        finally:
            session.close()

    def scan_and_process_orders(self) -> None:
        """扫描并处理交易指令文件"""
        try:
            today_dir = Path(self.switchPos_files_dir) / datetime.now().strftime("%Y%m%d")
            today_str = datetime.now().strftime("%Y%m%d")
            csv_files = [
                f
                for f in today_dir.glob("*.csv")
                if today_str in f.name and self.config.account_id in f.name
            ]
            if not csv_files:
                return

            # logger.info(f"扫描到 {len(csv_files)} 个换仓文件")
            session = get_session()
            for csv_file in csv_files:
                # 检查该文件是否已导入
                existing = session.query(OrderFile).filter_by(file_name=csv_file.name).first()
                if existing:
                    continue

                # 导入文件
                result = self.import_csv(
                    csv_file.read_text(encoding="gbk"), csv_file.name, mode="replace"
                )
                # 记录导入成功，写入导入记录
                if result and result.get("imported", 0) > 0:
                    record = OrderFile(
                        file_name=csv_file.name,
                        file_path=str(csv_file.parent),
                        created_at=datetime.now(),
                    )
                    session.add(record)
                    session.commit()
                    logger.info(f"文件 {csv_file.name} 导入记录已保存")

        except Exception as e:
            logger.error(f"扫描订单文件时出错: {e}")

    async def execute_position_rotation(self, trading_type: str = "", is_manual: bool = False) -> None:
        """
        执行换仓逻辑（使用OrderCmd）

        Args:
            is_manual: 是否手动换仓
        """
        if self.working:
            logger.info("换仓任务已在进行中，跳过")
            return
        self.working = True
        self.is_manual = is_manual
        logger.info(f"开始换仓, 手动: {is_manual}")

        all_instructions = self._get_all_instructions()
        self.running_instructions = all_instructions
        if not all_instructions:
            logger.info("今日无换仓指令")
            self.working = False
            return
        logger.info(f"获取到 {len(all_instructions)} 条可执行换仓指令")

        try:
            # 重置所有指令状态
            for instruction in all_instructions:
                if instruction.filled_volume >= instruction.volume:
                    instruction.status = "COMPLETED"

                if instruction.status not in ("COMPLETED"):
                    instruction.status = "PENDING"
                    instruction.error_message = None
                    instruction.current_order_id = None

            # 为每个指令创建OrderCmd
            for instruction in all_instructions:
                if instruction.status != "PENDING":
                    continue

                # 检查是否满足换仓时间
                if not self._check_instruction(instruction, is_manual):
                    continue

                # 创建报单指令
                price = instruction.price if instruction.price and instruction.price > 0 else None
                order_cmd: OrderCmd = OrderCmd(
                    symbol=instruction.symbol,
                    direction=instruction.direction,
                    offset=instruction.offset,
                    volume=instruction.remaining_volume,
                    price=price,
                    max_volume_per_order=self.config.trading.risk_control.max_split_volume,
                    order_interval=0.5,
                    total_timeout=self.config.trading.risk_control.order_timeout * 10,  # 总超时为单笔超时的10倍
                    order_timeout=self.config.trading.risk_control.order_timeout,
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
            #self._monitor_order_commands(all_instructions)
            await asyncio.to_thread(self._monitor_order_commands, all_instructions)

        except Exception as e:
            logger.exception(f"换仓执行时出错: {e}")
        finally:
            self._update_instructions(all_instructions)
            self.working = False
            logger.info("换仓任务结束")

    def _on_cmd_changed(self, order_cmd: OrderCmd):
        """处理订单状态变化"""
        if not order_cmd.is_finished:
            return

        pass

    def _monitor_order_commands(
        self,
        instructions: List[RotationInstructionPo],
    ) -> None:
        """
        监控OrderCmd执行状态

        Args:
            instructions: 所有换仓指令
            cmd_map: 指令symbol到cmd_id的映射
            is_manual: 是否手动换仓
        """
        active_instructions = [inst for inst in instructions if inst.status == "RUNNING"]
        if not active_instructions:
            logger.info("没有活动的报单指令")
            return

        logger.info(f"开始监控 {len(active_instructions)} 个报单指令...")
        check_interval = 2.0  # 每2秒检查一次
        max_wait_time = 600  # 最大等待时间10分钟
        start_time = time.time()

        while True:
            # 检查总超时
            if time.time() - start_time > max_wait_time:
                logger.warning("换仓监控超时，强制退出")
                break

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

                if cmd["is_active"]:
                    # 指令仍在运行
                    all_finished = False
                    # 更新已成交手数
                    # instruction.filled_volume = cmd["filled_volume"]
                    # instruction.remaining_volume = cmd["remaining_volume"]

                else:
                    # 指令已结束
                    finish_reason = cmd.get("finish_reason")
                    filled = cmd["filled_volume"]
                    instruction.filled_volume += filled
                    instruction.remaining_volume -= filled
                    if finish_reason == OrderCmdFinishReason.ALL_COMPLETED:
                        instruction.status = "COMPLETED"
                    else:
                        instruction.status = "FAILED"
                        instruction.error_message = finish_reason
                    instruction.current_order_id = None

            # 更新数据库
            self._update_instructions(active_instructions)

            # 检查是否全部完成
            if all_finished:
                logger.info("所有报单指令已完成")
                break

            time.sleep(check_interval)

        # 清理已完成的OrderCmd
        self.trading_engine.cleanup_finished_order_cmds()

    def _update_instructions(self, instructions: List[RotationInstructionPo]) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        session = get_session()
        if not session:
            return

        try:
            for instruction in instructions:
                session.merge(instruction)
            session.commit()
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")
            session.rollback()

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

        except Exception as e:
            logger.error(f"检查指令状态时出错: {e}")

        return True

    def _get_all_instructions(self) -> List[RotationInstructionPo]:
        """
        获取所有指令列表

        Returns:
            List[RotationInstructionPo]: 所有指令列表
        """
        session = get_session()
        if not session:
            return []

        try:
            today = datetime.now().strftime("%Y%m%d")
            instructions = (
                session.query(RotationInstructionPo)
                .filter(
                    RotationInstructionPo.status != "COMPLETED",
                    RotationInstructionPo.trading_date == today,
                    RotationInstructionPo.is_deleted == False,
                    RotationInstructionPo.enabled == True,
                )
                .all()
            )
            return instructions
        except Exception as e:
            logger.error(f"获取所有指令列表时出错: {e}")
            return []
        finally:
            session.close()

    def _update_instruction(self, instruction: RotationInstructionPo) -> None:
        """
        更新指令状态

        Args:
            instruction: 待更新的指令
        """
        session = get_session()
        if not session:
            return

        try:
            session.merge(instruction)
            session.commit()
        except Exception as e:
            logger.error(f"更新指令状态时出错: {e}")
        finally:
            session.close()


    def _load_all_instructions(self) -> List[OrderInstruction]:
        """
        加载所有交易指令

        Returns:
            List[OrderInstruction]: 订单指令列表
        """
        instructions = []

        try:
            csv_files = list(Path(self.switchPos_files_dir).glob("*.csv"))

            for csv_file in csv_files:
                instructions.extend(self._parse_csv_file(csv_file))

            return instructions

        except Exception as e:
            logger.error(f"加载交易指令时出错: {e}")
            return []

    def _parse_csv_file(self, file_path: Path) -> List[OrderInstruction]:
        """
        解析CSV订单文件

        Args:
            file_path: 文件路径

        Returns:
            List[OrderInstruction]: 订单指令列表
        """
        instructions = []

        try:
            with open(file_path, "r", encoding="gbk") as f:
                reader = csv.DictReader(f)

                required_columns = [
                    "实盘账户",
                    "合约代码",
                    "交易所代码",
                    "开平类型",
                    "买卖方向",
                    "手数",
                    "价格",
                ]
                for col in required_columns:
                    if col not in reader.fieldnames or []:
                        logger.error(f"CSV文件缺少必需的列: {col}")
                        return []

                for row in reader:
                    try:
                        symbol = row["实盘账户"].strip()
                        exchange_id = row["交易所代码"].strip()
                        offset = row["开平类型"].strip().upper()
                        direction = row["买卖方向"].strip().upper()
                        volume = int(row["手数"])
                        price_str = row["价格"].strip()
                        order_time = row.get("报单时间", "").strip() or None

                        if offset not in ("OPEN", "CLOSE", "CLOSETODAY"):
                            continue

                        if direction not in ("BUY", "SELL"):
                            continue

                        if volume <= 0:
                            continue

                        price = 0
                        if price_str and price_str != "0":
                            try:
                                price = float(price_str)
                            except ValueError:
                                price = 0

                        instruction = OrderInstruction(
                            symbol=symbol,
                            exchange_id=exchange_id,
                            offset=offset,
                            direction=direction,
                            volume=volume,
                            price=price,
                            order_time=order_time,
                        )
                        instructions.append(instruction)

                    except Exception as e:
                        logger.warning(f"解析行失败: {e}，跳过")

            return instructions

        except Exception as e:
            logger.error(f"读取CSV文件失败: {e}")
            return []
