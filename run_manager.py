"""
主程序入口
调用qtrader.manager.app启动整个应用
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from qtrader.utils.proxy import disable_proxy

disable_proxy()

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from qtrader.manager.app import main

if __name__ == "__main__":
    main()
