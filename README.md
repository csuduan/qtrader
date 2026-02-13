# Q-Trader 量化交易系统

Q-Trader 是一款专为现代金融投资打造的专业量化交易平台，致力于通过技术驱动投资决策，为交易者、投资机构与金融开发者提供高效、稳定、可扩展的自动化交易解决方案。



## 架构说明

### 技术栈

- **后端**: Python 3.12+FastAPI
- **前端**: Vue 3 + TypeScript

### Manager-Trader 分离架构

Q-Trader 采用 Manager-Trader 分离架构，实现了多账户独立运行：

```
┌─────────────────────────────────────────────────────────────┐
│                      Manager 进程                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   FastAPI    │  │   WebSocket  │  │   Scheduler  │       │
│  │   Web服务    │  │   实时推送    │  │   定时任务    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                             │                               │
│                    ┌────────▼────────┐                      │
│                    │ TradingManager  │                      │
│                    │   交易管理器     │                      │
│                    └────────┬────────┘                      │
│                             │                               │
│              ┌──────────────┼──────────────┐                │
│              │              │              │                │
│         ┌────▼────┐    ┌────▼────┐    ┌────▼────┐           │
│         │Trader DQ│    │Trader GW│    │Trader...│           │
│         │Proxy    │    │Proxy    │    │Proxy    │           │
│         └────┬────┘    └────┬────┘    └────┬────┘           │
└──────────────┼──────────────┼──────────────┼────────────────┘
               │              │              │
           Unix Socket    Unix Socket    Unix Socket
               │              │              │
         ┌─────▼─────┐  ┌─────▼─────┐  ┌─────▼─────┐
         │Trader DQ  │  │Trader GW  │  │Trader ... │
         │ 交易进程   │  │ 交易进程   │  │ 交易进程   │
         └───────────┘  └───────────┘  └───────────┘
```

* 进程间通信
Manager 和 Trader 通过 Unix Domain Socket 进行通信：
- **请求-响应模式**: Manager 主动查询 Trader 数据（账户、持仓、订单等）
- **推送模式**: Trader 主动推送数据更新（tick、订单状态、成交等）


## 快速开始

### 1. 安装依赖

```bash
# 创建虚拟环境
conda create -n qts python=3.12
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


### 3. 运行系统
* 启动管理平台
```bash
# 启动 Manager（会自动启动配置中的 Trader）
python -m src.run_manager

```
* 启动账户

```bash

# 终端1：启动 Trader（可选，Manager 会自动启动）
python -m src.run_trader --account-id DQ
```
* 启动前端
```bash
# 终端启动前端
cd web
npm install
npm run dev
```
>>注意：生产环境应当部署到ngix中

* 访问
- **Web 界面**: http://localhost:3000


## 文档

* 系统文档
- **开发指南**: [AGENTS.md](AGENTS.md) - 开发规范和指南
- **测试规范**: [TESTING.md](TESTING.md) - 测试规范和流程

* 参考文档
- **tqsdk**: https://doc.shinnytech.com/tqsdk/latest/usage/

## 许可证

MIT License
