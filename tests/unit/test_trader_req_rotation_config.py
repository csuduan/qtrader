"""
TraderReqHandler 换仓开关请求处理单元测试

覆盖：
- get_rotation_config 读取账户配置
- update_rotation_config 内存更新 + 持久化到账户配置文件
"""

from unittest.mock import MagicMock, patch

import pytest

from qtrader.trader.trader_req import TraderReqHandler
from qtrader.utils.config_loader import AccountConfig


def build_handler(
    enable_instruction: bool = True, enable_target: bool = True, account_id: str = "DQ"
) -> TraderReqHandler:
    """构造一个不依赖 socket/数据库的请求处理器"""
    trader = MagicMock()
    trader.account_id = account_id
    trader.account_config = AccountConfig(
        account_id=account_id,
        enable_instruction_rotation=enable_instruction,
        enable_target_pos_rotation=enable_target,
    )
    return TraderReqHandler(trader)


@pytest.mark.asyncio
async def test_get_rotation_config_returns_account_config():
    """获取换仓开关返回账户配置值"""
    handler = build_handler(enable_instruction=True, enable_target=False)

    result = await handler._req_get_rotation_config({})

    assert result == {
        "enable_instruction_rotation": True,
        "enable_target_pos_rotation": False,
    }


@pytest.mark.asyncio
async def test_update_rotation_config_mutates_and_persists():
    """更新换仓开关：内存即时生效并逐字段持久化"""
    handler = build_handler(enable_instruction=True, enable_target=True)

    with patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader:
        mock_loader = MagicMock()
        mock_get_loader.return_value = mock_loader

        result = await handler._req_update_rotation_config({"enable_instruction_rotation": False})

    assert result["enable_instruction_rotation"] is False
    assert result["enable_target_pos_rotation"] is True
    assert handler.trader.account_config.enable_instruction_rotation is False
    mock_loader.update_account_config_field.assert_called_once_with(
        "DQ", "enable_instruction_rotation", False
    )


@pytest.mark.asyncio
async def test_update_rotation_config_both_fields():
    """一次更新两个字段时两个字段都持久化"""
    handler = build_handler(enable_instruction=True, enable_target=True)

    with patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader:
        mock_loader = MagicMock()
        mock_get_loader.return_value = mock_loader

        result = await handler._req_update_rotation_config(
            {"enable_instruction_rotation": False, "enable_target_pos_rotation": False}
        )

    assert result == {
        "enable_instruction_rotation": False,
        "enable_target_pos_rotation": False,
    }
    assert mock_loader.update_account_config_field.call_count == 2


@pytest.mark.asyncio
async def test_update_rotation_config_no_fields_no_persist():
    """请求中无字段时不写配置文件"""
    handler = build_handler(enable_instruction=True, enable_target=True)

    with patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader:
        result = await handler._req_update_rotation_config({})

    mock_get_loader.assert_not_called()
    assert result["enable_instruction_rotation"] is True
