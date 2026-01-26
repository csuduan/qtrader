"""
系统初始化脚本
根据 config.yaml 初始化系统数据库和参数
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy.orm import Session

from src.config_loader import load_config
from src.database import Database, get_database
from src.models.po import JobPo, SystemParamPo
from src.utils.logger import get_logger

logger = get_logger(__name__)


def init_system(config_path: Optional[str] = None, db_path: Optional[str] = None) -> None:
    """
    初始化系统

    Args:
        config_path: 配置文件路径，默认为 ./config/config.yaml
        db_path: 数据库文件路径，默认从配置文件读取
    """
    print("=" * 60)
    print("开始初始化系统")
    print("=" * 60)
    logger.info("=" * 60)
    logger.info("开始初始化系统")
    logger.info("=" * 60)

    try:
        config = load_config(config_path)

        if db_path:
            final_db_path = db_path
        else:
            final_db_path = config.paths.database

        logger.info(f"数据库路径: {final_db_path}")

        from src.database import init_database

        db: Database = init_database(final_db_path, echo=False)

        logger.info("正在重建数据库表...")
        db.drop_and_recreate()

        logger.info("正在初始化系统参数...")
        _init_system_params(config, db)

        logger.info("=" * 60)
        logger.info("系统初始化完成！")
        logger.info("=" * 60)

    except FileNotFoundError as e:
        logger.error(f"配置文件不存在: {e}")
        raise
    except Exception as e:
        logger.error(f"系统初始化失败: {e}", exc_info=True)
        raise


def _init_system_params(config, db: Database) -> None:
    """
    初始化系统参数

    Args:
        config: 配置对象
        db: 数据库实例
    """
    with db.get_session() as session:
        params = []

        risk_control = config.risk_control

        params.append(
            SystemParamPo(
                param_key="risk_control.max_daily_orders",
                param_value=str(risk_control.max_daily_orders),
                param_type="integer",
                description="每日最大报单数量",
                group="risk_control",
            )
        )

        params.append(
            SystemParamPo(
                param_key="risk_control.max_daily_cancels",
                param_value=str(risk_control.max_daily_cancels),
                param_type="integer",
                description="每日最大撤单数量",
                group="risk_control",
            )
        )

        params.append(
            SystemParamPo(
                param_key="risk_control.max_order_volume",
                param_value=str(risk_control.max_order_volume),
                param_type="integer",
                description="单次最大报单手数",
                group="risk_control",
            )
        )

        params.append(
            SystemParamPo(
                param_key="risk_control.max_split_volume",
                param_value=str(risk_control.max_split_volume),
                param_type="integer",
                description="最大拆单手数",
                group="risk_control",
            )
        )

        params.append(
            SystemParamPo(
                param_key="risk_control.order_timeout",
                param_value=str(risk_control.order_timeout),
                param_type="integer",
                description="报单超时时间（秒）",
                group="risk_control",
            )
        )

        session.add_all(params)
        session.commit()

        logger.info(f"已初始化 {len(params)} 个系统参数")

if __name__ == "__main__":
    import sys

    config_arg = sys.argv[1] if len(sys.argv) > 1 else None
    db_arg = sys.argv[2] if len(sys.argv) > 2 else None

    init_system(config_arg, db_arg)
