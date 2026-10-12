"""
Author      : Madan U
Email       : madanu135@gmail.com
Date        : 2026-09-16
Script Path : /data/database-management/backend/services/notification_service.py
Description : Notification framework for operation completion. Email-only
               today, on purpose: send_notification() is the one entry point
               every caller uses, and it dispatches to whichever channels are
               enabled — so adding Slack/Teams/webhook later is a new
               _send_via_slack()-style function plus one line in
               send_notification(), not a rewrite of every call site.

               Nothing here ever raises into the caller — a notification
               failure must never fail the DB operation it's reporting on.
               If SMTP isn't configured (no ATLAS_SMTP_HOST env var), this
               silently no-ops so the app works fine without it.
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("atlas.notifications")

IST_OFFSET_NOTE = "IST (Asia/Kolkata)"


def _smtp_config() -> Optional[dict]:
    host = os.environ.get("ATLAS_SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("ATLAS_SMTP_PORT", "587")),
        "username": os.environ.get("ATLAS_SMTP_USERNAME"),
        "password": os.environ.get("ATLAS_SMTP_PASSWORD"),
        "from_addr": os.environ.get("ATLAS_SMTP_FROM", os.environ.get("ATLAS_SMTP_USERNAME", "")),
        "use_tls": os.environ.get("ATLAS_SMTP_USE_TLS", "true").lower() != "false",
        "to_addrs": [a.strip() for a in os.environ.get("ATLAS_ALERT_TO", "").split(",") if a.strip()],
    }


# Static HTML template — deliberately simple (table of key/value rows) so it
# renders consistently across Outlook/Gmail without a templating engine.
# `rows` is an ordered list of (label, value) tuples.
_EMAIL_TEMPLATE = """\
<html><body style="font-family:Segoe UI,Arial,sans-serif;background:#f1f5f9;padding:24px;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:10px;
              border:1px solid #e2e8f0;overflow:hidden;">
    <div style="background:{banner_color};padding:16px 20px;">
      <span style="color:#ffffff;font-size:15px;font-weight:700;">MongoFleet &middot; {title}</span>
    </div>
    <div style="padding:20px;">
      <table style="width:100%;border-collapse:collapse;font-size:13px;color:#0f172a;">
        {rows_html}
      </table>
      {message_html}
    </div>
    <div style="padding:12px 20px;background:#f8fafc;font-size:11px;color:#94a3b8;">
      Automated notification from MongoFleet. Times shown in {tz_note}.
    </div>
  </div>
</body></html>
"""

_ROW_TEMPLATE = (
    '<tr><td style="padding:6px 0;color:#64748b;width:150px;">{label}</td>'
    '<td style="padding:6px 0;font-weight:600;">{value}</td></tr>'
)


def render_operation_email(event: str, hostname: str, operation_type: str, status: str,
                            started_ist: str, completed_ist: str, duration: str,
                            requested_by: str, error_message: Optional[str] = None) -> tuple:
    """Returns (subject, html_body) for an operation success/failure email.
    This is the "sample static template" — swap in a templating engine later
    if the notification catalogue in the spec (backup success, approval
    required, etc.) grows past a handful of variants."""
    is_failure = status == "FAILED"
    banner_color = "#a4231b" if is_failure else "#0f5132"
    subject = f"[MongoFleet] {operation_type} {'FAILED' if is_failure else 'succeeded'} on {hostname}"
    rows = [
        ("Server", hostname), ("Operation", operation_type), ("Status", status),
        ("Requested by", requested_by), ("Started", started_ist),
        ("Completed", completed_ist), ("Duration", duration),
    ]
    rows_html = "".join(_ROW_TEMPLATE.format(label=l, value=v) for l, v in rows)
    message_html = (
        f'<p style="margin-top:16px;padding:12px;background:#fdecea;border-radius:6px;'
        f'color:#a4231b;font-size:13px;">{error_message}</p>' if (is_failure and error_message) else ""
    )
    html = _EMAIL_TEMPLATE.format(
        banner_color=banner_color, title=event, rows_html=rows_html,
        message_html=message_html, tz_note=IST_OFFSET_NOTE,
    )
    return subject, html


def send_email(subject: str, html_body: str, to_addrs: Optional[list] = None) -> bool:
    """Sends via whatever SMTP server is configured in the environment
    (works as-is with a Gmail account + an app password:
    ATLAS_SMTP_HOST=smtp.gmail.com, ATLAS_SMTP_PORT=587,
    ATLAS_SMTP_USERNAME=you@gmail.com, ATLAS_SMTP_PASSWORD=<app password>).
    Returns False (never raises) if unconfigured or on any send failure."""
    config = _smtp_config()
    if not config:
        logger.info("Email not sent (ATLAS_SMTP_HOST not set) — subject=%r", subject)
        return False
    recipients = to_addrs or config["to_addrs"]
    if not recipients:
        logger.info("Email not sent (no recipients configured) — subject=%r", subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["from_addr"]
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=10) as server:
            if config["use_tls"]:
                server.starttls()
            if config["username"]:
                server.login(config["username"], config["password"])
            server.sendmail(config["from_addr"], recipients, msg.as_string())
        return True
    except Exception as exc:  # noqa: BLE001 — a notification failure must never break the caller
        logger.warning("Failed to send email %r: %s", subject, exc)
        return False


def notify_operation_result(hostname: str, operation_type: str, status: str,
                             started_ist: str, completed_ist: str, duration: str,
                             requested_by: str, error_message: Optional[str] = None) -> None:
    """The one entry point operations_service calls. Silently does nothing
    if email isn't configured — that's expected until .env is filled in."""
    event = "Operation Failed" if status == "FAILED" else "Operation Succeeded"
    subject, html = render_operation_email(
        event, hostname, operation_type, status, started_ist, completed_ist, duration,
        requested_by, error_message,
    )
    send_email(subject, html)
