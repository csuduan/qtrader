# Q-Trader - 前端管理界面

基于 Vue 3 + Vite + Element Plus 的交易管理系统前端。

## 技术栈

- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件**: Element Plus
- **图表**: ECharts
- **状态管理**: Pinia
- **路由**: Vue Router
- **HTTP客户端**: Axios
- **WebSocket**: 原生WebSocket

## 功能特性

 - 📊 **总览页面**: 账户概览、盈亏统计、风控信息、最近成交
 - 💼 **账户管理**: 详细账户信息和资产状况
 - 🔄 **换仓管理**: 创建、编辑、执行换仓指令，一键平仓
 - 📦 **持仓管理**: 实时查看和管理持仓，支持平仓操作
 - 📝 **成交记录**: 查看历史成交记录
 - 📋 **委托单管理**: 手动报单、撤单、查看委托单状态
 - 📊 **行情管理**: 订阅/取消订阅合约行情，查看实时行情数据
 - ⚙️ **系统控制**: 连接/断开交易系统、暂停/恢复交易
 - ⏰ **定时任务**: 查看和管理定时任务，支持启用/禁用和手动触发
 - 🔔 **告警管理**: 查看和清除告警信息
 - 🔴 **实时推送**: WebSocket 实时数据更新（账户信息每3秒推送一次）

## 快速开始

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

访问 http://localhost:3000

### 构建生产版本

```bash
npm run build
```

### 预览生产版本

```bash
npm run preview
```

## 项目结构

```
web/
├── public/          # 静态资源
├── src/
│   ├── api/         # API 服务层
│   │   ├── request.ts      # Axios 封装
│   │   ├── account.ts      # 账户相关API
│   │   ├── position.ts     # 持仓相关API
│   │   ├── trade.ts        # 成交相关API
│   │   ├── order.ts        # 委托单相关API
│   │   ├── quote.ts        # 行情相关API
│   │   ├── rotation.ts     # 换仓相关API
│   │   ├── system.ts       # 系统控制API
│   │   ├── jobs.ts         # 定时任务API
│   │   └── alarm.ts        # 告警相关API
│   ├── stores/      # Pinia 状态管理
│   │   └── index.ts
│   ├── router/      # Vue Router 路由配置
│   │   └── index.ts
│   ├── types/       # TypeScript 类型定义
│   │   └── index.ts
│   ├── views/       # 页面组件
│   │   ├── Dashboard.vue   # 总览页面
│   │   ├── Account.vue     # 账户管理
│   │   ├── Rotation.vue    # 换仓管理
│   │   ├── Alarm.vue       # 告警管理
│   │   └── System.vue     # 系统控制
│   ├── App.vue      # 根组件
│   ├── main.ts      # 应用入口
│   ├── ws.ts        # WebSocket 管理
│   └── style.css    # 全局样式
├── .env             # 环境变量
├── vite.config.ts   # Vite 配置
└── package.json
```

## 环境变量

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 开发说明

### 添加新的 API

1. 在 `src/api/` 目录下创建新的 API 文件
2. 使用 `axios` 创建 API 方法
3. 在 `src/stores/index.ts` 中添加相应的加载方法

### 添加新的页面

1. 在 `src/views/` 目录下创建新的 Vue 组件
2. 在 `src/router/index.ts` 中添加路由配置
3. 在 `src/App.vue` 中添加侧边栏菜单项

### WebSocket 消息处理

WebSocket 消息在 `src/ws.ts` 中处理，支持以下消息类型：

- `connected` - 连接成功
- `account_update` - 账户信息更新
- `position_update` - 持仓信息更新
- `trade_update` - 新成交记录
- `order_update` - 委托单状态更新
- `kline_update` - K线数据更新

## 路由

| 路径 | 组件 | 说明 |
|------|------|------|
| `/` | 重定向到 /dashboard | |
| `/dashboard` | Dashboard | 总览 |
| `/account` | Account | 账户管理（包含持仓、成交、委托单、行情） |
| `/rotation` | Rotation | 换仓管理 |
| `/system` | System | 系统控制 |
| `/alarms` | Alarm | 告警管理 |

## 代码规范

- 使用 TypeScript 进行类型检查
- 使用 ESLint 进行代码检查
- 组件命名使用 PascalCase
- 文件命名使用 PascalCase（组件）或 camelCase（工具）
- 使用 Composition API (`<script setup>`)
