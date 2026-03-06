#!/bin/bash
# Q-Trader 启动脚本
#
# 功能:
# - 启动 Manager 和指定账户的 Trader
# - 检查进程是否已存在
# - 输出启动结果报告
#
# 用法:
#   ./start.sh ALL           # 启动所有
#   ./start.sh DQ,GWQ        # 启动指定账户
#   ./start.sh               # 默认启动 Manager

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Conda 环境名称
CONDA_ENV="qts"

# 从 config.yaml 读取可用账户列表
get_available_accounts() {
    local config_file="config/config.yaml"
    if [ -f "$config_file" ]; then
        # 提取 account_ids 部分（从 account_ids 到 paths 之间）
        sed -n '/^account_ids:/,/^paths:/p' "$config_file" | grep -E '^\s+-\s*"' | sed 's/.*"\(.*\)".*/\1/'
    else
        log_error "配置文件不存在: $config_file"
        exit 1
    fi
}

declare -a AVAILABLE_ACCOUNTS=()
# 读取账户列表到数组
while IFS= read -r line; do
    [ -n "$line" ] && AVAILABLE_ACCOUNTS+=("$line")
done < <(get_available_accounts)

# 结果统计
MANAGER_STARTED=false
declare -a STARTED_TRADERS=()
declare -a SKIPPED_TRADERS=()
declare -a FAILED_TRADERS=()

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 conda 环境是否存在
check_conda_env() {
    if ! conda env list | grep -q "^${CONDA_ENV} "; then
        log_error "Conda 环境 '${CONDA_ENV}' 不存在"
        log_info "请先创建环境: conda create -n ${CONDA_ENV} python=3.8"
        exit 1
    fi
}

# 激活 conda 环境
activate_conda() {
    log_info "激活 conda 环境: ${CONDA_ENV}"
    # 根据 shell 类型选择激活方式
    if [ -n "$ZSH_VERSION" ]; then
        source "$(conda info --base)/etc/profile.d/conda.sh"
        conda activate ${CONDA_ENV}
    elif [ -n "$BASH_VERSION" ]; then
        eval "$(conda shell.bash hook)"
        conda activate ${CONDA_ENV}
    else
        log_warning "未检测到 bash 或 zsh，尝试使用 conda activate"
        conda activate ${CONDA_ENV}
    fi
}

# 获取 socket 目录
get_socket_dir() {
    local config_file="config/config.yaml"

    if [ -f "$config_file" ]; then
        # 提取 socket_dir（在 paths 段中）
        local socket_dir=$(grep -A10 "^paths:" "$config_file" | grep "socket_dir:" | sed 's/.*socket_dir:[[:space:]]*"\(.*\)".*/\1/')
        if [ -z "$socket_dir" ]; then
            echo "data/socks"
        else
            echo "$socket_dir"
        fi
    else
        echo "data/socks"
    fi
}

# 获取日志目录
get_log_dir() {
    local config_file="config/config.yaml"

    if [ -f "$config_file" ]; then
        # 提取 logs（在 paths 段中）
        local logs_dir=$(grep -A10 "^paths:" "$config_file" | grep "logs:" | sed 's/.*logs:[[:space:]]*"\(.*\)".*/\1/')
        if [ -z "$logs_dir" ]; then
            echo "logs"
        else
            echo "$logs_dir"
        fi
    else
        echo "logs"
    fi
}

# 检查进程是否运行（通过 PID 文件）
is_process_running() {
    local pid_file="$1"
    local process_name="$2"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            return 0  # 进程运行中
        else
            # PID 文件存在但进程不存在，清理
            rm -f "$pid_file"
            return 1  # 进程未运行
        fi
    fi
    return 1  # 进程未运行
}

# 启动 Manager
start_manager() {
    log_info "检查 Manager 进程..."

    # 获取 socket 目录
    local socket_dir=$(get_socket_dir)
    local pid_file="${socket_dir}/qtrader_manager.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            log_warning "Manager 已在运行 (PID: $pid)"
            return 0
        else
            log_info "清理过期的 Manager PID 文件"
            rm -f "$pid_file"
        fi
    fi

    log_info "启动 Manager..."
    local log_dir=$(get_log_dir)
    mkdir -p "$log_dir"
    nohup python -m src.run_manager > "$log_dir/manager.log" 2>&1 &
    local pid=$!

    # 等待并检查
    sleep 2
    if kill -0 $pid 2>/dev/null; then
        log_success "Manager 启动成功 (PID: $pid)"
        MANAGER_STARTED=true
    else
        log_error "Manager 启动失败"
        return 1
    fi
}

# 启动 Trader
start_trader() {
    local account_id="$1"
    log_info "检查 Trader[$account_id] 进程..."

    # 获取 socket 目录
    local socket_dir=$(get_socket_dir)
    local pid_file="${socket_dir}/qtrader_${account_id}.pid"

    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            log_warning "Trader[$account_id] 已在运行 (PID: $pid)"
            SKIPPED_TRADERS+=("$account_id")
            return 0
        else
            log_info "清理过期的 Trader[$account_id] PID 文件"
            rm -f "$pid_file"
        fi
    fi

    log_info "启动 Trader[$account_id]..."
    local log_dir=$(get_log_dir)
    mkdir -p "$log_dir"
    nohup python -m src.run_trader --account-id "$account_id" > "$log_dir/trader-${account_id}.log" 2>&1 &
    local pid=$!

    # 等待并检查
    sleep 2
    if kill -0 $pid 2>/dev/null; then
        log_success "Trader[$account_id] 启动成功 (PID: $pid)"
        STARTED_TRADERS+=("$account_id")
    else
        log_error "Trader[$account_id] 启动失败"
        FAILED_TRADERS+=("$account_id")
        return 1
    fi
}

# 输出启动结果报告
print_report() {
    echo ""
    echo "========================================"
    echo "         启动结果报告"
    echo "========================================"

    if [ "$MANAGER_STARTED" = true ]; then
        echo -e "${GREEN}✓${NC} Manager: 已启动"
    else
        # 检查是否本来就运行中
        local socket_dir=$(get_socket_dir)
        local pid_file="${socket_dir}/qtrader_manager.pid"
        if [ -f "$pid_file" ]; then
            local pid=$(cat "$pid_file")
            if kill -0 "$pid" 2>/dev/null; then
                echo -e "${YELLOW}○${NC} Manager: 已在运行 (PID: $pid)"
            else
                echo -e "${RED}✗${NC} Manager: 未启动"
            fi
        else
            echo -e "${RED}✗${NC} Manager: 未启动"
        fi
    fi

    echo ""
    echo "Trader 进程:"

    if [ ${#STARTED_TRADERS[@]} -gt 0 ]; then
        echo -e "  ${GREEN}本次启动:${NC}"
        for trader in "${STARTED_TRADERS[@]}"; do
            echo -e "    ${GREEN}✓${NC} $trader"
        done
    fi

    if [ ${#SKIPPED_TRADERS[@]} -gt 0 ]; then
        echo -e "  ${YELLOW}已在运行:${NC}"
        for trader in "${SKIPPED_TRADERS[@]}"; do
            echo -e "    ${YELLOW}○${NC} $trader"
        done
    fi

    if [ ${#FAILED_TRADERS[@]} -gt 0 ]; then
        echo -e "  ${RED}启动失败:${NC}"
        for trader in "${FAILED_TRADERS[@]}"; do
            echo -e "    ${RED}✗${NC} $trader"
        done
    fi

    echo ""
    echo "========================================"

    # 显示进程信息
    echo ""
    log_info "当前运行的 Q-Trader 进程:"
    ps aux | grep -E "(run_manager|run_trader)" | grep -v grep || echo "  无"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "========================================"
    echo "       Q-Trader 启动脚本"
    echo "========================================"
    echo ""

    # 检查 conda 环境
    check_conda_env

    # 激活 conda 环境
    activate_conda

    # 确保 logs 目录存在
    mkdir -p logs

    # 解析参数
    local accounts_to_start=()

    if [ $# -eq 0 ]; then
        # 无参数，只启动 Manager
        log_info "无参数，仅启动 Manager"
        start_manager
    else
        local arg="$1"

        if [ "$arg" = "ALL" ]; then
            # 启动所有账户
            log_info "启动模式: ALL"
            accounts_to_start=("${AVAILABLE_ACCOUNTS[@]}")
        else
            # 解析账户列表（逗号分隔）
            IFS=',' read -ra accounts <<< "$arg"
            for acc in "${accounts[@]}"; do
                acc=$(echo "$acc" | xargs)  # 去除空格
                # 检查账户是否在可用列表中
                local valid=false
                for available in "${AVAILABLE_ACCOUNTS[@]}"; do
                    if [ "$acc" = "$available" ]; then
                        valid=true
                        break
                    fi
                done
                if [ "$valid" = true ]; then
                    accounts_to_start+=("$acc")
                else
                    log_warning "未知账户: $acc (已跳过)"
                fi
            done
        fi

        # 先启动 Manager
        start_manager

        # 再启动 Trader
        for account in "${accounts_to_start[@]}"; do
            start_trader "$account" || true
        done
    fi

    # 输出报告
    print_report
}

# 运行主函数
main "$@"
