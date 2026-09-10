import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from qtrader.utils.proxy import disable_proxy

# 禁用代理
disable_proxy()

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from qtrader.trader.app import main as trader_main


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Q-Trader 交易执行器")
    parser.add_argument("--account-id", type=str, required=True, help="账户ID")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    parser.add_argument("--debug", action="store_true", help="启用调试模式（输出详细日志）")
    return parser.parse_args()


def main():
    args = parse_args()
    trader_main(args)


if __name__ == "__main__":
    main()
