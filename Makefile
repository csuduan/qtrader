# qrader Makefile
# 常用命令快捷方式

.PHONY: help test test-unit test-api test-e2e test-all test-coverage clean lint format

help:  ## 显示帮助信息
	@echo "qrader 开发命令："
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

test-unit:  ## 运行单元测试
	pytest tests/unit/ -v

test-api:  ## 运行API集成测试（需先启动后端）
	pytest tests/integration/ -v

test-e2e:  ## 运行E2E测试（需先启动前后端）
	pytest tests/e2e/ -v --headed

test-all:  ## 运行所有测试（按顺序）
	@echo "运行完整测试套件..."
	python run_tests.py

test-coverage:  ## 生成测试覆盖率报告
	pytest tests/ --cov=qtrader --cov-report=html
	@echo "覆盖率报告: htmlcov/index.html"

clean:  ## 清理测试生成的文件
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -f test-results.xml
	rm -f test.log
	rm -rf test-results/
	rm -rf .hypothesis/
	rm -rf .playwright/

lint:  ## 运行代码检查
	black src/qtrader/ --line-length 100 --target py312 --check
	isort src/qtrader/ --profile black --check
	mypy src/qtrader/

format:  ## 格式化代码
	black src/qtrader/ --line-length 100 --target py312
	isort src/qtrader/ --profile black


install:  ## 安装项目
	uv pip install -e .
