"""Send report PDF via Gmail SMTP."""
import logging
import os
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger(__name__)


def send_report(pdf_path: str, report_date: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]
    email_password = os.environ["EMAIL_PASSWORD"]

    date_fmt = datetime.strptime(report_date, "%Y%m%d").strftime("%Y년 %m월 %d일")
    subject = f"[신세계그룹] 주식 시황 리포트 - {date_fmt}"

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject

    body = f"""안녕하세요,

{date_fmt} 신세계그룹 주식 시황 리포트를 첨부해 드립니다.

본 리포트에는 다음 내용이 포함되어 있습니다:
1. 전체 시장 요약 (KOSPI/KOSDAQ/환율/금)
2. 신세계그룹 6개 종목 현황
3. (주)신세계 주가 요인 분석
4. 국내외 유통 섹터 이슈
5. 참고자료

※ 본 리포트는 AI 기반 자동 생성 자료입니다.
"""
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with open(pdf_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="pdf")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=Path(pdf_path).name,
        )
        msg.attach(attachment)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(email_from, email_password)
        server.sendmail(email_from, email_to.split(","), msg.as_string())

    logger.info(f"Report email sent to {email_to}")
