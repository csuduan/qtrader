#!/bin/bash
# Q-Trader 完整测试流程脚本
# 按照 TESTING.md 规范执行测试

set -e

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Q-Trader 完整测试流程"
echo "=========================================="
echo ""

# 检查 conda 环境
if [ -z "$CONDA_DEFAULT_ENV" ] || [ "$CONDA_DEFAULT_ENV" != "qts" ]; then
    echo -e "${YELLOW}警告: 未检测到 qts conda 环境${NC}"
    echo "请运行: conda activate qts"
    exit 1
fi

echo -e "${GREEN}✓ 当前环境: $CONDA_DEFAULT_ENV${NC}"
echo ""

# ============================================
# 第一步：静态代码检测 (mypy)
# ============================================
echo "=========================================="
echo "第一步：静态代码检测 (mypy)"
echo "=========================================="
echo ""

MYPY_OUTPUT=$(python -m mypy src/ --show-error-codes --ignore-missing-imports 2>&1) || true
MYPY_ERRORS=$(echo "$MYPY_OUTPUT" | grep -c "error:" || echo "0")

echo "$MYPY_OUTPUT"
echo ""

if [ "$MYPY_ERRORS" -eq 0 ]; then
    echo -e "${GREEN}✓ mypy 检查通过 (0 错误)${NC}"
else
    echo -e "${RED}✗ mypy 发现 $MYPY_ERRORS 个错误${NC}"
    echo -e "${YELLOW}请修复上述错误后再继续测试${NC}"
    exit 1
fi

echo ""

# ============================================
# 第二步：单元测试 (pytest + coverage)
# ============================================
echo "=========================================="
echo "第二步：单元测试 (pytest + coverage)"
echo "=========================================="
echo ""

# 运行单元测试并收集覆盖率
pytest tests/unit/ -v --cov=src --cov-report=term-missing --cov-report=html 2>&1 | tee /tmp/pytest_output.txt || true

# 检查是否有测试失败
FAILED_TESTS=$(grep -c "FAILED" /tmp/pytest_output.txt || echo "0")

if [ "$FAILED_TESTS" -gt 0 ]; then
    echo -e "${RED}✗ 有 $FAILED_TESTS 个测试失败${NC}"
    exit 1
fi

# 提取覆盖率
COVERAGE=$(grep "TOTAL" /tmp/pytest_output.txt | awk '{print $4}' | tr -d '%')
if [ -z "$COVERAGE" ]; then
    COVERAGE="0"
fi

echo ""
echo -e "当前代码覆盖率: ${YELLOW}${COVERAGE}%${NC}"
echo ""

# 检查覆盖率是否达到 95%
if [ "$(echo "$COVERAGE >= 95" | bc -l)" -eq 1 ]; then
    echo -e "${GREEN}✓ 代码覆盖率达标 (≥95%)${NC}"
else
    echo -e "${RED}✗ 代码覆盖率未达标 (当前: ${COVERAGE}%, 要求: ≥95%)${NC}"
    echo ""
    echo "需要补充单元测试："
    echo "1. 查看覆盖率报告: open htmlcov/index.html"
    echo "2. 找到未覆盖的代码模块"
    echo "3. 在 tests/unit/ 下创建对应的测试文件"
    echo "4. 重新运行测试直到覆盖率达标"
    exit 1
fi

echo ""

# ============================================
# 第三步：RESTful API 测试
# ============================================
echo "=========================================="
echo "第三步：RESTful API 测试"
echo "=========================================="
echo ""

# 检查后端服务是否已启动
echo "检查后端服务状态..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ 后端服务已启动${NC}"
else
    echo -e "${YELLOW}警告: 后端服务未启动${NC}"
    echo "请运行: python -m src.main"
    echo ""
    echo -e "${YELLOW}跳过 API 测试${NC}"
    echo ""
    API_SKIPPED=true
fi

if [ "$API_SKIPPED" != "true" ]; then
    # 运行 API 测试
    pytest tests/integration/test_api.py -v 2>&1 | tee /tmp/api_test_output.txt || true

    # 检查 API 测试结果
    API_FAILED=$(grep -c "FAILED" /tmp/api_test_output.txt || echo "0")
    API_PASSED=$(grep -c "PASSED" /tmp/api_test_output.txt || echo "0")

    echo ""
    echo -e "API 测试结果: ${GREEN}通过: $API_PASSED${NC}, ${RED}失败: $API_FAILED${NC}"

    if [ "$API_FAILED" -gt 0 ]; then
        echo -e "${RED}✗ API 测试有失败项${NC}"
        exit 1
    else
        echo -e "${GREEN}✓ 所有 API 测试通过${NC}"
    fi
fi

echo ""

# ============================================
# 第四步：用户验收测试 (UAT)
# ============================================
echo "=========================================="
echo "第四步：用户验收测试 (UAT)"
echo "=========================================="
echo ""

echo "UAT 测试需要手动执行："
echo ""
echo "1. 确保前后端服务已启动："
echo "   - 后端: python -m src.main"
echo "   - 前端: cd web && npm run dev"
echo ""
echo "2. 打开 Chrome 浏览器，访问 http://localhost:5173"
echo ""
echo "3. 按 F12 打开 Chrome DevTools"
echo ""
echo "4. 按照测试案例执行测试："
echo "   测试案例文件: tests/UAT测试案例.xls"
echo ""
echo "5. 验证要点："
echo "   - 页面加载正常，无 JavaScript 错误"
echo "   - 用户操作响应及时"
echo "   - 数据显示正确"
echo "   - 错误提示友好"
echo ""

# ============================================
# 测试汇总
# ============================================
echo "=========================================="
echo "测试汇总"
echo "=========================================="
echo ""

echo "| 测试阶段 | 工具 | 通过标准 | 状态 |"
echo "|----------|------|----------|------|"

if [ "$MYPY_ERRORS" -eq 0 ]; then
    echo "| 1. 静态检测 | mypy | 无 error 级别错误 | ✅ 通过 |"
else
    echo "| 1. 静态检测 | mypy | 无 error 级别错误 | ❌ 失败 ($MYPY_ERRORS 错误) |"
fi

if [ "$(echo "$COVERAGE >= 95" | bc -l)" -eq 1 ] && [ "$FAILED_TESTS" -eq 0 ]; then
    echo "| 2. 单元测试 | pytest | 覆盖率 ≥ 95% | ✅ 通过 (${COVERAGE}%) |"
else
    echo "| 2. 单元测试 | pytest | 覆盖率 ≥ 95% | ❌ 失败 (${COVERAGE}%) |"
fi

if [ "$API_SKIPPED" = "true" ]; then
    echo "| 3. API 测试 | pytest | 所有端点通过 | ⏭️ 跳过 |"
elif [ "$API_FAILED" -eq 0 ]; then
    echo "| 4. API 测试 | pytest | 所有端点通过 | ✅ 通过 |"
else
    echo "| 4. API 测试 | pytest | 所有端点通过 | ❌ 失败 |"
fi

echo "| 5. UAT 测试 | Chrome DevTools | 所有场景通过 | ⏸️ 手动执行 |"
echo ""

echo "=========================================="
echo "测试完成"
echo "=========================================="
