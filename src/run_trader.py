import argparse

from src.trader.app import main


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Q-Trader 交易执行器")
    parser.add_argument("--account-id", type=str, required=True, help="账户ID")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    parser.add_argument("--debug", action="store_true", help="启用调试模式（输出详细日志）")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args)
