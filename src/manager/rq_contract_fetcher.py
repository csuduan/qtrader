"""
米筐数据服务合约查询器
通过 rqdatac 补充合约交易参数（最小开仓手数等）
"""

import logging
from datetime import datetime
from typing import Dict

import pandas as pd

logger = logging.getLogger(__name__)


class RqContractFetcher:
    """通过米筐 rqdatac 补充合约交易参数"""

    def __init__(self, username: str, password: str):
        """
        初始化

        Args:
            username: 米筐账户用户名
            password: 米筐账户密码
        """
        self.username = username
        self.password = password

    def fetch_min_order_quantities(self) -> Dict[str, int]:
        """
        查询活跃期货合约的最小开仓手数

        Returns:
            {order_book_id: min_order_qty}，key 格式如 "IF2605"（无交易所前缀）
            对于郑商所(CZCE)合约，同时返回短格式和长格式两种key，以便兼容TqSdk
        """
        import rqdatac

        rqdatac.init(username=self.username, password=self.password)
        logger.info("米筐 rqdatac 已初始化")

        # 获取所有期货合约列表
        futures = rqdatac.all_instruments(type="Future", date=None, market="cn")
        today = datetime.now().strftime("%Y-%m-%d")
        # 过滤活跃合约
        active = futures[futures["de_listed_date"] >= today]
        order_book_ids = active["order_book_id"].tolist()
        logger.info(f"米筐查询到 {len(order_book_ids)} 个活跃合约")

        # 查询交易参数
        params = rqdatac.futures.get_trading_parameters(
            order_book_ids=order_book_ids, market="cn"
        )
        df_min_order = params["min_order_quantity"]

        # 构建 order_book_id -> exchange 映射，用于判断郑商所合约
        ob_id_exchange = dict(zip(active["order_book_id"], active["exchange"]))

        result: Dict[str, int] = {}
        for ob_id in order_book_ids:
            if ob_id in df_min_order.index:
                series = df_min_order.loc[ob_id]
                if isinstance(series, pd.Series):
                    valid = series.dropna()
                    latest = int(valid.iloc[-1]) if len(valid) > 0 else 1
                else:
                    latest = int(series) if not pd.isna(series) else 1

                # 原始格式（米筐长格式）
                result[ob_id] = latest

                # 郑商所合约：米筐补齐为4位年份(如CF1701)，TqSdk用3位(如CF701)
                # 同时添加短格式key以便与TqSdk匹配
                exchange = ob_id_exchange.get(ob_id, "")
                if exchange.upper() in ("CZCE", "ZF", "郑商所"):
                    short_format = self._czce_to_short(ob_id)
                    if short_format != ob_id:
                        result[short_format] = latest

        logger.info(f"米筐获取了 {len(result)} 个合约的最小开仓手数（含短格式兼容）")
        return result

    @staticmethod
    def _czce_to_short(symbol: str) -> str:
        """
        将米筐郑商所合约代码从长格式转换为短格式

        米筐补齐规则：CF701 -> CF1701（补全年份以避免歧义）
        TqSdk使用短格式：CF701

        Args:
            symbol: 长格式合约代码，如 "CF1701"

        Returns:
            短格式合约代码，如 "CF701"
        """
        import re

        match = re.match(r'^([A-Za-z]+)(\d{4})$', symbol)
        if not match:
            return symbol

        product = match.group(1)
        year_month = match.group(2)
        # 去掉年份首位：1701 -> 701
        return f"{product}{year_month[1:]}"
