import io
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL = "gemini-2.5-flash"


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


def validate_document(filename: str, file_bytes: bytes, runbook_text: str) -> dict:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    prompt = f"""
You are a legal document validator for Verse Innovation Private Ltd.

Below is the validation runbook — policies, required clauses, and standard terms extracted from all previously accepted vendor contracts at Verse:

--- RUNBOOK START ---
{runbook_text}
--- RUNBOOK END ---

Analyze the attached vendor document against this runbook.
Respond in clean plain text only — NO markdown, NO asterisks, NO pipe tables, NO symbols.
Use the exact structure below:

================================================
VENDOR DOCUMENT VALIDATION REPORT
================================================

DOCUMENT TYPE   : <NDA / MSA / SOW / Purchase Order / Service Agreement / Other>
RESULT          : VALID / REVIEW NEEDED
FILENAME        : {filename}

------------------------------------------------
DOCUMENT OVERVIEW
------------------------------------------------
IMPORTANT: This section is REQUIRED. Do not skip it.
Write a clear, detailed paragraph that anyone can read and immediately understand
what this document is about -- even with no prior context. Cover all of the following:

- Who are the parties? (full names, roles -- who is Verse, who is the vendor)
- What is this agreement for? (purpose of the engagement in plain language)
- What exactly will the vendor do? (specific services or deliverables)
- How long is the agreement? (start date, end date, renewal terms)
- How does payment work? (amount or structure, when paid, conditions, currency)
- What are the key obligations on each side?
- Any important restrictions, conditions, or context a reader should know about

------------------------------------------------
SUMMARY
------------------------------------------------
<2-3 sentences on overall assessment against Verse standards>

------------------------------------------------
CLAUSE-BY-CLAUSE ANALYSIS
------------------------------------------------
For each key clause write a block like this:

CLAUSE          : <clause name>
VERSE STANDARD  : <what Verse expects>
THIS DOCUMENT   : <what this doc says>
STATUS          : VALID / REVIEW NEEDED / RED FLAG

(Repeat for each clause: Payment Terms, IP Ownership, Governing Law, Liability Cap,
Indemnification, Confidentiality, Termination, Compliance, Signatures, etc.)

------------------------------------------------
MISSING CLAUSES
------------------------------------------------
List each missing clause and why it matters to Verse.
If none, write: None

------------------------------------------------
NON-STANDARD / RISKY CLAUSES
------------------------------------------------
List each risky clause and what Verse normally expects instead.
If none, write: None

------------------------------------------------
SUGGESTIONS
------------------------------------------------
For each issue, write:

ISSUE           : <clause name>
VERSE FOLLOWS   : <Verse standard>
THIS DOC SAYS   : <what this doc has>
RECOMMENDED FIX : <exact change needed>

================================================

Rules:
- VALID: All required legal clauses are present. Unfilled admin fields (execution date, email, bank details, signatures) and missing optional clauses (non-solicitation, arbitration, anti-bribery) do NOT make a document REVIEW NEEDED -- always add them to the SUGGESTIONS section with a recommended fix.
- REVIEW NEEDED: One or more of the following -- missing critical legal clause (termination right, scope of services, governing law, indemnification), vendor explicitly retains IP for deliverables created for Verse, governing law is not Indian law, legal clause placeholders left blank (e.g., jurisdiction is [blank], liability cap is [blank], party name is [blank]).

IMPORTANT: Unfilled admin fields (execution date, email, bank details, signatures) and missing optional clauses MUST appear in SUGGESTIONS with a recommended fix -- never use them to justify REVIEW NEEDED.
"""

    doc_part = _to_gemini_part(filename, file_bytes)
    contents = [prompt]
    if doc_part:
        contents.append(doc_part)
    response = client.models.generate_content(model=MODEL, contents=contents)
    text = (response.text or "").strip()

    status = "REVIEW NEEDED"
    if "RESULT          : VALID" in text:
        status = "VALID"

    return {"status": status, "details": text}
