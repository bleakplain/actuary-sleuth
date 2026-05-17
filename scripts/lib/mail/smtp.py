"""SMTP 邮件发送。"""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosmtplib

from lib.config import get_mail_config

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """发送 HTML 邮件。返回 True 表示成功，False 表示失败。"""
    cfg = get_mail_config()
    if not cfg.enabled:
        logger.warning("邮件服务未配置，邮件未发送")
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = cfg.from_address
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user,
            password=cfg.smtp_password,
            use_tls=True,
        )
        return True
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")
        return False


async def send_verification_email(email: str, token: str) -> bool:
    """发送邮箱验证邮件。"""
    verify_url = f"/api/auth/verify-email?token={token}"
    html = f'<p>请点击以下链接验证邮箱：</p><p><a href="{verify_url}">验证邮箱</a></p><p>链接 24 小时内有效。</p>'
    return await send_email(email, "邮箱验证 - Actuary Sleuth", html)


async def send_reset_email(email: str, token: str) -> bool:
    """发送密码重置邮件。"""
    reset_url = f"/reset-password?token={token}"
    html = f'<p>请点击以下链接重置密码：</p><p><a href="{reset_url}">重置密码</a></p><p>链接 24 小时内有效。</p>'
    return await send_email(email, "密码重置 - Actuary Sleuth", html)
