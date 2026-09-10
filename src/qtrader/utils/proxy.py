"""
禁用代理的工具

tqsdk 依赖的 websockets>=14 默认自动使用系统/环境代理，
会把到 shinnytech 行情/交易服务器的连接劫持进本机代理(Clash 等)导致无法连接。
必须在任何网络相关模块被 import 之前调用。
"""

import os


def disable_proxy() -> None:
    """删除所有代理环境变量，并用 no_proxy 通配符让所有 HTTP/WebSocket
    客户端(urllib/requests/websockets)绕过环境代理与系统代理。"""
    for key in list(os.environ):
        if key.lower().endswith("_proxy"):
            del os.environ[key]
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"
