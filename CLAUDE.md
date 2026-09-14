# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码库中工作时提供指导。
项目概况请查看 @README.md 。

## 原则
### 1. 编码前思考
**不要假设。不要隐藏困惑。呈现权衡。**
- **明确说明假设** — 如果不确定，询问而不是猜测
- **呈现多种解释** — 当存在歧义时，不要默默选择
- **适时提出异议** — 如果存在更简单的方法，说出来
- **困惑时停下来** — 指出不清楚的地方并要求澄清

### 2. 简洁优先
**用最少的代码解决问题。不要过度推测。**
- 不要添加要求之外的功能
- 不要为一次性代码创建抽象
- 不要添加未要求的"灵活性"或"可配置性"
- 不要为不可能发生的场景做错误处理
- 如果 200 行代码可以写成 50 行，重写它

**检验标准：** 资深工程师会觉得这过于复杂吗？如果是，简化。

### 3. 精准修改
**只碰必须碰的。只清理自己造成的混乱。**
编辑现有代码时：
- 不要"改进"相邻的代码、注释或格式
- 不要重构没坏的东西
- 匹配现有风格，即使你更倾向于不同的写法
- 如果注意到无关的死代码，提一下 —— 不要删除它

当你的改动产生孤儿代码时：
- 删除因你的改动而变得无用的导入/变量/函数
- 不要删除预先存在的死代码，除非被要求
**检验标准：** 每一行修改都应该能直接追溯到用户的请求。

### 4. 目标驱动执行

**定义成功标准。循环验证直到达成。**
将指令式任务转化为可验证的目标：
- 添加验证" -> 为无效输入编写测试，然后让它们通过
- 修复 bug" -> 编写重现 bug 的测试，然后让它通过
- 重构 X" -> 确保重构前后测试都能通过，然后让它们通过
对于多步骤任务，说明一个简短的计划：
```
1. [步骤] → 验证: [检查]
2. [步骤] → 验证: [检查]
3. [步骤] → 验证: [检查]
```
强有力的成功标准让 LLM 能够独立循环执行。弱标准（"让它工作"）需要不断澄清。



## 规范与约束
### 后端 (Python)
- **Python版本**: 3.12+，使用 `typing` 模块的类型提示
- **格式化**: Ruff 100字符行长度（format 接替 Black，lint I 规则接替 isort）
- **导入顺序**: 标准库 → 第三方库 → 本地模块
- **命名规范**: 函数/变量使用 snake_case，类使用 CamelCase
- **文档字符串**: 中文，三引号，描述 Args/Returns
- **日志记录**: 使用 `qtrader.utils.logger` 的 `get_logger(__name__)`
- **错误处理**: 异常日志两种形态——需要堆栈 `logger.exception("动作失败")`（堆栈本身已含异常信息，消息不再重复插值异常，可保留普通上下文如 `logger.exception("策略 [{}] 失败", name)`），预期内失败无堆栈 `logger.error("动作失败: {!r}", e)`；方法整体"仅打日志"的兜底优先用 `@logger.catch(message="动作失败")`（总是带堆栈、吞异常返回 None，等价于 try 包裹全函数体；无堆栈场景不可用，仍用 try/except）；异常值用 `{!r}` 位置参数（loguru 延迟格式化），禁止 `exc_info=True`（loguru 不支持该参数）；except 块外记录异常对象用 `logger.opt(exception=exc).error("描述")`；全库统一 loguru（含合约 fetcher），无 stdlib logging
- **数据模型**: SQLAlchemy ORM (`qtrader.models.po`) 使用 `__repr__`，API 模式使用 Pydantic (`qtrader.manager.api.schemas`)
- **API开发**: FastAPI 异步端点，Config 中设置 `from_attributes = True`
- **注释**: 中文，简洁（除非有特殊要求，否则不写行内注释）
- **事件系统**: 使用事件引擎进行解耦通信，在 `EventTypes` 类中定义事件类型
- **强类型约束**: 方法的输入及输出应当明确指明类型
- **规范工具**: 使用 ruff 检查并格式化代码
```bash
make format   # 或: ruff check --fix src/ && ruff format src/
```

### 前端 (Vue + TypeScript)
- **框架**: Vue 3 组合式 API (`<script setup>`)
- **语言**: TypeScript 严格模式
- **组件命名**: .vue 文件使用 PascalCase
- **文件命名**: 组件用 PascalCase，工具函数用 camelCase
- **状态管理**: Pinia stores 位于 `web/src/stores/`
- **API调用**: Axios HTTP 客户端位于 `web/src/api/`
- **WebSocket**: 自定义管理器位于 `web/src/ws.ts`
- **UI组件**: Element Plus
- **图表**: ECharts 数据可视化
- **lint**：使用ESLint和Prettier格式化代码，保持一致的代码风格
- **打包验证**：开发完后执行 `npm run build` 进行语法验证

### 前后端通信规范
**HTTP API**
- 基础URL：`/api`
- 响应包装：`{code: 0, message: "", data: {}}`
- Axios 拦截器在成功时自动解包 `data`
- 使用 `qtrader.manager.api.responses` 中的 `success_response()` 和 `error_response()`

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
1. 后端在 `qtrader.manager.api.schemas` 定义Pydantic模型
2. 前端在 `web/src/types/index.ts` 定义对应的TypeScript接口
3. 字段名称、类型、结构必须保持一致
4. 可选字段使用Optional (Python) / | null (TypeScript)

### 错误处理规范

**后端错误处理**
- 全局异常处理器捕获所有未处理异常（`qtrader.manager.api.responses.global_exception_handler`）
- HTTP异常由 `http_exception_handler` 处理
- 请求验证错误由 `validation_exception_handler` 处理
- 所有错误使用 `get_logger(__name__)` 记录日志

**前端错误处理**
- axios响应拦截器自动捕获code≠0的错误并抛出异常
- 网络错误统一处理并提示"网络请求失败"
- 具体业务错误由错误消息显示


### 安全规范
- 敏感信息（密码、API密钥）禁止在日志中输出
- WebSocket消息不包含敏感数据
- 前端不在URL或localStorage中存储敏感信息
- 错误响应避免暴露内部实现细节

### 测试规范
测试规范及方法参见 @tests/TESTING.md

## 架构概览

```
Manager 进程 (run_manager.py)          Trader 进程 (run_trader.py --account-id xxx)
┌─────────────────────────┐            ┌──────────────────────────────────────┐
│ FastAPI + WebSocket     │            │ Trader (主类，协调所有子组件)          │
│ TradingManager          │◄─Unix──►  │   ├── TradingEngine (→ Gateway)      │
│ TraderProxy (进程管理)   │  Socket   │   ├── StrategyManager → Strategy     │
│ 数据持久化 (PostgreSQL)   │            │   ├── SwitchPosManager (换仓)        │
└─────────────────────────┘            │   ├── JobManager (定时任务)           │
                                       │   ├── RiskControl (风控)             │
                                       │   └── TraderReqHandler (IPC请求)     │
                                       └──────────────────────────────────────┘
```

**关键调用链**:
```
Gateway → TradingEngine.emit() → EventTypes → StrategyManager._dispatch_event() → Strategy.on_*()
策略下单: Strategy → strategy_manager.buy/sell() → TradingEngine → Gateway.insert_order()
IPC请求: Manager → TraderProxy → SocketClient → SocketServer → TraderReqHandler → TradingEngine
```

**Gateway** (`qtrader.trader.gateway`): `BaseGateway`(抽象) → `TqGateway`(TqSdk) / `CtpGateway`(CTP)
**数据模型**: Pydantic (`qtrader.models.object`) + SQLAlchemy PO (`qtrader.models.po`)，属性访问，禁止 `.get()`
**DAO层** (`qtrader.trader.dao`): Pydantic ↔ PO 转换和持久化
**事件引擎**: `qtrader.utils.async_event_engine.EventTypes`，行情分发给所有策略，订单/成交按 `order_strategy_map` 分发
**IPC协议**: `qtrader.utils.ipc.protocol`，orjson 序列化，消息类型: `HEARTBEAT/REQUEST/RESPONSE/PUSH/ERROR`
**数据库**: PostgreSQL (asyncpg 异步驱动)，`get_async_session()` context manager
**配置**: `config/config.yaml`(全局) + `config/account-{ID}.yaml`(含 `strategies` 字段)

## 常用命令

```bash
# 格式化
make format

# 代码检查
make lint

# 综合检查（先 mypy 静态检查，再 lint）
make check

# 单元测试
make test-unit

# API 集成测试（需先启动后端）
make test-api

# 全部测试
make test-all

# 测试覆盖率
make test-coverage

# 安装依赖
make install
```
