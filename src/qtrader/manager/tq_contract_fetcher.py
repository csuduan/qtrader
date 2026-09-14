"""
TqSdk 合约查询器
用于 Manager 进程独立查询合约基础信息（不需要完整交易 Gateway）
"""

from typing import Any

from tqsdk import TqApi, TqAuth, TqKq
from tqsdk.exceptions import TqTimeoutError

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


class TqContractFetcher:
    """通过 TqSdk 查询合约基础信息"""

    def __init__(self, username: str, password: str):
        """
        初始化

        Args:
            username: 天勤账户用户名
            password: 天勤账户密码
        """
        self.auth = TqAuth(username, password)

    def fetch_contracts(self) -> list[dict[str, Any]] | None:
        """
        查询所有活跃期货合约基础信息（同步阻塞方法）

        使用 TqKq() 模拟账户，不需要实盘连接。

        Returns:
            合约信息字典列表，每个字典包含:
            - symbol: "EXCHANGE.code" 格式，如 "SHFE.rb2505"
            - exchange_id: 交易所代码
            - instrument_name: 合约名称
            - product_type: 产品类型
            - volume_multiple: 合约乘数
            - price_tick: 最小变动价位
            如果获取失败返回 None
        """
        api = None
        try:
            logger.info("正在连接 TqSdk...")
            api = TqApi(TqKq(), auth=self.auth)
            logger.info("TqSdk 连接成功，正在查询合约信息...")

            quotes = api.query_quotes(ins_class=["FUTURE"], expired=False)
            quotes = [x for x in quotes if len(x) <= 12]
            symbol_infos = api.query_symbol_info(quotes)
            logger.info(f"TqSdk 查询到 {len(symbol_infos)} 个合约")

            contracts = []
            for _, item in symbol_infos.iterrows():
                instrument_id = item.instrument_id
                if "." in instrument_id:
                    symbol = instrument_id.split(".")[1]
                    exchange_id = item.exchange_id
                else:
                    symbol = instrument_id
                    exchange_id = item.get("exchange_id", "")

                contracts.append(
                    {
                        "symbol": symbol,  # 格式: "rb2505" (无交易所前缀)
                        "exchange_id": exchange_id,
                        "instrument_name": item.instrument_name,
                        "product_type": "FUTURES",
                        "volume_multiple": item.volume_multiple,
                        "price_tick": item.price_tick,
                    }
                )

            logger.info(f"TqSdk 合约解析完成，共 {len(contracts)} 个")
            self._mark_dominant_contracts(api, contracts)
            return contracts
        except TqTimeoutError as e:
            logger.error("TqSdk 连接超时: {!r}", e)
            return None
        except Exception:
            logger.exception("TqSdk 获取合约失败")
            return None
        finally:
            if api:
                try:
                    api.close()
                    logger.info("TqSdk API 已关闭")
                except Exception as e:
                    logger.warning("关闭 TqSdk API 失败: {!r}", e)

    @staticmethod
    def _mark_dominant_contracts(api: TqApi, contracts: list[dict[str, Any]]) -> None:
        """
        标记主力合约（打标失败不阻塞主流程，仅全部置 False）

        通过 KQ.m@EXCH.product 主连合约的 underlying_symbol 判定当前主力，
        如 KQ.m@SHFE.rb → SHFE.rb2701。用 get_quote_list 批量订阅一次就绪。
        """
        try:
            # 提取品种集合 (exchange, product前缀)，同品种共用一次主连查询。
            # 仅境内期货交易所支持 KQ.m 主连（KQD 外盘等无主连，跳过）；
            # 剔除 DCE 月均/组合合约的尾部 F 后缀（如 l2703F → l）
            _kq_exchanges = {"CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"}
            products: set[tuple[str, str]] = set()
            for c in contracts:
                if c["exchange_id"] not in _kq_exchanges:
                    continue
                code = str(c["symbol"]).rstrip("F")
                product = "".join(ch for ch in code if not ch.isdigit())
                if product:
                    products.add((c["exchange_id"], product))

            # 批量订阅全部主连，等待数据就绪后统一读取
            kq_symbols = [f"KQ.m@{exch}.{product}" for exch, product in sorted(products)]
            dominant: set[str] = set()
            if kq_symbols:
                quote_list = api.get_quote_list(kq_symbols)
                for kq_symbol, quote in zip(kq_symbols, quote_list, strict=True):
                    underlying = quote.underlying_symbol
                    if underlying:
                        dominant.add(underlying.split(".")[-1])
                    else:
                        logger.debug(f"主连无 underlying_symbol: {kq_symbol}")

            marked = 0
            for c in contracts:
                c["is_main"] = c["symbol"] in dominant
                marked += 1 if c["is_main"] else 0
            logger.info(f"主力合约打标完成: {marked}/{len(contracts)}")
        except Exception as e:
            logger.warning("主力合约打标失败（不影响主流程）: {!r}", e)
            for c in contracts:
                c["is_main"] = False
