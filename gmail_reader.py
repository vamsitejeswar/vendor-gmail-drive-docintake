import email
import imaplib
import os

from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
VENDOR_SENDER_WHITELIST = [
    s.strip().lower()
    for s in os.getenv("VENDOR_SENDER_WHITELIST", "").split(",")
    if s.strip()
]


def _is_allowed_sender(from_address: str) -> bool:
    if not VENDOR_SENDER_WHITELIST:
        return True
    return any(vendor in from_address.lower() for vendor in VENDOR_SENDER_WHITELIST)


def fetch_new_vendor_emails():
    """
    Connects to Gmail via IMAP using email + app password.
    Fetches UNREAD emails with attachments.
    Returns: [{subject, from, attachments: [(filename, bytes)]}]
    Marks each processed email as read.
    """
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_ADDRESS or "", GMAIL_APP_PASSWORD or "")
    mail.select("INBOX")

    _, message_numbers = mail.search(None, "UNSEEN")

    results = []
    nums = message_numbers[0].split()
    if not nums:
        mail.logout()
        return results

    for num in nums:
        _, msg_data = mail.fetch(num, "(RFC822)")
        raw = msg_data[0]
        if not isinstance(raw, tuple):
            continue
        msg = email.message_from_bytes(raw[1])

        from_address = msg.get("From", "")
        subject = msg.get("Subject", "")

        if not _is_allowed_sender(from_address):
            continue

        attachments = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename()
                if filename:
                    file_bytes = part.get_payload(decode=True)
                    attachments.append((filename, file_bytes))

        if attachments:
            results.append({
                "subject": subject,
                "from": from_address,
                "attachments": attachments,
            })
            mail.store(num, "+FLAGS", "\\Seen")

    mail.logout()
    return results


if __name__ == "__main__":
    emails = fetch_new_vendor_emails()
    print(f"Found {len(emails)} email(s) with attachments:\n")
    for e in emails:
        print(f"From: {e['from']}")
        print(f"Subject: {e['subject']}")
        print(f"Attachments: {[name for name, _ in e['attachments']]}")
        print("-" * 40)
