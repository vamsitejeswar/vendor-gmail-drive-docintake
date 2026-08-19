import io
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

from drive_uploader import _get_drive_service, DRIVE_VALIDATED_FOLDER_ID, DRIVE_RUNBOOK_FOLDER_ID
from gmail_reader import fetch_valid_vendor_email_threads

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL = "gemini-2.5-flash"
RUNBOOK_FILENAME = "validation_runbook.txt"

GENERATION_PROMPT = """
You are a legal policy analyst for Verse Innovation Private Ltd.

You have been given previously accepted vendor contracts and email conversations from those vendor engagements.

Analyze all of them and create a structured Validation Policy Runbook to validate future vendor documents.

The runbook must include:

1. ACCEPTED DOCUMENT TYPES
   - List all document types seen (NDA, MSA, SOW, PO, etc.)

2. REQUIRED CLAUSES (by document type)
   - For each document type, list all clauses that must be present
   - Include acceptable variations seen across documents

3. STANDARD TERMS VERSE ACCEPTS
   - Payment terms (net days, currency)
   - Notice periods
   - Governing law / jurisdiction
   - Liability caps
   - IP ownership terms

4. RED FLAGS
   - Clauses or terms flagged or negotiated in email conversations
   - Terms Verse consistently pushes back on

5. VALIDATION CHECKLIST
   - Step-by-step checklist to validate any new vendor document

Extract real patterns from the documents provided. This runbook will be used by an AI agent to automatically validate future vendor contracts.
"""


def _list_files_in_folder(service, folder_id: str) -> list:
    query = f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    resp = service.files().list(
        q=query,
        fields="files(id, name, mimeType)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        pageSize=100,
    ).execute()
    return resp.get("files", [])


def _list_subfolders(service, folder_id: str) -> list:
    query = f"'{folder_id}' in parents and trashed = false and mimeType = 'application/vnd.google-apps.folder'"
    resp = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return resp.get("files", [])


def _download_file(service, file_id: str) -> bytes:
    return service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()


def _save_runbook_to_drive(service, content: str) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    query = f"'{DRIVE_RUNBOOK_FOLDER_ID}' in parents and name = '{RUNBOOK_FILENAME}' and trashed = false"
    existing = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    for f in existing:
        service.files().delete(fileId=f["id"], supportsAllDrives=True).execute()

    media = MediaIoBaseUpload(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", resumable=True)
    metadata = {"name": RUNBOOK_FILENAME, "parents": [DRIVE_RUNBOOK_FOLDER_ID]}
    new_file = service.files().create(
        body=metadata, media_body=media, fields="id", supportsAllDrives=True
    ).execute()
    return new_file["id"]


def fetch_runbook() -> str | None:
    service = _get_drive_service()
    query = f"'{DRIVE_RUNBOOK_FOLDER_ID}' in parents and name = '{RUNBOOK_FILENAME}' and trashed = false"
    existing = service.files().list(
        q=query, fields="files(id)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute().get("files", [])
    if not existing:
        return None
    return _download_file(service, existing[0]["id"]).decode("utf-8", errors="ignore")


def generate_runbook() -> dict:
    service = _get_drive_service()
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    contents = [GENERATION_PROMPT]
    doc_count = 0

    all_folders = [{"id": DRIVE_VALIDATED_FOLDER_ID}] + _list_subfolders(service, DRIVE_VALIDATED_FOLDER_ID)

    for folder in all_folders:
        for f in _list_files_in_folder(service, folder["id"]):
            if f["name"] == RUNBOOK_FILENAME:
                continue
            try:
                file_bytes = _download_file(service, f["id"])
                mime = f.get("mimeType", "application/octet-stream")
                contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))
                doc_count += 1
            except Exception:
                pass

    threads = fetch_valid_vendor_email_threads()
    if threads:
        contents.append("\n\n--- EMAIL THREADS ---\n\n" + "\n\n---\n\n".join(threads))

    if doc_count == 0 and not threads:
        return {"status": "error", "message": "No validated docs or email threads found."}

    response = client.models.generate_content(model=MODEL, contents=contents)
    runbook_text = response.text.strip()
    file_id = _save_runbook_to_drive(service, runbook_text)

    return {
        "status": "ok",
        "message": f"Runbook generated from {doc_count} docs and {len(threads)} email threads.",
        "file_id": file_id,
    }
