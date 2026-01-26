# Agent 开发指南

## 启动
### 后端 (Python)
```bash
# 激活虚拟环境
conda activate qts
# 安装依赖(可选)
pip install -r requirements.txt

# 运行主服务
python -m src.main

# 格式化代码
black src/ --line-length 100 --target py38
isort src/ --profile black

# 检查运行进程
lsof -i :8000  # 后端API
```

### 前端 (Vue)
```bash
cd web
npm install
npm run dev     # 开发服务器 (默认端口5173，代理到8000)
```

### 使用 Chrome DevTools 测试
使用 `chrome-devtools` MCP 工具测试前端：
1. 启动后端 (`python -m src.main`) 和前端 (`cd web && npm run dev`)
2. 使用 `new_page` 导航到 `http://localhost:5173`
3. 使用 `take_snapshot` 检查页面结构
4. 使用 `list_console_messages` 检查错误


## 代码规范

### 后端 (Python)
- **Python版本**: 3.8+，使用 `typing` 模块的类型提示
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

## 架构说明

### 事件驱动系统
- 交易引擎使用事件引擎进行解耦通知
- 事件在 `update()` 方法中的 `api.wait_update()` 之后触发
- 事件类型在 `src.trading_engine.EventTypes` 类中定义
- 全局事件引擎: `src.utils.event.event_engine`
- 使用示例见 `examples/event_usage.py`

### 重要约束
1. **策略不得直接访问 `trading_engine`** - 必须使用 `strategy_manager`
2. **Pydantic模型始终使用属性访问** (`order.order_id` 而非 `order.get("order_id")`)
3. **事件处理器应在 Gateway 的 `update()` 方法中的 `api.wait_update()` 之后触发**
4. **账户信息采用缓存机制** - 每3秒批量更新并通过WebSocket推送
5. **追踪订单所有权** - 每个订单映射到创建它的策略，据此进行事件路由

### 前后端通信规范

#### HTTP API 规范
**请求格式**
- Content-Type: `application/json`
- Base URL: `/api`
- 所有请求和响应使用UTF-8编码
- 时间字段格式：ISO 8601字符串 (datetime → isoformat())
- 数值精度：金额/价格保留2位小数，数量使用整数

**统一响应结构**
```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```
- `code`: 0表示成功，非0表示错误
- `message`: 操作结果描述
- `data`: 响应数据对象，无数据时为null

**错误响应结构**
```json
{
  "code": 9999,
  "message": "错误信息"
}
```
- `code=400`: 请求参数验证失败
- `code=500`: 服务器内部错误
- `code=9999`: 其他业务错误

**后端实现**
- 使用 `src.api.responses.success_response()` 包装成功响应
- 使用 `src.api.responses.error_response()` 包装错误响应
- Pydantic模型通过 `from_attributes = True` 自动序列化ORM对象
- 日期时间自动转换为ISO格式字符串

**前端实现**
- 使用 `web/src/api/request.ts` 的axios实例
- 响应拦截器自动解包 `data` 字段，code=0时返回data，非0时抛出异常
- 使用 `web/src/types/index.ts` 中定义的TypeScript接口
- API调用示例见 `web/src/api/*.ts`

#### WebSocket 规范
**连接**
- URL: `/ws`
- 连接建立后发送connected确认消息

**消息格式**
```json
{
  "type": "message_type",
  "data": {},
  "timestamp": "2026-01-16T10:30:00.123456"
}
```

**服务端推送消息类型**
- `connected`: 连接成功
- `account_update`: 账户信息更新（每3秒推送一次，使用缓存机制）
- `position_update`: 持仓信息更新（实时）
- `trade_update`: 成交记录更新（实时）
- `order_update`: 委托单状态更新（实时）
- `quote_update`: 行情数据更新（实时）
- `tick_update`: tick数据更新（实时）
- `system_status`: 系统状态更新
- `log_update`: 日志更新
- `alarm_update`: 告警更新

**WebSocket推送优化**
- 账户信息采用缓存机制，收到更新时只缓存最新数据
- 定时任务每3秒推送一次缓存的最新账户数据
- 无连接时自动停止推送任务，有连接时自动启动
- 其他类型数据（持仓、成交、委托单、行情）实时推送

**客户端发送消息类型**
- `subscribe_logs`: 订阅日志流
- `unsubscribe_logs`: 取消订阅日志流

**前端实现**
- 使用 `web/src/ws.ts` 的WebSocketManager单例
- 支持自动重连（最多5次，间隔3秒）
- 提供订阅/取消订阅各类更新的方法

#### 数据类型约束

**通用字段类型**
- `id`: 整数（数据库主键）
- `account_id`: 字符串（交易账户ID）
- `symbol`: 字符串（合约代码，格式：EXCHANGE.symbol）
- `created_at/updated_at`: ISO 8601字符串
- 金额字段：浮点数，保留2位小数
- 数量字段：整数

**枚举类型**
- `direction`: "BUY" | "SELL"
- `offset`: "OPEN" | "CLOSE" | "CLOSETODAY"
- `status`: 订单状态字符串（由券商返回）
- `price_type`: 价格类型字符串

**类型同步规则**
1. 后端在 `src/api/schemas.py` 定义Pydantic模型
2. 前端在 `web/src/types/index.ts` 定义对应的TypeScript接口
3. 字段名称、类型、结构必须保持一致
4. 可选字段使用Optional (Python) / | null (TypeScript)

#### 错误处理规范

**后端错误处理**
- 全局异常处理器捕获所有未处理异常（`src.api.responses.global_exception_handler`）
- HTTP异常由 `http_exception_handler` 处理
- 请求验证错误由 `validation_exception_handler` 处理
- 所有错误使用 `get_logger(__name__)` 记录日志

**前端错误处理**
- axios响应拦截器自动捕获code≠0的错误并抛出异常
- 网络错误统一处理并提示"网络请求失败"
- 具体业务错误由错误消息显示

#### CORS配置
- 默认允许所有源：`allow_origins=["*"]`
- 支持自定义源列表：`config.api.cors_origins`
- 允许所有方法和请求头

#### 安全规范
- 敏感信息（密码、API密钥）禁止在日志中输出
- WebSocket消息不包含敏感数据
- 前端不在URL或localStorage中存储敏感信息
- 错误响应避免暴露内部实现细节

## 测试方法

### 启动后端服务
```bash
# 方式1：直接运行
python -m src.main

# 方式2：后台运行（推荐）
powershell -Command "Start-Process -FilePath 'python' -ArgumentList '-m','src.main' -WorkingDirectory 'D:\dev\py-trade' -WindowStyle Hidden"

# 检查后端是否启动
netstat -ano | findstr ":8000"
```

### 启动前端服务
```bash
cd web
npm run dev

# 默认端口3000，如果被占用会自动使用其他端口（如3001）
# 访问地址：http://localhost:3000
```

### 使用Chrome DevTools测试
1. 启动后端和前端服务
2. 使用Chrome DevTools工具打开浏览器访问前端
3. 测试流程：
   - 登录系统（如需要）
   - 连接交易系统
   - 测试账户信息显示
   - 测试持仓列表
   - 测试报单功能
   - 测试平仓功能
   - 测试成交记录查询
   - 测试定时任务操作

### 常见测试场景
1. **交易功能测试**
   - 下单（开仓、平仓、市价、限价）
   - 撤单
   - 查看持仓变化
   - 查看成交记录

2. **数据查询测试**
   - 查询今日成交（内存查询）
   - 查询历史成交（数据库查询）
   - 查询账户信息
   - 查询持仓信息

3. **定时任务测试**
   - 查看任务列表
   - 暂停/恢复任务
   - 手动触发任务
   - 验证任务执行日志

4. **WebSocket测试**
   - 检查连接状态
   - 验证实时数据更新
   - 测试断线重连
