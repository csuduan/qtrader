from abc import ABC, abstractmethod
from qts.common.object import  TickData,BarData,OrderData,TradeData

class BaseStrategy(ABC):
    def __init__(self):
        pass

    def reload(self):
        '''
        重新加载策略
        1. 从配置文件中读取策略参数
        2. 初始化策略参数
        '''
        pass

    @abstractmethod
    def on_tick(self, tick:TickData):
        '''
        处理tick数据
        :param tick: tick数据
        '''
        pass

    @abstractmethod
    def on_bar(self, bar:BarData):
        '''
        处理bar数据
        :param bar: bar数据
        '''
        pass


    def get_config(self, key:str):
        '''
        获取策略参数
        :param key: 参数名
        :return: 参数值
        '''
        pass

    def open(self,symbol:str,price:float,volume:float):
        '''
        开仓
        '''
        pass

    def close(self,symbol:str,price:float,volume:float):
        '''
        平仓
        '''
        pass

    def cancel(self,order_id:str):
        '''
        撤销委托单
        :param order_id: 委托单ID
        '''
        pass