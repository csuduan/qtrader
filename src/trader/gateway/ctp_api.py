"""
CTP API 封装模块

封装 CTP Market Data API 和 Trader API，提供行情订阅、交易操作等功能。
需要安装 CTP SDK（如 openctp_ctp 或类似库）才能运行。

参考：
- CTP API 文档：https://www.simnow.com.cn
"""

import platform
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from xxlimited import Str

from openctp_ctp import mdapi, tdapi
from tqsdk.ins_schema import cont

from src.models.object import (
    AccountData,
    CancelRequest,
    ContractData,
    Direction,
    Exchange,
    Offset,
    OrderData,
    OrderRequest,
    OrderStatus,
    OrderType,
    PosDirection,
    PositionData,
    ProductType,
    SubscribeRequest,
    TickData,
    TradeData,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.trader.gateway.ctp_gateway import CtpGateway

logger = get_logger(__name__)


# ==================== CTP 常量映射 ====================

# 订单状态映射: CTP -> 系统内部
STATUS_CTP2VT = {
    tdapi.THOST_FTDC_OAS_Submitted: OrderStatus.PENDING,
    tdapi.THOST_FTDC_OAS_Accepted: OrderStatus.PENDING,
    tdapi.THOST_FTDC_OAS_Rejected: OrderStatus.REJECTED,
    tdapi.THOST_FTDC_OST_NoTradeQueueing: OrderStatus.PENDING,
    tdapi.THOST_FTDC_OST_PartTradedQueueing: OrderStatus.PENDING,
    tdapi.THOST_FTDC_OST_AllTraded: OrderStatus.FINISHED,
    tdapi.THOST_FTDC_OST_Canceled: OrderStatus.FINISHED,
}


# 方向映射: 系统内部 -> CTP
DIRECTION_VT2CTP = {Direction.BUY: tdapi.THOST_FTDC_D_Buy, Direction.SELL: tdapi.THOST_FTDC_D_Sell}
DIRECTION_CTP2VT = {v: k for k, v in DIRECTION_VT2CTP.items()}

POS_DIRECTION_VT2CTP = {
    PosDirection.LONG: tdapi.THOST_FTDC_PD_Long,
    PosDirection.SHORT: tdapi.THOST_FTDC_PD_Short,
}
POS_DIRECTION_CTP2VT = {v: k for k, v in POS_DIRECTION_VT2CTP.items()}

# 开平映射: 系统内部 -> CTP
OFFSET_VT2CTP = {
    Offset.OPEN: tdapi.THOST_FTDC_OF_Open,
    Offset.CLOSE: tdapi.THOST_FTDC_OFEN_Close,
    Offset.CLOSETODAY: tdapi.THOST_FTDC_OFEN_CloseToday,
    Offset.CLOSEYESTERDAY: tdapi.THOST_FTDC_OFEN_CloseYesterday,
}

# 开平映射: CTP -> 系统内部
OFFSET_CTP2VT = {v: k for k, v in OFFSET_VT2CTP.items()}

# 交易所映射: CTP -> 系统内部
EXCHANGE_CTP2VT = {
    "CFFEX": Exchange.CFFEX,
    "SHFE": Exchange.SHFE,
    "CZCE": Exchange.CZCE,
    "DCE": Exchange.DCE,
    "INE": Exchange.INE,
    "GFEX": Exchange.GFEX,
}

# 交易所映射: 系统内部 -> CTP
EXCHANGE_VT2CTP = {v: k for k, v in EXCHANGE_CTP2VT.items()}

# 产品类型映射: CTP -> 系统内部
PRODUCT_CTP2VT = {
    tdapi.THOST_FTDC_PC_Futures: ProductType.FUTURES,
    tdapi.THOST_FTDC_PC_Options: ProductType.OPTION,
    tdapi.THOST_FTDC_PC_SpotOption: ProductType.OPTION,
    tdapi.THOST_FTDC_PC_Combination: ProductType.SPREAD,
}


# CTP 常用常量
MIN_VOLUME = 1


def adjust_price(price: float, max_value: float = 1e308) -> float:
    """调整异常价格（CTP 无效价格转换为 0）"""
    if price >= max_value:
        return 0.0
    return price


class CtpMdApi(mdapi.CThostFtdcMdSpi):
    """
    CTP 行情接口

    封装 CTP Market Data API，处理行情订阅和数据推送。
    """

    def __init__(self, gateway: "CtpGateway"):
        """初始化行情接口"""
        super().__init__()
        self.gateway: "CtpGateway" = gateway
        self.config = gateway.config

        # 连接状态
        self._running = False
        self.connected = False

        # 请求 ID
        self.reqid = 0

        # 已订阅合约
        self.subscribed: set = set()
        # 历史订阅合约
        self.hist_subscribed: set = set()
        self.hist_subscribed.update(self.config.subscribe_symbols)

        # API 实例
        self.api: Optional[mdapi.CThostFtdcMdApi] = None

        # 行情地址
        broker = self.config.broker
        if not broker or not broker.md_address:
            logger.error("CTP 行情地址未配置")
            raise ValueError("CTP 行情地址未配置")

        self.address = broker.md_address
        self.current_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"CTP 行情接口初始化，地址: {self.address}")

    def connect(self) -> bool:
        """连接行情服务器"""
        if self._running:
            logger.warning("行情接口已启动，无需重复启动")
            return True

        try:
            # 创建临时目录
            self.subscribed.clear()
            temp_path = self._get_temp_path("md")
            flow_path = str(temp_path) + "/md-"

            # 创建 API 实例
            self.api = mdapi.CThostFtdcMdApi.CreateFtdcMdApi(flow_path)
            self.api.RegisterSpi(self)
            self.api.RegisterFront(self.address)
            self.api.Init()

            self._running = True
            logger.info("CTP 行情接口开始连接...")
            return True

        except Exception as e:
            logger.exception(f"CTP 行情接口连接失败: {e}")
            return False

    def close(self) -> None:
        """关闭行情接口"""
        if self.api:
            try:
                self.api.Release()
            except Exception as e:
                logger.warning(f"关闭行情接口异常: {e}")
            self.api = None

        self._running = False
        self.connected = False
        logger.info("CTP 行情接口已关闭")

    def login(self) -> None:
        """用户登录"""
        if not self.api or self.connected:
            return

        self.reqid += 1
        req = mdapi.CThostFtdcReqUserLoginField()
        if self.config.broker:
            req.BrokerID = self.config.broker.broker_id or ""
            req.UserID = self.config.broker.user_id or ""
            req.Password = self.config.broker.password or ""

        self.api.ReqUserLogin(req, self.reqid)
        logger.debug("CTP 行情接口发送登录请求")

    def resubscribe(self) -> None:
        """重新订阅已订阅的合约"""
        if self.hist_subscribed and len(self.hist_subscribed) > 0:
            self.subscribe(list(self.hist_subscribed))  # type: ignore[arg-type]

    def subscribe(self, symbols: list[Str]) -> None:
        """订阅行情"""
        self.hist_subscribed.update(symbols)
        if not self.connected or not self.api:
            logger.warning("行情接口未登录，无法订阅")
            return

        std_symbols = [self.gateway.std_symbol(s) for s in symbols]
        std_symbols = [s.split(".")[0] for s in std_symbols if s]
        symbols_to_subscribe = [s for s in std_symbols if s not in self.subscribed]
        if not symbols_to_subscribe:
            return

        self.api.SubscribeMarketData(
            [s.encode("utf-8") for s in symbols_to_subscribe if s], len(symbols_to_subscribe)
        )
        logger.info(f"CTP 订阅行情: {symbols_to_subscribe}")

    # ==================== CTP 回调方法 ====================

    def OnFrontConnected(self) -> None:
        """服务器连接成功回报"""
        logger.info("CTP 行情服务器连接成功")
        self.login()

    def OnFrontDisconnected(self, reason: int) -> None:
        """服务器连接断开回报"""
        self.connected = False
        logger.warning(f"CTP 行情服务器连接断开，原因: {reason}")

    def OnRspUserLogin(
        self, pRspUserLogin: Any, pRspInfo: Any, nRequestID: int, bIsLast: bool
    ) -> None:
        """用户登录请求回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 行情服务器登录失败: {pRspInfo.ErrorID}-{pRspInfo.ErrorMsg}")
            return

        self.connected = True
        trading_day = pRspUserLogin.TradingDay if pRspUserLogin else ""
        logger.info(f"CTP 行情服务器登录成功，交易日: {trading_day}")

        self.gateway.on_status()

    def OnRspSubMarketData(
        self, pSpecificInstrument: Any, pRspInfo: Any, nRequestID: int, bIsLast: bool
    ) -> None:
        """订阅行情回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(
                f"CTP 订阅行情失败: {pSpecificInstrument.InstrumentID if pSpecificInstrument else ''}"
            )
            return

        if pSpecificInstrument:
            self.subscribed.update(pSpecificInstrument.InstrumentID)
            logger.info(f"CTP 订阅行情成功: {pSpecificInstrument.InstrumentID}")

    def OnRtnDepthMarketData(self, data: mdapi.CThostFtdcDepthMarketDataField) -> None:
        """行情数据推送"""
        try:
            if not data or not data.UpdateTime:
                return

            symbol = data.InstrumentID
            contract = self.gateway.get_contract(symbol)
            if not contract:
                return

            # 解析时间
            if not data.ActionDay or contract.exchange == Exchange.DCE:
                date_str = self.current_date
            else:
                date_str = data.ActionDay

            timestamp = f"{date_str} {data.UpdateTime}.{data.UpdateMillisec}"
            dt = datetime.strptime(timestamp, "%Y%m%d %H:%M:%S.%f")

            # 创建 Tick 数据
            tick = TickData.model_construct(
                symbol=symbol,
                exchange=contract.exchange,
                datetime=dt,
                last_price=adjust_price(data.LastPrice),
                volume=data.Volume,
                turnover=data.Turnover,
                open_interest=data.OpenInterest,
                bid_price1=adjust_price(data.BidPrice1),
                ask_price1=adjust_price(data.AskPrice1),
                bid_volume1=data.BidVolume1,
                ask_volume1=data.AskVolume1,
                open_price=adjust_price(data.OpenPrice),
                high_price=adjust_price(data.HighestPrice),
                low_price=adjust_price(data.LowestPrice),
                pre_close=adjust_price(data.PreClosePrice),
                limit_up=data.UpperLimitPrice,
                limit_down=data.LowerLimitPrice,
            )

            # 五档行情
            if data.BidVolume2 or data.AskVolume2:
                tick.bid_price2 = adjust_price(data.BidPrice2)
                tick.bid_price3 = adjust_price(data.BidPrice3)
                tick.bid_price4 = adjust_price(data.BidPrice4)
                tick.bid_price5 = adjust_price(data.BidPrice5)
                tick.ask_price2 = adjust_price(data.AskPrice2)
                tick.ask_price3 = adjust_price(data.AskPrice3)
                tick.ask_price4 = adjust_price(data.AskPrice4)
                tick.ask_price5 = adjust_price(data.AskPrice5)
                tick.bid_volume2 = data.BidVolume2
                tick.bid_volume3 = data.BidVolume3
                tick.bid_volume4 = data.BidVolume4
                tick.bid_volume5 = data.BidVolume5
                tick.ask_volume2 = data.AskVolume2
                tick.ask_volume3 = data.AskVolume3
                tick.ask_volume4 = data.AskVolume4
                tick.ask_volume5 = data.AskVolume5

            # 推送 tick
            self.gateway.on_tick(tick)

        except Exception as e:
            logger.exception(f"处理行情数据异常: {e}")

    def _get_temp_path(self, subdir: str) -> Path:
        """获取临时文件路径"""
        temp_dir = Path.home() / ".qtrader" / "temp" / f"ctp_{subdir}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir


class CtpTdApi(tdapi.CThostFtdcTraderSpi):
    """
    CTP 交易接口

    封装 CTP Trader API，处理账户查询、下单、撤单等交易操作。
    """

    def __init__(self, gateway: "CtpGateway"):
        """初始化交易接口"""
        super().__init__()

        self.gateway: "CtpGateway" = gateway
        self.config = gateway.config

        # 连接状态
        self._running = False
        self.connected = False
        self.is_ready = False
        self.contract_inited = False

        # 请求 ID 和订单引用
        self.reqid = 0
        self.order_ref = 0
        self.frontid = 0
        self.sessionid = 0

        # API 实例
        self.api: Optional[tdapi.CThostFtdcTraderApi] = None

        # 交易地址和认证信息
        broker = self.config.broker
        if not broker:
            raise ValueError("CTP 交易接口配置缺失 broker 信息")

        self.address = broker.td_address
        self.user = broker.user_id or ""
        self.pwd = broker.password or ""
        self.broker = broker.broker_id or ""
        self.app_id = broker.app_id or ""
        self.auth = broker.auth_code or ""

        # 数据缓存
        self.position_map: Dict[str, PositionData] = {}
        self.order_map: Dict[str, OrderData] = {}

        # 信号量（用于同步查询）
        self.semaphore = threading.Semaphore(1)

        logger.info(f"CTP 交易接口初始化，地址: {self.address}")

    def connect(self) -> bool:
        """连接交易服务器"""
        if self._running:
            logger.warning("交易接口已启动，跳过重复连接")
            return True

        try:
            # 创建临时目录
            temp_path = self._get_temp_path("td")
            flow_path = str(temp_path) + "/td-"

            # 创建 API 实例
            self.api = tdapi.CThostFtdcTraderApi.CreateFtdcTraderApi(flow_path)
            self.api.RegisterSpi(self)
            self.api.RegisterFront(self.address)
            self.api.SubscribePrivateTopic(tdapi.THOST_TERT_QUICK)
            self.api.SubscribePublicTopic(tdapi.THOST_TERT_QUICK)
            self.api.Init()

            self._running = True
            logger.info("CTP 交易接口开始连接...")
            return True

        except Exception as e:
            logger.exception(f"CTP 交易接口连接失败: {e}")
            return False

    def close(self) -> None:
        """关闭交易接口"""
        if self.api:
            try:
                self.api.Release()
            except Exception as e:
                logger.warning(f"关闭交易接口异常: {e}")
            self.api = None

        self._running = False
        self.connected = False
        logger.info("CTP 交易接口已关闭")

    def authenticate(self) -> None:
        """发起授权验证"""
        if not self.api:
            return

        req = tdapi.CThostFtdcReqAuthenticateField()
        req.BrokerID = self.broker
        req.UserID = self.user
        req.AppID = self.app_id
        req.AuthCode = self.auth

        self.reqid += 1
        self.api.ReqAuthenticate(req, self.reqid)
        logger.debug("CTP 发送授权验证请求")

    def login(self) -> None:
        """用户登录"""
        if not self.api or self.connected:
            return

        req = tdapi.CThostFtdcReqUserLoginField()
        req.BrokerID = self.broker
        req.UserID = self.user
        req.Password = self.pwd
        req.UserProductInfo = "qtrader"

        self.reqid += 1
        if platform.system() == "Darwin":
            ret = self.api.ReqUserLogin(req, self.reqid, 0, None)
        else:
            ret = self.api.ReqUserLogin(req, self.reqid)

        if ret != 0:
            logger.error(f"CTP 交易服务器登录请求失败，错误码: {ret}")

    def insert_order(self, req: OrderRequest) -> Optional[OrderData]:
        """委托下单"""
        if not self.api or not self.connected:
            logger.error("CTP 交易接口未连接或未登录")
            return None

        # 生成订单引用
        self.order_ref += 1
        order_ref = str(self.order_ref)

        # 创建 CTP 请求
        ctp_req = tdapi.CThostFtdcInputOrderField()
        ctp_req.BrokerID = self.broker
        ctp_req.InvestorID = self.user
        ctp_req.OrderRef = order_ref
        ctp_req.InstrumentID = req.symbol
        ctp_req.ExchangeID = EXCHANGE_VT2CTP.get(req.exchange, "")
        ctp_req.Direction = DIRECTION_VT2CTP.get(req.direction, "")
        ctp_req.CombOffsetFlag = OFFSET_VT2CTP.get(req.offset, "")
        ctp_req.CombHedgeFlag = tdapi.THOST_FTDC_HF_Speculation
        ctp_req.OrderPriceType = tdapi.THOST_FTDC_OPT_LimitPrice
        ctp_req.LimitPrice = req.price
        ctp_req.VolumeTotalOriginal = req.volume
        ctp_req.ContingentCondition = tdapi.THOST_FTDC_CC_Immediately
        ctp_req.ForceCloseReason = tdapi.THOST_FTDC_FCC_NotForceClose
        ctp_req.IsAutoSuspend = 0
        ctp_req.MinVolume = MIN_VOLUME

        # 时间条件和数量条件
        if req.price_type == OrderType.FAK:
            ctp_req.TimeCondition = tdapi.THOST_FTDC_TC_IOC  # 委托有效期: 立即成交剩余转限价
            ctp_req.VolumeCondition = tdapi.THOST_FTDC_VC_AV
        elif req.price_type == OrderType.FOK:
            ctp_req.TimeCondition = tdapi.THOST_FTDC_TC_IOC
            ctp_req.VolumeCondition = tdapi.THOST_FTDC_VC_CV
        else:
            ctp_req.TimeCondition = tdapi.THOST_FTDC_TC_GFD  # 委托有效期: 当日有效
            ctp_req.VolumeCondition = tdapi.THOST_FTDC_VC_AV

        self.reqid += 1
        ret = self.api.ReqOrderInsert(ctp_req, self.reqid)

        if ret != 0:
            logger.error(f"CTP 下单请求发送失败，错误码: {ret}")
            return None

        # 创建订单数据
        order = OrderData.model_construct(
            account_id=self.gateway.account_id,
            order_id=order_ref,
            symbol=req.symbol,
            exchange=req.exchange,
            direction=req.direction,
            offset=req.offset,
            volume=req.volume,
            price=req.price,
            traded=0,
            status=OrderStatus.PENDING,
            price_type=req.price_type,
            insert_time=datetime.now(),
            trading_day=getattr(self.gateway, "trading_day", None),
        )

        self.order_map[order_ref] = order
        logger.info(
            f"CTP 下单成功: {req.symbol} {req.direction.value} {req.offset.value} "
            f"{req.volume}手 @{req.price}, OrderRef: {order_ref}"
        )

        return order

    def cancel_order(self, req: CancelRequest) -> bool:
        """委托撤单"""
        if not self.api or not self.connected:
            return False

        order = self.order_map.get(req.order_id)
        if not order:
            logger.warning(f"CTP 撤单失败，找不到订单: {req.order_id}")
            return False

        ctp_req = tdapi.CThostFtdcInputOrderActionField()
        ctp_req.BrokerID = self.broker
        ctp_req.InvestorID = self.user
        ctp_req.OrderRef = order.order_id
        ctp_req.FrontID = self.frontid
        ctp_req.SessionID = self.sessionid
        ctp_req.ActionFlag = tdapi.THOST_FTDC_AF_Delete
        ctp_req.InstrumentID = order.symbol
        ctp_req.ExchangeID = EXCHANGE_VT2CTP.get(order.exchange, "")

        self.reqid += 1
        ret = self.api.ReqOrderAction(ctp_req, self.reqid)

        if ret != 0:
            logger.error(f"CTP 撤单请求发送失败，错误码: {ret}")
            return False

        logger.info(f"CTP 撤单请求发送成功: {req.order_id}")
        return True

    def query_account(self) -> None:
        """查询资金"""
        if not self.api or not self.connected:
            self.semaphore.release()
            return
        req = tdapi.CThostFtdcQryTradingAccountField()
        self.reqid += 1
        ret = self.api.ReqQryTradingAccount(req, self.reqid)
        if ret != 0:
            logger.error(f"查询资金失败，错误代码：{ret}")
            self.semaphore.release()

    def query_position(self) -> None:
        """查询持仓"""
        if not self.api or not self.connected:
            self.semaphore.release()
            return

        req = tdapi.CThostFtdcQryInvestorPositionField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        self.reqid += 1
        ret = self.api.ReqQryInvestorPosition(req, self.reqid)
        if ret != 0:
            logger.error(f"查询持仓失败，错误代码：{ret}")
            self.semaphore.release()

    def query_instrument(self) -> None:
        """查询合约"""
        # 检查是否已有当日合约缓存
        today = datetime.now().strftime("%Y-%m-%d")
        if self.gateway.contracts and self.gateway._contracts_update_date == today:
            logger.info(f"合约信息已缓存 ({len(self.gateway.contracts)} 个)，跳过查询")
            self.contract_inited = True
            self.semaphore.release()
            return

        if not self.api or not self.connected:
            self.semaphore.release()
            return
        req = tdapi.CThostFtdcQryInstrumentField()
        self.reqid += 1
        ret = self.api.ReqQryInstrument(req, self.reqid)
        if ret != 0:
            logger.error(f"查询合约失败，错误代码：{ret}")
            self.semaphore.release()

    def query_trades(self):
        """查询成交"""
        if not self.api or not self.connected:
            self.semaphore.release()
            return
        logger.info("开始查询成交...")
        req = tdapi.CThostFtdcQryTradeField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        self.reqid += 1
        ret = self.api.ReqQryTrade(req, self.reqid)
        if ret != 0:
            logger.error(f"查询成交失败，错误代码：{ret}")
            self.semaphore.release()

    def query_orders(self):
        """查询订单"""
        if not self.api or not self.connected:
            self.semaphore.release()
            return
        logger.info("开始查询订单...")
        req = tdapi.CThostFtdcQryOrderField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        self.reqid += 1
        ret = self.api.ReqQryOrder(req, self.reqid)
        if ret != 0:
            logger.error(f"查询订单失败，错误代码：{ret}")
            self.semaphore.release()

    # ==================== CTP 回调方法 ====================

    def OnFrontConnected(self) -> None:
        """服务器连接成功回报"""
        logger.info("CTP 交易服务器连接成功")

        if self.auth:
            self.authenticate()
        else:
            self.login()

    def OnFrontDisconnected(self, reason: int) -> None:
        """服务器连接断开回报"""
        self.connected = False
        logger.error(f"CTP 交易服务器连接断开，原因: {reason}")

    def OnRspAuthenticate(
        self,
        pRspAuthenticateField: tdapi.CThostFtdcRspAuthenticateField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """用户授权验证回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 交易服务器授权验证失败: {pRspInfo.ErrorID}-{pRspInfo.ErrorMsg}")
            return

        logger.info("CTP 交易服务器授权验证成功")
        self.login()

    def OnRspUserLogin(
        self,
        pRspUserLogin: tdapi.CThostFtdcRspUserLoginField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """用户登录请求回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 交易服务器登录失败: {pRspInfo.ErrorID}-{pRspInfo.ErrorMsg}")
            return

        self.frontid = pRspUserLogin.FrontID
        self.sessionid = pRspUserLogin.SessionID
        self.connected = True
        trading_day = pRspUserLogin.TradingDay

        # 更新订单引用
        max_order_ref = int(pRspUserLogin.MaxOrderRef) if pRspUserLogin.MaxOrderRef else 0
        unsigned_sessionid = self.sessionid & 0xFFFF
        self.order_ref = (unsigned_sessionid << 16) + max_order_ref + 1

        logger.info(
            f"CTP 交易服务器登录成功，交易日: {trading_day}, "
            f"FrontID: {self.frontid}, SessionID: {self.sessionid}"
        )

        # 设置交易日期
        self.gateway.trading_day = trading_day

        # 启动查询线程
        threading.Thread(target=self._run_query, daemon=True).start()

    def OnRspOrderInsert(
        self,
        pInputOrder: tdapi.CThostFtdcInputOrderField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """委托下单失败回报"""
        if not pRspInfo:
            return

        order_ref = pInputOrder.OrderRef if pInputOrder else ""
        logger.error(f"CTP 报单失败: {order_ref}, {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}")

        order = self.order_map.get(order_ref)
        if order:
            order.status = OrderStatus.REJECTED
            order.status_msg = pRspInfo.ErrorMsg
            order.update_time = datetime.now()
            self.gateway.on_order(order)
            self.order_map.pop(order_ref, None)

    def OnRspOrderAction(
        self,
        pInputOrderAction: tdapi.CThostFtdcInputOrderActionField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """委托撤单失败回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(
                f"CTP 撤单失败: {pInputOrderAction.OrderRef}, {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}"
            )

    def OnRtnOrder(self, pOrder: tdapi.CThostFtdcOrderField) -> None:
        """委托更新推送"""
        if not pOrder:
            return

        order_ref = pOrder.OrderRef
        status = STATUS_CTP2VT.get(pOrder.OrderStatus)
        if not status:
            logger.warning(f"CTP 未知的订单状态: {pOrder.OrderStatus}")
            return

        order = self.order_map.get(order_ref)
        if not order:
            logger.warning(f"CTP 找不到订单: {order_ref}")
            return

        order.status = status
        order.status_msg = pOrder.StatusMsg
        order.traded = pOrder.VolumeTraded
        order.update_time = datetime.now()

        # 订单完成后移除
        if status in [OrderStatus.FINISHED, OrderStatus.REJECTED]:
            self.order_map.pop(order_ref, None)

        self.gateway.on_order(order)

    def OnRtnTrade(self, pTrade: tdapi.CThostFtdcTradeField) -> None:
        """成交数据推送"""
        if not pTrade:
            return

        trade = TradeData.model_construct(
            account_id=self.gateway.account_id,
            trade_id=pTrade.TradeID,
            order_id=pTrade.OrderRef,
            symbol=pTrade.InstrumentID,
            exchange=EXCHANGE_CTP2VT.get(pTrade.ExchangeID, Exchange.NONE),
            direction=DIRECTION_CTP2VT.get(pTrade.Direction, Direction.BUY),
            offset=OFFSET_CTP2VT.get(pTrade.OffsetFlag, Offset.OPEN),
            price=pTrade.Price,
            volume=pTrade.Volume,
            trade_time=datetime.strptime(
                pTrade.TradeDate + " " + pTrade.TradeTime, "%Y%m%d %H:%M:%S"
            ),
            trading_day=pTrade.TradeDate,
        )

        logger.info(
            f"CTP 成交回报: {trade.symbol} {trade.direction.value} {trade.offset.value} "
            f"{trade.volume}手 @{trade.price}"
        )

        self.gateway.on_trade(trade)

    def OnRspSettlementInfoConfirm(
        self, pSettlementInfoConfirm: Any, pRspInfo: Any, nRequestID: int, bIsLast: bool
    ) -> None:
        """确认结算单回报"""
        logger.info("结算信息确认成功")
        self.semaphore.release()

    def OnRspQryTradingAccount(
        self,
        pTradingAccount: tdapi.CThostFtdcTradingAccountField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """资金查询回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 查询资金失败: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}")
            self.semaphore.release()
            return

        if pTradingAccount:
            account = AccountData.model_construct(
                account_id=self.gateway.account_id,
                balance=round(pTradingAccount.Balance, 2),
                available=round(pTradingAccount.Available, 2),
                margin=round(pTradingAccount.CurrMargin, 2),
                risk_ratio=(
                    round(pTradingAccount.CurrMargin / pTradingAccount.Balance, 4)
                    if pTradingAccount.Balance > 0
                    else 0
                ),
                frozen=round(
                    pTradingAccount.FrozenMargin
                    + pTradingAccount.FrozenCash
                    + pTradingAccount.FrozenCommission,
                    2,
                ),
                hold_profit=round(pTradingAccount.PositionProfit, 2),
                close_profit=round(pTradingAccount.CloseProfit, 2),
                pre_balance=round(pTradingAccount.PreBalance, 2),
            )

            self.gateway.on_account(account)
            self.semaphore.release()
            logger.info(f"CTP 资金查询成功，余额: {account.balance}")

    def OnRspQryInvestorPosition(
        self,
        pInvestorPosition: tdapi.CThostFtdcInvestorPositionField,
        pRspInfo: Any,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """持仓查询回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 查询持仓失败: {pRspInfo.ErrorID}-{pRspInfo.ErrorMsg}")
            self.semaphore.release()
            return

        if pInvestorPosition:
            symbol = pInvestorPosition.InstrumentID
            contract = self.gateway.contracts.get(symbol)
            multiple = contract.multiple if contract and contract.multiple else 1
            direction = POS_DIRECTION_CTP2VT.get(pInvestorPosition.PosiDirection)

            # 获取或创建持仓
            position = self.position_map.get(symbol)
            if not position:
                position = PositionData.model_construct(
                    account_id=self.gateway.account_id,
                    symbol=symbol,
                    exchange=EXCHANGE_CTP2VT.get(pInvestorPosition.ExchangeID, Exchange.NONE),
                    pos=0,
                    pos_long=0,
                    pos_short=0,
                    pos_long_yd=0,
                    pos_short_yd=0,
                    pos_long_td=0,
                    pos_short_td=0,
                    open_price_long=0.0,
                    open_price_short=0.0,
                    float_profit_long=0.0,
                    float_profit_short=0.0,
                    hold_profit_long=0.0,
                    hold_profit_short=0.0,
                    margin_long=0.0,
                    margin_short=0.0,
                )
                self.position_map[symbol] = position

            if direction:
                # 说明：
                # YdPosition是当前键值下的昨仓，是个静态值，不会更新。当前真实的昨仓值为Position-TodayPosition；
                # 对于非上期/能源的交易所，合约的昨仓YdPosition和今仓TodayPosition在一条记录里面，而上期/能源是分成了两条记录。
                volume = pInvestorPosition.Position
                td_volume = pInvestorPosition.TodayPosition or 0
                yd_volume = volume - td_volume

                position.pos_long += volume if direction == PosDirection.LONG else 0  # type: ignore[operator]
                position.pos_short += volume if direction == PosDirection.SHORT else 0  # type: ignore[operator]
                position.pos_long_td = (position.pos_long_td or 0) + (
                    td_volume if direction == PosDirection.LONG else 0
                )
                position.pos_short_td = (position.pos_short_td or 0) + (
                    td_volume if direction == PosDirection.SHORT else 0
                )
                position.pos_long_yd = (position.pos_long_yd or 0) + (
                    yd_volume if direction == PosDirection.LONG else 0
                )
                position.pos_short_yd = (position.pos_short_yd or 0) + (
                    yd_volume if direction == PosDirection.SHORT else 0
                )

                # 更新净持仓
                position.pos = position.pos_long - position.pos_short

                # 更新持仓成本和盈亏
                hold_cost_long = position.hold_cost_long or 0.0
                hold_cost_short = position.hold_cost_short or 0.0
                if pInvestorPosition.PositionCost:
                    if direction == PosDirection.LONG:
                        position.hold_cost_long = hold_cost_long + (
                            pInvestorPosition.PositionCost if volume > 0 else 0
                        )
                        position.hold_price_long = (
                            round(position.hold_cost_long / position.pos_long / multiple, 2)
                            if position.pos_long > 0
                            else 0.0
                        )
                    else:
                        position.hold_cost_short = hold_cost_short + (
                            pInvestorPosition.PositionCost if volume > 0 else 0
                        )
                        position.hold_price_short = (
                            round(position.hold_cost_short / position.pos_short / multiple, 2)
                            if position.pos_short > 0
                            else 0.0
                        )

                if pInvestorPosition.PositionProfit:
                    # 持仓盈亏(逐日盯市)
                    if direction == PosDirection.LONG:
                        position.hold_profit_long += pInvestorPosition.PositionProfit
                    else:
                        position.hold_profit_short += pInvestorPosition.PositionProfit
                if pInvestorPosition.CloseProfitByDate:
                    # 平仓盈亏(逐日盯市)
                    if direction == PosDirection.LONG:
                        position.close_profit_long += pInvestorPosition.CloseProfitByDate
                    else:
                        position.close_profit_short += pInvestorPosition.CloseProfitByDate

                if pInvestorPosition.UseMargin:
                    if direction == PosDirection.LONG:
                        position.margin_long += pInvestorPosition.UseMargin
                    else:
                        position.margin_short += pInvestorPosition.UseMargin

        if bIsLast:
            # 推送所有持仓
            for position in self.position_map.values():
                self.gateway.add_position(position)

            self.semaphore.release()
            logger.info(f"CTP 持仓查询成功，共 {len(self.position_map)} 条")
            self.position_map.clear()

    def OnRspQryInstrument(
        self,
        pInstrument: tdapi.CThostFtdcInstrumentField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """合约查询回报"""
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"CTP 查询合约失败: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}")
            self.semaphore.release()
            return

        if pInstrument:
            product_type = PRODUCT_CTP2VT.get(pInstrument.ProductClass)
            if product_type:
                contract = ContractData.model_construct(
                    symbol=pInstrument.InstrumentID,
                    exchange=EXCHANGE_CTP2VT.get(pInstrument.ExchangeID, Exchange.NONE),
                    name=pInstrument.InstrumentName,
                    product_type=product_type,
                    multiple=pInstrument.VolumeMultiple,
                    pricetick=pInstrument.PriceTick,
                    min_volume=1,
                    expire_date=pInstrument.ExpireDate,
                )
                if len(contract.symbol) <= 6 and contract.expire_date and contract.expire_date >= datetime.now().strftime(
                    "%Y%m%d"
                ) :
                    self.gateway.add_contract(contract)

        if bIsLast:
            self.contract_inited = True
            # 更新合约缓存日期
            self.gateway._contracts_update_date = datetime.now().strftime("%Y-%m-%d")
            self.semaphore.release()
            self._save_contracts()
            logger.info(f"CTP 合约查询成功，共 {len(self.gateway.contracts)} 条")

    def OnRspQryTrade(
        self,
        pTrade: tdapi.CThostFtdcTradeField,
        pRspInfo: tdapi.CThostFtdcRspInfoField,
        nRequestID: int,
        bIsLast: bool,
    ) -> None:
        """请求查询成交响应"""
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            logger.error(f"查询成交失败,{pRspInfo.ErrorMsg}")
            self.semaphore.release()
            return

        if pTrade:
            symbol: str = pTrade.InstrumentID
            order_ref: str = pTrade.OrderRef

            trade: TradeData = TradeData(
                trade_id=pTrade.TradeID,
                trading_day=pTrade.TradeDate,
                symbol=symbol,
                exchange=EXCHANGE_CTP2VT[pTrade.ExchangeID],
                order_id=order_ref,
                direction=DIRECTION_CTP2VT[pTrade.Direction],
                offset=OFFSET_CTP2VT[pTrade.OffsetFlag],
                price=pTrade.Price,
                volume=pTrade.Volume,
                trade_time=datetime.strptime(
                    pTrade.TradeDate + " " + pTrade.TradeTime, "%Y%m%d %H:%M:%S"
                ),
                account_id=self.config.account_id or "",
                commission=0.0,
            )
            self.gateway.add_trade(trade)

        if bIsLast:
            logger.info(f"成交信息查询成功")
            self.semaphore.release()

    def OnRspQryOrder(
        self, pOrder: tdapi.CThostFtdcOrderField, pRspInfo: Any, nRequestID: int, bIsLast: bool
    ) -> None:
        """请求查询订单响应"""
        if pRspInfo is not None and pRspInfo.ErrorID != 0:
            logger.error(f"查询订单失败,{pRspInfo.ErrorMsg}")
            self.semaphore.release()
            return

        if pOrder:
            order_id = pOrder.OrderSysID
            order: OrderData = OrderData(
                order_id=order_id,
                trading_day=pOrder.TradingDay,
                symbol=pOrder.InstrumentID,
                exchange=EXCHANGE_CTP2VT[pOrder.ExchangeID],
                direction=DIRECTION_CTP2VT[pOrder.Direction],
                offset=OFFSET_CTP2VT[pOrder.CombOffsetFlag],
                price=pOrder.LimitPrice,
                volume=pOrder.VolumeTotalOriginal,
                traded=pOrder.VolumeTraded,
                traded_price=None,
                status=STATUS_CTP2VT[pOrder.OrderStatus],
                status_msg=pOrder.StatusMsg,
                insert_time=datetime.strptime(
                    pOrder.InsertDate + " " + pOrder.InsertTime, "%Y%m%d %H:%M:%S"
                ),
                account_id=self.config.account_id or "",
                gateway_order_id=pOrder.OrderSysID,
                update_time=datetime.now(),
            )
            self.gateway.add_order(order)
            if order.is_active():
                self.order_map[pOrder.OrderRef] = order

        if bIsLast:
            logger.info(f"订单信息查询成功")
            self.semaphore.release()

    def _run_query(self) -> None:
        """运行查询序列"""
        time.sleep(1)

        query_functions = [
            ("结算单确认", self.query_settlement),
            ("资金查询", self.query_account),
            ("合约查询", self.query_instrument),
            ("持仓查询", self.query_position),
            ("成交查询", self.query_trades),
            ("报单查询", self.query_orders),
        ]

        for i, (name, func) in enumerate(query_functions, 1):
            self.semaphore.acquire()
            logger.info(f"CTP 查询进度: [{i}/{len(query_functions)}] {name}")
            func()
            time.sleep(1)

        self.semaphore.acquire()
        logger.info("CTP 查询完成！")
        self.semaphore.release()
        self.is_ready = True
        self.gateway.on_status()

    def query_settlement(self) -> None:
        """查询结算单确认"""
        if not self.api or not self.connected:
            self.semaphore.release()
            return
        req = tdapi.CThostFtdcSettlementInfoConfirmField()
        req.BrokerID = self.broker
        req.InvestorID = self.user
        self.reqid += 1
        ret = self.api.ReqSettlementInfoConfirm(req, self.reqid)
        if ret != 0:
            logger.error(f"查询结算单失败，错误代码：{ret}")
            self.semaphore.release()

    def _get_temp_path(self, subdir: str) -> Path:
        """获取临时文件路径"""
        temp_dir = Path.home() / ".qtrader" / "temp" / f"ctp_{subdir}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir
    
    def _save_contracts(self) -> None:
        from src.utils.database import session_scope
        from src.models.po import ContractPo

        """保存合约信息到文件"""
        update_date = self.gateway._contracts_update_date
        contracts_to_save = []
        for item in self.gateway.contracts.values():
            symbol = item.symbol
            contract_po = ContractPo(
                    symbol=symbol,
                    exchange_id=item.exchange.value,
                    instrument_name=item.name,
                    product_type="FUTURES",
                    volume_multiple=item.multiple,
                    price_tick=item.pricetick,
                    min_volume=1,
                    option_strike=None,
                    option_underlying=None,
                    option_type=None,
                    update_date=update_date,
                )
            contracts_to_save.append(contract_po)
        if len(contracts_to_save) > 0:
            try:

                with session_scope() as session:
                    # 先删除历史数据
                    deleted_count = session.query(ContractPo).delete(synchronize_session=False)
                    logger.info(f"删除了 {deleted_count} 条旧合约信息")
                    # 批量插入新数据
                    session.add_all(contracts_to_save)
                    logger.info(f"成功保存 {len(contracts_to_save)} 个合约信息到数据库")
            except Exception as e:
                logger.exception(f"保存合约信息到数据库失败: {e}")
