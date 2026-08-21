import io
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv


def _to_gemini_part(filename: str, file_bytes: bytes):
    if not file_bytes:
        return None
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return types.Part.from_bytes(data=file_bytes, mime_type="application/pdf")
    elif ext in (".doc", ".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            if not text.strip():
                return None
            return types.Part.from_bytes(data=text.encode("utf-8"), mime_type="text/plain")
        except Exception:
            return None
    elif ext == ".txt":
        if not file_bytes.strip():
            return None
        return types.Part.from_bytes(data=file_bytes, mime_type="text/plain")
    return None

from google.cloud import storage as gcs
from drive_uploader import _get_drive_service, DRIVE_VALIDATED_FOLDER_ID
from gmail_reader import fetch_valid_vendor_email_threads

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL = "gemini-2.5-flash"
RUNBOOK_FILENAME = "validation_runbook.txt"
GCS_BUCKET = os.getenv("GCS_RUNBOOK_BUCKET", "verse-contracts-runbook")

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


def _save_runbook_to_gcs(content: str) -> None:
    client = gcs.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(RUNBOOK_FILENAME)
    blob.upload_from_string(content.encode("utf-8"), content_type="text/plain")


def _append_to_runbook_gcs(additions: str) -> None:
    client = gcs.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(RUNBOOK_FILENAME)
    existing = blob.download_as_text(encoding="utf-8") if blob.exists() else ""
    updated = existing.rstrip() + f"\n\n---\n\n## INCREMENTAL UPDATE — New Patterns from Recent Valid Docs\n\n{additions}\n"
    blob.upload_from_string(updated.encode("utf-8"), content_type="text/plain")


def fetch_runbook() -> str | None:
    client = gcs.Client(project=PROJECT_ID)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(RUNBOOK_FILENAME)
    if not blob.exists():
        return None
    return blob.download_as_text(encoding="utf-8")


BATCH_SIZE = 20

MERGE_PROMPT = """
You are a legal policy analyst for Verse Innovation Private Ltd.

Below are multiple partial validation runbooks, each generated from a different batch of Verse's accepted vendor contracts.

Merge them into ONE unified, deduplicated Validation Policy Runbook. Keep all unique patterns, clauses, and red flags found across all batches. Remove duplicates. Organize clearly.

The final runbook must include:
1. ACCEPTED DOCUMENT TYPES
2. REQUIRED CLAUSES (by document type)
3. STANDARD TERMS VERSE ACCEPTS
4. RED FLAGS
5. VALIDATION CHECKLIST
"""


def _generate_batch_runbook(client, files: list, service) -> str:
    contents: list = [GENERATION_PROMPT]
    for f in files:
        try:
            file_bytes = _download_file(service, f["id"])
            part = _to_gemini_part(f["name"], file_bytes)
            if part:
                contents.append(part)
        except Exception:
            pass
    if len(contents) == 1:
        return ""
    response = client.models.generate_content(model=MODEL, contents=contents)
    return (response.text or "").strip()


def generate_runbook() -> dict:
    service = _get_drive_service()
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    all_folders = [{"id": DRIVE_VALIDATED_FOLDER_ID}] + _list_subfolders(service, DRIVE_VALIDATED_FOLDER_ID)
    all_files = []
    for folder in all_folders:
        for f in _list_files_in_folder(service, folder["id"]):
            if f["name"] != RUNBOOK_FILENAME:
                all_files.append(f)

    # Generate one mini-runbook per batch
    batches = [all_files[i:i + BATCH_SIZE] for i in range(0, len(all_files), BATCH_SIZE)]
    batch_runbooks = []
    doc_count = 0
    for batch in batches:
        text = _generate_batch_runbook(client, batch, service)
        if text:
            batch_runbooks.append(text)
            doc_count += len(batch)

    # Also include valid-vendor email threads
    threads = fetch_valid_vendor_email_threads()
    email_count = len(threads)
    attachment_count = 0
    if threads:
        email_contents: list = [GENERATION_PROMPT, "\n\n--- VALID VENDOR EMAIL THREADS ---\n"]
        for thread in threads:
            email_contents.append(thread["text"])
            for filename, file_bytes in thread["attachments"]:
                part = _to_gemini_part(filename, file_bytes)
                if part:
                    email_contents.append(part)
                    attachment_count += 1
            email_contents.append("\n---\n")
        if len(email_contents) > 2:
            resp = client.models.generate_content(model=MODEL, contents=email_contents)
            if resp.text:
                batch_runbooks.append(resp.text.strip())

    if not batch_runbooks:
        return {"status": "error", "message": "No validated docs or email threads found."}

    # Merge all batch runbooks into one
    if len(batch_runbooks) == 1:
        final_runbook = batch_runbooks[0]
    else:
        merge_contents = [MERGE_PROMPT] + [f"\n\n--- BATCH {i+1} ---\n\n{rb}" for i, rb in enumerate(batch_runbooks)]
        merge_response = client.models.generate_content(model=MODEL, contents=merge_contents)
        final_runbook = (merge_response.text or "").strip()

    _save_runbook_to_gcs(final_runbook)

    return {
        "status": "ok",
        "message": f"Runbook generated from {doc_count} docs across {len(batches)} batches, {email_count} email threads, {attachment_count} email attachments.",
        "bucket": GCS_BUCKET,
        "file": RUNBOOK_FILENAME,
    }


UPDATE_PROMPT = """
You are a legal policy analyst for Verse Innovation Private Ltd.

Below is the EXISTING validation runbook that is already in use:

--- EXISTING RUNBOOK START ---
{existing_runbook}
--- EXISTING RUNBOOK END ---

Below are NEW vendor documents that were just accepted as VALID:

--- NEW DOCUMENTS START ---
"""

UPDATE_MERGE_PROMPT = """
--- NEW DOCUMENTS END ---

Your task: Identify ONLY what is NEW or DIFFERENT in these documents compared to the existing runbook.

Look for:
- New document types not listed in Section 1
- New clause patterns or acceptable variations not already in Section 2
- New standard terms Verse accepts not in Section 3
- New red flags not already in Section 4

DO NOT repeat anything already in the existing runbook.
DO NOT rewrite the whole runbook.
DO NOT change existing rules, relaxations, or the SUGGESTIONS ONLY section.

Return ONLY the incremental additions in this format:

NEW DOCUMENT TYPES (if any):
- [list]

NEW / UPDATED CLAUSE PATTERNS (if any):
- [clause name]: [what was found]

NEW STANDARD TERMS (if any):
- [term]: [detail]

NEW RED FLAGS (if any):
- [flag]: [detail]

If nothing is new, respond with exactly: NO NEW PATTERNS FOUND
"""


def update_runbook(new_docs: list) -> dict:
    """Incrementally update the runbook with patterns from new valid docs only.
    Preserves all existing manual rules and only appends genuinely new findings."""
    if not new_docs:
        return {"status": "ok", "message": "No new docs to update runbook with."}

    existing_runbook = fetch_runbook()
    if not existing_runbook:
        return {"status": "skip", "message": "No existing runbook found. Run /generate-runbook first."}

    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    # Build prompt with existing runbook + new docs
    contents: list = [UPDATE_PROMPT.format(existing_runbook=existing_runbook)]
    added = 0
    for filename, file_bytes in new_docs:
        part = _to_gemini_part(filename, file_bytes)
        if part:
            contents.append(part)
            added += 1

    if added == 0:
        return {"status": "skip", "message": "New docs could not be parsed (unsupported format)."}

    contents.append(UPDATE_MERGE_PROMPT)

    response = client.models.generate_content(model=MODEL, contents=contents)
    additions = (response.text or "").strip()

    if not additions or "NO NEW PATTERNS FOUND" in additions:
        return {"status": "ok", "message": "Runbook already covers all patterns in new docs. No update needed."}

    # Append only new findings — never replace existing rules
    _append_to_runbook_gcs(additions)

    return {
        "status": "ok",
        "message": f"Runbook appended with patterns from {added} new doc(s).",
        "additions": additions,
    }
