# Q-Trader 量化交易系统

Q-Trader 是一款专为现代金融投资打造的专业量化交易平台，致力于通过技术驱动投资决策，为交易者、投资机构与金融开发者提供高效、稳定、可扩展的自动化交易解决方案。

## 技术栈

### 后端
- **语言**: Python 3.8+
- **Web框架**: FastAPI
- **数据库**: SQLite
- **ORM**: SQLAlchemy
- **交易接口**: TqSdk (天勤量化)
- **任务调度**: APScheduler
- **异步**: asyncio

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

 - **配置管理**: 支持YAML配置文件，可配置天勤账号、交易参数、风控参数等
 - **行情订阅**: 支持订阅实时行情数据
 - **订单扫描**: 自动扫描CSV格式的交易指令文件并执行
 - **风控模块**: 支持单日最大报单次数、撤单次数、单笔最大手数等风控参数
 - **数据持久化**: 使用SQLite存储账户、持仓、成交、委托单等数据
 - **RESTful API**: 提供完整的API接口，支持账户、持仓、成交、委托单查询及手动报单
 - **WebSocket实时推送**: 支持实时推送账户、持仓、成交、委托单等数据更新（账户信息每3秒推送一次）
 - **Vue管理界面**: 完整的Web管理界面，支持账户管理、持仓管理、成交记录、委托单管理、系统控制等
 - **定时任务调度**: 支持配置定时任务，如盘前自动连接、盘后自动断开、自动换仓等

## 项目结构

```
qtrader/
├── config/
│   └── config.yaml           # 主配置文件
├── src/
│   ├── main.py               # 主程序入口
│   ├── config_loader.py      # 配置加载器
│   ├── trading_engine.py     # 交易引擎核心
│   ├── switch_mgr.py         # 换仓管理器
│   ├── risk_control.py       # 风控模块
│   ├── database.py           # 数据库操作
│   ├── persistence.py        # 数据持久化
│   ├── scheduler.py          # 定时任务调度器
│   ├── job_mgr.py            # 任务管理
│   ├── init_sys.py           # 系统初始化脚本
│   ├── param_loader.py       # 参数加载器
│   ├── models/               # 数据模型
│   ├── api/
│   │   ├── app.py            # FastAPI应用
│   │   ├── websocket_manager.py  # WebSocket管理器
│   │   ├── routes/           # API路由
│   │   └── schemas.py        # API数据模型
│   └── utils/                # 工具模块
├── data/
│   ├── orders/               # 交易指令文件目录
│   └── logs/                 # 日志目录
├── storage/
│   └── trading.db            # SQLite数据库
├── web/                      # 前端项目
│   └── ...                   # Vue 3 + Vite + Element Plus
├── docs/                     # 文档目录
│   ├── INIT_SYSTEM.md        # 系统初始化文档
│   └── INIT_SYSTEM_UPDATE.md # 系统更新文档
├── requirements.txt          # Python依赖
├── AGENTS.md                 # 开发指南
└── README.md                 # 项目说明
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置文件

复制示例配置文件并修改：

```bash
cp config/config.yaml config/config.yaml
```

编辑 `config/config.yaml`，配置交易账户信息。

### 3. 初始化系统

首次运行或需要重置系统时，请运行初始化脚本：

```bash
python -m src.init_sys
```

这将：
- 创建/重建所有数据库表
- 从配置文件导入定时任务到数据库
- 从配置文件初始化风控参数到数据库

### 4. 运行程序

```bash
python -m src.main
```

### 4. 访问API

程序启动后，可以访问：

- API文档: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/ws

## 交易指令CSV文件格式

在 `data/orders/` 目录下放置CSV文件，格式如下：

```csv
实盘账户,合约代码,交易所代码,开平类型,买卖方向,手数,价格,报单时间
SHFE.rb2505,SHFE,OPEN,BUY,5,0,09:30:00
SHFE.ag2505,SHFE,CLOSE,SELL,3,4500,
```

字段说明：
- **实盘账户**: 完整合约代码（如 SHFE.rb2505）
- **合约代码**: 交易所代码（如 SHFE）
- **交易所代码**: 开平类型（OPEN=开仓, CLOSE=平仓, CLOSETODAY=平今）
- **开平类型**: 买卖方向（BUY=买, SELL=卖）
- **买卖方向**: 手数
- **手数**: 价格（0=使用对手价，否则为限价）
- **价格**: 报单时间（格式HH:MM:SS，空则不限制）

## API接口

### 账户相关
- `GET /api/account` - 获取账户信息
- `GET /api/account/all` - 获取所有账户信息

### 持仓相关
- `GET /api/position` - 获取持仓列表
- `GET /api/position/{symbol}` - 获取指定合约持仓

### 成交相关
- `GET /api/trade` - 获取成交记录
- `GET /api/trade/{trade_id}` - 获取指定成交详情
- `GET /api/trade/order/{order_id}` - 获取指定委托单的成交记录

### 委托单相关
- `GET /api/order` - 获取委托单列表
- `GET /api/order/{order_id}` - 获取指定委托单详情
- `POST /api/order` - 手动报单
- `DELETE /api/order/{order_id}` - 撤销委托单

### 行情相关
- `GET /api/quote/subscribe` - 订阅行情
- `GET /api/quote/unsubscribe` - 取消订阅行情
- `GET /api/quotes` - 获取订阅的行情列表

### 系统控制
- `GET /api/system/status` - 获取系统状态
- `POST /api/system/connect` - 连接到交易系统
- `POST /api/system/disconnect` - 断开连接
- `POST /api/system/pause` - 暂停交易
- `POST /api/system/resume` - 恢复交易

### 系统参数
- `GET /api/system-params` - 获取所有系统参数
- `GET /api/system-params/{param_key}` - 获取单个参数
- `PUT /api/system-params/{param_key}` - 更新参数
- `GET /api/system-params/group/{group}` - 按分组获取参数

### 换仓管理
- `GET /api/rotation/instructions` - 获取换仓指令列表
- `GET /api/rotation/instructions/{id}` - 获取换仓指令详情
- `POST /api/rotation/instructions` - 创建换仓指令
- `PUT /api/rotation/instructions/{id}` - 更新换仓指令
- `DELETE /api/rotation/instructions/{id}` - 删除换仓指令
- `POST /api/rotation/execute` - 执行换仓
- `POST /api/rotation/close-all` - 平掉所有持仓
- `POST /api/rotation/check` - 检查换仓状态

### 定时任务
- `GET /api/jobs` - 获取定时任务列表
- `GET /api/jobs/{job_id}` - 获取任务详情
- `POST /api/jobs/{job_id}/toggle` - 启用/禁用任务
- `POST /api/jobs/{job_id}/trigger` - 手动触发任务

### 告警管理
- `GET /api/alarms` - 获取告警列表
- `POST /api/alarms/clear` - 清除已处理告警

## WebSocket消息格式

### 连接

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');
```

### 服务端推送消息类型

- `connected` - 连接成功
- `account_update` - 账户信息更新（每3秒推送一次）
- `position_update` - 持仓信息更新（实时）
- `trade_update` - 新成交记录（实时）
- `order_update` - 委托单状态更新（实时）
- `quote_update` - 行情数据更新（实时）
- `tick_update` - tick数据更新（实时）
- `system_status` - 系统状态更新
- `alarm_update` - 告警更新

### 客户端发送消息类型

- `subscribe_logs` - 订阅日志流
- `unsubscribe_logs` - 取消订阅日志流

### 消息格式

```json
{
  "type": "account_update",
  "data": {
    "account_id": "xxx",
    "balance": 100000.00,
    "available": 95000.00,
    ...
  },
  "timestamp": "2025-01-10T10:30:00"
}
```

## 配置说明

### 账户类型

支持三种账户类型：

1. **sim** - 本地模拟账户（默认）
2. **kq** - 快期模拟账户
3. **real** - 实盘账户（需配置交易账户信息）

### 风控参数

- `max_daily_orders` - 单日最大报单次数
- `max_daily_cancels` - 单日最大撤单次数
- `max_order_volume` - 单笔最大报单手数

### 行情订阅

- `subscribe_symbols` - 订阅的合约列表
- `kline_duration` - K线周期（秒），60=1分钟

## 开发计划

- [x] 项目基础搭建
- [x] 配置文件支持
- [x] 日志系统
- [x] 数据库和ORM模型
- [x] 交易引擎核心
- [x] 换仓管理器
- [x] 风控模块
- [x] 定时任务调度
- [x] 数据持久化
- [x] RESTful API
- [x] WebSocket实时推送
- [x] Vue前端管理界面
- [ ] 单元测试
- [ ] 部署文档

## 前端管理界面

前端管理界面位于 `web/` 目录，使用 Vue 3 + Vite + Element Plus 开发。

### 前端功能

- **总览页面**: 显示账户概览、盈亏统计、风控信息和最近成交
- **账户管理**: 查看详细账户信息和资产状况
- **换仓管理**: 创建、编辑、执行换仓指令，一键平仓
- **持仓管理**: 实时查看和管理持仓，支持平仓操作
- **成交记录**: 查看历史成交记录
- **委托单管理**: 手动报单、撤单、查看委托单状态
- **行情管理**: 订阅/取消订阅合约行情，查看实时行情数据
- **系统控制**: 连接/断开交易系统、暂停/恢复交易
- **定时任务**: 查看和管理定时任务，支持启用/禁用和手动触发
- **告警管理**: 查看和清除告警信息

### 前端启动

```bash
cd web
npm install
npm run dev
```

访问 http://localhost:3000

**注意**：
- Vite 配置了代理，`/api` 和 `/ws` 请求会自动转发到 `http://localhost:8000`
- 如需修改后端地址，请编辑 `vite.config.ts` 中的 `proxy` 配置

### 前端技术栈

- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件**: Element Plus
- **图表**: ECharts
- **状态管理**: Pinia
- **路由**: Vue Router
- **HTTP客户端**: Axios
- **WebSocket**: 原生WebSocket

## 文档

- **系统初始化**: [docs/INIT_SYSTEM.md](docs/INIT_SYSTEM.md) - 系统初始化和使用说明
- **系统更新**: [docs/INIT_SYSTEM_UPDATE.md](docs/INIT_SYSTEM_UPDATE.md) - 系统优化更新说明
- **WebSocket优化**: [docs/WEBSOCKET_OPTIMIZATION.md](docs/WEBSOCKET_OPTIMIZATION.md) - WebSocket推送优化说明
- **开发指南**: [AGENTS.md](AGENTS.md) - 开发规范和指南
- **前端文档**: [web/README.md](web/README.md) - 前端项目说明

## 许可证

MIT License
