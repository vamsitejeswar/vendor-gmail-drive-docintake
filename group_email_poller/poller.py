import email
import imaplib
import os
import re
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

GROUP_EMAIL = os.getenv("GROUP_EMAIL", "test_contract@verse.in")
MEMBER_EMAIL = os.getenv("GROUP_MEMBER_EMAIL", "")
MEMBER_APP_PASSWORD = os.getenv("GROUP_MEMBER_APP_PASSWORD", "")
EXCLUDED_EXTENSIONS = {".ics"}


def _connect():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(MEMBER_EMAIL, MEMBER_APP_PASSWORD)
    return mail


def _decode_header_value(value: str) -> str:
    parts = decode_header(value or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return " ".join(decoded).strip()


def _extract_body(msg) -> str:
    body = ""
    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        if content_type == "text/plain" and disposition != "attachment":
            raw = part.get_payload(decode=True)
            if raw and not body:
                body = raw.decode("utf-8", errors="ignore")
    return body.strip()


def _extract_attachments(msg) -> list:
    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename()
            if filename:
                ext = os.path.splitext(filename)[1].lower()
                if ext in EXCLUDED_EXTENSIONS:
                    continue
                file_bytes = part.get_payload(decode=True)
                if file_bytes:
                    attachments.append((filename, file_bytes))
    return attachments


INTERNAL_DOMAIN = "verse.in"


def _extract_vendor_name(emails: list) -> str:
    for e in emails:
        match = re.search(r"@([\w.-]+)", e.get("from", ""))
        if match:
            domain = match.group(1)
            if INTERNAL_DOMAIN not in domain:
                name = domain.split(".")[0]
                return name.replace("-", " ").replace("_", " ").title()
    return "Unknown Vendor"


def _group_into_threads(emails: list) -> dict:
    threads = {}
    id_to_subject = {}

    for e in emails:
        msg_id = e.get("message_id", "").strip()
        in_reply_to = e.get("in_reply_to", "").strip()
        references = e.get("references", "").strip()
        subject = e.get("subject", "No Subject")

        thread_key = None

        # Check references first
        if references:
            for ref in references.split():
                if ref in id_to_subject:
                    thread_key = id_to_subject[ref]
                    break

        # Then check in_reply_to
        if not thread_key and in_reply_to and in_reply_to in id_to_subject:
            thread_key = id_to_subject[in_reply_to]

        # New thread
        if not thread_key:
            clean_subject = re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()
            thread_key = clean_subject or subject

        if msg_id:
            id_to_subject[msg_id] = thread_key

        if thread_key not in threads:
            threads[thread_key] = []
        threads[thread_key].append(e)

    # Sort each thread by date
    for key in threads:
        threads[key].sort(key=lambda x: x.get("date", ""))

    return threads


def _get_real_from(msg) -> str:
    # Google Groups rewrites From to the group address — use Reply-To or X-Original-Sender to get real sender
    for header in ("Reply-To", "X-Original-Sender", "X-Google-Original-From"):
        val = msg.get(header, "")
        if val:
            return _decode_header_value(val)
    return _decode_header_value(msg.get("From", ""))


def _fetch_from_mailbox(mail, mailbox: str) -> list:
    try:
        mail.select(mailbox)
    except Exception:
        return []

    # Search both TO and CC for group email
    seen_nums = set()
    all_nums = []
    for criteria in [f'TO "{GROUP_EMAIL}"', f'CC "{GROUP_EMAIL}"']:
        _, nums = mail.search(None, criteria)
        for n in (nums[0].split() if nums[0] else []):
            if n not in seen_nums:
                seen_nums.add(n)
                all_nums.append(n)

    results = []
    for num in all_nums:
        try:
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0]
            if not isinstance(raw, tuple):
                continue
            msg = email.message_from_bytes(raw[1])
            results.append({
                "message_id": msg.get("Message-ID", ""),
                "in_reply_to": msg.get("In-Reply-To", ""),
                "references": msg.get("References", ""),
                "from": _get_real_from(msg),
                "to": _decode_header_value(msg.get("To", "")),
                "cc": _decode_header_value(msg.get("Cc", "")),
                "subject": _decode_header_value(msg.get("Subject", "No Subject")),
                "date": msg.get("Date", ""),
                "direction": "RECEIVED",
                "body": _extract_body(msg),
                "attachments": _extract_attachments(msg),
            })
        except Exception:
            pass
    return results


def _fetch_sent(mail) -> list:
    for sent_folder in ('"[Gmail]/Sent Mail"', "Sent", '"[Gmail]/Sent"'):
        try:
            status, _ = mail.select(sent_folder)
            if status != "OK":
                continue
            _, nums = mail.search(None, "ALL")
            results = []
            for num in (nums[0].split() if nums[0] else []):
                try:
                    _, msg_data = mail.fetch(num, "(RFC822)")
                    raw = msg_data[0]
                    if not isinstance(raw, tuple):
                        continue
                    msg = email.message_from_bytes(raw[1])
                    to_field = _decode_header_value(msg.get("To", ""))
                    cc_field = _decode_header_value(msg.get("Cc", ""))
                    from_field = _decode_header_value(msg.get("From", ""))
                    if GROUP_EMAIL not in to_field and GROUP_EMAIL not in cc_field and GROUP_EMAIL not in from_field:
                        continue
                    results.append({
                        "message_id": msg.get("Message-ID", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                        "references": msg.get("References", ""),
                        "from": _get_real_from(msg),
                        "to": to_field,
                        "cc": cc_field,
                        "subject": _decode_header_value(msg.get("Subject", "No Subject")),
                        "date": msg.get("Date", ""),
                        "direction": "SENT",
                        "body": _extract_body(msg),
                        "attachments": _extract_attachments(msg),
                    })
                except Exception:
                    pass
            return results
        except Exception:
            continue
    return []


def fetch_group_email_threads() -> list:
    mail = _connect()

    inbox_emails = _fetch_from_mailbox(mail, "INBOX")
    sent_emails = _fetch_sent(mail)
    mail.logout()

    # Merge and deduplicate by Message-ID
    seen_ids = set()
    all_emails = []
    for e in inbox_emails + sent_emails:
        mid = e.get("message_id", "").strip()
        if mid and mid in seen_ids:
            continue
        if mid:
            seen_ids.add(mid)
        all_emails.append(e)

    threads = _group_into_threads(all_emails)

    result = []
    for subject, emails in threads.items():
        vendor = _extract_vendor_name(emails)
        first_date = emails[0].get("date", "")[:10].replace(" ", "-")
        attachments = []
        for e in emails:
            attachments.extend(e["attachments"])
        result.append({
            "subject": subject,
            "vendor": vendor,
            "date": first_date,
            "emails": emails,
            "attachments": attachments,
        })

    return result
