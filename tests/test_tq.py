# 引入TqSdk模块
from tqsdk import TqApi, TqAuth
from datetime import datetime, timedelta
# 创建api实例，设置web_gui=True生成图形化界面
api = TqApi(web_gui=True, auth=TqAuth("csuduan", "715300"))
# 订阅 ni2010 合约的10秒线
kline = api.get_kline_serial("CFFEX.IM2603", 60*5,data_length=600).copy()
api.wait_update()
kline['datetime'] = kline['datetime'].apply(lambda x: datetime.fromtimestamp(x/1e9))
today_kline = kline[kline['datetime'].dt.date == (datetime.now() - timedelta(days=1)).date()]
while True:
    # 通过wait_update刷新数据
    api.wait_update()