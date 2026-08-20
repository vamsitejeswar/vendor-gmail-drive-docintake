import email
import imaplib
import os

from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
PROCESSED_LABEL = "uploaded-to-drive"
VALID_VENDOR_LABEL = "valid-vendor"
REVIEW_VENDOR_LABEL = "review-vendor"
EXCLUDED_EXTENSIONS = {".ics"}


def _connect():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")
    return mail


def _ensure_label_exists(mail):
    try:
        mail.create(PROCESSED_LABEL)
    except Exception:
        pass


def _ensure_valid_vendor_label(mail):
    try:
        mail.create(VALID_VENDOR_LABEL)
    except Exception:
        pass


def _ensure_review_vendor_label(mail):
    try:
        mail.create(REVIEW_VENDOR_LABEL)
    except Exception:
        pass


def _get_labels(mail, num):
    _, label_data = mail.fetch(num, "(X-GM-LABELS)")
    if label_data and label_data[0]:
        return str(label_data[0]).lower()
    return ""


def fetch_new_vendor_emails(sender_filter: str = None):
    mail = _connect()
    _ensure_label_exists(mail)

    if sender_filter:
        _, message_numbers = mail.search(None, f'FROM "{sender_filter}"')
    else:
        _, message_numbers = mail.search(None, "ALL")

    results = []
    nums = message_numbers[0].split()
    if not nums:
        mail.logout()
        return results

    for num in nums:
        labels = _get_labels(mail, num)
        if PROCESSED_LABEL in labels:
            continue

        _, msg_data = mail.fetch(num, "(RFC822)")
        raw = msg_data[0]
        if not isinstance(raw, tuple):
            continue
        msg = email.message_from_bytes(raw[1])

        from_address = msg.get("From", "")
        subject = msg.get("Subject", "")

        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in EXCLUDED_EXTENSIONS:
                        continue
                    file_bytes = part.get_payload(decode=True)
                    attachments.append((filename, file_bytes))

        if attachments:
            results.append({
                "subject": subject,
                "from": from_address,
                "attachments": attachments,
                "num": num,
            })

    mail.logout()
    return results


def mark_email(num, is_valid: bool):
    """Open one IMAP connection, set all labels for this email, then close."""
    mail = _connect()
    try:
        _ensure_label_exists(mail)
        if is_valid:
            _ensure_valid_vendor_label(mail)
            mail.store(num, "+X-GM-LABELS", VALID_VENDOR_LABEL)
        else:
            _ensure_review_vendor_label(mail)
            mail.store(num, "+X-GM-LABELS", REVIEW_VENDOR_LABEL)
        mail.store(num, "+X-GM-LABELS", PROCESSED_LABEL)
        mail.store(num, "-FLAGS", "\\Seen")
    finally:
        mail.logout()


def fetch_valid_vendor_email_threads() -> list:
    mail = _connect()
    _, message_numbers = mail.search(None, f'X-GM-LABELS "{VALID_VENDOR_LABEL}"')
    threads = []
    nums = message_numbers[0].split()
    for num in nums:
        try:
            _, msg_data = mail.fetch(num, "(RFC822)")
            raw = msg_data[0]
            if not isinstance(raw, tuple):
                continue
            msg = email.message_from_bytes(raw[1])
            from_addr = msg.get("From", "")
            subject = msg.get("Subject", "")
            body = ""
            attachments = []
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = part.get_content_disposition()
                if content_type == "text/plain" and disposition != "attachment":
                    raw_body = part.get_payload(decode=True)
                    if not body and isinstance(raw_body, bytes):
                        body = raw_body.decode("utf-8", errors="ignore")
                elif disposition == "attachment":
                    filename = part.get_filename()
                    if filename:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext not in EXCLUDED_EXTENSIONS:
                            file_bytes = part.get_payload(decode=True)
                            if file_bytes:
                                attachments.append((filename, file_bytes))
            threads.append({
                "text": f"From: {from_addr}\nSubject: {subject}\n\n{body}",
                "attachments": attachments,
            })
        except Exception:
            pass

    mail.logout()
    return threads
