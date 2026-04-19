"""
TqSdk 合约查询器
用于 Manager 进程独立查询合约基础信息（不需要完整交易 Gateway）
"""

import logging

from tqsdk import TqApi, TqAuth, TqKq
from tqsdk.exceptions import TqTimeoutError

logger = logging.getLogger(__name__)


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

    def fetch_contracts(self) -> list[dict] | None:
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
            return contracts
        except TqTimeoutError as e:
            logger.error(f"TqSdk 连接超时: {e}")
            return None
        except Exception as e:
            logger.exception(f"TqSdk 获取合约失败: {e}")
            return None
        finally:
            if api:
                try:
                    api.close()
                    logger.info("TqSdk API 已关闭")
                except Exception as e:
                    logger.warning(f"关闭 TqSdk API 失败: {e}")
