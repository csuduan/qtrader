#!/bin/bash
# Q-Trader 停止脚本
#
# 功能:
# - 停止 Manager 和/或指定账户的 Trader
# - 优雅停止（SIGTERM）+ 强制停止（SIGKILL）
# - 输出停止结果报告
#
# 用法:
#   ./stop.sh ALL           # 停止所有
#   ./stop.sh DQ,GWQ        # 停止指定账户
#   ./stop.sh               # 只停止 Manager

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

# 超时时间（秒）
TIMEOUT=5

# 结果统计
declare -a STOPPED_TRADERS=()
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

# 停止进程
stop_process() {
    local pid="$1"
    local name="$2"
    local timeout="${3:-5}"

    # 发送 SIGTERM
    log_info "停止 $name (PID: $pid)..."
    kill -TERM "$pid" 2>/dev/null || return 1

    # 等待进程退出
    local count=0
    while [ $count -lt $timeout ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            log_success "$name 已停止"
            return 0
        fi
        sleep 1
        count=$((count + 1))
    done

    # 超时，发送 SIGKILL
    log_warning "$name 未响应 SIGTERM，发送 SIGKILL..."
    kill -KILL "$pid" 2>/dev/null || return 1

    # 最后检查
    if ! kill -0 "$pid" 2>/dev/null; then
        log_success "$name 已强制停止"
        return 0
    else
        log_error "$name 停止失败"
        return 1
    fi
}

# 停止 Manager
stop_manager() {
    log_info "检查 Manager 进程..."

    # 获取 socket 目录
    local socket_dir=$(get_socket_dir)
    local pid_file="${socket_dir}/qtrader_manager.pid"

    if [ ! -f "$pid_file" ]; then
        log_warning "Manager PID 文件不存在,$pid_file"
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        log_warning "Manager 进程不存在 (PID: $pid)"
        rm -f "$pid_file"
        return 0
    fi

    if stop_process "$pid" "Manager" $TIMEOUT; then
        rm -f "$pid_file"
        return 0
    else
        return 1
    fi
}

# 停止 Trader
stop_trader() {
    local account_id="$1"
    log_info "检查 Trader[$account_id] 进程..."

    # 获取 socket 目录
    local socket_dir=$(get_socket_dir)
    local pid_file="${socket_dir}/qtrader_${account_id}.pid"

    if [ ! -f "$pid_file" ]; then
        log_warning "Trader[$account_id] PID 文件不存在"
        SKIPPED_TRADERS+=("$account_id")
        return 0
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 "$pid" 2>/dev/null; then
        log_warning "Trader[$account_id] 进程不存在 (PID: $pid)"
        rm -f "$pid_file"
        SKIPPED_TRADERS+=("$account_id")
        return 0
    fi

    if stop_process "$pid" "Trader[$account_id]" $TIMEOUT; then
        rm -f "$pid_file"
        STOPPED_TRADERS+=("$account_id")
        return 0
    else
        FAILED_TRADERS+=("$account_id")
        return 1
    fi
}

# 输出停止结果报告
print_report() {
    echo ""
    echo "========================================"
    echo "         停止结果报告"
    echo "========================================"
    echo ""

    if [ ${#STOPPED_TRADERS[@]} -gt 0 ]; then
        echo -e "${GREEN}已停止:${NC}"
        for trader in "${STOPPED_TRADERS[@]}"; do
            echo -e "  ${GREEN}✓${NC} $trader"
        done
        echo ""
    fi

    if [ ${#SKIPPED_TRADERS[@]} -gt 0 ]; then
        echo -e "${YELLOW}未运行:${NC}"
        for trader in "${SKIPPED_TRADERS[@]}"; do
            echo -e "  ${YELLOW}○${NC} $trader"
        done
        echo ""
    fi

    if [ ${#FAILED_TRADERS[@]} -gt 0 ]; then
        echo -e "${RED}停止失败:${NC}"
        for trader in "${FAILED_TRADERS[@]}"; do
            echo -e "  ${RED}✗${NC} $trader"
        done
        echo ""
    fi

    echo "========================================"

    # 显示剩余进程
    echo ""
    log_info "剩余运行的 Q-Trader 进程:"
    ps aux | grep -E "(run_manager|run_trader)" | grep -v grep || echo "  无"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "========================================"
    echo "       Q-Trader 停止脚本"
    echo "========================================"
    echo ""

    # 解析参数
    if [ $# -eq 0 ]; then
        # 无参数，只停止 Manager
        log_info "无参数，仅停止 Manager"
        stop_manager
    else
        local arg="$1"

        if [ "$arg" = "ALL" ]; then
            # 停止所有
            log_info "停止模式: ALL"

            # 先停止所有 Trader
            for account in "${AVAILABLE_ACCOUNTS[@]}"; do
                stop_trader "$account" || true
            done

            # 再停止 Manager
            stop_manager
        else
            # 解析账户列表（逗号分隔）
            IFS=',' read -ra accounts <<< "$arg"
            local manager_needed=false

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
                    stop_trader "$acc" || true
                else
                    log_warning "未知账户: $acc (已跳过)"
                fi
            done
        fi
    fi

    # 输出报告
    print_report
}

# 运行主函数
main "$@"
