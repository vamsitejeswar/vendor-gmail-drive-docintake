import email
import imaplib
import os

from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
PROCESSED_LABEL = "contractsexplorer-processed-doc"
VALID_VENDOR_LABEL = "valid-vendor"
REVIEW_VENDOR_LABEL = "review-vendor"


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


def fetch_new_vendor_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")
    _ensure_label_exists(mail)

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

        EXCLUDED_EXTENSIONS = {".ics"}
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
                "mail": mail,
            })

    return results


def mark_as_processed(mail, num):
    mail.store(num, "+X-GM-LABELS", PROCESSED_LABEL)
    mail.store(num, "-FLAGS", "\\Seen")


def mark_as_valid_vendor(mail, num):
    _ensure_valid_vendor_label(mail)
    mail.store(num, "+X-GM-LABELS", VALID_VENDOR_LABEL)


def mark_as_review_vendor(mail, num):
    _ensure_review_vendor_label(mail)
    mail.store(num, "+X-GM-LABELS", REVIEW_VENDOR_LABEL)


def fetch_valid_vendor_email_threads() -> list:
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")

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
            for part in msg.walk():
                if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                    raw_body = part.get_payload(decode=True)
                    body = raw_body.decode("utf-8", errors="ignore") if isinstance(raw_body, bytes) else ""
                    break
            if body:
                threads.append(f"From: {from_addr}\nSubject: {subject}\n\n{body}")
        except Exception:
            pass

    mail.logout()
    return threads


if __name__ == "__main__":
    emails = fetch_new_vendor_emails()
    print(f"Found {len(emails)} email(s) with attachments:\n")
    for e in emails:
        print(f"From: {e['from']}")
        print(f"Subject: {e['subject']}")
        print(f"Attachments: {[name for name, _ in e['attachments']]}")
        print("-" * 40)
