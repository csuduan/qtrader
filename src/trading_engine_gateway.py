"""
TradingEngine Gateway统一管理
根据配置自动创建对应的Gateway（TqGateway或CtpGateway）
"""
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_gateway(trading_engine):
    """
    根据配置创建对应的Gateway实例

    Args:
        trading_engine: TradingEngine实例

    Returns:
        Gateway实例（TqGateway或CtpGateway）
    """
    config = trading_engine.config
    
    # 获取Gateway类型配置（新增到config_loader.py）
    gateway_type = getattr(config, 'gateway_type', 'TQSDK')
    
    logger.info(f"创建Gateway，类型: {gateway_type}")
    
    if gateway_type == 'CTP':
        from src.adapters.ctp_gateway import CtpGateway
        gateway = CtpGateway()
        logger.info("CTP Gateway创建成功（框架实现，需CTP SDK）")
    else:  # 默认TQSDK
        from src.adapters.tq_gateway import TqGateway
        gateway = TqGateway(trading_engine)
        logger.info("TqSdk Gateway创建成功")
    
    return gateway
