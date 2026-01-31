# Q-Trader Makefile
# 常用命令快捷方式

.PHONY: help test test-unit test-api test-e2e test-all test-coverage clean lint format

help:  ## 显示帮助信息
	@echo "Q-Trader 开发命令："
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
	pytest tests/ --cov=src --cov-report=html
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
	black src/ --line-length 100 --target py38 --check
	isort src/ --profile black --check
	mypy src/

format:  ## 格式化代码
	black src/ --line-length 100 --target py38
	isort src/ --profile black

start-backend:  ## 启动后端服务
	python -m src.main

start-frontend:  ## 启动前端服务
	cd web && npm run dev

install-deps:  ## 安装所有依赖
	pip install -r requirements.txt
	pip install -r requirements-test.txt
	playwright install chromium

dev-setup:  ## 开发环境初始化
	@echo "初始化开发环境..."
	@echo "1. 安装依赖..."
	pip install -r requirements.txt
	pip install -r requirements-test.txt
	playwright install chromium
	cd web && npm install
	@echo ""
	@echo "开发环境初始化完成！"
	@echo ""
	@echo "启动服务："
	@echo "  后端: make start-backend"
	@echo "  前端: make start-frontend"
	@echo "  测试: make test-all"
