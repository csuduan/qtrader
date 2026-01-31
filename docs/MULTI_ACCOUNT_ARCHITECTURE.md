# 多账号架构设计文档

## 一、架构概览

### 1.1 设计目标

- **多进程架构**：TradingManager（父进程）管理多个 Trader（子进程）
- **内嵌模式支持**：Trader 可作为线程运行在 Manager 进程中，方便调试
- **数据隔离**：每个账号独立进程、独立数据库
- **故障隔离**：单个 Trader 崩溃不影响其他账号
- **独立运行**：Trader 可独立启动测试

### 1.2 Trader 运行模式

Trader有两种启动方式：
* 自动启动：Trader 进程在 TradingManager 启动时自动创建，无需手动操作
* 手动启动：Trader 进程也可以手动python -m src.run_trader --account_id XXX,

在配置文件中通过 `trader_mode` 字段指定：
```yaml
accounts:
  - account_id: "DQ1"
  - account_id: "DQ2"
```

### 1.3 架构分层

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TradingManager (父进程)                             │
│                        职责：进程管理、数据聚合、API                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  src/manager/                                                               │
│  ├── core/                                                                  │
│  │   ├── TradingManager      - 统一管理内嵌和独立模式 Trader                  │
│  │   ├── BaseTraderProxy      - Trader Proxy 基类                            │
│  │   ├── EmbeddedTraderProxy - 内嵌模式 Trader Proxy                        │
│  │   ├── StandaloneTraderProxy- 独立模式 Trader Proxy（进程模式）            │
│  │   ├── SocketServer         - Unix Domain Socket 服务端（独立模式）         │
│  │   └── DataAggregator       - 数据聚合和缓存                                │
│  └── api/                      - API 服务                                        │
│      ├── routes/                 - HTTP 路由                                  │
│      └── websocket_manager.py    - WebSocket 管理                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                        ↓
                    ┌───────────────────────────────────────────┐
                    │  Unix Domain Sockets (IPC，仅独立模式)    │
                    │   /tmp/qtrader_sockets/qtrader_{id}.sock  │
                    └───────────────────────────────────────────┘
                                        ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Trader (子进程或线程)                          │
│                    职责：交易执行、策略运行、行情处理                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  src/trader/                                                                │
│  ├── core/                                                                  │
│  │   ├── Trader           - 交易执行器主类                                    │
│  │   ├── SocketClient     - Socket 客户端（独立模式）                       │
│  │   ├── TradingEngine    - 交易引擎                                        │
│  │   └── RiskControl      - 风控                                            │
│  ├── adapters/              - Gateway 适配器                                │
│  │   ├── base_gateway.py   │                                                │
│  │   ├── tq_gateway.py     │                                                │
│  │   └── ctp_gateway.py    │                                                │
│  └── strategy/              - 策略模块                                       │
│      ├── strategy_manager.py                                                 │
│      ├── base_strategy.py                                                    │
│      └── strategies/                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                        ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                          公共模块                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  src/models/           │  src/utils/           │  src/db/                  │
│  • 数据模型 (Pydantic)  │  • logger             │  • 数据库连接管理          │
│  • ORM 模型             │  • event_engine       │  • 每账户独立 DB          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

```
src/
├── main.py                          # 主入口（启动 TradingManager）
│
├── manager/                         # TradingManager (父进程)
│   ├── __init__.py
│   ├── main.py                     # 可选：独立启动入口
│   │
│   ├── core/                       # 核心功能
│   │   ├── __init__.py
│   │   ├── trading_manager.py      # 交易管理器（统一管理内嵌/独立模式）
│   │   ├── trader_proxy.py         # Trader Proxy 基类
│   │   ├── embedded_trader_proxy.py # 内嵌模式 Trader Proxy
│   │   ├── standalone_trader_proxy.py# 独立模式 Trader Proxy
│   │   ├── socket_server.py        # Socket 服务端
│   │   └── data_aggregator.py      # 数据聚合器
│   │
│   └── api/                        # API 服务
│       ├── __init__.py
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── account.py          # 账户管理 API
│       │   ├── trader.py           # Trader 管理 API
│       │   ├── order.py            # 订单 API
│       │   ├── trade.py            # 成交 API
│       │   ├── position.py         # 持仓 API
│       │   └── ...
│       ├── websocket_manager.py    # WebSocket 管理
│       └── app.py                  # FastAPI 应用
│
├── trader/                          # Trader (子进程)
│   ├── __init__.py
│   ├── main.py                     # 独立启动入口
│   │
│   ├── core/                       # 核心功能
│   │   ├── __init__.py
│   │   ├── trader.py               # 交易执行器主类
│   │   ├── socket_client.py        # Socket 客户端
│   │   ├── trading_engine.py       # 交易引擎
│   │   └── risk_control.py         # 风控
│   │
│   ├── adapters/                   # Gateway 适配器
│   │   ├── __init__.py
│   │   ├── base_gateway.py
│   │   ├── tq_gateway.py
│   │   └── ctp_gateway.py
│   │
│   └── strategy/                   # 策略模块
│       ├── __init__.py
│       ├── strategy_manager.py
│       ├── base_strategy.py
│       └── strategies/
│           ├── __init__.py
│           ├── rsi_strategy.py
│           ├── ma_strategy.py
│           └── ...
│
├── models/                          # 公共数据模型
│   ├── __init__.py
│   ├── object.py                   # Pydantic 模型
│   └── po.py                       # 数据库 ORM
│
├── utils/                           # 公共工具
│   ├── __init__.py
│   ├── logger.py
│   ├── event_engine.py             # 独立事件引擎
│   └── ...
│
├── db/                              # 数据库管理
│   ├── __init__.py
│   ├── database.py                 # 数据库连接管理
│   └── migrations/                 # 数据库迁移
│
└── config_loader.py                 # 配置加载（公共）
```

---

## 三、核心组件设计

### 3.1 TradingManager (父进程)

**位置**：`src/manager/core/trading_manager.py`

**职责**：
- 启动/停止/重启 Trader 子进程
- 进程健康检查和自动重启
- Unix Domain Socket 服务端
- 数据聚合和缓存
- API 服务集成

**关键方法**：
```python
class TradingManager:
    async def start()                      # 启动管理器
    async def start_trader(account_config) # 启动单个 Trader
    async def stop_trader(account_id)      # 停止单个 Trader
    async def restart_trader(account_id)   # 重启单个 Trader
    async def _health_check_loop()         # 健康检查循环
    async def send_order_request(...)      # 发送下单请求到 Trader
    async def get_status()                 # 获取所有 Trader 状态
```

### 3.2 Trader (子进程)

**位置**：`src/trader/core/trader.py`

**职责**：
- 连接 TradingManager (Socket)
- 执行交易逻辑
- 运行策略
- 推送数据到 Manager

**两种启动模式**：
```bash
# Managed 模式（连接 Manager）
python -m src.trader.main --account-id DQ1 --socket-path /tmp/qtrader_sockets/qtrader_DQ1.sock

# Standalone 模式（独立运行，用于测试）
python -m src.trader.main --account-id DQ1 --mode standalone
```

**关键方法**：
```python
class Trader:
    async def start()                          # 启动 Trader
    async def connect_to_manager(socket_path) # 连接 Manager
    async def run_standalone()                 # 独立运行
    async def _heartbeat_loop()                # 心跳循环
    async def _handle_order_request(data)      # 处理下单请求
    async def stop()                           # 停止 Trader
```

### 3.3 SocketServer (Manager 侧)

**位置**：`src/manager/core/socket_server.py`

**职责**：
- 创建 Unix Domain Socket
- 接受 Trader 连接
- 接收/发送消息
- 消息协议处理

**Socket 路径**：`/tmp/qtrader_sockets/qtrader_{account_id}.sock`

### 3.4 SocketClient (Trader 侧)

**位置**：`src/trader/core/socket_client.py`

**职责**：
- 连接到 Manager Socket
- 发送/接收消息
- 消息协议处理

### 3.5 DataAggregator

**位置**：`src/manager/core/data_aggregator.py`

**职责**：
- 聚合所有 Trader 数据
- 内存缓存管理
- 数据转发到 WebSocket
- 响应 API 查询

---

## 四、通信协议

### 4.1 Socket 消息格式

```
┌─────────────┬──────────────────────────────────────┐
│  4 字节     │         JSON 内容                     │
│  长度前缀    │  {"type": "xxx", "account_id": "xxx", │
│  (Big Endian)│   "data": {...}}                     │
└─────────────┴──────────────────────────────────────┘
```

### 4.2 消息类型

| 类型 | 方向 | 频率 | 说明 |
|------|------|------|------|
| register | Trader → Manager | 一次 | 注册上线 |
| heartbeat | Trader → Manager | 5秒/次 | 心跳保活 |
| account | Trader → Manager | 实时 | 账户数据更新 |
| order | Trader → Manager | 实时 | 订单状态更新 |
| trade | Trader → Manager | 实时 | 成交数据更新 |
| position | Trader → Manager | 实时 | 持仓数据更新 |
| tick | Trader → Manager | 实时 | 行情数据更新 |
| order_req | Manager → Trader | 按需 | 下单请求 |
| cancel_req | Manager → Trader | 按需 | 撤单请求 |
| status_req | Manager → Trader | 按需 | 状态查询 |

---

## 五、独立数据库设计

### 5.1 数据库文件结构

```
storage/
├── trading_DQ1.db              # DQ1 账户数据库
├── trading_DQ2.db              # DQ2 账户数据库
├── trading_DQ3.db              # DQ3 账户数据库
└── ...
```

### 5.2 数据库连接管理

**位置**：`src/db/database.py`

```python
class DatabaseManager:
    """数据库连接管理器"""

    @classmethod
    def get_database(cls, account_id: str) -> Database:
        """获取指定账户的数据库连接"""
        db_filename = f"{cls._db_prefix}{account_id}.db"
        db_path = str(Path(cls._base_path) / db_filename)
        db_url = f"sqlite:///{db_path}"
        db = Database(db_url, echo=echo)
        db.create_tables()
        return db
```

### 5.3 TradingEngine 中的使用

```python
# src/trader/core/trading_engine.py

class TradingEngine:
    def __init__(self, account_config: AccountConfig):
        self.account_id = account_config.account_id
        # 获取该账户专属的数据库连接
        self.db = DatabaseManager.get_database(self.account_id)
```

---

## 六、配置结构

```yaml
# config/config.yaml

# 多账号配置
accounts:
  - account_id: "DQ1"
    account_type: "kq"
    gateway_type: "TQSDK"
    enabled: true
    tianqin:
      username: "user1"
      password: "pass1"
    # 该账号运行的策略
    strategies:
      - rsi_strategy
      - ma_strategy

  - account_id: "DQ2"
    account_type: "real"
    gateway_type: "CTP"
    enabled: true
    trading_account:
      broker_name: "中信期货"
      user_id: "xxx"
      password: "xxx"
    strategies:
      - arbitrage_strategy

# Socket 配置
socket:
  socket_dir: "/tmp/qtrader_sockets"
  health_check_interval: 10    # 健康检查间隔（秒）
  heartbeat_timeout: 30        # 心跳超时（秒）

# 数据库配置
database:
  base_path: "./storage"
  db_prefix: "trading_"

# API 配置
api:
  host: "0.0.0.0"
  port: 8000
  cors_origins: ["*"]
```

---

## 七、API 设计

### 7.1 账户管理 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/accounts` | GET | 获取所有账号信息 |
| `/api/accounts/{account_id}` | GET | 获取单个账号信息 |
| `/api/traders` | GET | 获取所有 Trader 状态 |
| `/api/traders/{account_id}/restart` | POST | 重启指定 Trader |
| `/api/traders/{account_id}/stop` | POST | 停止指定 Trader |
| `/api/traders/{account_id}/start` | POST | 启动指定 Trader |

### 7.2 交易 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/orders` | GET | 获取订单（支持 account_id 过滤） |
| `/api/orders` | POST | 发送下单请求 |
| `/api/orders/{order_id}/cancel` | POST | 撤单请求 |
| `/api/trades` | GET | 获取成交（支持 account_id 过滤） |
| `/api/positions` | GET | 获取持仓（支持 account_id 过滤） |

### 7.3 WebSocket 消息

```json
// 账户更新
{
  "type": "accounts_update",
  "data": [
    {
      "account_id": "DQ1",
      "balance": 100000.00,
      "available": 95000.00,
      ...
    }
  ],
  "timestamp": "2026-01-26T10:00:00"
}

// 订单更新
{
  "type": "order_update",
  "account_id": "DQ1",
  "data": {...},
  "timestamp": "2026-01-26T10:00:00"
}
```

---

## 八、前端设计

### 8.1 页面结构

```
前端页面
│
├── 总览页面 (/)
│   ├── 所有账户汇总信息
│   │   ├── 总资产、总持仓、今日盈亏
│   │   └── Trader 状态
│   │
│   ├── 各账户卡片列表
│   │   ├── 账户 A 卡片（余额、可用、盈亏...）
│   │   ├── 账户 B 卡片
│   │   └── ...
│   │
│   └── 快捷操作（全部连接/断开）
│
├── 账户详情页 (/account)
│   ├── 右上角账户切换器 [当前账户 ▼]
│   ├── 账户信息面板
│   └── Tab 内容（持仓、委托单、成交记录、策略状态）
│
└── 其他页面保持不变
```

### 8.2 路由设计

```typescript
// web/src/router/index.ts

const routes = [
  { path: '/', name: 'Dashboard', component: DashboardView },
  { path: '/account', name: 'Account', component: AccountView },
  // ...
]
```

### 8.3 Store 状态管理

```typescript
interface AccountState {
  accounts: Account[]           // 所有账号
  selectedAccountId: string      // 当前选中账号

  loadAccounts(): void
  switchAccount(id: string): void
  restartTrader(id: string): void
}
```

### 8.4 账户切换器组件

```vue
<!-- web/src/components/AccountSelector.vue -->
<template>
  <el-dropdown @command="handleSwitch">
    <span class="account-selector">
      {{ currentAccountName }} ▼
    </span>
    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item
          v-for="account in accounts"
          :key="account.account_id"
          :command="account.account_id"
        >
          {{ account.account_id }} - {{ account.broker_name }}
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>
```

---

## 九、数据模型改造

### 9.1 需要修改的文件

| 文件 | 修改内容 |
|------|----------|
| `src/models/object.py` | 为 `OrderData`, `TradeData` 添加 `account_id` 必需字段<br>为 `PositionData` 添加 `account_id` 可选字段 |
| `src/utils/config_loader.py` | 扩展 `AppConfig` 支持 `accounts` 数组<br>新增 `AccountConfig` 模型<br>实现 `get_active_accounts()` 方法 |

### 9.2 数据模型示例

```python
# src/models/object.py

class OrderData(BaseModel):
    """订单数据"""
    # 新增必需字段
    account_id: str = Field(..., description="账户ID")
    # 其他字段保持不变...

class TradeData(BaseModel):
    """成交数据"""
    # 新增必需字段
    account_id: str = Field(..., description="账户ID")
    # 其他字段保持不变...

class PositionData(BaseModel):
    """持仓数据"""
    # 新增可选字段
    account_id: Optional[str] = Field(None, description="账户ID")
    # 其他字段保持不变...
```

---

## 十、使用方式

### 10.1 单账号模式（向后兼容）

```yaml
# config/config.yaml
account_id: "DQ1"
account_type: "kq"
# 其他单账号配置...
```

启动：
```bash
python -m src.main
```

### 10.2 多账号模式

```yaml
# config/config.yaml
accounts:
  - account_id: "DQ1"
    account_type: "kq"
    enabled: true
    # ...
  - account_id: "DQ2"
    account_type: "real"
    enabled: true
    # ...
```

启动：
```bash
python -m src.main
```

### 10.3 Trader 独立启动（测试）

```bash
python -m src.trader.main --account-id DQ1 --mode standalone
```

---

## 十一、关键文件清单

### 11.1 新建文件

| 文件 | 说明 |
|------|------|
| `src/manager/__init__.py` | Manager 模块初始化 |
| `src/manager/core/__init__.py` | 核心模块初始化 |
| `src/manager/core/trading_manager.py` | 交易管理器主类 |
| `src/manager/core/embedded_trader_proxy.py` | 内嵌模式 Trader Proxy |
| `src/manager/core/standalone_trader_proxy.py` | 独立模式 Trader Proxy |
| `src/manager/core/socket_server.py` | Socket 服务端 |
| `src/manager/core/data_aggregator.py` | 数据聚合器 |
| `src/manager/api/__init__.py` | API 模块初始化 |
| `src/manager/api/routes/__init__.py` | 路由模块初始化 |
| `src/trader/__init__.py` | Trader 模块初始化 |
| `src/trader/core/__init__.py` | 核心模块初始化 |
| `src/trader/core/trader.py` | 交易执行器主类 |
| `src/trader/core/socket_client.py` | Socket 客户端 |
| `src/trader/main.py` | Trader 独立启动入口 |
| `src/utils/event_engine.py` | 独立事件引擎 |
| `src/db/__init__.py` | 数据库模块初始化 |
| `src/db/database.py` | 数据库连接管理 |

### 11.2 移动文件

| 原路径 | 新路径 |
|--------|--------|
| `src/trading_engine.py` | `src/trader/core/trading_engine.py` |
| `src/risk_control.py` | `src/trader/core/risk_control.py` |
| `src/adapters/*` | `src/trader/adapters/*` |
| `src/strategy/*` | `src/trader/strategy/*` |
| `src/api/routes/*` | `src/manager/api/routes/*` |
| `src/api/websocket_manager.py` | `src/manager/api/websocket_manager.py` |
| `src/api/app.py` | `src/manager/api/app.py` |

### 11.3 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/main.py` | 改为启动 TradingManager |
| `src/config_loader.py` | 扩展多账号配置支持 |
| `src/models/object.py` | 添加 account_id 字段 |

---

## 十二、向后兼容性

- ✅ 单账号配置继续有效
- ✅ API 保持兼容
- ✅ 前端自动适配
- ✅ 数据库结构兼容（新增字段可选）

---

**文档版本**: 2.0
**最后更新**: 2026-01-28
**维护者**: Q-Trader 开发团队
