# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。
更多项目概况和规则请在 @AGENTS.md 中查看和维护。

## 启动

### 后端 (Python)
```bash
# 激活虚拟环境
conda activate qts
# 安装依赖(可选)
pip install -r requirements.txt

# 运行管理平台 (Manager 进程)
python -m src.run_manager

# 运行交易账户 (Trader 进程)
python -m src.run_trader --account-id DQ

# 格式化代码
black src/ --line-length 100 --target py38
isort src/ --profile black

# 检查运行进程
lsof -i :8000  # Manager API 端口
```

### 前端 (Vue)
```bash
cd web
npm install
npm run dev     # 开发服务器 (默认端口5173，代理到8000)
```

### 使用 Chrome DevTools 测试
使用 `chrome-devtools` MCP 工具测试前端：
1. 启动 Manager (`python -m src.run_manager`) 和前端 (`cd web && npm run dev`)
2. 使用 `new_page` 导航到 `http://localhost:5173`
3. 使用 `take_snapshot` 检查页面结构
4. 使用 `list_console_messages` 检查错误

## 架构概览

### 多进程架构 (Manager-Trader 分离)

**Manager 进程** (`src/run_manager.py`)
- Web 服务、API 路由、WebSocket 连接管理
- 通过 TraderProxy 与 Trader 进程通信 (Unix Socket)
- 管理多个 Trader 进程的生命周期
- 数据持久化（Manager 本地数据库）

**Trader 进程** (`src/run_trader.py`)
- 独立进程执行交易逻辑
- 每个账户一个独立 Trader 进程
- 通过 Unix Socket 与 Manager 通信
- 独立数据库、独立进程、互不干扰

### 核心组件

**TradingEngine** (`src/trader/trading_engine.py`)
- Trader 进程内的中央协调器
- 管理 Gateway 抽象层 (TqSdk, CTP)
- 属性委托给 Gateway：`account`, `positions`, `orders`, `trades`, `quotes`
- 事件驱动：通过 `src.utils.event.event_engine` 触发事件
- 不包含业务逻辑 - 委托给 Gateway

**Gateway 模式** (`src/trader/gateway/`)
- `BaseGateway`：所有交易适配器的抽象接口
- `TqGateway`：TqSdk 实现
- `CtpGateway`：CTP 实现
- 方法：`connect()`, `disconnect()`, `insert_order()`, `cancel_order()`, `subscribe_symbol()`
- 返回类型来自 `src.models.object`：`AccountData`, `PositionData`, `OrderData`, `TradeData`, `TickData`

**策略系统** (`src/trader/strategy/`)
- `BaseStrategy`：基类，持有 `strategy_manager` 引用（不直接访问 `trading_engine`）
- `StrategyManager`：管理策略生命周期、路由事件、处理交易
- **关键**：策略调用 `strategy_manager.buy/sell/cancel_order()`，而非直接调用 `trading_engine`
- `order_strategy_map: Dict[str, str]` 映射 `order_id -> strategy_id`
- 事件根据订单所有权分发给策略
- 策略配置在 `config/strategies.yaml`，CSV参数在 `data/params/`

**数据模型** (`src/models/object.py`)
- Pydantic 模型：`TickData`, `BarData`, `OrderData`, `TradeData`, `PositionData`, `AccountData`
- 使用**属性访问** (`order.order_id`)，而非 `.get()` 方法
- `OrderData.volume` 是委托数量，`OrderData.traded` 是已成交数量，`volume_left` 是计算属性

### 事件流
```
Gateway -> TradingEngine.emit() -> EventTypes -> StrategyManager._dispatch_event() -> Strategy.on_*()
```

- 事件类型在 `src.utils.event.EventTypes` 中定义
- 行情事件分发给所有活跃策略
- 订单/成交事件只分发给拥有该订单的策略（通过 `order_strategy_map`）

### Manager-Trader 通信

**Unix Socket 通信**
- Manager 通过 `TraderProxy` 与 Trader 进程通信
- Socket 文件位于 `config.socket.socket_dir`
- 消息类型：状态查询、报单、撤单、订阅等

**数据同步**
- Trader 进程推送实时数据到 Manager
- Manager 缓存数据并通过 WebSocket 推送给前端
- 账户信息每3秒批量推送（缓存机制）

### 前后端通信

**HTTP API**
- 基础URL：`/api`
- 响应包装：`{code: 0, message: "", data: {}}`
- Axios 拦截器在成功时自动解包 `data`
- 使用 `src.manager.api.responses` 中的 `success_response()` 和 `error_response()`

**WebSocket** (`/ws`)
- 消息格式：`{type: "...", data: {...}, timestamp: "..."}`
- 类型：`connected`, `account_update`, `position_update`, `trade_update`, `order_update`, `quote_update`, `tick_update`
- 账户信息缓存并每3秒推送一次（根据连接状态自动启动/停止）

### 关键文件

| 文件 | 用途 |
|------|------|
| `src/run_manager.py` | Manager 进程入口 |
| `src/run_trader.py` | Trader 进程入口 |
| `src/manager/app.py` | Manager 应用主逻辑 |
| `src/trader/app.py` | Trader 应用主逻辑 |
| `src/utils/config_loader.py` | YAML配置解析 (account_type, paths, risk_control) |
| `src/trader/trading_engine.py` | Trader 中央协调器 |
| `src/trader/gateway/base_gateway.py` | Gateway接口 |
| `src/models/object.py` | Pydantic数据模型 |
| `src/trader/strategy_manager.py` | 策略生命周期和事件路由 |
| `src/trader/strategy/base_strategy.py` | 策略基类 |
| `src/manager/manager.py` | TradingManager 交易管理器 |
| `src/manager/trader_proxy.py` | TraderProxy 代理类 |
| `src/manager/api/routes/` | FastAPI路由处理器 |
| `src/utils/scheduler.py` | APScheduler任务管理 |
| `src/manager/api/schemas.py` | API响应模型 |
