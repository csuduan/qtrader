# Q-Trader 测试规范

## 概述

本文档定义 Q-Trader 的五层测试体系与提交流程。所有代码在提交前必须按照以下流程进行测试。

| 层 | 名称 | 定义 | 目录 |
|---|------|------|------|
| 1 | 单元测试 | 所有功能都需要有单元测试，核心功能覆盖率 ≥ 90% | `tests/unit/` |
| 2 | 集成测试 | 关键模块之间联动；mock 外部服务（如交易接口）；数据库测试完回退数据 | `tests/integration/` |
| 3 | API 测试 | 启动后端所有服务，关键 API 单个或组合测试；最小化 mock | `tests/api/` |
| 4 | E2E 测试 | Playwright 前后端联调，覆盖关键路径和操作；可能受外部服务影响（如非交易时段） | `tests/e2e/` |
| 5 | UAT 测试 | 用户真实操作，不自动化；维护关键场景清单，用户按场景逐条测试 | 本文档第五步 |

> **提示**：本文档定义测试标准和流程。关于如何运行和编写测试的详细操作指南，请参见 [README.md](README.md)

---

## 测试流程

### 第零步：静态代码检测 (mypy)

**目的**：检查类型注解，提前发现潜在错误。

**命令**：
```bash
make test-mypy
```

**通过标准**：
- [ ] 无 `error` 级别错误

---

### 第一层：单元测试

**目的**：验证单个模块/函数的业务逻辑，无外部依赖（数据库用 SQLite 内存库，外部服务全 mock）。

**运行测试**：`make test-unit`（覆盖率报告命令见 [README](README.md#3-测试覆盖率)）

**通过标准**：
- [ ] 所有测试通过（passed，xfail 属正常）
- [ ] **核心模块覆盖率 ≥ 90%**
- [ ] **本次变更的代码已覆盖**（见下方检查清单）

**核心模块界定**（以下模块的公共方法必须有单元测试，覆盖率 ≥ 90%）：

| 模块 | 现状基线 |
|------|----------|
| `src/qtrader/trader/` 核心逻辑（trading_engine、order_executor、order_cmd、switch_mgr、strategy_manager、job_mgr、risk_control、dao/） | ~95% |
| `src/qtrader/models/` | 93.8% |
| `src/qtrader/utils/` 基础组件（event_engine、scheduler、logger 等） | 见覆盖率报告 |

**不设指标的排除项**：
- `trader/gateway/`（CTP/TQ 原生封装）——由集成测试 + 手工 UAT 覆盖
- `trader/app.py`、`manager/app.py` 等进程入口/装配代码——无法脱离进程单测
- `manager/api/` 路由层——由集成测试覆盖
- 外设通知（wecomm、email_sender、db_url）

**变动代码必测（提交前检查清单）**：
- [ ] `git diff --name-only <base>...HEAD` 列出变更文件
- [ ] 变更涉及核心模块的，新增/修改的公共方法均有对应测试用例
- [ ] `make test-coverage` 报告中，变更文件无整块未覆盖逻辑

---

### 第二层：集成测试

**目的**：验证关键模块之间的联动。mock 外部服务（交易接口等），数据库联动用真实 PostgreSQL（测完回退数据）。

**运行测试**：`make test-integration`

**组成**：

1. **API 路由联动**（TestClient + mock TradingManager，无需启动后端）：验证"路由 → 鉴权 → 异常处理 → TradingManager 边界"的真实链路。

2. **真实数据库联动**（`test_db_integration.py`）：验证 DAO 层在 PG 方言下的真实行为（upsert、约束、事务）。

   ```bash
   # 环境隔离二选一（均不触碰生产数据），未设置则该部分 skip
   # 方式A：独立 schema（同库，URL 传 search_path）
   export QTRADER_TEST_DB_URL='postgresql+psycopg://user:pass@host:5432/qtrader?options=-csearch_path=test'
   # 方式B：独立数据库（需 pg_hba.conf 放行）
   export QTRADER_TEST_DB_URL='postgresql+psycopg://user:pass@host:5432/qtrader_test'
   ```

   **数据回退**：每个用例结束后自动 TRUNCATE 涉及表（DAO 内部 `session_scope` 自行 commit，外部回滚管不到）。

**通过标准**：
- [ ] 全部通过（真实库用例在未配置 `QTRADER_TEST_DB_URL` 时 skip 属正常）
- [ ] 测后无残留数据（TRUNCATE 回退生效）

---

### 第三层：API 测试（真实后端）

**目的**：启动后端所有服务（Manager + Trader），通过 HTTP 请求对关键 API 做单个或组合测试。最小化 mock——除登录凭据外全链路真实（含 Unix Socket IPC 与网关）。

**前置条件**：
```bash
# 终端 1：启动 Manager（配置中 account_ids 含 DQ）
uv run python run_manager.py
# DQ Trader 已连接（Web 平台启动，或 POST /api/account/DQ/start）
```

**运行测试**：
```bash
E2E_USERNAME=admin E2E_PASSWORD=xxx make test-api
```

**门控机制**（未就绪时 skip 而非 fail）：
- 后端在线探测：`GET /health` 不在线 → 整层 skip
- 登录：`E2E_USERNAME` / `E2E_PASSWORD` → `POST /api/auth/login` 取 token；未设置 → skip
- 写路径：DQ Trader 已连接 + 交易时段守卫（非交易时段 skip）；仅在 **DQ 模拟盘账户**执行

**用例组成**：

| 文件 | 范围 | 依赖 |
|------|------|------|
| test_api_smoke.py | 核心读端点可用性 + 响应结构 + 鉴权拦截 | 后端在线 + 登录 |
| test_api_trading.py | 报单指令全流程、挂单撤销、错误链路透传 | + DQ 连接 + 交易时段 |
| test_api_invalid_orders.py | 直接/指令下单无效参数、无效合约、风控拦截、账户/持仓/成交/合约结构 | 部分需 DQ 连接 |
| test_api_rotation.py | 导入换仓CSV（append/replace/坏行）、批量删除、开始/停止换仓 | start/stop 需 DQ 连接 |

**通过标准**：
- [ ] 读路径全绿
- [ ] 写路径全绿（非交易时段/Trader 未连接时 skip 属正常）

---

### 第四层：E2E 测试（Playwright 前后端联调）

**目的**：真实浏览器中验证前后端联调的关键路径与操作。可能受外部服务影响（如非交易时段）。

**两种模式**：
- **冒烟模式（默认）**：屏蔽 API/WebSocket 验证页面渲染，零写操作，CI 可跑
- **联调模式**：设置 `E2E_USERNAME` / `E2E_PASSWORD` 真实登录，允许在 **DQ 模拟盘账户**上触发真实交易（写路径用例受交易时段守卫约束，非交易时段自动 skip）

**场景覆盖**：账户信息/持仓/成交/合约页签渲染、直接下单（弹窗流程 + 无效单前端拦截 + 联调模式真实报单）、指令下单（新增流程 + 无效单拦截 + 联调模式全流程成交）、导入换仓文件（对话框流程 + 真实文件上传解析 + 开始/停止换仓）。

**命令**：`make test-e2e`（前置与模式的详细说明见 [README](README.md#e2e测试特殊配置)）

**通过标准**：
- [ ] 冒烟模式全部通过（联调模式用例 skip 属正常）
- [ ] 联调模式全绿（非交易时段 skip 属正常）

---

### 第五层：用户验收测试 (UAT)

**目的**：用户按关键场景清单逐条真实操作验证，不自动化。

**前置条件**：
```bash
# 终端 1：启动后端（Manager）
uv run python run_manager.py

# 终端 2：启动前端
cd web && npm run dev
```

**关键场景**：

| 场景 | 路径 | 前置自动化覆盖 |
|------|------|----------------|
| 用户登录 | `/login` | E2E 冒烟 |
| 查看账户信息 | `/dashboard` | E2E 冒烟 + API 冒烟 |
| 查看持仓/成交记录 | `/account` | E2E 冒烟 + API 冒烟 |
| 报单流程 | `/account` 账户交易页签 → 报单 → 确认 | E2E 冒烟（到弹窗）+ API 写路径 |
| 报单指令全流程 | `/account` 报单指令页签 | E2E 联调 + API 写路径 |
| 撤单操作 | `/account` 挂单列表 → 撤单 | API 写路径 |
| 管理定时任务 | `/account` 账户设置页签 → 启停任务 | 纯手工 |

**手工验证约束**：
- 仅使用 DQ 账户（模拟盘），非交易时段下单/撤单会失败
- 验证要点：页面无 JS 错误、操作响应及时、数据显示正确、错误提示友好

**通过标准**：
- [ ] 所有手工场景通过（仅 DQ）
- [ ] 无明显 UI/UX 问题

---

## 测试报告

### 测试汇总表

| 阶段 | 工具 | 通过标准 | 状态 |
|------|------|----------|------|
| 0. 静态检测 | mypy | 无 error 级别错误 | ⬜ |
| 1. 单元测试 | pytest | 核心模块 ≥ 90%，变动代码必测 | ⬜ |
| 2. 集成测试 | pytest | 模块联动全通过（真实库部分按需） | ⬜ |
| 3. API 测试 | pytest + httpx | 读路径全绿，写路径按时段 | ⬜ |
| 4. E2E 测试 | Playwright | 冒烟全绿，联调按时段 | ⬜ |
| 5. UAT 测试 | 手工 | 场景清单逐条通过（仅 DQ） | ⬜ |

### 代码覆盖率报告

覆盖率命令见 [README](README.md#3-测试覆盖率)。口径：核心模块 ≥ 90%，非核心模块与排除项不设硬指标，变动代码必测（清单见第一层）。

---

## 快速命令

```bash
# 完整测试流程（mypy → unit → integration；api/e2e 单独执行）
make test-all

# 分层测试
make test-mypy          # 静态检测
make test-unit          # 第1层：单元测试
make test-integration   # 第2层：集成测试
make test-api           # 第3层：API 测试（需真实后端）
make test-e2e           # 第4层：E2E 测试（Playwright）

# 覆盖率报告
make test-coverage
```

---

## 附录

### 相关文档

- **[CLAUDE.md](../CLAUDE.md)** - 项目开发指南
- **[README.md](README.md)** - 测试操作指南（如何运行、编写、调试测试）
