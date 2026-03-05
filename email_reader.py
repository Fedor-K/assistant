"""Read emails from Yandex IMAP for daily recap."""
import imaplib
import email
import os
from datetime import datetime
from email.header import decode_header
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dubai"))


def _decode_header(raw):
    """Decode email header (subject, from)."""
    if not raw:
        return ""
    parts = decode_header(raw)
    result = []
    for data, charset in parts:
        if isinstance(data, bytes):
            result.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(data)
    return " ".join(result)


def _get_text(msg) -> str:
    """Extract plain text from email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return ""
        # Fallback to HTML if no plain text
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return ""
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            return msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            return ""
    return ""


def read_emails_today(days_back: int = 7) -> list[dict]:
    """Read emails for the last N days. Returns list of {from, subject, date, body}."""
    address = os.getenv("EMAIL_ADDRESS", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    server = os.getenv("EMAIL_IMAP_SERVER", "imap.yandex.ru")

    if not address or not password:
        print("[email] EMAIL_ADDRESS or EMAIL_PASSWORD not set")
        return []

    from datetime import timedelta
    since = datetime.now(TZ) - timedelta(days=days_back)
    date_str = since.strftime("%d-%b-%Y")

    try:
        mail = imaplib.IMAP4_SSL(server)
        mail.login(address, password)
        mail.select("INBOX")

        _, msg_ids = mail.search(None, f'(SINCE "{date_str}")')
        ids = msg_ids[0].split()

        emails = []
        for mid in ids:
            _, data = mail.fetch(mid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            sender = _decode_header(msg.get("From", ""))
            subject = _decode_header(msg.get("Subject", ""))
            date_raw = msg.get("Date", "")
            body = _get_text(msg)

            # Trim long bodies
            if len(body) > 3000:
                body = body[:3000] + "..."

            emails.append({
                "from": sender,
                "subject": subject,
                "date": date_raw,
                "body": body.strip(),
            })

        mail.logout()
        print(f"[email] Read {len(emails)} emails for today")
        return emails

    except Exception as e:
        print(f"[email] Error: {e}")
        return []


def format_emails_for_recap(emails: list[dict]) -> str:
    """Format emails as text for Claude recap prompt."""
    if not emails:
        return ""

    parts = ["\n=== ПОЧТА ===\n"]
    for e in emails:
        parts.append(f"От: {e['from']}")
        parts.append(f"Тема: {e['subject']}")
        parts.append(f"Дата: {e['date']}")
        parts.append(f"Текст:\n{e['body']}")
        parts.append("---")
    return "\n".join(parts)
