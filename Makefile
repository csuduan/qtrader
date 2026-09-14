# qrader Makefile
# 常用命令快捷方式

.PHONY: help test test-mypy test-unit test-integration test-api test-e2e test-all test-coverage clean lint check format

help:  ## 显示帮助信息
	@echo "qrader 开发命令："
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

test-mypy:  ## 运行静态类型检查
	uv run python -m mypy src/ --show-error-codes --ignore-missing-imports

test-unit:  ## 运行单元测试（第1层）
	uv run pytest tests/unit/ -v

test-integration:  ## 运行集成测试（第2层：模块联动，mock 交易接口；真实库用例需设置 QTRADER_TEST_DB_URL）
	uv run pytest tests/integration/ -v

test-api:  ## 运行API测试（第3层：真实后端，最小化 mock；需先启动 Manager + DQ Trader，设置 E2E_USERNAME/E2E_PASSWORD）
	uv run pytest tests/api/ -v

test-e2e:  ## 运行E2E测试（第4层：Playwright 前后端联调；冒烟模式需先启动前端 dev server，真实模式设置 E2E_USERNAME/E2E_PASSWORD）
	uv run pytest tests/e2e/ -v --headed

test-all:  ## 运行自动化测试全链路（mypy → unit → integration；api/e2e 依赖真实后端与前端，单独执行）
	@echo "运行完整测试套件..."
	uv run python -m mypy src/ --show-error-codes --ignore-missing-imports
	uv run pytest tests/unit/ -v
	uv run pytest tests/integration/ -v

test-coverage:  ## 生成测试覆盖率报告（单元测试层）
	uv run pytest tests/unit/ --cov=src/qtrader --cov-report=html
	@echo "覆盖率报告: htmlcov/index.html"

clean:  ## 清理测试生成的文件
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -f test-results.xml
	rm -f test.log
	rm -rf test-results/
	rm -rf .hypothesis/
	rm -rf .playwright/

lint:  ## 运行代码检查（ruff lint/format）
	uv run ruff check src/
	uv run ruff format --check src/

check: test-mypy lint  ## 综合检查（先 mypy 静态检查，再 lint 代码检查）

format:  ## 格式化代码
	uv run ruff check --fix src/
	uv run ruff format src/


install:  ## 安装项目
	uv sync --group dev
