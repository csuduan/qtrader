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
* 安装虚拟环境  

```bash
# 创建虚拟环境(本项目要求python3.12以上)
conda create -n qts python=3.12
conda activate qts

# 安装项目
pip install -e .

```

* 安装数据库(可选)
```bash
# 安装官方仓库最新版
sudo apt update
sudo apt install postgresql postgresql-contrib
# 启动服务
sudo systemctl start postgresql
sudo systemctl enable postgresql
# 创建DB
sudo -u postgres psql
CREATE USER qtrader WITH PASSWORD 'xxxxxx';
CREATE DATABASE qtrader OWNER trader;
GRANT ALL PRIVILEGES ON DATABASE qtrader TO trader;
# 访问DB
psql -U trader -d qtrader -h localhost
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


### 3. 启动
* 启动管理平台
```bash
# 启动 Manager（会自动启动配置中的 Trader）
python -m run_manager

```
* 启动账户(可选)
  - WEB平台操作
略 
  - 手动启动 
```bash
python -m run_trader --account-id DQ
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


## 常见问题
* 启动报错：locale::facet::_S_create_c_locale name not valid  
结局方案：安装字符集
locale-gen zh_CN.GB18030

## 文档
* 参考文档
- **tqsdk**: https://doc.shinnytech.com/tqsdk/latest/usage/


## 许可证

MIT License
