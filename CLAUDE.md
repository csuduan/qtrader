# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。
项目概况请查看 @README.md 。


## 规范与约束
### 后端 (Python)
- **Python版本**: 3.12+，使用 `typing` 模块的类型提示
- **格式化**: Black 100字符行长度
- **导入顺序**: 标准库 → 第三方库 → 本地模块
- **命名规范**: 函数/变量使用 snake_case，类使用 CamelCase
- **文档字符串**: 中文，三引号，描述 Args/Returns
- **日志记录**: 使用 `src.utils.logger` 的 `get_logger(__name__)`
- **错误处理**: Try/except 配合 logger.exception()
- **数据模型**: SQLAlchemy ORM 使用 `__repr__`，API 模式使用 Pydantic
- **API开发**: FastAPI 异步端点，Config 中设置 `from_attributes = True`
- **注释**: 中文，简洁（除非有特殊要求，否则不写行内注释）
- **事件系统**: 使用事件引擎进行解耦通信，在 `EventTypes` 类中定义事件类型
- **强类型约束**: 方法的输出及输出应当明确指明类型
- **规范工具**: 可以使用black和isort格式化代码
```bash
black src/ --line-length 100 --target py38
isort src/ --profile black
```

### 前端 (Vue + TypeScript)
- **框架**: Vue 3 组合式 API (`<script setup>`)
- **语言**: TypeScript 严格模式
- **组件命名**: .vue 文件使用 PascalCase
- **文件命名**: 组件用 PascalCase，工具函数用 camelCase
- **状态管理**: Pinia stores 位于 `src/stores/`
- **API调用**: Axios HTTP 客户端位于 `src/api/`
- **WebSocket**: 自定义管理器位于 `src/ws.ts`
- **UI组件**: Element Plus
- **图表**: ECharts 数据可视化
- **lint**：使用ESLint和Prettier格式化代码，保持一致的代码风格
- **打包验证**：开发完后执行npm run build进行语法验证


### 前后端通信规范
**HTTP API**
- 基础URL：`/api`
- 响应包装：`{code: 0, message: "", data: {}}`
- Axios 拦截器在成功时自动解包 `data`
- 使用 `src.manager.api.responses` 中的 `success_response()` 和 `error_response()`

**WebSocket** (`/ws`)
- 消息格式：`{type: "...", data: {...}, timestamp: "..."}`
- 类型：`connected`, `account_update`, `position_update`, `trade_update`, `order_update`, `quote_update`, `tick_update`
- 账户信息缓存并每3秒推送一次（根据连接状态自动启动/停止）

### 数据类型约束

**通用字段类型**
- `id`: 整数（数据库主键）
- `account_id`: 字符串（交易账户ID）
- `symbol`: 字符串（合约代码，格式：EXCHANGE.symbol）
- `created_at/updated_at`: ISO 8601字符串
- 金额字段：浮点数，保留2位小数
- 数量字段：整数

**时间字段格式**
- 默认格式：ISO 8601字符串 (datetime → isoformat())
- **成交时间字段特殊处理**：`trade_date_time` 支持两种格式
  - **后端输出**：ISO 8601字符串（自动从 Unix 时间戳或 datetime 对象转换）
  - **前端接收**：`number | string`（兼容 Unix 时间戳秒或 ISO 字符串）
  - **后端处理逻辑**：
    - 支持 datetime 对象转换为 Unix 时间戳
    - 支持 int/float 类型的时间戳
    - 最终统一转换为 ISO 格式返回给前端
  - **前端处理逻辑**：
    - 排序时兼容两种格式（数字直接比较，字符串转换为 Date）
    - 显示时使用统一的日期格式化函数

**枚举类型**
- `direction`: "BUY" | "SELL"
- `offset`: "OPEN" | "CLOSE" | "CLOSETODAY"
- `status`: 订单状态字符串（由券商返回）
- `price_type`: 价格类型字符串

**类型同步规则**
1. 后端在 `src.manager.api.schemas.py` 定义Pydantic模型
2. 前端在 `web/src/types/index.ts` 定义对应的TypeScript接口
3. 字段名称、类型、结构必须保持一致
4. 可选字段使用Optional (Python) / | null (TypeScript)

### 错误处理规范

**后端错误处理**
- 全局异常处理器捕获所有未处理异常（`src.manager.api.responses.global_exception_handler`）
- HTTP异常由 `http_exception_handler` 处理
- 请求验证错误由 `validation_exception_handler` 处理
- 所有错误使用 `get_logger(__name__)` 记录日志

**前端错误处理**
- axios响应拦截器自动捕获code≠0的错误并抛出异常
- 网络错误统一处理并提示"网络请求失败"
- 具体业务错误由错误消息显示

### CORS配置
- 默认允许所有源：`allow_origins=["*"]`
- 支持自定义源列表：`config.api.cors_origins`
- 允许所有方法和请求头

### 安全规范
- 敏感信息（密码、API密钥）禁止在日志中输出
- WebSocket消息不包含敏感数据
- 前端不在URL或localStorage中存储敏感信息
- 错误响应避免暴露内部实现细节

### 测试规范
测试规范及方法参见 @TESTING.md

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

