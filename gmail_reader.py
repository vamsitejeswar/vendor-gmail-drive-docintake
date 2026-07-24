"""
gmail_reader.py

Connects to Gmail via Gmail API using OAuth2.
First run opens a browser for one-time consent and saves token.json.
Subsequent runs use token.json automatically (no browser needed).
"""

import base64
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
VENDOR_SENDER_WHITELIST = [
    s.strip().lower()
    for s in os.getenv("VENDOR_SENDER_WHITELIST", "").split(",")
    if s.strip()
]

CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]


def _get_gmail_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _is_allowed_sender(from_address: str) -> bool:
    if not VENDOR_SENDER_WHITELIST:
        return True
    from_address = from_address.lower()
    return any(vendor in from_address for vendor in VENDOR_SENDER_WHITELIST)


def _get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _get_parts(payload):
    """Recursively collect all parts from a message payload."""
    parts = payload.get("parts", [])
    result = []
    for part in parts:
        result.append(part)
        if "parts" in part:
            result.extend(_get_parts(part))
    return result


def fetch_new_vendor_emails():
    """
    Fetches UNREAD emails with attachments via Gmail API.
    Returns: [{subject, from, message_id, attachments: [(filename, bytes)]}]
    Marks each processed email as read so it won't be picked up again.
    """
    service = _get_gmail_service()
    results = []

    response = service.users().messages().list(
        userId="me",
        q="is:unread has:attachment"
    ).execute()

    messages = response.get("messages", [])
    if not messages:
        return results

    for msg_ref in messages:
        msg_id = msg_ref["id"]
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()

        headers = msg["payload"].get("headers", [])
        from_address = _get_header(headers, "From")
        subject = _get_header(headers, "Subject")
        message_id_header = _get_header(headers, "Message-ID")

        if not _is_allowed_sender(from_address):
            continue

        attachments = []
        for part in _get_parts(msg["payload"]):
            filename = part.get("filename")
            att_id = part.get("body", {}).get("attachmentId")
            if filename and att_id:
                att = service.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=att_id
                ).execute()
                file_bytes = base64.urlsafe_b64decode(att["data"])
                attachments.append((filename, file_bytes))

        if attachments:
            results.append({
                "subject": subject,
                "from": from_address,
                "message_id": message_id_header,
                "attachments": attachments,
            })
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["UNREAD"]}
            ).execute()

    return results


if __name__ == "__main__":
    emails = fetch_new_vendor_emails()
    print(f"Found {len(emails)} email(s) with attachments:\n")
    for e in emails:
        print(f"From: {e['from']}")
        print(f"Subject: {e['subject']}")
        print(f"Attachments: {[name for name, _ in e['attachments']]}")
        print("-" * 40)
