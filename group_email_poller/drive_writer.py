import io
import json
import os
import re

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

GROUP_EMAILS_FOLDER_ID = os.getenv("DRIVE_GROUP_EMAILS_FOLDER_ID", "")
SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_drive_service():
    sa_json = os.getenv("SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
    else:
        sa_file = os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json")
        sa_path = os.path.join(os.path.dirname(__file__), sa_file)
        creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_or_create_subfolder(service, parent_id: str, name: str) -> str:
    safe = name.replace("'", "\\'")
    query = (
        f"'{parent_id}' in parents and "
        f"name = '{safe}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    resp = service.files().list(q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    folder = service.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
    return folder["id"]


def _next_versioned_filename(service, folder_id: str, filename: str) -> str:
    name, ext = os.path.splitext(filename)

    def exists(fname):
        safe = fname.replace("'", "\\'")
        q = f"'{folder_id}' in parents and name = '{safe}' and trashed = false"
        return bool(service.files().list(q=q, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files"))

    if not exists(filename):
        return filename
    version = 2
    while True:
        candidate = f"{name}_v{version}{ext}"
        if not exists(candidate):
            return candidate
        version += 1


def _sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()[:80]


def _build_thread_txt(thread: dict) -> str:
    emails = thread["emails"]
    lines = [
        "================================================================",
        f"THREAD : {thread['subject']}",
        f"VENDOR : {thread['vendor']}",
        f"EMAILS : {len(emails)} messages",
        "================================================================",
    ]
    for i, e in enumerate(emails, 1):
        lines += [
            "",
            "----------------------------------------------------------------",
            f"[{i}/{len(emails)}] {e['direction']}",
            f"Date    : {e.get('date', '')}",
            f"From    : {e.get('from', '')}",
            f"To      : {e.get('to', '')}",
            f"CC      : {e.get('cc', '') or '—'}",
            f"Subject : {e.get('subject', '')}",
            "",
            e.get("body", "").strip(),
        ]
        if e.get("attachments"):
            lines.append("")
            lines.append("Attachments: " + ", ".join(a[0] for a in e["attachments"]))
        lines.append("----------------------------------------------------------------")
    return "\n".join(lines)


def _upload_file(service, folder_id: str, filename: str, content_bytes: bytes, mime: str) -> str:
    final_name = _next_versioned_filename(service, folder_id, filename)
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype=mime, resumable=True)
    metadata = {"name": final_name, "parents": [folder_id]}
    f = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return f["id"]


def upload_thread_to_drive(thread: dict) -> dict:
    service = _get_drive_service()

    vendor_folder_id = _get_or_create_subfolder(service, GROUP_EMAILS_FOLDER_ID, _sanitize(thread["vendor"]))

    thread_folder_name = _sanitize(f"{thread['subject']}_{thread['date']}")
    thread_folder_id = _get_or_create_subfolder(service, vendor_folder_id, thread_folder_name)

    thread_txt = _build_thread_txt(thread)
    _upload_file(service, thread_folder_id, "thread.txt", thread_txt.encode("utf-8"), "text/plain")

    uploaded_attachments = []
    seen = set()
    for filename, file_bytes in thread["attachments"]:
        if filename in seen:
            continue
        seen.add(filename)
        _upload_file(service, thread_folder_id, filename, file_bytes, "application/octet-stream")
        uploaded_attachments.append(filename)

    return {
        "vendor": thread["vendor"],
        "subject": thread["subject"],
        "emails": len(thread["emails"]),
        "attachments": uploaded_attachments,
    }
