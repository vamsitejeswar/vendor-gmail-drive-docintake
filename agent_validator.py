import io
import os
import logging

from dotenv import load_dotenv
load_dotenv()

# ── StreamAssist (commented out — service account lacks GE license) ────────────
# from google.cloud import discoveryengine_v1beta as discoveryengine
#
# ENGINE_ID    = os.getenv("DISCOVERY_ENGINE_ID", "gemini-enterprise-legal-app")
# ASSISTANT_ID = os.getenv("DISCOVERY_ASSISTANT_ID", "default_assistant")
# AGENT_ID     = "2431253715885581897"  # Legal Watcher Contracts Analysis Agent
# PROJECT_NUM  = "852267154002"
#
# def _assistant_name():
#     return (
#         f"projects/{PROJECT_NUM}/locations/global"
#         f"/collections/default_collection"
#         f"/engines/{ENGINE_ID}/assistants/{ASSISTANT_ID}"
#     )
#
# def _stream_assist(prompt):
#     client = discoveryengine.AssistantServiceClient()
#     request = discoveryengine.StreamAssistRequest(
#         name=_assistant_name(),
#         query=discoveryengine.Query(text=prompt),
#     )
#     full_text = ""
#     for chunk in client.stream_assist(request=request):
#         try:
#             for reply in chunk.answer.replies:
#                 text = reply.grounded_content.content.text
#                 if text:
#                     full_text += text
#         except Exception as e:
#             pass
#     return full_text.strip()

# ── Reverted to Vertex AI (Gemini 2.5 Flash) ──────────────────────────────────

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
LOCATION   = os.getenv("GCP_LOCATION", "us-central1")
MODEL      = "gemini-2.5-flash"

AGENT_INSTRUCTIONS_PATH = os.path.join(os.path.dirname(__file__), "agent_instructions.md")


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


def _load_agent_instructions() -> str:
    if os.path.exists(AGENT_INSTRUCTIONS_PATH):
        with open(AGENT_INSTRUCTIONS_PATH, encoding="utf-8") as f:
            return f.read()
    return ""


def validate_document(filename: str, file_bytes: bytes, runbook_text: str = "") -> dict:
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    instructions = _load_agent_instructions()
    prompt = f"""{instructions}

---

## Runbook Reference

{runbook_text}

---

**Filename:** {filename}

Produce the complete Verse Innovation Vendor Contract Analysis Report now in the exact format defined above.
"""

    doc_part = _to_gemini_part(filename, file_bytes)
    contents = [prompt]
    if doc_part:
        contents.append(doc_part)

    response = client.models.generate_content(model=MODEL, contents=contents)
    text = (response.text or "").strip()

    status = "REVIEW NEEDED" if "REVIEW NEEDED" in text else "VALID"
    return {"status": status, "details": text}
