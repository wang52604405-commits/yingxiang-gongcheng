# -*- coding: utf-8 -*-
"""邮件发送模块：用 QQ 邮箱 SMTP 发送验证码邮件。

配置（环境变量）：
  ALBUM_MAIL_USER  发件邮箱（如 you@example.com）
  ALBUM_MAIL_PASS  授权码（QQ 邮箱设置里开启 SMTP 后生成的 16 位授权码，非登录密码）
  ALBUM_MAIL_HOST  默认 smtp.qq.com，一般不用改
  ALBUM_MAIL_PORT  默认 465（SSL）
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

MAIL_HOST = os.environ.get("ALBUM_MAIL_HOST", "smtp.qq.com")
MAIL_PORT = int(os.environ.get("ALBUM_MAIL_PORT", "465"))
MAIL_USER = os.environ.get("ALBUM_MAIL_USER", "")
MAIL_PASS = os.environ.get("ALBUM_MAIL_PASS", "")

APP_NAME = "工程影像管理平台"


def configured() -> bool:
    """是否已配置发件邮箱与授权码。"""
    return bool(MAIL_USER and MAIL_PASS)


def send_code_email(to_email: str, code: str) -> None:
    """发送验证码邮件。未配置时抛 ValueError。"""
    if not configured():
        raise ValueError("服务器未配置发件邮箱，请联系管理员")
    body = (
        f"您好：\n\n"
        f"您在《{APP_NAME}》的操作需要验证，本次验证码为：\n\n"
        f"    {code}\n\n"
        f"验证码 10 分钟内有效，请勿泄露给他人。\n"
        f"如非本人操作，请忽略本邮件。\n\n"
        f"—— {APP_NAME}"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(f"{APP_NAME} 验证码", "utf-8")
    msg["From"] = formataddr((str(Header(APP_NAME, "utf-8")), MAIL_USER))
    msg["To"] = to_email

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(MAIL_HOST, MAIL_PORT, timeout=15, context=ctx) as server:
        server.login(MAIL_USER, MAIL_PASS)
        server.sendmail(MAIL_USER, [to_email], msg.as_string())
