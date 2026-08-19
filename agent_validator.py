import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
MODEL = "gemini-2.5-flash"

MIME_MAP = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


def validate_document(filename: str, file_bytes: bytes, runbook_text: str) -> dict:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    ext = os.path.splitext(filename)[1].lower()
    mime_type = MIME_MAP.get(ext, "application/octet-stream")

    prompt = f"""
You are a legal document validator for Verse Innovation Private Ltd.

Below is the validation runbook — policies, required clauses, and patterns extracted from all previously accepted vendor contracts:

--- RUNBOOK START ---
{runbook_text}
--- RUNBOOK END ---

Analyze the attached vendor document against this runbook and respond in exactly this format:

Document Type: <NDA | MSA | SOW | Purchase Order | Service Agreement | Other>
Result: VALID | REVIEW NEEDED | ESCALATE
Reason: <one sentence>
Missing Clauses: <comma-separated list, or None>
Non-Standard Clauses: <comma-separated list, or None>

Rules:
- VALID: matches runbook requirements, all standard clauses present, no red flags
- REVIEW NEEDED: minor gaps or unusual terms compared to runbook, needs human check
- ESCALATE: major deviations from runbook, missing critical clauses, or high-risk content
"""

    contents = [prompt, types.Part.from_bytes(data=file_bytes, mime_type=mime_type)]
    response = client.models.generate_content(model=MODEL, contents=contents)
    text = response.text.strip()

    status = "REVIEW NEEDED"
    if "Result: VALID" in text:
        status = "VALID"
    elif "Result: ESCALATE" in text:
        status = "ESCALATE"

    return {"status": status, "details": text}
