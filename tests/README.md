# Q-Trader 测试操作指南

## 概述

本文档提供 Q-Trader 项目的测试操作指南，包括如何运行、编写和调试测试。

> **注意**：本文档是测试的"操作手册"。关于测试流程、标准和通过要求，请参见项目根目录的 [TESTING.md](../TESTING.md)

---

## 测试目录结构

```
tests/
├── conftest.py          # pytest全局配置和共享fixtures
├── unit/                # 单元测试
│   └── test_models.py  # 模型测试
├── integration/         # 集成测试
│   └── test_api.py     # API接口测试
└── e2e/                 # 端到端测试
    ├── conftest.py     # E2E测试配置
    └── test_user_flow.py  # 用户流程测试
```

## 快速开始

### 1. 安装测试依赖

```bash
# 安装Python测试依赖
pip install -r requirements-test.txt

# 安装Playwright浏览器（首次运行）
playwright install chromium
```

### 2. 运行测试

```bash
# 按照测试流程：单元测试 -> API测试 -> E2E测试

# 第一步：运行单元测试
pytest tests/unit/ -v

# 第二步：运行API集成测试（需先启动后端）
python -m src.main &  # 启动后端
pytest tests/integration/ -v

# 第三步：运行E2E测试（需先启动前后端）
python -m src.main &  # 终端1：启动后端
cd web && npm run dev &  # 终端2：启动前端
pytest tests/e2e/ -v --headed
```

### 3. 测试覆盖率

```bash
# 生成覆盖率报告
pytest tests/ --cov=src --cov-report=html

# 查看报告
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## 测试标记

使用pytest标记来分类测试：

- `@pytest.mark.unit` - 单元测试
- `@pytest.mark.integration` - 集成测试
- `@pytest.mark.e2e` - 端到端测试
- `@pytest.mark.slow` - 慢速测试

### 运行特定标记的测试

```bash
# 只运行单元测试
pytest -m unit -v

# 只运行集成测试
pytest -m integration -v

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

## E2E测试特殊配置

### Playwright配置

E2E测试使用Playwright进行浏览器自动化测试。配置文件：`playwright.config.py`

```python
[playwright]
base_url = "http://localhost:5173"
browser = "chromium"
headless = false  # 显示浏览器窗口
slowmo = 0  # 慢速延迟（毫秒）
viewport = "1280x720"
video = "retain-on-failure"  # 失败时保留视频
screenshot = "only-on-failure"  # 失败时截图
```

### 运行E2E测试

```bash
# 显示浏览器窗口
pytest tests/e2e/ -v --headed

# 无头模式（适合CI/CD）
pytest tests/e2e/ -v

# 慢速模式（便于观察）
pytest tests/e2e/ -v --slowmo=1000

# 查看生成的视频和截图
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
from src.manager.app import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_create_order(client: TestClient):
    response = client.post("/api/orders", json={
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
    page.goto("http://localhost:5173")
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

确保激活虚拟环境并安装依赖：
```bash
conda activate qts
pip install -r requirements-test.txt
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

如果后端端口8000或前端端口5173被占用：
```bash
# 查找占用进程
lsof -i :8000
lsof -i :5173

# 终止进程
kill -9 <PID>
```

### 5. 测试超时

增加测试超时时间：
```bash
pytest --timeout=300 tests/e2e/ -v
```

## 持续集成

在CI/CD环境中运行测试：

```bash
# 完整测试套件
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v --headless

# 生成报告
pytest tests/ --cov=src --cov-report=xml --junitxml=test-results.xml
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
