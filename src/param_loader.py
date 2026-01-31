"""
系统参数加载器
从数据库加载系统参数并转换为配置对象
"""

from typing import Optional

from sqlalchemy.orm import Session

from src.db.database import get_session
from src.models.po import SystemParamPo
from src.utils.config_loader import RiskControlConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_risk_control_config() -> RiskControlConfig:
    """
    从数据库加载风控配置

    Returns:
        RiskControlConfig: 风控配置对象

    Raises:
        ValueError: 如果数据库中缺少必要的参数
    """
    session = get_session()
    if not session:
        logger.warning("数据库未初始化，使用默认风控配置")
        return RiskControlConfig()

    try:
        params = {
            param.param_key: param.param_value for param in session.query(SystemParamPo).all()
        }

        risk_control_params = {
            "max_daily_orders": _get_int_param(params, "risk_control.max_daily_orders", 1000),
            "max_daily_cancels": _get_int_param(params, "risk_control.max_daily_cancels", 500),
            "max_order_volume": _get_int_param(params, "risk_control.max_order_volume", 50),
            "max_split_volume": _get_int_param(params, "risk_control.max_split_volume", 5),
            "order_timeout": _get_int_param(params, "risk_control.order_timeout", 5),
        }

        logger.info(f"从数据库加载风控配置: {risk_control_params}")

        return RiskControlConfig(**risk_control_params)

    except Exception as e:
        logger.error(f"加载风控配置失败: {e}", exc_info=True)
        logger.warning("使用默认风控配置")
        return RiskControlConfig()
    finally:
        session.close()


def _get_int_param(params: dict, key: str, default: int) -> int:
    """
    获取整数类型的参数

    Args:
        params: 参数字典
        key: 参数键名
        default: 默认值

    Returns:
        int: 参数值
    """
    value = params.get(key)
    if value is None:
        logger.warning(f"参数 {key} 不存在，使用默认值: {default}")
        return default

    try:
        return int(value)
    except (ValueError, TypeError) as e:
        logger.error(f"参数 {key} 值 '{value}' 转换为整数失败: {e}，使用默认值: {default}")
        return default


def _get_str_param(params: dict, key: str, default: str) -> str:
    """
    获取字符串类型的参数

    Args:
        params: 参数字典
        key: 参数键名
        default: 默认值

    Returns:
        str: 参数值
    """
    value = params.get(key)
    if value is None:
        logger.warning(f"参数 {key} 不存在，使用默认值: {default}")
        return default

    return str(value)


def _get_bool_param(params: dict, key: str, default: bool) -> bool:
    """
    获取布尔类型的参数

    Args:
        params: 参数字典
        key: 参数键名
        default: 默认值

    Returns:
        bool: 参数值
    """
    value = params.get(key)
    if value is None:
        logger.warning(f"参数 {key} 不存在，使用默认值: {default}")
        return default

    if isinstance(value, bool):
        return value

    return value.lower() in ("true", "1", "yes", "on")
