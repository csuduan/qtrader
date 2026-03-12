# Q-Trader 测试规范

## 概述

本文档描述 Q-Trader 项目的测试流程和规范。所有代码在提交前必须按照以下流程进行测试。

> **提示**：本文档定义测试标准和流程。关于如何运行和编写测试的详细操作指南，请参见 [tests/README.md](tests/README.md)

---

## 测试流程

### 第一步：静态代码检测 (mypy)

**目的**：检查类型注解，提前发现潜在错误。

**命令**：
```bash
# 运行 mypy 静态检查
python -m mypy src/ --show-error-codes --ignore-missing-imports
```

**通过标准**：
- [ ] 无 `error` 级别错误
- [ ] 可选：尽量减少 `warning`

**发现错误时**：
1. 根据 mypy 提示修复类型注解
2. 修复后重新运行 mypy 直到通过
3. 将修复提交到代码库

---

### 第二步：单元测试 (pytest + coverage)

**目的**：验证核心功能，确保代码质量。

**运行测试**：
```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 生成覆盖率报告
pytest tests/unit/ --cov=src --cov-report=term-missing --cov-report=html
```

**通过标准**：
- [ ] 所有测试通过（passed）
- [ ] **代码覆盖率 ≥ 95%**

**覆盖率不足 95% 时**：

1. **查看未覆盖代码**：
   ```bash
   # 查看 HTML 报告
   open htmlcov/index.html
   ```

2. **补充单元测试**：
   - 找到覆盖率低的模块（如 `src/adapters/`, `src/trader/`）
   - 在 `tests/unit/` 下创建对应的测试文件
   - 确保每个公共方法都有对应的测试用例

3. **重新运行测试**，直到覆盖率达到 95%

**单元测试补充模板**：
```python
# tests/unit/test_xxx.py
import pytest
from src.xxx import SomeClass

class TestSomeClass:
    def test_method_name(self):
        # 准备数据
        obj = SomeClass()

        # 执行操作
        result = obj.method()

        # 验证结果
        assert result == expected_value
```

---

### 第三步：RESTful API 测试

**目的**：验证所有 API 接口功能正常。

**前置条件**：
```bash
# 启动后端服务
python -m src.main
```

**运行测试**：
```bash
# 运行 API 集成测试
pytest tests/integration/test_api.py -v
```

**通过标准**：
- [ ] 所有 API 端点测试通过
- [ ] HTTP 状态码符合预期
- [ ] 响应数据结构正确

**测试覆盖的 API 端点**：

| 模块 | 端点 | 方法 | 状态 |
|------|------|------|------|
| 账户 | `/api/account` | GET | ⬜ |
| 账户 | `/api/account/all` | GET | ⬜ |
| 持仓 | `/api/positions` | GET | ⬜ |
| 订单 | `/api/orders` | GET | ⬜ |
| 订单 | `/api/orders` | POST | ⬜ |
| 成交 | `/api/trades/today` | GET | ⬜ |
| 成交 | `/api/trades/history` | GET | ⬜ |
| 系统 | `/` | GET | ⬜ |
| 系统 | `/health` | GET | ⬜ |

---

### 第四步：用户验收测试 (UAT) - Chrome DevTools

**目的**：模拟真实用户操作，验证完整业务流程。

**前置条件**：
```bash
# 终端 1：启动后端
python -m src.main

# 终端 2：启动前端
cd web && npm run dev
```

**测试依据**：
- 测试案例文件：`tests/UAT测试案例.xls`

**测试步骤**：

1. **启动 Chrome DevTools**
   - 打开 Chrome 浏览器
   - 访问 `http://localhost:5173`
   - 按 F12 打开 DevTools

2. **按照测试案例执行测试**

   | 测试场景 | 操作步骤 | 预期结果 | 状态 |
   |----------|----------|----------|------|
   | 用户登录 | 1. 输入用户名<br>2. 输入密码<br>3. 点击登录 | 登录成功，跳转到首页 | ⬜ |
   | 查看账户信息 | 1. 点击账户菜单<br>2. 查看账户信息 | 显示账户ID、余额、可用资金 | ⬜ |
   | 创建订单 | 1. 进入下单页面<br>2. 选择合约<br>3. 输入数量<br>4. 点击提交 | 订单创建成功，显示订单ID | ⬜ |
   | 撤单操作 | 1. 进入订单列表<br>2. 选择待撤订单<br>3. 点击撤单 | 撤单成功，订单状态更新 | ⬜ |
   | 查看持仓 | 1. 点击持仓菜单<br>2. 查看持仓列表 | 显示当前持仓合约、数量、盈亏 | ⬜ |
   | 查看成交记录 | 1. 点击成交菜单<br>2. 查看今日成交 | 显示今日成交记录 | ⬜ |
   | 管理定时任务 | 1. 进入任务管理<br>2. 暂停/恢复任务 | 任务状态更新 | ⬜ |

3. **验证要点**
   - 页面加载正常，无 JavaScript 错误
   - 用户操作响应及时
   - 数据显示正确
   - 错误提示友好

**通过标准**：
- [ ] 所有 UAT 测试场景通过
- [ ] 无明显 UI/UX 问题
- [ ] 业务逻辑正确

---

## 测试报告

### 测试汇总表

| 测试阶段 | 工具 | 通过标准 | 状态 |
|----------|------|----------|------|
| 1. 静态检测 | mypy | 无 error 级别错误 | ⬜ |
| 2. 单元测试 | pytest | 覆盖率 ≥ 95% | ⬜ |
| 3. API 测试 | pytest | 所有端点通过 | ⬜ |
| 4. UAT 测试 | Chrome DevTools | 所有场景通过 | ⬜ |

### 代码覆盖率报告

```bash
# 生成覆盖率报告
pytest tests/unit/ --cov=src --cov-report=term-missing
```

**覆盖率目标**：≥ 95%

---

## 快速命令

```bash
# 完整测试流程
make test-all

# 分阶段测试
make test-mypy      # 静态检测
make test-unit      # 单元测试
make test-api       # API 测试
make test-uat       # UAT 测试

# 覆盖率报告
make test-coverage
```

---

## 附录

### 测试文件清单

- `tests/conftest.py` - pytest全局配置
- `tests/unit/` - 单元测试
- `tests/integration/` - API集成测试
- `tests/e2e/` - 端到端测试
- `tests/UAT测试案例.xls` - UAT测试案例

### 相关文档

- **[CLAUDE.md](./CLAUDE.md)** - 项目开发指南
- **[AGENTS.md](./AGENTS.md)** - Agent开发指南（代码规范、架构说明、开发环境）
- **[tests/README.md](./tests/README.md)** - 测试操作指南（如何运行、编写、调试测试）
