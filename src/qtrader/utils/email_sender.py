"""
邮件发送工具
使用标准库 smtplib 发送 HTML 邮件
"""

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from qtrader.utils.logger import get_logger

logger = get_logger(__name__)


def send_email(
    subject: str,
    html_body: str,
    recipients: list[str],
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    from_addr: str,
) -> None:
    """
    发送 HTML 邮件

    Args:
        subject: 邮件主题
        html_body: HTML 格式正文
        recipients: 收件人列表
        smtp_host: SMTP 服务器地址
        smtp_port: SMTP 端口（SSL）
        username: SMTP 登录用户名
        password: SMTP 授权码/密码
        from_addr: 发件人地址

    Raises:
        smtplib.SMTPException: 发送失败时抛出
    """
    if not recipients:
        logger.warning("收件人列表为空，跳过邮件发送")
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr(("Q-Trader", from_addr))
    message["To"] = ",".join(recipients)
    message.set_content(html_body, subtype="html", charset="utf-8")

    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)

    logger.info(f"邮件发送成功: {subject} -> {recipients}")
