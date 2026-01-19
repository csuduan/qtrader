"""
交易引擎核心模块
使用TradingAdapter接口支持多种交易接口
"""
import asyncio
import math
from datetime import datetime
import time
from typing import Any, Dict, List, Optional
from threading import Thread

from src.config_loader import AppConfig
from src.risk_control import RiskControl
from src.utils.logger import get_logger
from src.utils.event import event_engine, EventTypes


logger = get_logger(__name__)


class TradingEngine:
    """交易引擎类"""

    def __init__(self, config: AppConfig):
        """
        初始化交易引擎

        Args:
            config: 应用配置对象
        """
        self.config = config
        self.account_id = config.account_id
        self.adapter: Optional["TradingAdapter"] = None
        self.connected = False
        self.paused = config.trading.paused
        self._running = False
        self._pending_disconnect = False

        self.quotes: Dict[str, Any] = {}
        self.positions: Dict[str, Any] = {}
        self.orders: Dict[str, Any] = {}
        self.trades: Dict[str, Any] = {}

        self.risk_control = RiskControl(config.risk_control)
        self.event_engine = event_engine

        logger.info(f"交易引擎初始化完成，账户类型: {config.account_type}")

    def reload_risk_control_config(self):
        """
        从数据库重新加载风控配置
        """
        try:
            from src.param_loader import load_risk_control_config
            new_config = load_risk_control_config()
            self.risk_control.config = new_config
            logger.info("风控配置已从数据库重新加载")
        except Exception as e:
            logger.error(f"重新加载风控配置失败: {e}", exc_info=True)

    def _create_adapter(self) -> "TradingAdapter":
        """
        根据配置创建对应的适配器

        Returns:
            TradingAdapter: 交易接口适配器
        """
        interface_type = getattr(self.config, "interface", "tqsdk")

        if interface_type == "tqsdk":
            from src.adapters.tqsdk_adapter import TqSdkAdapter

            return TqSdkAdapter(
                account_type=self.config.account_type,
                account_id=self.config.account_id,
                tianqin_username=self.config.tianqin.username,
                tianqin_password=self.config.tianqin.password,
                trading_account_config={
                    "broker_name": self.config.trading_account.broker_name,
                    "user_id": self.config.trading_account.user_id,
                    "password": self.config.trading_account.password,
                } if self.config.trading_account else None,
            )
        elif interface_type == "ctp":
            from src.adapters.ctp_adapter import CtpAdapter

            ctp_config = getattr(self.config, "ctp_config", None)
            if not ctp_config:
                raise ValueError("CTP接口需要配置 ctp_config")

            return CtpAdapter(
                account_id=self.config.account_id,
                broker_id=ctp_config.get("broker_id", ""),
                investor_id=ctp_config.get("investor_id", ""),
                password=ctp_config.get("password", ""),
                front_addresses=ctp_config.get("front_addresses", []),
            )
        else:
            raise ValueError(f"不支持的接口类型: {interface_type}")

    def connect(self) -> bool:
        """
        连接到交易接口

        Returns:
            bool: 连接是否成功
        """
        try:
            logger.info(f"连接到交易接口: {getattr(self.config, 'interface', 'tqsdk')}")

            self.adapter = self._create_adapter()

            if not self.adapter.connect():
                logger.error("连接失败")
                return False

            self.connected = True
            self._running = True

            account_info = self.adapter.get_account()
            logger.info(f"成功连接，账户ID: {self.config.account_id}")

            self.positions = self.adapter.get_position()
            logger.info(f"成功获取持仓信息: {len(self.positions)}条")

            self.trades = self.adapter.get_trade()
            logger.info(f"成功获取成交记录: {len(self.trades)}条")

            self.orders = self.adapter.get_order()
            logger.info(f"成功获取挂单信息: {len(self.orders)}条")

            self._init_risk_counts_from_orders()

            logger.info("正在从数据库加载风控配置...")
            self.reload_risk_control_config()

            quote_list = self.adapter.query_quotes(ins_class=["FUTURE"], expired=False)
            self.symbols = {symbol.split(".")[1]: symbol.split(".")[0] for symbol in quote_list}
            self.upper_symbols = {symbol.split(".")[1].upper(): symbol for symbol in quote_list}
            logger.info(f"成功查询到{len(quote_list)}个合约")

            self._init_subscriptions()

            self._emit_event(EventTypes.ACCOUNT_STATUS, {
                "account_id": self.config.account_id,
                "account_type": self.config.account_type,
                "status": "connected",
            })

            self.loop_thread = Thread(target=self.loop_run, daemon=True)
            self.loop_thread.start()
            return True

        except Exception as e:
            logger.error(f"连接失败: {e}")
            self.connected = False
            return False

    def loop_run(self) -> None:
        """主循环运行"""
        while self._running:
            try:
                if self._pending_disconnect:
                    self._do_disconnect()
                    break

                self.update()
            except Exception as e:
                logger.error(f"主循环更新出错: {e}")

    def disconnect(self) -> None:
        """请求断开连接（设置标志位，由主循环执行）"""
        if not self._pending_disconnect and self.connected:
            self._pending_disconnect = True
            logger.info("已设置断开连接请求")

    def _do_disconnect(self) -> None:
        """实际执行断开连接（在主循环中调用）"""
        if self.adapter:
            try:
                self.adapter.close()
                logger.info("已断开连接")

                self._emit_event(EventTypes.ACCOUNT_STATUS, {
                    "account_id": self.config.account_id,
                    "status": "disconnected",
                    "timestamp": datetime.now().isoformat(),
                })

            except Exception as e:
                logger.error(f"断开连接时出错: {e}")

        self.connected = False
        self._pending_disconnect = False
        self._running = False
        self.adapter = None

    def _init_risk_counts_from_orders(self) -> None:
        """根据orders列表初始化当日已发送的报单次数和撤单次数"""
        try:
            today = datetime.now().date()
            daily_order_count = 0
            daily_cancel_count = 0

            for order_id, order in self.orders.items():
                insert_time = order.get("insert_date_time", 0)
                order_time = datetime.fromtimestamp(insert_time / 1e9).date()

                if order_time == today:
                    daily_order_count += 1

                    order_status = order.get("status", "")
                    if order_status == "FINISHED" and order.get("volume_left", 0) > 0:
                        daily_cancel_count += 1

            self.risk_control.daily_order_count = daily_order_count
            self.risk_control.daily_cancel_count = daily_cancel_count
            self.risk_control._last_reset_date = today

            logger.info(
                f"从orders列表初始化风控计数 - 当日报单: {daily_order_count}, "
                f"当日撤单: {daily_cancel_count}"
            )
        except Exception as e:
            logger.error(f"初始化风控计数失败: {e}")

    def _init_subscriptions(self) -> None:
        """初始化行情订阅"""
        for symbol in self.positions.keys():
            try:
                self.adapter.subscribe_quote([symbol])
                logger.info(f"已订阅tick行情: {symbol}")
            except Exception as e:
                logger.error(f"订阅 {symbol} 失败: {e}")

    def update(self) -> bool:
        """
        更新交易数据（在主循环中调用）

        Returns:
            bool: 是否继续运行
        """
        if not self.connected or not self.adapter:
            return False

        try:
            has_data = self.adapter.wait_update()
            if not has_data:
                return False

            self._check_and_save_account()
            self._check_and_save_positions()
            self._check_and_save_orders()
            self._check_and_save_trades()
            self._check_and_emit_tick_updates()
            return True

        except Exception as e:
            logger.error(f"更新数据时出错: {e}")
            self._emit_event(EventTypes.SYSTEM_ERROR, {"error": str(e)})
            return False

    def _check_and_save_account(self) -> None:
        """检查并推送账户信息"""
        account_info = self.adapter.get_account()
        if account_info and self.adapter.is_changing(account_info):
            try:
                account_data = {
                    "account_id": account_info.account_id,
                    "broker_name": account_info.broker_name,
                    "currency": account_info.currency,
                    "balance": account_info.balance,
                    "available": account_info.available,
                    "margin": account_info.margin,
                    "float_profit": account_info.float_profit,
                    "position_profit": account_info.position_profit,
                    "close_profit": account_info.close_profit,
                    "risk_ratio": account_info.risk_ratio,
                    "updated_at": datetime.now().isoformat(),
                    "user_id": account_info.user_id,
                }

                self._emit_event(EventTypes.ACCOUNT_UPDATE, account_data)

            except Exception as e:
                logger.error(f"处理账户信息时出错: {e}")

    def _check_and_save_positions(self) -> None:
        """检查并推送持仓信息"""
        all_positions = self.adapter.get_position()

        for symbol, pos in all_positions.items():
            if self.adapter.is_changing(pos):
                if symbol not in self.positions:
                    self.positions[symbol] = pos

                event_data = {
                    "account_id": self.account_id,
                    "symbol": symbol,
                    "exchange_id": pos.exchange_id,
                    "instrument_id": pos.instrument_id,
                    "pos_long": pos.pos_long,
                    "pos_short": pos.pos_short,
                    "open_price_long": pos.open_price_long,
                    "open_price_short": pos.open_price_short,
                    "float_profit": pos.float_profit,
                    "margin": pos.margin,
                    "updated_at": datetime.now().isoformat(),
                }

                self._emit_event(EventTypes.POSITION_UPDATE, event_data)

    def _check_and_save_orders(self) -> None:
        """检查并推送委托单信息"""
        all_orders = self.adapter.get_order()

        for order_id, order in all_orders.items():
            if self.adapter.is_changing(order):
                self.orders[order_id] = order

                event_data = {
                    "order_id": order_id,
                    "account_id": self.account_id,
                    "exchange_order_id": order.exchange_order_id,
                    "symbol": order.symbol,
                    "exchange_id": order.exchange_id,
                    "instrument_id": order.instrument_id,
                    "direction": order.direction,
                    "offset": order.offset,
                    "volume_orign": order.volume_orign,
                    "volume_left": order.volume_left,
                    "limit_price": float(order.limit_price) if order.limit_price else None,
                    "price_type": order.price_type,
                    "status": order.status,
                    "insert_date_time": order.insert_date_time,
                    "last_msg": order.last_msg,
                    "updated_at": datetime.now().isoformat(),
                }

                logger.info(
                    f"委托单更新 - order_id: {order_id}, "
                    f"symbol: {event_data['symbol']}, "
                    f"direction: {event_data['direction']}, "
                    f"offset: {event_data['offset']}, "
                    f"volume_orign: {event_data['volume_orign']}, "
                    f"volume_left: {event_data['volume_left']}, "
                    f"limit_price: {event_data['limit_price']:.2f} " if event_data['limit_price'] else "None",
                    f"price_type: {event_data['price_type']}, "
                    f"status: {event_data['status']}, "
                )

                self._emit_event(EventTypes.ORDER_UPDATE, event_data)

    def _check_and_save_trades(self) -> None:
        """检查并推送成交信息"""
        all_orders = self.adapter.get_order()

        for order_id, order in all_orders.items():
            if self.adapter.is_changing(order):
                trade_records = order.get("trade_records", {})
                for trade_id, trade in trade_records.items():
                    try:
                        existing = next((t for t in self.trades if t.get("trade_id") == trade_id), None)
                        if existing:
                            continue

                        trade_data = {
                            "trade_id": trade_id,
                            "order_id": order_id,
                            "account_id": self.account_id,
                            "symbol": trade.symbol,
                            "exchange_id": trade.exchange_id,
                            "instrument_id": trade.instrument_id,
                            "direction": trade.direction,
                            "offset": trade.offset,
                            "price": float(trade.price),
                            "volume": trade.volume,
                            "trade_date_time": trade.trade_date_time,
                            "created_at": datetime.now().isoformat(),
                        }
                        self.trades[trade_id] = trade_data

                        logger.bind(tags=["trade"]).info(
                            f"成交更新 - trade_id: {trade_id}, "
                            f"symbol: {trade_data['symbol']}, "
                            f"direction: {trade_data['direction']}, "
                            f"offset: {trade_data['offset']}, "
                            f"volume: {trade_data['volume']}, "
                            f"price: {trade_data['price']:.2f}"
                        )

                        self._emit_event(EventTypes.TRADE_UPDATE, trade_data)

                    except Exception as e:
                        logger.error(f"处理成交信息时出错: {e}")

    def insert_order(
        self,
        symbol: str,
        direction: str,
        offset: str,
        volume: int,
        price: float = 0,
    ) -> Optional[str]:
        """
        下单

        Args:
            symbol: 合约代码
            direction: 方向 (BUY/SELL)
            offset: 开平 (OPEN/CLOSE/CLOSETODAY)
            volume: 手数
            price: 0-市价，>0限价

        Returns:
            Optional[str]: 委托单ID，失败返回None
        """
        if not self.connected or not self.adapter:
            logger.error("交易引擎未连接，无法下单")
            raise Exception("交易引擎未连接，无法下单")

        if self.paused:
            logger.warning("交易已暂停，无法下单")
            raise Exception("交易已暂停，无法下单")

        if not self.risk_control.check_order(volume):
            logger.error(f"风控检查失败: 手数 {volume} 超过限制")
            raise Exception(f"风控检查失败: 手数 {volume} 超过限制")

        try:
            order_id = self.adapter.insert_order(
                symbol=symbol,
                direction=direction,
                offset=offset,
                volume=volume,
                price=price,
            )

            if order_id:
                logger.bind(tags=["trade"]).info(
                    f"下单: {symbol} {direction} {offset} {volume}手 @{price}, 委托单ID: {order_id}"
                )
                self.risk_control.on_order_inserted()

                self._emit_event(EventTypes.ORDER_UPDATE, {
                    "order_id": order_id,
                    "account_id": self.account_id,
                    "symbol": symbol,
                    "direction": direction,
                    "offset": offset,
                    "volume": volume,
                    "price": float(price) if price else None,
                    "price_type": "LIMIT" if price else "MARKET",
                    "timestamp": datetime.now().isoformat(),
                })
            else:
                raise Exception("下单失败，未返回order_id")

            return order_id

        except Exception as e:
            raise Exception(f"下单失败: {e}")

    def cancel_order(self, order_id: str) -> bool:
        """
        撤单

        Args:
            order_id: 委托单ID

        Returns:
            bool: 是否成功
        """
        if not self.connected or not self.adapter:
            logger.error("交易引擎未连接，无法撤单")
            return False

        try:
            if self.adapter.cancel_order(order_id):
                logger.bind(tags=["trade"]).info(f"撤单: {order_id}")
                self.risk_control.on_order_cancelled()

                self._emit_event(EventTypes.ORDER_UPDATE, {
                    "order_id": order_id,
                    "status": "cancelled",
                    "timestamp": datetime.now().isoformat(),
                })
                return True
            else:
                logger.error(f"撤单失败: {order_id}")
                return False

        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def pause(self) -> None:
        """暂停交易"""
        self.paused = True
        logger.info("交易已暂停")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "paused",
            "timestamp": datetime.now().isoformat(),
        })

    def resume(self) -> None:
        """恢复交易"""
        self.paused = False
        logger.info("交易已恢复")

        self._emit_event(EventTypes.ACCOUNT_STATUS, {
            "account_id": self.config.account_id,
            "status": "running",
            "timestamp": datetime.now().isoformat(),
        })

    def get_status(self) -> Dict[str, Any]:
        """
        获取引擎状态

        Returns:
            状态字典
        """
        return {
            "connected": self.connected,
            "paused": self.paused,
            "account_id": self.config.account_id,
            "daily_orders": self.risk_control.daily_order_count,
            "daily_cancels": self.risk_control.daily_cancel_count,
        }

    def _check_and_emit_tick_updates(self) -> None:
        """检查并推送tick行情更新事件"""
        for symbol, quote in self.quotes.items():
            if self.adapter.is_changing(quote):
                try:
                    if math.isnan(quote.get("last_price", 0)):
                        continue

                    event_data = {
                        "symbol": symbol,
                        "last_price": quote.get("last_price", 0),
                        "bid_price1": quote.get("bid_price1", 0),
                        "ask_price1": quote.get("ask_price1", 0),
                        "volume": quote.get("volume", 0),
                        "open_interest": quote.get("open_interest", 0),
                        "datetime": quote.get("datetime", 0),
                        "timestamp": datetime.now().isoformat(),
                    }

                    logger.debug(f"行情更新 - symbol: {symbol}, "
                                f"last_price: {event_data['last_price']:.2f}, "
                                f"bid_price1: {event_data['bid_price1']:.2f}, "
                                f"ask_price1: {event_data['ask_price1']:.2f}")

                    self._emit_event(EventTypes.TICK_UPDATE, event_data)

                except Exception as e:
                    logger.error(f"推送tick事件失败 {symbol}: {e}")

    def _emit_event(self, event_type: str, data: Any) -> None:
        """
        推送事件到事件引擎

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        try:
            self.event_engine.put(event_type, data)
        except Exception as e:
            logger.error(f"推送事件失败 [{event_type}]: {e}")
