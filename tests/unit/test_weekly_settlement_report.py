"""
结算权益周报单元测试

测试周报任务的核心功能，包括：
- 黑名单账户过滤
- 多收件人一次发送
- 无数据/全过滤/邮件未启用时跳过发送
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from qtrader.manager.job_mgr import ManagerJobManager
from qtrader.models.po import AccountHistoryPo
from qtrader.utils.config_loader import EmailConfig
from qtrader.utils.email_sender import send_email


def _make_record(account_id: str, settle_date: date) -> AccountHistoryPo:
    """构造一条结算权益快照记录"""
    return AccountHistoryPo(account_id=account_id, settle_date=settle_date, balance=100000.0)


def _make_records() -> list[AccountHistoryPo]:
    """构造本周多账户多日结算权益快照（DQ/GW 含周一与周五，TEST 仅周五）"""
    monday = date.today() - timedelta(days=date.today().weekday())
    friday = monday + timedelta(days=4)
    return [
        _make_record("DQ", monday),
        _make_record("DQ", friday),
        _make_record("GW", monday),
        _make_record("GW", friday),
        _make_record("TEST", friday),
    ]


def _make_email_config(**overrides) -> EmailConfig:
    """构造测试用邮件配置"""
    defaults = {"enabled": True, "recipients": ["a@qq.com"]}
    defaults.update(overrides)
    return EmailConfig(**defaults)


async def _run_report(
    job_manager: ManagerJobManager,
    email_config: EmailConfig,
    records,
    account_ids: list[str] | None = None,
) -> Mock:
    """执行周报任务并返回 send_email 的 mock"""
    if account_ids is None:
        account_ids = ["DQ", "GW", "TEST"]
    with (
        patch("qtrader.trader.dao.settlement_dao.SettlementDao") as mock_dao,
        patch("qtrader.utils.config_loader.get_config_loader") as mock_loader,
        patch("qtrader.utils.email_sender.send_email") as mock_send,
    ):
        mock_loader.return_value.load_config.return_value = Mock(
            email=email_config, account_ids=account_ids
        )
        mock_dao.return_value.query_settlements = AsyncMock(return_value=records)
        await job_manager.send_weekly_settlement_report()
    _run_report.last_dao_mock = mock_dao
    return mock_send


@pytest.fixture
def job_manager() -> ManagerJobManager:
    """任务管理器实例"""
    return ManagerJobManager(trading_manager=Mock())


class TestWeeklySettlementReport:
    """结算权益周报任务测试"""

    async def test_blacklist_accounts_excluded(self, job_manager):
        """黑名单账户被排除：query_settlements 只查询非黑名单账户"""
        email_config = _make_email_config(exclude_accounts=["TEST"])

        mock_send = await _run_report(job_manager, email_config, _make_records())

        mock_send.assert_called_once()
        queried = _run_report.last_dao_mock.return_value.query_settlements.call_args[0][0]
        assert queried == ["DQ", "GW"]

    async def test_all_accounts_blacklisted_skips_send(self, job_manager):
        """全部账户都在黑名单时不发送邮件"""
        email_config = _make_email_config(exclude_accounts=["DQ", "GW", "TEST"])

        mock_send = await _run_report(job_manager, email_config, _make_records())

        mock_send.assert_not_called()

    async def test_only_configured_accounts_sent(self, job_manager):
        """仅查询 config.yaml 中配置的账户：未配置账户（TEST）不进入查询参数"""
        mock_send = await _run_report(
            job_manager, _make_email_config(), _make_records(), account_ids=["DQ", "GW"]
        )

        mock_send.assert_called_once()
        queried = _run_report.last_dao_mock.return_value.query_settlements.call_args[0][0]
        assert queried == ["DQ", "GW"]

    async def test_no_blacklist_sends_all_accounts(self, job_manager):
        """未配置黑名单时发送全部账户"""
        mock_send = await _run_report(job_manager, _make_email_config(), _make_records())

        mock_send.assert_called_once()
        html_body = mock_send.call_args.kwargs["html_body"]
        assert ">DQ<" in html_body
        assert ">GW<" in html_body
        assert ">TEST<" in html_body

    async def test_single_table_latest_day_per_account(self, job_manager):
        """所有账户合并为一张表，每账户仅显示最新一天数据"""
        mock_send = await _run_report(job_manager, _make_email_config(), _make_records())

        html_body = mock_send.call_args.kwargs["html_body"]
        # 单张表格：表头 + 每账户一行
        assert html_body.count("<table") == 1
        assert html_body.count("<tr>") == 1 + 3
        # DQ/GW 有周一与周五两天记录，表格中仅保留周五（>日期< 匹配单元格，避免误匹配标题）
        monday = date.today() - timedelta(days=date.today().weekday())
        friday = monday + timedelta(days=4)
        assert f">{monday.isoformat()}<" not in html_body
        assert f">{friday.isoformat()}<" in html_body
        # 正文标题只包含区间结束日期（当天）
        assert f"Q-Trader 结算权益周报（{date.today()}）" in html_body

    async def test_no_profit_columns(self, job_manager):
        """表格不含盈亏列"""
        mock_send = await _run_report(job_manager, _make_email_config(), _make_records())

        html_body = mock_send.call_args.kwargs["html_body"]
        assert "平仓盈亏" not in html_body
        assert "持仓盈亏" not in html_body

    async def test_multiple_recipients_sent_at_once(self, job_manager):
        """多个收件人一次发送，recipients 完整透传"""
        recipients = ["a@qq.com", "b@qq.com", "c@qq.com"]

        mock_send = await _run_report(
            job_manager, _make_email_config(recipients=recipients), _make_records()
        )

        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["recipients"] == recipients

    async def test_subject_uses_end_date(self, job_manager):
        """邮件主题只包含区间结束日期（当天）"""
        mock_send = await _run_report(job_manager, _make_email_config(), _make_records())

        subject = mock_send.call_args.kwargs["subject"]
        assert subject == f"Q-Trader 结算权益周报 ({date.today():%m-%d})"

    async def test_email_disabled_skips_send(self, job_manager):
        """邮件功能未启用时不发送"""
        mock_send = await _run_report(
            job_manager, _make_email_config(enabled=False), _make_records()
        )

        mock_send.assert_not_called()

    async def test_no_records_skips_send(self, job_manager):
        """本周无结算数据时不发送"""
        mock_send = await _run_report(job_manager, _make_email_config(), [])

        mock_send.assert_not_called()


class TestSendEmailMultipleRecipients:
    """邮件发送多收件人测试"""

    def test_single_smtp_send_to_all_recipients(self):
        """多收件人合并进一封邮件，一次 SMTP 发送"""
        with patch("qtrader.utils.email_sender.smtplib.SMTP_SSL") as mock_smtp:
            smtp = mock_smtp.return_value.__enter__.return_value

            send_email(
                subject="周报",
                html_body="<p>ok</p>",
                recipients=["a@qq.com", "b@qq.com", "c@qq.com"],
                smtp_host="smtp.qq.com",
                smtp_port=465,
                username="user",
                password="pass",
                from_addr="a@qq.com",
            )

        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args[0][0]
        assert [addr.addr_spec for addr in message["To"].addresses] == [
            "a@qq.com",
            "b@qq.com",
            "c@qq.com",
        ]
