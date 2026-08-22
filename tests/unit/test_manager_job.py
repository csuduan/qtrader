"""
ManagerJobManager 单元测试
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from qtrader.manager.job_mgr import ManagerJobManager


def test_weekly_report_queries_configured_accounts_excluding_blacklist():
    """结算权益周报只查询 config.yaml 中配置、且不在黑名单中的账户"""
    mgr = ManagerJobManager(MagicMock())

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    with (
        patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader,
        patch("qtrader.trader.dao.settlement_dao.SettlementDao") as mock_dao,
        patch("qtrader.utils.email_sender.send_email") as mock_send,
        patch("qtrader.manager.job_mgr._build_settlement_report_html", return_value="<html>"),
    ):
        app_config = MagicMock()
        app_config.account_ids = ["DQ", "GW", "RF"]
        app_config.email.enabled = True
        app_config.email.exclude_accounts = ["RF", "Unknown"]
        app_config.email.recipients = ["a@b.com"]
        app_config.email.smtp_host = "smtp.test"
        app_config.email.smtp_port = 465
        app_config.email.username = "u"
        app_config.email.password = "p"
        app_config.email.from_addr = "f@test"
        mock_get_loader.return_value.load_config.return_value = app_config

        mock_record = MagicMock()
        mock_record.account_id = "DQ"
        mock_dao.return_value.query_settlements.return_value = [mock_record]

        mgr.send_weekly_settlement_report()

        mock_dao.return_value.query_settlements.assert_called_once_with(["DQ", "GW"], monday, today)
        mock_send.assert_called_once()


def test_weekly_report_skips_when_no_configured_accounts():
    """config.yaml 中没有配置账户时跳过周报"""
    mgr = ManagerJobManager(MagicMock())

    with (
        patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader,
        patch("qtrader.trader.dao.settlement_dao.SettlementDao") as mock_dao,
        patch("qtrader.utils.email_sender.send_email") as mock_send,
    ):
        app_config = MagicMock()
        app_config.account_ids = []
        app_config.email.enabled = True
        app_config.email.exclude_accounts = []
        mock_get_loader.return_value.load_config.return_value = app_config

        mgr.send_weekly_settlement_report()

        mock_dao.return_value.query_settlements.assert_not_called()
        mock_send.assert_not_called()


def test_weekly_report_skips_when_email_disabled():
    """邮件未启用时跳过周报"""
    mgr = ManagerJobManager(MagicMock())

    with (
        patch("qtrader.utils.config_loader.get_config_loader") as mock_get_loader,
        patch("qtrader.trader.dao.settlement_dao.SettlementDao") as mock_dao,
        patch("qtrader.utils.email_sender.send_email") as mock_send,
    ):
        app_config = MagicMock()
        app_config.email.enabled = False
        mock_get_loader.return_value.load_config.return_value = app_config

        mgr.send_weekly_settlement_report()

        mock_dao.return_value.query_settlements.assert_not_called()
        mock_send.assert_not_called()
