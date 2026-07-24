import io
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
DRIVE_ROOT_FOLDER_ID = os.getenv("DRIVE_ROOT_FOLDER_ID", "")

TOKEN_FILE = "token.json"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
]


def _get_drive_service():
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
    return build("drive", "v3", credentials=creds)


def _get_or_create_subfolder(service, parent_folder_id: str, subfolder_name: str) -> str:
    safe_name = subfolder_name.replace("'", "\\'")
    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{safe_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    response = service.files().list(q=query, fields="files(id, name)").execute()
    files = response.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {
        "name": subfolder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_folder_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def _next_versioned_filename(service, folder_id: str, filename: str) -> str:
    """Returns the next available filename: file.docx -> file_v2.docx -> file_v3.docx ..."""
    name, ext = os.path.splitext(filename)

    def exists(fname):
        safe = fname.replace("'", "\\'")
        q = f"'{folder_id}' in parents and name = '{safe}' and trashed = false"
        return bool(service.files().list(q=q, fields="files(id)").execute().get("files"))

    if not exists(filename):
        return filename

    version = 2
    while True:
        candidate = f"{name}_v{version}{ext}"
        if not exists(candidate):
            return candidate
        version += 1


def upload_vendor_attachment(vendor_name: str, filename: str, file_bytes: bytes) -> dict:
    service = _get_drive_service()
    vendor_folder_id = _get_or_create_subfolder(service, DRIVE_ROOT_FOLDER_ID, vendor_name)
    final_name = _next_versioned_filename(service, vendor_folder_id, filename)
    action = "versioned" if final_name != filename else "created"
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype="application/octet-stream", resumable=True)
    metadata = {"name": final_name, "parents": [vendor_folder_id]}
    new_file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    return {"action": action, "file_id": new_file["id"], "filename": final_name}
