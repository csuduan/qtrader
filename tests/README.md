# Q-Trader 测试操作指南

## 概述

本文档提供 Q-Trader 项目的测试操作指南，包括如何运行、编写和调试测试。

> **注意**：本文档是测试的"操作手册"。关于测试流程、标准和通过要求，请参见项目根目录的 [TESTING.md](../TESTING.md)

---

## 测试目录结构

```
tests/
├── conftest.py          # pytest全局配置和共享fixtures
├── unit/                # 第1层：单元测试
│   └── test_models.py  # 模型测试
├── integration/         # 第2层：集成测试（模块联动；含真实PG库联动 test_db_integration.py）
│   └── test_api.py     # API路由联动测试
├── api/                 # 第3层：API测试（真实后端，最小化mock）
│   ├── conftest.py     # 后端探测/登录/时段守卫 fixtures
│   ├── test_api_smoke.py    # 读路径冒烟
│   ├── test_api_trading.py  # 写路径交易流程（DQ模拟盘）
│   ├── test_api_invalid_orders.py  # 无效单：参数校验/风控/错误透传
│   └── test_api_rotation.py  # 换仓：导入CSV/批量删除/开始停止
└── e2e/                 # 第4层：端到端测试（Playwright 前后端联调）
    ├── conftest.py     # E2E测试配置
    ├── test_user_flow.py  # 用户流程测试
    ├── test_rotation_flow.py  # 换仓流程测试（mock后端）
    └── test_trading_scenarios.py  # 合约信息/无效单拦截/真实报单/导入上传
```

## 快速开始

### 1. 安装测试依赖

```bash
# 安装Python测试依赖
uv sync --group dev

# 安装Playwright浏览器（首次运行，国内可加 PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright/）
playwright install chromium
```

### 2. 运行测试

完整流程（静态检测 → 五层）与通过标准见 [TESTING.md](TESTING.md)。

```bash
make test-unit          # 第1层：单元测试
make test-integration   # 第2层：集成测试
make test-api           # 第3层：API测试（需先启动后端 Manager + DQ Trader）
make test-e2e           # 第4层：E2E测试（前置：前端 dev server，见下方"E2E测试特殊配置"）
```

### 3. 测试覆盖率

```bash
# 生成覆盖率报告（与 make test-coverage 一致）
pytest tests/unit/ --cov=src/qtrader --cov-report=html

# 查看报告
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## 测试标记

使用pytest标记来分类测试：

- `@pytest.mark.unit` - 单元测试
- `@pytest.mark.integration` - 集成测试
- `@pytest.mark.api` - 真实后端API测试
- `@pytest.mark.e2e` - 端到端测试（Playwright 前后端联调）
- `@pytest.mark.slow` - 慢速测试

### 运行特定标记的测试

```bash
# 只运行单元测试
pytest -m unit -v

# 只运行集成测试
pytest -m integration -v

# 只运行API测试
pytest -m api -v

# 只运行E2E测试
pytest -m e2e -v

# 排除慢速测试
pytest -m "not slow" -v
```

## 调试测试

### 运行单个测试

```bash
# 运行特定测试函数
pytest tests/unit/test_models.py::TestAccountModel::test_account_creation -v

# 运行特定测试类
pytest tests/unit/test_models.py::TestAccountModel -v

# 运行特定文件
pytest tests/unit/test_models.py -v
```

### 查看详细输出

```bash
# 显示print输出
pytest -v -s tests/unit/test_models.py

# 显示更详细的错误信息
pytest --tb=long tests/unit/test_models.py

# 只在第一个失败时停止
pytest -x tests/unit/
```

### 调试失败测试

```bash
# 重新运行上次失败的测试
pytest --lf

# 进入pdb调试器
pytest --pdb tests/unit/test_models.py

# 在第一个失败时进入pdb
pytest --pdb -x tests/unit/test_models.py
```

## API测试（真实后端）

第3层 API 测试直连运行中的后端服务，最小化 mock。详细流程与通过标准见 [TESTING.md](TESTING.md#第三层api-测试真实后端)。

```bash
# 前置：启动 Manager 并确保 DQ Trader 已连接
uv run python run_manager.py

# 运行（需登录凭据；写路径用例另需交易时段）
E2E_USERNAME=admin E2E_PASSWORD=xxx pytest tests/api/ -v

# 自定义后端地址（默认 http://localhost:8000）
API_TEST_BASE_URL=http://host:8000 E2E_USERNAME=... E2E_PASSWORD=... pytest tests/api/ -v
```

门控机制（未就绪时 skip 而非 fail）：
- 后端未启动：`GET /health` 探测失败 → 整层 skip
- 未设置 `E2E_USERNAME` / `E2E_PASSWORD`：登录 fixture skip
- 写路径：DQ Trader 未连接或非交易时段 → 自动 skip

## 数据库集成测试（真实 PostgreSQL）

第2层中的 `tests/integration/test_db_integration.py` 连接真实 PostgreSQL，验证 DAO 层在 PG 方言下的行为（upsert、约束、事务）——SQLite 单测无法覆盖的路径。

```bash
# 环境隔离二选一（均不触碰生产数据）：

# 方式A：独立 schema（同库，URL 传 search_path，无额外权限要求）
export QTRADER_TEST_DB_URL='postgresql+psycopg://user:pass@host:5432/qtrader?options=-csearch_path=test'

# 方式B：独立数据库（需 pg_hba.conf 放行该库的客户端访问）
# CREATE DATABASE qtrader_test OWNER tester;
export QTRADER_TEST_DB_URL='postgresql+psycopg://user:pass@host:5432/qtrader_test'

# 运行（未设置则该部分自动 skip）
pytest tests/integration/test_db_integration.py -v
```

数据回退：每个用例结束后自动 TRUNCATE 涉及表，不留残留数据。

## E2E测试特殊配置

### Playwright配置

E2E测试基于 `pytest-playwright` 插件，`base_url` 统一在 `pytest.ini` 中配置（`http://localhost:3000`，与 `web/vite.config.ts` 一致）。

两种运行模式：

- **冒烟模式（默认）**：无需后端。自动屏蔽 API/WebSocket 并注入模拟登录态，仅验证页面渲染，不触碰真实交易系统，零写操作。
- **真实模式**：设置 `E2E_USERNAME` / `E2E_PASSWORD` 环境变量后执行真实登录，账户/持仓相关用例（标记为 skip 的）随之生效。登录后自动切换到 **DQ 账户**，所有账户相关操作仅限 DQ。

```bash
# 安全约束：
# - 冒烟模式零写操作，报单流程仅验证到确认弹窗
# - 真实模式允许触发真实交易（DQ 为模拟盘账户）：写路径用例仅在本模式生效，
#   且受交易时段守卫约束（非交易时段自动 skip，不 fail）
# - 写路径用例合约默认 SHFE.rb2701，主力换月时用 E2E_SYMBOL 环境变量覆盖
```

### 运行E2E测试

```bash
# 前置：启动前端 dev server（冒烟模式无需后端）
cd web && npm run dev

# 显示浏览器窗口
pytest tests/e2e/ -v --headed

# 无头模式（适合CI/CD）
pytest tests/e2e/ -v

# 真实登录模式（含写路径用例，需后端 + 交易时段 + DQ 模拟盘）
E2E_USERNAME=admin E2E_PASSWORD=xxx pytest tests/e2e/ -v

# 覆盖写路径用例的主力合约
E2E_USERNAME=admin E2E_PASSWORD=xxx E2E_SYMBOL=SHFE.rb2701 pytest tests/e2e/ -v

# 失败时截图
pytest tests/e2e/ -v --screenshot only-on-failure

# 查看生成的截图
ls -l test-results/
```

## 编写测试

### 单元测试示例

```python
import pytest
from src.models.object import Account

class TestAccountModel:
    def test_account_creation(self):
        account = Account(
            account_id="test",
            total_assets=1000.0
        )
        assert account.account_id == "test"
        assert account.total_assets == 1000.0

    @pytest.mark.parametrize("total_assets,expected", [
        (1000.0, 950.0),
        (2000.0, 1950.0),
    ])
    def test_available_calculation(self, total_assets, expected):
        account = Account(
            account_id="test",
            total_assets=total_assets,
            frozen=50.0
        )
        assert account.available == expected
```

### API测试示例

```python
from fastapi.testclient import TestClient
from qtrader.manager.app import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_create_order(client: TestClient):
    response = client.post("/api/order", json={
        "symbol": "SHFE.rb2505",
        "direction": "BUY",
        "offset": "OPEN",
        "volume": 1,
        "price": 3500.0
    })
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 0
    assert "order_id" in data["data"]
```

### E2E测试示例

```python
from playwright.sync_api import Page

def test_create_order(page: Page):
    # 导航到页面
    page.goto("http://localhost:3000")
    page.wait_for_load_state("networkidle")
    
    # 填写表单
    page.fill("input[name='symbol']", "SHFE.rb2505")
    page.fill("input[name='volume']", "1")
    
    # 提交表单
    page.click("button[type='submit']")
    
    # 验证结果
    success_message = page.query_selector(".message.success")
    assert success_message is not None
```

## 常见问题

### 1. 导入错误

确保安装了依赖：
```bash
uv sync --group dev
```

### 2. 数据库连接错误

API测试使用内存数据库，无需配置。如果遇到数据库问题，检查：
- 是否正确导入Base和models
- 是否正确覆盖get_db依赖

### 3. 浏览器未安装

首次运行E2E测试前，安装Playwright浏览器：
```bash
playwright install chromium
```

### 4. 端口被占用

如果后端端口8000或前端端口3000被占用：
```bash
# 查找占用进程
lsof -i :8000
lsof -i :3000

# 终止进程
kill -9 <PID>
```

### 5. 测试超时

增加测试超时时间：
```bash
pytest --timeout=300 tests/e2e/ -v
```

## 持续集成

在CI/CD环境中运行测试（第1、2层无需外部服务；第3、4层依赖真实后端/前端与凭据，单独执行）：

```bash
# CI 可跑的测试套件
pytest tests/unit/ -v
pytest tests/integration/ -v

# 生成报告
pytest tests/unit/ tests/integration/ --cov=src --cov-report=xml --junitxml=test-results.xml
```

## 最佳实践

1. **保持测试独立** - 每个测试应该独立运行，不依赖其他测试
2. **使用fixtures** - 重用测试数据和配置
3. **命名清晰** - 测试名称应该描述测试内容
4. **覆盖边界情况** - 测试正常和异常情况
5. **定期运行** - 在提交代码前运行测试
6. **维护测试** - 及时更新过时的测试

## 参考资料

- **[TESTING.md](../TESTING.md)** - Q-Trader 测试规范（测试流程、标准、报告）
- **[AGENTS.md](../AGENTS.md)** - Q-Trader 开发指南（代码规范、架构）
- [Pytest Documentation](https://docs.pytest.org/)
- [Playwright Documentation](https://playwright.dev/python/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
