"""
TqSdk Gateway适配器
"""
from datetime import datetime
from typing import Optional, Dict, Any, List,Union,Set
import threading
import time

from tqsdk import TqApi, TqAuth, TqKq, TqSim, TqAccount, data_extension
from tqsdk.objs import Account, Order, Position, Quote, Trade

from src.adapters.base_gateway import BaseGateway
from src.models.object import (
    TickData, BarData, OrderData, TradeData,
    PositionData, AccountData, ContractData,
    SubscribeRequest, OrderRequest, CancelRequest,
    Direction, Offset, OrderStatus, OrderType, Exchange, ProductType
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

exchange_map = {
    "SHFE": Exchange.SHFE,
    "DCE": Exchange.DCE,
    "CZCE": Exchange.CZCE,
    "CFFEX": Exchange.CFFEX,
    "INE": Exchange.INE,
    "GFEX": Exchange.GFEX,
}


class TqGateway(BaseGateway):
    """TqSdk Gateway适配器(完整实现)"""

    gateway_name = "TqSdk"

    def __init__(self, trading_engine=None):
        super().__init__()
        self.trading_engine = trading_engine
        self.connected = False
        self.config = trading_engine.config
        self.account_id = self.config.account_id

        
        # TqSdk API实例
        self.api: Optional[TqApi] = None
        self.auth: Optional[TqAuth] = None
           
        # TqSdk原始数据缓存(用于is_changing检查)
        self._account: Optional[Account] = None
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Order] = {}
        self._trades: Dict[str, Trade] = {}
        self._quotes: Dict[str, Quote] = {}
        
        # 合约符号映射(原始symbol -> 统一symbol)
        self._upper_symbols: Dict[str, str] = {}
        self._contracts: Dict[str, ContractData] = {}
        

        # 历史订阅的合约符号列表
        self.hist_subs: Set[str] = []
        
    
        # 订单引用计数
        self._order_ref = 0


    
    
    # ==================== 连接管理 ====================
    
    def connect(self) -> bool:
        """
        连接到TqSdk
        """
        try:      
            if self.connected:
                logger.warning("已连接到TqSdk,无需重复连接")
                return True

            account_type = self.config.account_type      
            # 创建认证
            tianqin = self.config.tianqin if self.config.tianqin else {}
            logger.info(f"连接到TqSdk,账户类型: {account_type}, 账户ID: {self.account_id}")

            # 创建认证
            tianqin = self.config.tianqin if self.config.tianqin else {}
            username = getattr(tianqin, 'username', '')
            password = getattr(tianqin, 'password', '')
            if username and password:
                self.auth = TqAuth(username, password)
            else:
                self.auth = None

            # 根据账户类型创建账户对象
            if account_type == 'kq':
                account = TqKq()
            elif account_type == 'real':
                trading_cfg = self.config.trading_account if self.config.trading_account else {}
                account = TqAccount(
                    broker_id=getattr(trading_cfg, 'broker_name', ''),
                    user_id=getattr(trading_cfg, 'user_id', ''),
                    password=getattr(trading_cfg, 'password', ''),
                )
            else:  # sim
                account = TqSim()
            
            # 创建TqApi
            self.api = TqApi(account, auth=self.auth, web_gui=False)
            
            # 获取账户和持仓、成交、委托单初始数据
            self._account = self.api.get_account()
            self._positions = self.api.get_position()
            self._orders = self.api.get_order()
            self._trades = self.api.get_trade()
            
            # 获取合约列表
            ls = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
            symbol_infos = self.api.query_symbol_info(ls)
            for index,item in symbol_infos.iterrows():
                instrument_id = item.instrument_id
                if item.exchange_id not in exchange_map:
                    continue
                contract = ContractData(
                    symbol=instrument_id,
                    exchange=exchange_map[item.exchange_id],
                    name=item.instrument_name,
                    size=item.volume_multiple,
                    price_tick=item.price_tick,
                    max_volume=item.max_limit_order_volume,
                )
                self._contracts[contract.symbol] = contract     
                self._upper_symbols[contract.symbol.rsplit(".")[1].upper()] = contract.symbol
            logger.info(f"成功加载{len(self._contracts)}个合约")     

            self.connected = True
            self.trading_day = datetime.now().strftime("%Y%m%d")
            logger.info(f"TqSdk连接成功,交易日: {self.trading_day}")      
            
            # 初始化持仓合约的行情订阅
            pos_symbols =  [symbol for symbol in self._positions if symbol not in self._quotes]
            self.hist_subs.extend(pos_symbols)
            self.subscribe(list(self.hist_subs))
                     
            # 启动主循环线程
            loop_thread = threading.Thread(target=self.loop_run, daemon=True)
            loop_thread.start()
            return True
            
        except Exception as e:
            logger.exception(f"TqSdk连接失败{e}")
            return False
    
    def disconnect(self) -> bool:
        """断开TqSdk连接"""
        try:
            #只设置连接断开，由主线程释放api
            self.connected = False
            logger.info("TqSdk已断开连接")
            return True
        except Exception as e:
            logger.error(f"TqSdk断开连接失败: {e}", exc_info=True)
            return False

    def loop_run(self) -> None:
        """主循环运行"""
        logger.info("Tq主循环已启动")
        while True:
            try:
                # 检查是否有待处理的断开连接请求
                if not self.connected:
                    if self.api:
                        self.api.close()
                        self.api = None
                        logger.info("TqSdk已销毁")
                    break

                self._wait_update()
            except Exception as e:
                logger.error(f"主循环更新出错: {e}")
        logger.info("Tq主循环已退出")
        
    def subscribe(self, symbol: Union[str, List[str]]) -> bool:
        """订阅行情"""
        try:
            if isinstance(symbol, str):
                symbol = [symbol]
            
            # 添加到订阅列表中     
            self.hist_subs.extend(symbol)
            if not self.connected:
                return

            # 格式化合约代码
            std_symbols = [self._format_symbol(sym) for sym in self.hist_subs]
            unsubscribe_symbols = [symbol for symbol in std_symbols if symbol not in self._quotes]
            if len(unsubscribe_symbols) ==0:
                return True
            quotes: List[Quote] = self.api.get_quote_list(symbols=unsubscribe_symbols)
            for quote in quotes:
                self._quotes[quote.instrument_id] = quote       
            logger.info(f"订阅行情: {unsubscribe_symbols}")
            
            return True
        except Exception as e:
            logger.exception(f"订阅行情失败: {e}")
            return False
    
        
    def send_order(self, req: OrderRequest) -> Optional[str]:
        """下单"""
        try:
            if not self.connected:
                logger.error("TqSdk未连接")
                return None
            
            formatted_symbol = self._format_symbol(req.symbol)
            if not formatted_symbol:
                logger.error(f"无效的合约代码: {req.symbol}")
                return None
            
            # 获取行情信息(市价单使用对手价)
            price = req.price
            if price is None or pirce==0:
                quote = self._quotes.get(formatted_symbol)
                if not quote:
                    logger.error(f"未获取到行情信息: {formatted_symbol}")
                    raise Exception(f"未获取到行情信息: {formatted_symbol}")
                
                # 使用对手价
                if req.direction == Direction.BUY:
                    price = quote.ask_price1
                else:
                    price = quote.bid_price1
            
            # 调用TqSdk下单
            order = self.api.insert_order(
                symbol=formatted_symbol,
                direction=req.direction.value,
                offset=req.offset.value,
                volume=req.volume,
                limit_price=price
            )
            
            order_id = order.get("order_id")
            logger.info(f"下单成功: {req.symbol} {req.direction.value} {req.offset.value} {req.volume}手 价格：{price}, order_id: {order_id}")
            
            # 更新缓存
            self._orders[order_id] = order
            self._emit_order(self._convert_order(order))       
            return order_id
        except Exception as e:
            logger.exception(f"下单失败: {e}")
            raise e
    
    def cancel_order(self, req: CancelRequest) -> bool:
        """撤单"""
        try:
            if not self.connected:
                logger.error("TqSdk未连接")
                return False
            
            order = self._orders.get(req.order_id)
            if not order:
                logger.error(f"订单不存在: {req.order_id}")
                return False
            
            self.api.cancel_order(order)
            logger.info(f"撤单成功: {req.order_id}")
            return True
        except Exception as e:
            logger.exception(f"撤单失败: {e}")
            raise e
    
    def get_contracts(self) -> Dict[str, ContractData]:
        """查询合约"""
        try:
            if not self.connected or not self.api:
                logger.error("TqSdk未连接")
                return None
            
            if not self._contracts:
                quotes = self.api.query_quotes(ins_class=["FUTURE"], expired=False)
                for symbol in quotes:
                    self._contracts[symbol] = ContractData(
                        symbol=symbol.split(".")[1] if "." in symbol else symbol,
                        exchange=self._parse_exchange(symbol),
                        name=symbol,
                        product_type=ProductType.FUTURES,
                    )
            
            return self._contracts
        except Exception as e:
            logger.error(f"查询合约失败: {e}")
            return {}
    
    
    def get_account(self) -> Optional[AccountData]:
        """获取账户数据(兼容)"""
        if self._account is None:
            return None
        return self._convert_account(self._account)
    
    def get_positions(self) -> Dict[str, PositionData]:
        """获取持仓数据(兼容,返回原始格式)"""
        return {symbol: self._convert_position(position) for symbol, position in self._positions.items()}

    def get_orders(self) -> Dict[str, OrderData]:
        """获取订单数据(兼容,返回原始格式)"""
        return {order_id: self._convert_order(order) for order_id, order in self._orders.items()}

    def get_trades(self) -> Dict[str, TradeData]:
        """获取成交数据(兼容,返回原始格式)"""
        return {trade_id: self._convert_trade(trade) for trade_id, trade in self._trades.items()}
    
    def get_quotes(self) -> Dict[str, TickData]:
        """获取行情数据(兼容,返回原始格式)"""
        return {symbol: self._convert_tick(quote) for symbol, quote in self._quotes.items()}
    
    def _wait_update(self, timeout: int = 3) -> bool:
        """
        等待数据更新(兼容方法)

        Args:
            timeout: 超时时间(秒)

        Returns:
            bool: 是否有数据更新
        """
        try:
            if not self.connected or not self.api:
                return False

            has_data = self.api.wait_update(time.time()+timeout)
            if has_data:
                if self.api.is_changing(self._account):
                    self._account = self.api.get_account()
                    self._emit_account(self._convert_account(self._account))

                if self.api.is_changing(self._positions):
                    self._positions = self.api.get_position()
                    for position in self._positions.values():
                        self._emit_position(self._convert_position(position))

                if self.api.is_changing(self._quotes):
                    self._quotes = self.api.get_quote()
                    for quote in self._quotes.values():
                        self._emit_tick(self._convert_tick(quote))

                if self.api.is_changing(self._orders):
                    self._orders = self.api.get_order()
                    for order in self._orders.values():
                        self._emit_order(self._convert_order(order))

                if self.api.is_changing(self._trades):
                    self._trades = self.api.get_trade()
                    for trade in self._trades.values():
                        self._emit_trade(self._convert_trade(trade))

            return has_data
        except Exception as e:
            logger.exception(f"等待更新失败: {e}")
            return False
    
    # ==================== 数据转换 ====================   
    def _convert_account(self, account: Account) -> AccountData:
        """转换账户数据"""
        return AccountData(
            account_id=self.account_id,
            balance=account.balance,
            available=account.available,
            margin=account.margin or 0,
            pre_balance=account.pre_balance or 0,
            hold_profit=account.position_profit or 0,
            close_profit=account.close_profit or 0,
            risk_ratio=account.risk_ratio or 0,
            update_time=datetime.now()
        )
    
    def _convert_position(self, pos: Position) -> PositionData:
        """转换持仓数据"""                        
        return PositionData(
            symbol=pos.instrument_id,
            exchange=pos.exchange_id,
            pos=pos.pos_long-pos.pos_short,
            pos_long=int(pos.pos_long),
            pos_short=int(pos.pos_short),
            pos_long_yd=int(pos.pos_long_his),
            pos_short_yd=int(pos.pos_short_his),
            pos_long_td=int(pos.pos_long_today),
            pos_short_td=int(pos.pos_short_today),
            open_price_long=float(pos.open_price_long) or 0,
            open_price_short=float(pos.open_price_short) or 0,
            float_profit_long=float(pos.float_profit_long) or 0,
            float_profit_short=float(pos.float_profit_short) or 0,
            hold_profit_long=float(pos.position_profit_long) or 0,
            hold_profit_short=float(pos.position_profit_short) or 0,
            margin_long=float(pos.margin_long) or 0,
            margin_short=float(pos.margin_short) or 0,
        )
    
    def _convert_order(self, order: Order) -> OrderData:
        """转换订单数据"""
        data = OrderData(
            order_id=order.get("order_id", ""),
            symbol=order.instrument_id,
            exchange=self._parse_exchange(order.exchange_id),
            direction=Direction(order.get("direction", "BUY")),
            offset=Offset(order.get("offset", "OPEN")),
            volume=int(order.get("volume_orign", 0)),
            traded=int(order.get("volume_orign", 0)) - int(order.get("volume_left", 0)),
            price=order.get("limit_price"),
            price_type=OrderType.LIMIT if order.get("limit_price") else OrderType.MARKET,
            #status=self._convert_status(order.get("status")),
            status=order.status,
            status_msg=order.get("last_msg", ""),            
            gateway_order_id=order.get("exchange_order_id", ""),
            insert_time=datetime.fromtimestamp(order.get("insert_date_time", 0) / 1e9) if order.get("insert_date_time") else None,
            update_time=datetime.now()
        )
        if data.status== "FINISHED" and data.status_msg :
            data.status = "REJECTED"
        return data
    
    def _convert_trade(self, trade: Trade) -> TradeData:
        """转换成交数据"""
        order_id = trade.get("order_id", "")
        exchange_id = trade.get("exchange_id", "")
        instrument_id = trade.get("instrument_id", "")
        
        return TradeData(
            trade_id=trade.get("trade_id", ""),
            order_id=order_id,
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            direction=Direction(trade.get("direction", "BUY")),
            offset=Offset(trade.get("offset", "OPEN")),
            price=float(trade.get("price", 0)),
            volume=int(trade.get("volume", 0)),
            trade_time=datetime.fromtimestamp(trade.get("trade_date_time", 0) / 1e9) if trade.get("trade_date_time") else None
        )
    
    def _convert_tick(self, quote: Quote) -> TickData:
        """转换tick数据"""
        exchange_id = quote.get("exchange_id", "")
        instrument_id = quote.get("instrument_id", "")
        try:
            datetime_obj = int(float(str(quote.get("datetime", 0)).strip()))
        except (ValueError, TypeError):
            datetime_obj = 0

        return TickData(
            symbol=instrument_id,
            exchange=self._parse_exchange(exchange_id),
            datetime=datetime.fromtimestamp(datetime_obj / 1e9) if datetime_obj else datetime.now(),
            last_price=float(quote.get("last_price", 0)),
            volume=float(quote.get("volume", 0)),
            turnover=float(quote.get("turnover", 0)),
            open_interest=float(quote.get("open_interest", 0)),
            bid_price1=float(quote.get("bid_price1", 0)),
            ask_price1=float(quote.get("ask_price1", 0)),
            bid_volume1=float(quote.get("bid_volume1", 0)),
            ask_volume1=float(quote.get("ask_volume1", 0)),
            open_price=float(quote.get("open", 0)),
            high_price=float(quote.get("highest", 0)),
            low_price=float(quote.get("lowest", 0)),
            pre_close=float(quote.get("pre_open_interest", 0)),
            limit_up=float(quote.get("upper_limit", 0)),
            limit_down=float(quote.get("lower_limit", 0))
        )
    
    # ==================== 辅助方法 ====================
    
    def _format_symbol(self, symbol: str) -> Optional[str]:
        """格式化合约代码"""
        if not symbol:
            return None
        upper_symbol = symbol.upper()
        for part in upper_symbol.rsplit("."):
            if part in self._upper_symbols:
                return self._upper_symbols[part]
        logger.warning(f"未找到匹配的合约符号: {symbol}")      
        return None
    
    def _parse_exchange(self, exchange_code: str) -> Exchange:
        """解析交易所代码"""
        return exchange_map.get(exchange_code.upper(), Exchange.NONE)
    
    def _convert_status(self, status: str) -> OrderStatus:
        """转换订单状态"""
        status_map = {
            "ALIVE": OrderStatus.NOTTRADED,
            "FINISHED": OrderStatus.ALLTRADED,
            "CANCELED": OrderStatus.CANCELLED
        }
        return status_map.get(status, OrderStatus.SUBMITTING)
