import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

DRIVE_INCOMING_FOLDER_ID = os.getenv("DRIVE_INCOMING_FOLDER_ID", "")
DRIVE_VALIDATED_FOLDER_ID = os.getenv("DRIVE_VALIDATED_FOLDER_ID", "")
DRIVE_RUNBOOK_FOLDER_ID = os.getenv("DRIVE_RUNBOOK_FOLDER_ID", "")
SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_drive_service():
    sa_json = os.getenv("SERVICE_ACCOUNT_JSON")
    if sa_json:
        creds = service_account.Credentials.from_service_account_info(json.loads(sa_json), scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file(os.getenv("SERVICE_ACCOUNT_FILE", "service_account.json"), scopes=SCOPES)
    return build("drive", "v3", credentials=creds)


def _get_or_create_subfolder(service, parent_folder_id: str, subfolder_name: str) -> str:
    safe_name = subfolder_name.replace("'", "\\'")
    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{safe_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    response = service.files().list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": subfolder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
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



def upload_to_validated(vendor_name: str, filename: str, file_bytes: bytes) -> dict:
    service = _get_drive_service()
    vendor_folder_id = _get_or_create_subfolder(service, DRIVE_VALIDATED_FOLDER_ID, vendor_name)
    final_name = _next_versioned_filename(service, vendor_folder_id, filename)
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream", resumable=True)
    metadata = {"name": final_name, "parents": [vendor_folder_id]}
    new_file = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return {"file_id": new_file["id"], "filename": final_name}


def upload_analysis_txt(vendor_name: str, doc_filename: str, analysis_text: str, dest_folder_id: str | None = None) -> dict:
    service = _get_drive_service()
    folder_id = dest_folder_id if dest_folder_id else DRIVE_INCOMING_FOLDER_ID
    vendor_folder_id = _get_or_create_subfolder(service, folder_id, vendor_name)
    analysis_folder_id = _get_or_create_subfolder(service, vendor_folder_id, "analysis")
    name = os.path.splitext(doc_filename)[0]
    txt_filename = _next_versioned_filename(service, analysis_folder_id, f"{name}_analysis.txt")
    content_bytes = analysis_text.encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(content_bytes), mimetype="text/plain", resumable=True)
    metadata = {"name": txt_filename, "parents": [analysis_folder_id]}
    new_file = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return {"file_id": new_file["id"], "filename": txt_filename}


def upload_vendor_attachment(vendor_name: str, filename: str, file_bytes: bytes) -> dict:
    service = _get_drive_service()
    vendor_folder_id = _get_or_create_subfolder(service, DRIVE_INCOMING_FOLDER_ID, vendor_name)
    final_name = _next_versioned_filename(service, vendor_folder_id, filename)
    action = "versioned" if final_name != filename else "created"
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream", resumable=True)
    metadata = {"name": final_name, "parents": [vendor_folder_id]}
    new_file = service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return {"action": action, "file_id": new_file["id"], "filename": final_name}
