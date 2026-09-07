import io
import logging
import os

from dotenv import load_dotenv
from google import genai
from google.genai import types
from googleapiclient.http import MediaIoBaseUpload

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL = "gemini-2.5-flash"
RUNBOOK_FILENAME = "group_email_runbook.txt"
RUNBOOK_FOLDER_NAME = "_runbook"
BATCH_SIZE = 50

GROUP_EMAILS_FOLDER_ID = os.getenv("DRIVE_GROUP_EMAILS_FOLDER_ID", "")

GENERATION_PROMPT = """
You are a procurement analyst for Verse Innovation Private Ltd.

You have been given vendor emails, contracts, proposals, quotations, invoices, SOWs, NDAs,
purchase orders, and other documents exchanged with external vendors via the group email
test_contract@verse.in.

Analyze ALL documents and email threads provided. Extract real patterns only — do not invent
clauses or terms not evidenced in the documents.

Produce a structured Vendor Procurement Runbook in EXACTLY this format:

---

# Vendor Procurement Runbook for Verse Innovation Private Ltd.

**Purpose:** [One paragraph describing what this runbook covers and how it should be used.]

**KEY PRINCIPLE — Validate Proportionately:**
[One paragraph: which clauses apply to which document types; when to flag vs. suggest; how to handle unknown document types.]

**OVERRIDING RULE — VALID vs. REVIEW NEEDED:**
[Bullet points: when to mark VALID, when to mark REVIEW NEEDED, what never triggers REVIEW NEEDED.]

---

## 1. ACCEPTED DOCUMENT TYPES

[List every document type observed across all vendor threads and docs. Group into:]

**A. Core Transactional Agreements:**
[Numbered list with document type name and one-line description.]

**B. Supplementary / Specific Agreements:**
[Numbered list.]

**C. Pre-Contractual / Supporting Documents:**
[Numbered list. Include "Other / Unknown Document Type" as the last item with guidance.]

---

## 2. REQUIRED CLAUSES (by document type)

[Start with an APPLICABILITY GUIDE — a bulleted list mapping document types to which clause groups apply (full set, lightweight, confidentiality-focus only, document-specific only).]

### A. General Clauses (Applicable to most Contractual Agreements)

[For each clause: name in bold, Verse's expectation, acceptable variations, what triggers a flag.]

Include at minimum:
- Parties Identification
- Effective Date & Term
- Definitions
- Scope of Services/Work/Deliverables
- Payment Terms / Consideration
- Taxes
- Confidentiality
- Intellectual Property Rights (IPR)
- Representations & Warranties
- Indemnification
- Limitation of Liability
- Termination
- Effects of Termination
- Relationship of Parties
- Governing Law & Jurisdiction
- Dispute Resolution
- Force Majeure
- Assignment
- Notices
- Entire Agreement / Amendment / Severability

### B. Specific Clauses (by Document Type)

[One subsection per distinct document type observed, e.g.:]
#### B1. [Document Type]
[Required clauses specific to this type.]
...

---

## 3. STANDARD TERMS VERSE ACCEPTS

[Structured list of Verse's preferred positions, grouped by topic:]

- **Payment Terms:** net days, currency, taxes, disputed invoices, audit rights
- **Notice Periods:** termination without cause, for cause, security incidents, force majeure
- **Governing Law / Jurisdiction:** preferred law, preferred court seat, acceptable variations
- **Liability Caps:** exclusion of indirect damages, Verse's cap, vendor's uncapped categories
- **IP Ownership Terms:** work product, pre-existing IP, vendor platform, brand usage

---

## 4. RED FLAGS

[Numbered list. Each item: bold title, description of what triggers the flag, and — where applicable — note what does NOT trigger the flag (missing clause ≠ active violation).]

Include at minimum:
1. IP Ownership Vests in Vendor for Commissioned Work
2. Active AI Model Training with Verse Data
3. Vendor Liability Cap too Low or Exempted for Critical Breaches
4. Verse Liability Cap too High
5. Unilateral Amendments by Vendor
6. Payment Terms Unfavorable to Verse
7. Subcontracting Actively Permitted Without Consent
8. Exclusivity Demanded by Vendor
9. Governing Law / Jurisdiction (non-Indian — SUGGESTIONS ONLY, NOT review needed)
10. Active Bribery / Corruption Violations
11. Vague or Undefined Scope of Services
[Continue with any additional red flags evidenced in the documents.]

---

## 4.5 SUGGESTIONS ONLY (NEVER RED FLAG)

[Numbered list of items that must ALWAYS go in SUGGESTIONS with a recommended fix, and must NEVER trigger REVIEW NEEDED. Include at minimum: missing anti-bribery, missing non-solicitation, missing AI prohibition, missing data security specifics, missing publicity restriction, missing assignment restriction, missing arbitration clause, unfilled admin fields, missing boilerplate, missing force majeure.]

---

## 5. VALIDATION CHECKLIST

[Step-by-step checklist in exactly this structure:]

**Phase 1: Document Intake & Classification**
[Numbered steps: Check → Action for each.]

**Phase 2: Core Clause Validation**
[Numbered steps with RED FLAG codes (R-#) and Human Review codes (H-#).]

**Phase 3: Document-Specific Clause Validation**
[One sub-section per document type group, with Check → Action for each clause.]

**Phase 4: Final Red Flag Check & Overall Assessment**
[Consolidation step and summary template.]

**Summary of Validation Results:**
- Overall Status: [VALID / REVIEW NEEDED]
- Total Red Flags: [Number]
- Total Suggestions: [Number]
- List of Specific Flags (with R/# or H/# codes)

---
**Disclaimer:** [Standard disclaimer that this runbook does not replace legal review.]

---

Extract every pattern from the documents provided. Use real clause language and real terms observed
in the vendor emails and attachments. Do not invent anything not present in the source material.
"""

MERGE_PROMPT = """
You are a procurement analyst for Verse Innovation Private Ltd.

Below are multiple partial vendor procurement runbooks, each generated from a different batch of
Verse's vendor email threads and documents.

Merge them into ONE unified, deduplicated Vendor Procurement Runbook.
Keep all unique patterns, clause types, standard terms, and red flags found across all batches.
Remove duplicates. Organize clearly.

The final runbook MUST follow this exact section structure — no deviation:

# Vendor Procurement Runbook for Verse Innovation Private Ltd.
**Purpose:** ...
**KEY PRINCIPLE — Validate Proportionately:** ...
**OVERRIDING RULE — VALID vs. REVIEW NEEDED:** ...

## 1. ACCEPTED DOCUMENT TYPES
  A. Core Transactional Agreements
  B. Supplementary / Specific Agreements
  C. Pre-Contractual / Supporting Documents

## 2. REQUIRED CLAUSES (by document type)
  APPLICABILITY GUIDE
  ### A. General Clauses
  ### B. Specific Clauses (one subsection per document type)

## 3. STANDARD TERMS VERSE ACCEPTS
  Payment Terms / Notice Periods / Governing Law / Liability Caps / IP Ownership

## 4. RED FLAGS
  (Numbered list with active-violation rule for each)

## 4.5 SUGGESTIONS ONLY (NEVER RED FLAG)
  (Numbered list)

## 5. VALIDATION CHECKLIST
  Phase 1 / Phase 2 / Phase 3 / Phase 4 / Summary template

**Disclaimer:** ...
"""

UPDATE_PROMPT = """
You are a procurement analyst for Verse Innovation Private Ltd.

Below is the EXISTING vendor procurement runbook that is already in use:

--- EXISTING RUNBOOK START ---
{existing_runbook}
--- EXISTING RUNBOOK END ---

Below are NEW vendor documents and email threads that were just added:

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

Return ONLY the incremental additions in this exact format:

## INCREMENTAL UPDATE — New Patterns from Recent Docs

NEW DOCUMENT TYPES (if any):
- [document type name]: [one-line description]

NEW / UPDATED CLAUSE PATTERNS (if any):
- **[Clause Name (in Document Type)]**: [what was found / Verse's position]

NEW STANDARD TERMS (if any):
- [term]: [detail]

NEW RED FLAGS (if any):
- [flag name]: [description of what triggers it and what does NOT trigger it]

If nothing is new, respond with exactly: NO NEW PATTERNS FOUND
"""


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
    elif ext in (".txt", ".csv", ".md"):
        if not file_bytes.strip():
            return None
        return types.Part.from_bytes(data=file_bytes, mime_type="text/plain")
    return None


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


def _get_drive_service():
    from drive_writer import _get_drive_service as _ds
    return _ds()


def _get_or_create_runbook_folder(service) -> str:
    resp = service.files().list(
        q=(
            f"'{GROUP_EMAILS_FOLDER_ID}' in parents and "
            f"name = '{RUNBOOK_FOLDER_NAME}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={
            "name": RUNBOOK_FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [GROUP_EMAILS_FOLDER_ID],
        },
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return folder["id"]


def _save_runbook_to_drive(service, content: str) -> None:
    folder_id = _get_or_create_runbook_folder(service)

    resp = service.files().list(
        q=(
            f"'{folder_id}' in parents and "
            f"name = '{RUNBOOK_FILENAME}' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    for old in resp.get("files", []):
        try:
            service.files().delete(fileId=old["id"], supportsAllDrives=True).execute()
            logger.info(f"Deleted old runbook: {old['id']}")
        except Exception as e:
            logger.warning(f"Could not delete old runbook {old['id']}: {e}")

    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/plain",
        resumable=True,
    )
    f = service.files().create(
        body={"name": RUNBOOK_FILENAME, "parents": [folder_id]},
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    logger.info(f"Runbook saved to Drive: {f['id']}")


def _append_to_runbook_drive(service, additions: str) -> None:
    folder_id = _get_or_create_runbook_folder(service)

    resp = service.files().list(
        q=(
            f"'{folder_id}' in parents and "
            f"name = '{RUNBOOK_FILENAME}' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])

    existing = ""
    if files:
        try:
            existing = _download_file(service, files[0]["id"]).decode("utf-8", errors="ignore")
            service.files().delete(fileId=files[0]["id"], supportsAllDrives=True).execute()
        except Exception as e:
            logger.warning(f"Could not read/delete old runbook for append: {e}")

    updated = (
        existing.rstrip()
        + f"\n\n---\n\n## INCREMENTAL UPDATE — New Patterns from Recent Docs\n\n{additions}\n"
    )
    media = MediaIoBaseUpload(
        io.BytesIO(updated.encode("utf-8")),
        mimetype="text/plain",
        resumable=True,
    )
    f = service.files().create(
        body={"name": RUNBOOK_FILENAME, "parents": [folder_id]},
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    logger.info(f"Runbook appended and re-saved: {f['id']}")


def fetch_runbook() -> str | None:
    service = _get_drive_service()
    folder_id = _get_or_create_runbook_folder(service)
    resp = service.files().list(
        q=(
            f"'{folder_id}' in parents and "
            f"name = '{RUNBOOK_FILENAME}' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if not files:
        return None
    return _download_file(service, files[0]["id"]).decode("utf-8", errors="ignore")


def _generate_batch_runbook(client, files: list, service) -> str:
    contents = [types.Part.from_text(text=GENERATION_PROMPT)]
    docs_added = 0
    threads_added = 0
    skipped = 0
    for f in files:
        try:
            file_bytes = _download_file(service, f["id"])
            part = _to_gemini_part(f["name"], file_bytes)
            if part:
                contents.append(part)
                if f["name"] == "thread.txt":
                    threads_added += 1
                else:
                    docs_added += 1
                    logger.info(f"  + doc: {f['name']}")
            else:
                logger.info(f"  - skipped (unsupported/empty): {f['name']}")
                skipped += 1
        except Exception as e:
            logger.warning(f"  Failed to download {f['name']}: {e}")
            skipped += 1
    if len(contents) == 1:
        return ""
    logger.info(
        f"  Calling Gemini — {docs_added} attachment docs + {threads_added} email threads "
        f"({skipped} skipped)"
    )
    response = client.models.generate_content(model=MODEL, contents=contents)
    return (response.text or "").strip()


def generate_runbook() -> dict:
    service = _get_drive_service()
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    all_attachments = []
    all_thread_txts = []

    vendor_folders = _list_subfolders(service, GROUP_EMAILS_FOLDER_ID)
    logger.info(f"Vendor folders found: {len(vendor_folders)}")

    for vf in vendor_folders:
        if vf["name"] == RUNBOOK_FOLDER_NAME:
            continue
        thread_folders = _list_subfolders(service, vf["id"])
        logger.info(f"  Vendor '{vf['name']}': {len(thread_folders)} thread folders")
        for tf in thread_folders:
            for f in _list_files_in_folder(service, tf["id"]):
                if f["name"] == RUNBOOK_FILENAME:
                    continue
                if f["name"] == "thread.txt":
                    all_thread_txts.append(f)
                else:
                    all_attachments.append(f)

    all_files = all_attachments + all_thread_txts
    logger.info(
        f"Total: {len(all_attachments)} attachment files + {len(all_thread_txts)} thread.txt = {len(all_files)} files"
    )

    if not all_files:
        return {"status": "error", "message": "No docs found in Drive. Run bulk upload first."}

    batches = [all_files[i: i + BATCH_SIZE] for i in range(0, len(all_files), BATCH_SIZE)]
    batch_runbooks = []
    doc_count = 0
    for i, batch in enumerate(batches, 1):
        logger.info(f"Batch {i}/{len(batches)}: {len(batch)} files")
        text = _generate_batch_runbook(client, batch, service)
        if text:
            batch_runbooks.append(text)
            doc_count += len(batch)
            logger.info(f"Batch {i}: {len(text)} chars generated")
        else:
            logger.warning(f"Batch {i}: empty response, skipping")

    if not batch_runbooks:
        return {"status": "error", "message": "No content generated from any batch."}

    if len(batch_runbooks) == 1:
        final_runbook = batch_runbooks[0]
    else:
        logger.info(f"Merging {len(batch_runbooks)} batch runbooks...")
        merge_contents = [types.Part.from_text(text=MERGE_PROMPT)]
        for i, rb in enumerate(batch_runbooks, 1):
            merge_contents.append(types.Part.from_text(text=f"\n\n--- BATCH {i} ---\n\n{rb}"))
        merge_response = client.models.generate_content(model=MODEL, contents=merge_contents)
        final_runbook = (merge_response.text or "").strip()
        logger.info(f"Merge complete: {len(final_runbook)} chars")

    _save_runbook_to_drive(service, final_runbook)

    return {
        "status": "ok",
        "message": f"Runbook generated from {doc_count} files across {len(batches)} batches.",
        "folder": RUNBOOK_FOLDER_NAME,
        "file": RUNBOOK_FILENAME,
    }


def update_runbook(new_docs: list) -> dict:
    """Incrementally update the runbook with patterns from new docs only."""
    if not new_docs:
        return {"status": "ok", "message": "No new docs to update runbook with."}

    existing_runbook = fetch_runbook()
    if not existing_runbook:
        return {"status": "skip", "message": "No existing runbook found. Run generate_runbook first."}

    service = _get_drive_service()
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    contents = [types.Part.from_text(text=UPDATE_PROMPT.format(existing_runbook=existing_runbook))]
    added = 0
    for filename, file_bytes in new_docs:
        part = _to_gemini_part(filename, file_bytes)
        if part:
            contents.append(part)
            added += 1
            logger.info(f"  Added to update: {filename}")

    if added == 0:
        return {"status": "skip", "message": "New docs could not be parsed (unsupported format)."}

    contents.append(types.Part.from_text(text=UPDATE_MERGE_PROMPT))

    logger.info(f"Calling Gemini for incremental update with {added} new docs...")
    response = client.models.generate_content(model=MODEL, contents=contents)
    additions = (response.text or "").strip()

    if not additions or "NO NEW PATTERNS FOUND" in additions:
        return {"status": "ok", "message": "Runbook already covers all patterns. No update needed."}

    _append_to_runbook_drive(service, additions)

    return {
        "status": "ok",
        "message": f"Runbook appended with patterns from {added} new doc(s).",
        "additions": additions,
    }
