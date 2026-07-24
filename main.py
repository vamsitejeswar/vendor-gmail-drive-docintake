"""
main.py

Vendor Document Intake - orchestrator

Flow:
    1. Check the shared inbox for new (unread) emails with attachments
    2. For each email, use the sender's name/domain as the "vendor" folder name
    3. Upload each attachment to Drive:
         - existing file with same name -> new version (Drive version history)
         - no match -> create new file
    4. Print a summary (this is where you'd log / notify Slack / etc. later)

Run manually for testing:
    python main.py
"""

import re
from gmail_reader import fetch_new_vendor_emails
from drive_uploader import upload_vendor_attachment


def vendor_name_from_email(from_address: str) -> str:
    """Extracts the full email address to use as the vendor folder name."""
    match = re.search(r"[\w.+-]+@[\w.-]+", from_address)
    return match.group(0) if match else "unknown-vendor"


def run():
    emails = fetch_new_vendor_emails()

    if not emails:
        print("No new vendor emails with attachments found.")
        return

    print(f"Processing {len(emails)} email(s)...\n")

    for e in emails:
        vendor = vendor_name_from_email(e["from"])
        print(f"From: {e['from']}  (vendor folder: {vendor})")
        print(f"Subject: {e['subject']}")

        for filename, file_bytes in e["attachments"]:
            result = upload_vendor_attachment(vendor, filename, file_bytes)
            if result["action"] == "versioned":
                print(f"  -> File exists, saved as: {result['filename']}")
            else:
                print(f"  -> Created new file: {result['filename']}")

        print("-" * 40)


if __name__ == "__main__":
    run()
