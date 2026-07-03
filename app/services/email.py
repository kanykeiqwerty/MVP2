"""
app/services/email.py

Отправка email через aiosmtplib.
Для продакшена можно заменить на SendGrid/Mailgun/AWS SES.
"""

from email.message import EmailMessage

import aiosmtplib

from app.db.config import settings


async def send_password_reset_code(to_email: str, code: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = "Код для сброса пароля"
    msg.set_content(
        f"Ваш код для сброса пароля: {code}\n\n"
        f"Код действителен 10 минут.\n"
        f"Если вы не запрашивали сброс — проигнорируйте это письмо."
    )
    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
        start_tls=True,
    )