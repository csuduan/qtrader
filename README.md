# Q-Trader 量化交易系统

Q-Trader 是一款专为现代金融投资打造的专业量化交易平台，致力于通过技术驱动投资决策，为交易者、投资机构与金融开发者提供高效、稳定、可扩展的自动化交易解决方案。

## 技术栈

### 后端
- **语言**: Python 3.8+
- **Web框架**: FastAPI
- **数据库**: SQLite
- **ORM**: SQLAlchemy
- **交易接口**: TqSdk (天勤量化)、CTP
- **任务调度**: APScheduler
- **异步**: asyncio + Unix Domain Socket

### 前端
- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件**: Element Plus
- **图表**: ECharts
- **状态管理**: Pinia
- **路由**: Vue Router
- **HTTP客户端**: Axios
- **WebSocket**: 原生WebSocket

## 功能特性

- **多账号架构**: 采用 Manager-Trader 分离架构，支持多账户独立运行
  - **Manager 进程**: 管理 Web 服务、API、WebSocket、定时任务
  - **Trader 进程**: 独立进程执行交易，通过 Unix Socket 与 Manager 通信
  - 每个账户独立数据库、独立进程、互不干扰
- **配置管理**: 支持 YAML 配置文件，可配置天勤账号、交易参数、风控参数等
- **行情订阅**: 支持订阅实时行情数据
- **订单扫描**: 自动扫描 CSV 格式的交易指令文件并执行
- **风控模块**: 支持单日最大报单次数、撤单次数、单笔最大手数等风控参数
- **数据持久化**: 使用 SQLite 存储账户、持仓、成交、委托单等数据
- **RESTful API**: 提供完整的 API 接口，支持账户、持仓、成交、委托单查询及手动报单
- **WebSocket 实时推送**: 支持实时推送账户、持仓、成交、委托单等数据更新
- **Vue 管理界面**: 完整的 Web 管理界面，支持账户管理、持仓管理、成交记录、委托单管理、系统控制等
- **定时任务调度**: 支持配置定时任务，如盘前自动连接、盘后自动断开、自动换仓等
- **策略系统**: 支持策略开发和回测，提供 RSI、均线等多种策略模板

## 项目结构

```
qtrader/
├── config/
│   ├── config.yaml           # 主配置文件（全局配置）
│   └── account-*.yaml        # 账户配置文件
├── src/
│   ├── manager/              # TradingManager (父进程/Manager)
│   │   ├── app.py            # Manager 主入口
│   │   ├── core/             # 核心功能
│   │   │   ├── trading_manager.py  # 交易管理器
│   │   │   ├── trader_proxy.py     # Trader 代理（Socket 客户端）
│   │   │   └── socket_client.py    # Socket 客户端
│   │   └── api/              # API 服务
│   │       ├── routes/       # API 路由
│   │       ├── websocket_manager.py
│   │       ├── responses.py   # API 响应工具
│   │       └── schemas.py     # API 数据模型
│   │
│   ├── trader/               # Trader (子进程/交易进程)
│   │   ├── app.py            # Trader 主入口
│   │   ├── core/             # 核心功能
│   │   │   ├── trader.py     # 交易执行器
│   │   │   ├── trading_engine.py  # 交易引擎
│   │   │   ├── socket_server.py   # Socket 服务端
│   │   │   ├── strategy_manager.py # 策略管理器
│   │   │   └── risk_control.py     # 风控模块
│   │   ├── adapters/         # Gateway 适配器
│   │   │   ├── base_gateway.py
│   │   │   ├── tq_gateway.py
│   │   │   └── ctp_gateway.py
│   │   ├── strategy/         # 策略模块
│   │   │   ├── base_strategy.py
│   │   │   └── strategy_rsi.py
│   │   └── persistence.py    # 数据持久化
│   │
│   ├── models/               # 数据模型
│   │   ├── object.py         # 业务数据模型（Pydantic）
│   │   └── po.py             # 数据库 ORM 模型
│   ├── db/                   # 数据库管理
│   ├── utils/                # 工具模块
│   ├── app_context.py        # 应用上下文
│   ├── config_loader.py      # 配置加载器
│   ├── scheduler.py          # 定时任务调度器
│   └── param_loader.py       # 参数加载器
│
├── data/
│   ├── socks/                # Unix Socket 文件目录
│   ├── orders/               # 交易指令文件目录
│   └── logs/                 # 日志目录
├── storage/
│   └── trading_*.db          # SQLite 数据库（每账户一个）
├── web/                      # 前端项目
├── tests/                    # 测试目录
├── docs/                     # 文档目录
├── requirements.txt          # Python 依赖
├── TESTING.md                # 测试规范
├── AGENTS.md                 # 开发指南
└── README.md                 # 项目说明
```

## 架构说明

### Manager-Trader 分离架构

Q-Trader 采用 Manager-Trader 分离架构，实现了多账户独立运行：

```
┌─────────────────────────────────────────────────────────────┐
│                      Manager 进程                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   FastAPI    │  │   WebSocket  │  │   Scheduler  │     │
│  │   Web 服务    │  │   实时推送    │  │   定时任务    │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│                             │                                │
│                    ┌────────▼────────┐                     │
│                    │ TradingManager  │                     │
│                    │  交易管理器      │                     │
│                    └────────┬────────┘                     │
│                             │                                │
│              ┌──────────────┼──────────────┐                │
│              │              │              │                │
│         ┌────▼────┐   ┌────▼────┐   ┌────▼────┐           │
│         │Trader DQ│   │Trader GW│   │Trader ...│          │
│         │(子进程)  │   │(子进程)  │   │(子进程)  │          │
│         └────┬────┘   └────┬────┘   └────┬────┘           │
└──────────────┼─────────────┼─────────────┼──────────────────┘
               │             │             │
           Unix Socket    Unix Socket   Unix Socket
               │             │             │
         ┌─────▼─────┐ ┌────▼─────┐ ┌────▼─────┐
         │Trader DQ  │ │Trader GW │ │Trader ...│
         │ 交易进程   │ │ 交易进程  │ │ 交易进程  │
         └───────────┘ └──────────┘ └───────────┘
```

### 进程间通信

Manager 和 Trader 通过 Unix Domain Socket 进行通信：

- **请求-响应模式**: Manager 主动查询 Trader 数据（账户、持仓、订单等）
- **推送模式**: Trader 主动推送数据更新（tick、订单状态、成交等）

### 数据流

```
行情数据 → Gateway → TradingEngine → EventEngine → StrategyManager
                                         ↓
                                    Persistence
                                         ↓
                                    Database
```

## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
conda create -n qts python=3.8
conda activate qts

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置文件

编辑配置文件：

**全局配置** (`config/config.yaml`):
```yaml

socket:
  socket_dir: "./data/socks"
  health_check_interval: 10
  heartbeat_timeout: 30

api:
  host: "0.0.0.0"
  port: 8000
```

**账户配置** (`config/account-DQ.yaml`):
```yaml
account_id: DQ
account_type: kq  # sim/kq/real
enabled: true
auto_start: true

gateway:
  type: TQSDK
  tianqin:
    username: "your_username"
    password: "your_password"
```

### 3. 初始化系统

首次运行需要初始化数据库和系统参数：

```bash
python -m src.init_sys
```

### 4. 运行系统

**方式一：直接运行 Manager（推荐）**

```bash
# 启动 Manager（会自动启动配置中的 Trader）
python -m src.run_manager

# 访问 Web 界面
# http://localhost:8000
```

**方式二：分别启动 Manager 和 Trader**

```bash
# 终端1：启动 Manager
python -m src.run_manager

# 终端2：启动 Trader（可选，Manager 会自动启动）
python -m src.run_trader --account-id DQ
```

### 5. 访问服务

- **Web 界面**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **WebSocket**: ws://localhost:8000/ws

## API 接口

### 账户相关
- `GET /api/account` - 获取当前账户信息
- `GET /api/account/all` - 获取所有账户信息（多账号模式）

### Trader 管理
- `GET /api/traders` - 获取所有 Trader 状态
- `POST /api/traders/{account_id}/start` - 启动指定 Trader
- `POST /api/traders/{account_id}/stop` - 停止指定 Trader
- `POST /api/traders/{account_id}/restart` - 重启指定 Trader

### 持仓相关
- `GET /api/positions` - 获取持仓列表

### 成交相关
- `GET /api/trades/today` - 获取今日成交
- `GET /api/trades/history` - 获取历史成交

### 委托单相关
- `GET /api/orders` - 获取委托单列表
- `POST /api/orders` - 创建订单
- `DELETE /api/orders/{order_id}` - 撤销订单

### 系统控制
- `GET /api/system/status` - 获取系统状态
- `POST /api/system/pause` - 暂停交易
- `POST /api/system/resume` - 恢复交易

### 定时任务
- `GET /api/jobs` - 获取定时任务列表
- `POST /api/jobs/{job_id}/trigger` - 手动触发任务

## WebSocket 消息格式

### 服务端推送消息类型

- `connected` - 连接成功
- `account_update` - 账户信息更新
- `position_update` - 持仓信息更新
- `trade_update` - 成交记录更新
- `order_update` - 委托单状态更新
- `tick_update` - tick 数据更新

### 消息格式

```json
{
  "type": "account_update",
  "data": {
    "account_id": "DQ",
    "balance": 100000.00,
    "available": 95000.00
  },
  "timestamp": "2026-01-29T10:30:00"
}
```

## 开发状态

- [x] 项目基础搭建
- [x] 配置文件支持
- [x] 日志系统
- [x] 数据库和 ORM 模型
- [x] Manager-Trader 分离架构
- [x] Unix Socket 通信
- [x] 交易引擎核心
- [x] Gateway 适配器（TqSdk、CTP）
- [x] 风控模块
- [x] 定时任务调度
- [x] 数据持久化
- [x] RESTful API
- [x] WebSocket 实时推送
- [x] Vue 前端管理界面
- [x] 多账号支持
- [x] 策略系统
- [x] 代码静态检测（mypy）
- [x] 代码格式化（black、isort）
- [x] API 集成测试

## 前端管理界面

前端管理界面位于 `web/` 目录，使用 Vue 3 + Vite + Element Plus 开发。

### 前端启动

```bash
cd web
npm install
npm run dev
```

访问 http://localhost:5173

### 前端功能

- **总览页面**: 显示账户概览、盈亏统计、风控信息
- **账户管理**: 查看详细账户信息
- **持仓管理**: 实时查看和管理持仓
- **委托单管理**: 手动报单、撤单
- **成交记录**: 查看历史成交记录
- **策略管理**: 启用/禁用策略

## 测试

项目包含完整的测试套件：

```bash
# 安装测试依赖
pip install -r requirements-test.txt

# 运行所有测试
pytest tests/ -v

# 运行 API 测试
pytest tests/integration/ -v

# 运行单元测试
pytest tests/unit/ -v
```

详细测试规范请参考 [TESTING.md](TESTING.md)

## 文档

- **开发指南**: [AGENTS.md](AGENTS.md) - 开发规范和指南
- **测试规范**: [TESTING.md](TESTING.md) - 测试规范和流程
- **多账号架构**: [docs/MULTI_ACCOUNT_ARCHITECTURE.md](docs/MULTI_ACCOUNT_ARCHITECTURE.md)

## 许可证

MIT License
