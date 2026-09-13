import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.core.config import settings


async def send_otp_email(
    to_email: str,
    otp_code: str
):

    msg = MIMEMultipart()

    msg["From"] = settings.SMTP_EMAIL
    msg["To"] = to_email
    msg["Subject"] = "Password Reset OTP"

    body = f"""
    Hello,

    Your OTP for password reset is: {otp_code}

    This OTP expires in 10 minutes.

    If you did not request this, please ignore this email.

    Regards,
    E-Commerce Team
    """

    msg.attach(MIMEText(body, "plain"))

    try:

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(
            settings.SMTP_EMAIL,
            settings.SMTP_PASSWORD
        )
        server.sendmail(
            settings.SMTP_EMAIL,
            to_email,
            msg.as_string()
        )
        server.quit()

        return True

    except Exception as e:

        print(f"EMAIL ERROR: {e}")

        return False