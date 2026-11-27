"""
策略盘中指标采集器

在策略 on_bar 过程中写入当日关键指标数据（M1 bar、RSI值、高波判定快照、
信号开平仓事件），init 时重置，仅保留当前交易日数据。
Manager 通过 IPC 查询后供前端画指标走势图，用于解释信号产生原因。
"""

from datetime import datetime
from typing import Any

from qtrader.models.object import BarData


class IndicatorManager:
    """RSI策略盘中指标采集器（内存态，不持久化）"""

    def __init__(self) -> None:
        self.active: bool = False
        self.trading_day: str = ""
        self.symbol: str = ""
        self.mode: int = 0
        self.params: dict[str, Any] = {}
        self.bars: list[dict[str, Any]] = []
        self.hv: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []

    def reset(self, trading_day: datetime, symbol: str, mode: int, params: dict[str, Any]) -> None:
        """重置采集器（策略init/回播时调用，随后由on_bar重建当日数据）"""
        self.active = True
        self.trading_day = trading_day.strftime("%Y-%m-%d")
        self.symbol = symbol
        self.mode = mode
        self.params = params
        self.bars = []
        self.hv = {}
        self.events = []

    def clear(self) -> None:
        """清空数据并停用（换月等场景，待重新init后恢复采集）"""
        self.active = False
        self.bars = []
        self.hv = {}
        self.events = []

    def record_bar(
        self, bar: BarData, rsi_short: float | None = None, rsi_long: float | None = None
    ) -> None:
        """记录一根当日M1 bar及该时点RSI值（RSI仅在短周期K线形成时非空）"""
        if not self.active:
            return
        point = {
            "time": bar.datetime.strftime("%H:%M"),
            "open": bar.open_price,
            "high": bar.high_price,
            "low": bar.low_price,
            "close": bar.close_price,
            "rsi_short": round(rsi_short, 2) if rsi_short is not None else None,
            "rsi_long": round(rsi_long, 2) if rsi_long is not None else None,
        }
        # 回播与实时行情可能重叠，同一分钟覆盖而非重复追加
        if self.bars and self.bars[-1]["time"] == point["time"]:
            self.bars[-1] = point
        else:
            self.bars.append(point)

    def update_hv(self, **fields: Any) -> None:
        """更新高波模式判定快照（昨收/今开/09:45判定结果等）"""
        if not self.active:
            return
        self.hv.update(fields)

    def record_event(
        self, t: str, event_type: str, side: int, price: float, reason: str = ""
    ) -> None:
        """记录信号事件（ENTRY开信号/EXIT信号结束）"""
        if not self.active:
            return
        self.events.append(
            {"time": t, "type": event_type, "side": side, "price": price, "reason": reason}
        )

    def to_dict(self) -> dict[str, Any] | None:
        """导出指标数据（未初始化返回None）"""
        if not self.active:
            return None
        return {
            "trading_day": self.trading_day,
            "symbol": self.symbol,
            "mode": self.mode,
            "params": self.params,
            "bars": self.bars,
            "hv": self.hv or None,
            "events": self.events,
        }
