# Agent Guidelines

## Commands
### Backend (Python)
- **Run main**: `python -m src.main`
- **Format**: `black src/` (line-length: 100, target: py38)
- **Sort imports**: `isort src/` (black profile, line-length: 100)
- **Tests**: Not configured yet (pytest recommended for future)

### Frontend (Vue)
- **Install deps**: `cd web && npm install`
- **Dev server**: `cd web && npm run dev`
- **Build**: `cd web && npm run build`
- **Preview**: `cd web && npm run preview`

## Code Style
### Backend (Python)
- **Python**: 3.8+, use type hints from `typing` module
- **Formatting**: Black 100-char line length
- **Imports**: Standard lib → third-party → local modules
- **Naming**: snake_case for functions/vars, CamelCase for classes
- **Docstrings**: Chinese, triple quotes, describe Args/Returns
- **Logging**: Use `get_logger(__name__)` from `src.utils.logger`
- **Error handling**: Try/except with logger.error()
- **Models**: SQLAlchemy ORM with `__repr__`, Pydantic for API schemas
- **API**: FastAPI with async endpoints, `from_attributes = True` in Config
- **Comments**: Chinese, concise (NO inline comments unless requested)
- **Event System**: Use event engine for decoupled communication, define event types in `EventTypes` class

### Frontend (Vue + TypeScript)
- **Framework**: Vue 3 with Composition API (`<script setup>`)
- **Language**: TypeScript with strict mode
- **Components**: PascalCase for .vue files
- **Files**: PascalCase for components, camelCase for utils
- **State**: Pinia stores in `src/stores/`
- **API**: Axios HTTP client in `src/api/`
- **WebSocket**: Custom manager in `src/ws.ts`
- **UI**: Element Plus components
- **Charts**: ECharts for data visualization

## Architecture Notes

### Event-Driven System
- Trading engine uses event engine for decoupled notifications
- Events are emitted after `api.wait_update()` in `update()` method
- Event types defined in `src.trading_engine.EventTypes` class
- Global event engine: `src.utils.event.event_engine`
- Example usage in `examples/event_usage.py`

### Frontend-Backend Communication Standards

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
