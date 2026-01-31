# CTP适配器和策略系统

## 概述

本文档描述Q-Trader新增的CTP适配器和策略系统架构。

---

## 一、架构设计

### 1.1 抽象数据模型层 (`src/models/object.py`)

定义统一的数据模型，作为所有外部接口的契约：

#### 枚举类型
- `Direction`: BUY/SELL（买卖方向）
- `Offset`: OPEN/CLOSE/CLOSETODAY/CLOSEYESTERDAY（开平类型）
- `Status`: SUBMITTING/NOTTRADED/PARTTRADED/ALLTRADED/CANCELLED/REJECTED（订单状态）
- `OrderType`: LIMIT/MARKET/FOK/FAK（订单类型）
- `Exchange`: CFFEX/SHFE/CZCE/DCE/INE/GFEX/SSE/SZSE（交易所）
- `ProductType`: FUTURES/OPTION/SPOT/INDEX/ETF（产品类型）
- `Interval`: tick/1m/1h/d/w（K线周期）
- `StrategyType`: tick/bar/both（策略驱动类型）

#### 核心数据模型
- `TickData`: Tick行情数据
- `BarData`: K线数据
- `OrderData`: 订单数据
- `TradeData`: 成交数据
- `PositionData`: 持仓数据
- `AccountData`: 账户数据
- `ContractData`: 合约数据

#### 请求模型
- `SubscribeRequest`: 订阅请求
- `OrderRequest`: 下单请求
- `CancelRequest`: 撤单请求

---

### 1.2 适配器层 (`src/adapters/`)

#### BaseGateway (`base_gateway.py`)
统一的交易接口抽象基类，定义接口契约：

- **连接管理**: `connect()`, `disconnect()`
- **行情订阅**: `subscribe()`, `unsubscribe()`
- **交易接口**: `send_order()`, `cancel_order()`
- **查询接口**: `query_account()`, `query_position()`, `query_orders()`, `query_trades()`, `query_contracts()`
- **回调机制**: `register_callbacks()`, `register_strategy_callbacks()`

#### TqGateway (`tq_gateway.py`)
TqSdk适配器实现，包装现有TradingEngine：
- 数据格式转换（TqSdk → 统一模型）
- 完成所有BaseGateway接口

#### CtpGateway (`ctp_gateway.py`)
CTP适配器框架实现（预留）：
- 占位实现，需要CTP SDK
- 预留数据转换方法

---

### 1.3 策略系统 (`src/strategy/`)

#### BaseStrategy (`strategy_manager.py`)
策略抽象基类：
- **生命周期**: `init()`, `start()`, `stop()`, `reload()`
- **事件回调**: `on_tick()`, `on_bar()`, `on_order()`, `on_trade()`
- **交易接口**: `buy()`, `sell()`, `cancel_order()`

#### StrategyManager (`strategy_manager.py`)
策略管理器：
- **配置加载**: `load_config()` - 从YAML加载策略配置
- **策略管理**: `add_strategy()`, `start_strategy()`, `stop_strategy()`, `start_all()`, `stop_all()`
- **状态查询**: `get_status()` - 获取所有策略状态

---

## 二、K线生成器 (`src/utils/bar_generator.py`)

从tick数据合成多周期bar数据：
- 支持周期：1m/5m/15m/1h/d
- 缓存历史bar数据
- 自动OHLCV聚合

主要方法：
- `update_tick(tick)`: 更新tick并生成1分钟bar
- `_generate_higher_bars(tick)`: 生成更高周期bar
- `get_bar(symbol, interval, n)`: 获取最新N根bar
- `get_bars(symbol, interval, count)`: 获取最新N根bar列表

---

## 三、策略配置 (`config/strategies.yaml`)

策略配置文件格式：

```yaml
strategies:
  rsi_strategy:
    enabled: true
    strategy_type: bar  # tick 或 bar
    symbol: "DCE.IM2605"
    exchange: "DCE"
    volume_per_trade: 1
    max_position: 5

    # RSI参数
    rsi_period: 14
    overbought: 70
    oversold: 30

    # 止盈止损
    take_profit_pct: 0.02
    stop_loss_pct: 0.01
    fee_rate: 0.0001

    # 交易窗口
    trade_start_time: "09:30:00"
    trade_end_time: "14:50:00"
    force_exit_time: "14:55:00"

    # 交易限制
    one_trade_per_day: true
    params_file: null
```

---

## 四、API接口 (`src/api/routes/strategy.py`)

策略管理API：

- `GET /strategies` - 获取策略列表
- `GET /strategies/{strategy_id}` - 获取策略状态
- `POST /strategies/{strategy_id}/start` - 启动策略
- `POST /strategies/{strategy_id}/stop` - 停止策略
- `POST /strategies/start-all` - 启动所有策略
- `POST /strategies/stop-all` - 停止所有策略

---

## 五、TradingEngine集成 (`src/trading_engine.py`)

新增方法支持Gateway和策略系统：

- `init_gateway_adapter()`: 初始化Gateway适配器
- `connect_gateway()`: 通过Gateway适配器连接
- `send_order_via_gateway()`: 通过Gateway适配器下单
- `cancel_order_via_gateway()`: 通过Gateway适配器撤单
- `init_strategy_system()`: 初始化策略系统
- `register_strategy_callbacks()`: 注册策略回调
- `_dispatch_to_strategies()`: 分发数据到策略
- `start_all_strategies()`: 启动所有策略
- `stop_all_strategies()`: 停止所有策略
- `get_strategy_status()`: 获取策略状态

---

## 六、前端类型同步 (`web/src/types/index.ts`)

新增TypeScript类型定义：

- 枚举类型：`Direction`, `Offset`, `OrderStatus`, `OrderType`, `Exchange`, `ProductType`, `Interval`, `StrategyType`
- 统一数据模型：`TickData`, `BarData`, `OrderData`, `TradeData`, `PositionData`, `AccountData`, `ContractData`
- 策略相关：`StrategyConfig`, `StrategyStatus`, `StrategySignal`, `StrategyEventType`

---

## 七、使用示例

### 7.1 启动策略系统

```python
from src.context import get_trading_engine

# 获取TradingEngine
engine = get_trading_engine()

# 初始化Gateway适配器
engine.init_gateway_adapter()

# 初始化策略系统
engine.init_strategy_system("config/strategies.yaml")

# 连接Gateway
engine.connect_gateway()

# 注册策略回调
engine.register_strategy_callbacks()

# 启动所有策略
engine.start_all_strategies()
```

### 7.2 创建自定义策略

```python
from src.strategy.strategy_manager import BaseStrategy
from src.models.object import TickData, BarData, Offset

class MyStrategy(BaseStrategy):
    def __init__(self, strategy_id, config):
        super().__init__(strategy_id, config)
        self.bar_count = 0

    def on_tick(self, tick: TickData):
        """Tick行情处理"""
        if not self.active:
            return

        # 策略逻辑
        if self._should_buy(tick):
            self.buy(tick.symbol, 1)

    def on_bar(self, bar: BarData):
        """Bar行情处理"""
        if not self.active:
            return

        self.bar_count += 1

        # 策略逻辑
        if self._should_buy(bar):
            self.buy(bar.symbol, 1)

    def _should_buy(self, data) -> bool:
        """自定义买入逻辑"""
        # 实现具体的买入条件判断
        return False
```

---

## 八、CTP适配器扩展

当需要使用CTP接口时：

1. 安装CTP SDK（如`vnpy`的CTP封装）
2. 实现CTP回调方法（OnRtnOrder, OnRtnTrade等）
3. 完成数据转换逻辑（已在框架中占位）

参考实现：`/opt/dev/qts/qts/trader/gateway`

---

## 九、注意事项

1. **兼容性**: 现有TradingEngine API保持向后兼容
2. **扩展性**: 新增Gateway只需实现BaseGateway接口
3. **策略隔离**: 每个策略维护独立状态，互不干扰
4. **类型安全**: 使用Pydantic模型保证数据完整性
5. **事件驱动**: 通过回调机制解耦组件

---

## 十、分支信息

**分支名称**: `feature/ctp-adapter-strategy-system`

**提交历史**:
```
8e0c34b [feature] 完成配置加载器和前端类型同步
5df9158 [feature] 完成TradingEngine集成和K线生成器
db3af7a [feature] 添加CTP适配器框架和策略管理器
a27cecd [feature] 实现CTP适配器和策略系统基础架构
```

---

## 十一、文件清单

### 新增文件（8个）
- `src/models/object.py` - 统一数据模型
- `src/adapters/base_gateway.py` - Gateway基类
- `src/adapters/tq_gateway.py` - TqSdk适配器
- `src/adapters/ctp_gateway.py` - CTP适配器框架
- `src/strategy/strategy_manager.py` - 策略管理器
- `config/strategies.yaml` - 策略配置文件
- `src/utils/bar_generator.py` - K线生成器
- `src/api/routes/strategy.py` - 策略API路由

### 修改文件（7个）
- `src/trading_engine.py` - 添加Gateway和策略系统支持
- `src/utils/config_loader.py` - 添加策略配置加载
- `src/api/app.py` - 注册策略路由
- `src/api/websocket_manager.py` - 添加策略事件推送
- `web/src/types/index.ts` - 同步前端类型定义
- `src/strategy/base_strategy.py` - 重写策略基类
- `src/strategy/strategy_rsi_demo.py` - 重写RSI策略

**总计**: 15个文件，新增约3000行代码

---

## 十二、待扩展功能

以下功能已预留接口，可根据需要实现：

1. **CTP适配器完整实现**: 需要CTP SDK环境
2. **RSI策略重构**: 移除qts依赖，使用新框架
3. **数据库模型扩展**: 添加策略配置表
4. **测试覆盖**: 策略框架和Gateway测试
5. **更多策略示例**: 均线交叉、Tick突破等

---

**文档版本**: 1.0  
**更新时间**: 2026-01-21
