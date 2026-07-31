import email
import imaplib
import os

from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
PROCESSED_LABEL = "contractsexplorer-processed-doc"


def _get_labels(mail, num):
    _, label_data = mail.fetch(num, "(X-GM-LABELS)")
    if label_data and label_data[0]:
        return str(label_data[0]).lower()
    return ""


def fetch_new_vendor_emails():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("INBOX")

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


if __name__ == "__main__":
    emails = fetch_new_vendor_emails()
    print(f"Found {len(emails)} email(s) with attachments:\n")
    for e in emails:
        print(f"From: {e['from']}")
        print(f"Subject: {e['subject']}")
        print(f"Attachments: {[name for name, _ in e['attachments']]}")
        print("-" * 40)
