"""
ASYM 股指择时策略

信号：早盘窗口（09:31-11:30，结束时刻口径）结束后计算
    ASYM = ln(H / O) + ln(L / O)
O 为窗口首根分钟线开盘价，H/L 为窗口最高/最低价。
IC：ASYM > +0.004 做多，ASYM < -0.006 做空；
IM：ASYM > +0.006 做多，ASYM < -0.008 做空；
其余情况（含刚好等于阈值）当日不新增批次。

建仓/退出：信号日 13:35 按信号新建一批（权重±0.5，实际手数由 volume 参数配置），
下一交易日 14:55 到期在原入场合约平仓（换月后新旧批次可分属不同合约）。
同一合约同向批次叠仓、反向批次按净额抵消，由分合约持仓自然体现。

系统 M1 为开始时刻标记，与交付口径（结束时刻标记）对应关系：
- 早盘窗口 09:31-11:30 ↔ 系统bar 09:30-11:29
- 13:35 建仓时点 ↔ 13:34 bar 收盘
- 14:55 退出时点 ↔ 14:54 bar 收盘

批次状态持久化在 system_params 表（key: asym_batches.{strategy_id}），重启后恢复；
"下一交易日到期"由每日策略重置（init）自然推进，周末/节假日自动顺延，无需交易日历。
"""

import asyncio
import json
import math
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from qtrader.models.object import BarData, Direction, Offset
from qtrader.models.po import SystemParamPo
from qtrader.trader.order_cmd import OrderCmd
from qtrader.trader.strategy.base_strategy import BaseParam, BaseStrategy
from qtrader.utils.async_database import fetch_one, get_async_session
from qtrader.utils.config_loader import StrategyConfig
from qtrader.utils.logger import get_logger

logger = get_logger(__name__)

# 早盘窗口（系统M1开始时刻口径）
MORNING_START_BAR = time(9, 30)  # 窗口首根（结束口径09:31）
MORNING_END_BAR = time(11, 29)  # 窗口末根（结束口径11:30）
MORNING_BARS = 120  # 早盘窗口完整M1根数
ENTRY_BAR = time(13, 34)  # 建仓触发bar（其收盘即13:35时点价）
EXIT_BAR = time(14, 54)  # 到期退出触发bar（其收盘即14:55时点价）

# 品种默认阈值：(做多阈值, 做空阈值幅度)
VARIETY_THRESHOLDS: dict[str, tuple[float, float]] = {
    "IC": (0.004, 0.006),
    "IM": (0.006, 0.008),
}


class AsymParam(BaseParam):
    """ASYM策略参数"""

    # 阈值配置为0时按品种默认值（IC: 0.004/0.006, IM: 0.006/0.008）
    asym_long_thr: float = Field(default=0.0, title="做多阈值")
    asym_short_thr: float = Field(default=0.0, title="做空阈值")


class AsymBatch(BaseModel):
    """ASYM持仓批次（每信号日一批，下一交易日14:55到期退出）"""

    entry_date: str  # 建仓交易日 YYYY-MM-DD
    symbol: str  # 建仓合约（到期时在该合约平仓）
    side: int  # 1多 -1空
    volume: int  # 批次手数（权重0.5换算结果）
    entry_price: float = 0.0  # 建仓信号价（13:35时点价，收益核对基准）
    entry_fill_price: float = 0.0  # 实际成交均价
    entry_cmd_id: str = ""
    status: str = "OPEN"  # OPEN/CLOSED
    exit_date: str = ""
    exit_price: float = 0.0  # 退出信号价（14:55时点价）
    exit_fill_price: float = 0.0  # 实际成交均价
    exit_cmd_id: str = ""


def asym_side(asym: float, long_thr: float, short_thr: float) -> int:
    """
    ASYM信号方向（严格大于/小于，等于阈值不新增批次）

    Args:
        asym: 当日上午ASYM值
        long_thr: 做多阈值（正数）
        short_thr: 做空阈值幅度（正数）

    Returns:
        方向 (1做多, -1做空, 0不新增)
    """
    if asym > long_thr:
        return 1
    if asym < -short_thr:
        return -1
    return 0


class AsymStrategy(BaseStrategy):
    """
    ASYM 股指择时策略

    IC/IM 各配置一个策略实例，独立计算信号和持仓。
    不走框架单信号模型（Signal/execute_signal），批次自行管理开平仓。
    """

    def __init__(self, strategy_id: str, strategy_config: StrategyConfig):
        super().__init__(strategy_id, strategy_config)
        self._batches: list[AsymBatch] = []
        self._long_thr: float = 0.0
        self._short_thr: float = 0.0
        self._reset_day_state()
        logger.info(f"ASYM策略 [{strategy_id}] 初始化完成")

    def _reset_day_state(self) -> None:
        """重置当日状态（早盘累积与信号，批次状态不受影响）"""
        self._m_open: float | None = None  # 早盘窗口首根开盘价
        self._m_high: float = 0.0
        self._m_low: float = 0.0
        self._m_count: int = 0  # 早盘窗口已收M1根数
        self._today_asym: float | None = None
        self._today_signal: int = 0
        self._signal_decided: bool = False

    async def init(self, trading_day: datetime) -> bool:
        """策略初始化：重置当日状态并从数据库恢复批次"""
        logger.info(f"策略 [{self.strategy_id}] 初始化...")
        self.inited = True
        self._pending_cmds = []
        self._hist_cmds = {}
        self.signal = None
        self.trading_day = trading_day

        if not self.config.params:
            self.enabled = False
            logger.error(f"策略 [{self.strategy_id}] 未配置参数")
            return False
        self.param: AsymParam = AsymParam(**self.config.params)
        self.symbol = self.param.symbol
        self.volume = self.param.volume

        self._resolve_thresholds()
        self._reset_day_state()
        await self._load_batches()

        due = self._due_batches()
        if due:
            logger.info(
                f"策略 [{self.strategy_id}] 今日14:55到期批次: "
                f"{[(b.entry_date, b.symbol, b.side, b.volume) for b in due]}"
            )
        logger.info(f"策略 [{self.strategy_id}] 初始化完成")
        return True

    def _resolve_thresholds(self) -> None:
        """解析阈值：参数优先，未配置（0）时按品种默认"""
        variety = "".join(ch for ch in self.symbol if ch.isalpha()).upper()
        default = VARIETY_THRESHOLDS.get(variety)
        self._long_thr = self.param.asym_long_thr or (default[0] if default else 0.0)
        self._short_thr = self.param.asym_short_thr or (default[1] if default else 0.0)
        if self._long_thr <= 0 or self._short_thr <= 0:
            logger.error(f"策略 [{self.strategy_id}] 未知品种 {variety} 且未配置阈值，信号停用")
        else:
            logger.info(f"策略 [{self.strategy_id}] ASYM阈值: +{self._long_thr}/-{self._short_thr}")

    def _today_str(self) -> str:
        """当前交易日字符串"""
        return self.trading_day.strftime("%Y-%m-%d") if self.trading_day else ""

    def _due_batches(self) -> list[AsymBatch]:
        """今日到期的OPEN批次（建仓日早于今日，周末/节假日由init自然顺延）"""
        today = self._today_str()
        return [b for b in self._batches if b.status == "OPEN" and b.entry_date < today]

    def _has_batch_today(self) -> bool:
        """今日是否已有批次（防止重复建仓/回播重复触发）"""
        return any(b.entry_date == self._today_str() for b in self._batches)

    def get_batches(self) -> list[dict[str, Any]]:
        """获取全部批次（对账回执用）"""
        return [b.model_dump() for b in self._batches]

    async def on_bar(self, bar: BarData) -> None:
        """K线行情回调（仅接收当前主力合约bar）"""
        try:
            if bar.symbol != self.symbol:
                return
            if self.trading_day is None or bar.datetime.date() != self.trading_day.date():
                return
            bar_time = bar.datetime.time()

            # 早盘窗口累积（09:30-11:29）
            if MORNING_START_BAR <= bar_time <= MORNING_END_BAR:
                if bar_time == MORNING_START_BAR:
                    self._m_open = bar.open_price
                    self._m_high = bar.high_price
                    self._m_low = bar.low_price
                    self._m_count = 0
                if self._m_open is not None:
                    self._m_high = max(self._m_high, bar.high_price)
                    self._m_low = min(self._m_low, bar.low_price)
                    self._m_count += 1

            # 早盘窗口结束后计算ASYM信号（每交易日一次）
            if not self._signal_decided and bar_time >= MORNING_END_BAR:
                self._decide_signal()

            # 13:35建仓（回播enabled=False不发单，批次由数据库恢复）
            if (
                self.enabled
                and self._today_signal != 0
                and bar_time >= ENTRY_BAR
                and not self._has_batch_today()
            ):
                await self._open_batch(bar)

            # 14:55到期批次退出（以当日主力bar为时钟，指令打到批次原合约）
            if bar_time >= EXIT_BAR and self.enabled:
                await self._exit_due_batches(bar)
        except Exception:
            logger.exception("策略 [{}] on_bar 异常", self.strategy_id)

    def _decide_signal(self) -> None:
        """早盘窗口结束，计算ASYM并判定当日信号"""
        self._signal_decided = True
        self._today_signal = 0
        self._resolve_thresholds()  # 参数热更新后重新解析
        if self._long_thr <= 0 or self._short_thr <= 0:
            logger.error(f"策略 [{self.strategy_id}] 阈值未配置，今日不新增批次")
            return
        if self._m_open is None or self._m_count < MORNING_BARS:
            logger.warning(
                f"策略 [{self.strategy_id}] 早盘数据不足"
                f"({self._m_count}/{MORNING_BARS})，今日不新增批次"
            )
            return
        asym = math.log(self._m_high / self._m_open) + math.log(self._m_low / self._m_open)
        self._today_asym = asym
        self._today_signal = asym_side(asym, self._long_thr, self._short_thr)
        logger.info(
            f"策略 [{self.strategy_id}] ASYM判定: O={self._m_open} H={self._m_high} "
            f"L={self._m_low} ASYM={asym:.6f} 阈值(+{self._long_thr}/-{self._short_thr}) "
            f"信号={self._today_signal}"
        )

    async def _open_batch(self, bar: BarData) -> None:
        """13:35按信号新建一批（当日主力合约）"""
        if bar.datetime.time() > ENTRY_BAR:
            logger.warning(
                f"策略 [{self.strategy_id}] 迟到建仓(bar={bar.datetime.time()})，"
                f"成交价将偏离13:35基准"
            )
        side = self._today_signal
        batch = AsymBatch(
            entry_date=self._today_str(),
            symbol=self.symbol,
            side=side,
            volume=self.volume,
            entry_price=bar.close_price,
        )
        cmd = OrderCmd(
            symbol=self.symbol,
            offset=Offset.OPEN,
            direction=Direction.BUY if side == 1 else Direction.SELL,
            volume=batch.volume,
            price=0,
        )
        batch.entry_cmd_id = cmd.cmd_id
        self._batches.append(batch)
        await self._save_batches()
        await self.send_order_cmds([cmd])
        logger.info(f"策略 [{self.strategy_id}] 新建批次: {batch}")

    async def _exit_due_batches(self, bar: BarData) -> None:
        """14:55退出到期批次（各批次在原入场合约平仓）"""
        due = self._due_batches()
        if not due:
            return
        today = self._today_str()
        quotes = self.trading_engine.quotes if self.trading_engine else {}
        cmds: list[OrderCmd] = []
        for batch in due:
            if batch.symbol != self.symbol and batch.symbol not in quotes:
                logger.error(
                    f"策略 [{self.strategy_id}] 旧合约退出行情缺失: "
                    f"日期={today} 合约={batch.symbol}，请人工核对退出价"
                )
            if batch.symbol == self.symbol:
                exit_price = bar.close_price
            else:
                tick = quotes.get(batch.symbol)
                exit_price = (tick.last_price or 0.0) if tick else 0.0
            cmd = OrderCmd(
                symbol=batch.symbol,
                offset=Offset.CLOSE,
                direction=Direction.SELL if batch.side == 1 else Direction.BUY,
                volume=batch.volume,
                price=0,
            )
            batch.status = "CLOSED"
            batch.exit_date = today
            batch.exit_price = exit_price
            batch.exit_cmd_id = cmd.cmd_id
            cmds.append(cmd)
            logger.info(f"策略 [{self.strategy_id}] 批次到期退出: {batch}")
        await self._save_batches()
        await self.send_order_cmds(cmds)

    def _on_cmd_change(self, cmd: OrderCmd) -> None:
        """指令完成时回填批次实际成交均价（收益核对用）"""
        super()._on_cmd_change(cmd)
        if not cmd.is_finished or cmd.filled_volume <= 0:
            return
        for batch in self._batches:
            if batch.entry_cmd_id == cmd.cmd_id and batch.entry_fill_price != cmd.filled_price:
                batch.entry_fill_price = cmd.filled_price
                self._save_batches_bg()
            elif batch.exit_cmd_id == cmd.cmd_id and batch.exit_fill_price != cmd.filled_price:
                batch.exit_fill_price = cmd.filled_price
                self._save_batches_bg()

    async def close_stale_positions(self) -> None:
        """平遗留持仓：OPEN批次覆盖的旧合约属正常隔夜持仓，不在此平仓"""
        protected_symbols = {
            b.symbol for b in self._batches if b.status == "OPEN" and b.symbol != self.symbol
        }
        protected = {s: self._positions.pop(s) for s in protected_symbols if s in self._positions}
        if protected:
            logger.info(
                f"策略 [{self.strategy_id}] OPEN批次覆盖的旧合约持仓不平: {list(protected)}"
            )
        try:
            await super().close_stale_positions()
        finally:
            self._positions.update(protected)

    def _on_symbol_changed(self, old_symbol: str) -> None:
        """换月清理当日早盘累积（信号口径要求当天主力行情，不可新旧合约混算）"""
        self._reset_day_state()
        logger.warning(
            f"策略 [{self.strategy_id}] 换月 {old_symbol} -> {self.symbol}，"
            f"当日早盘数据已清空，如需当日信号请回播新主力行情；"
            f"存量批次仍在原入场合约到期退出"
        )

    # ==================== 批次持久化（system_params KV） ====================

    def _batches_key(self) -> str:
        return f"asym_batches.{self.strategy_id}"

    def _account_id(self) -> str | None:
        if self.strategy_manager and self.strategy_manager.trading_engine:
            return self.strategy_manager.trading_engine.account_id
        return None

    async def _load_batches(self) -> None:
        """从数据库恢复批次状态"""
        self._batches = []
        account_id = self._account_id()
        if not account_id:
            return
        try:
            async with get_async_session() as session:
                row = await fetch_one(
                    session,
                    select(SystemParamPo).filter(
                        SystemParamPo.account_id == account_id,
                        SystemParamPo.param_key == self._batches_key(),
                    ),
                )
                if row and row.param_value:
                    self._batches = [AsymBatch(**d) for d in json.loads(row.param_value)]
                    open_count = sum(1 for b in self._batches if b.status == "OPEN")
                    logger.info(
                        f"策略 [{self.strategy_id}] 恢复批次 {len(self._batches)} 条"
                        f"（OPEN {open_count}）"
                    )
        except Exception:
            logger.exception("策略 [{}] 加载批次失败", self.strategy_id)

    async def _save_batches(self) -> None:
        """持久化批次状态到system_params"""
        account_id = self._account_id()
        if not account_id:
            return
        payload = json.dumps([b.model_dump() for b in self._batches], ensure_ascii=False)
        try:
            async with get_async_session() as session:
                row = await fetch_one(
                    session,
                    select(SystemParamPo).filter(
                        SystemParamPo.account_id == account_id,
                        SystemParamPo.param_key == self._batches_key(),
                    ),
                )
                if row:
                    row.param_value = payload
                else:
                    session.add(
                        SystemParamPo(
                            account_id=account_id,
                            param_key=self._batches_key(),
                            param_value=payload,
                            param_type="json",
                            group="strategy",
                            description=f"ASYM策略 [{self.strategy_id}] 批次状态",
                        )
                    )
        except Exception:
            logger.exception("策略 [{}] 保存批次失败", self.strategy_id)

    def _save_batches_bg(self) -> None:
        """后台异步保存批次（供同步回调使用）"""
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._save_batches())
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            logger.warning(f"策略 [{self.strategy_id}] 无事件循环，跳过批次保存")
