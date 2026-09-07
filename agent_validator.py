import io
import os
import logging

from dotenv import load_dotenv
load_dotenv()

from google.cloud import discoveryengine_v1beta as discoveryengine

logger = logging.getLogger(__name__)

ENGINE_ID    = os.getenv("DISCOVERY_ENGINE_ID", "gemini-enterprise-legal-app")
ASSISTANT_ID = os.getenv("DISCOVERY_ASSISTANT_ID", "default_assistant")
AGENT_ID     = "2431253715885581897"  # Legal Watcher Contracts Analysis Agent
PROJECT_NUM  = "852267154002"

AGENT_INSTRUCTIONS_PATH = os.path.join(os.path.dirname(__file__), "agent_instructions.md")


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_text(filename: str, file_bytes: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        except Exception as e:
            logger.warning(f"PDF extraction failed: {e}")
            return ""
    elif ext in (".doc", ".docx"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            logger.warning(f"DOCX extraction failed: {e}")
            return ""
    elif ext in (".txt", ".md"):
        return file_bytes.decode("utf-8", errors="ignore").strip()
    return ""


def _strip_surrogates(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


# ── StreamAssist ───────────────────────────────────────────────────────────────

def _assistant_name() -> str:
    return (
        f"projects/{PROJECT_NUM}/locations/global"
        f"/collections/default_collection"
        f"/engines/{ENGINE_ID}/assistants/{ASSISTANT_ID}"
    )


def _stream_assist(prompt: str) -> str:
    client = discoveryengine.AssistantServiceClient()
    request = discoveryengine.StreamAssistRequest(
        name=_assistant_name(),
        query=discoveryengine.Query(text=prompt),
    )
    full_text = ""
    for chunk in client.stream_assist(request=request):
        try:
            for reply in chunk.answer.replies:
                text = reply.grounded_content.content.text
                if text:
                    full_text += text
        except Exception as e:
            logger.debug(f"Chunk parse skip: {e}")
    return full_text.strip()


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _load_agent_instructions() -> str:
    if os.path.exists(AGENT_INSTRUCTIONS_PATH):
        with open(AGENT_INSTRUCTIONS_PATH, encoding="utf-8") as f:
            return f.read()
    return (
        "You are a legal document validator for Verse Innovation Private Ltd. "
        "Read validation_runbook.txt from the connected GCS data store and produce "
        "the full Verse Innovation Vendor Contract Analysis Report."
    )


def _build_prompt(filename: str, doc_text: str) -> str:
    instructions = _load_agent_instructions()
    doc_text = _strip_surrogates(doc_text)
    return f"""{instructions}

---

## Document to Validate

**Filename:** {filename}

{doc_text}

---

Produce the complete Verse Innovation Vendor Contract Analysis Report now in the exact format defined above.
Reference validation_runbook.txt from the Legal Contract Analysis Runbook data store for all R-# and S-# codes.
"""


# ── Public API (same signature as before) ─────────────────────────────────────

def validate_document(filename: str, file_bytes: bytes, _runbook_text: str = "") -> dict:
    """Validate a vendor contract via StreamAssist (Legal engine).

    _runbook_text is accepted for backwards compatibility but ignored —
    the engine already has validation_runbook.txt grounded via the GCS data store.
    """
    doc_text = _extract_text(filename, file_bytes)
    if not doc_text:
        return {
            "status": "ERROR",
            "details": f"Could not extract text from {filename}. Supported formats: PDF, DOCX, TXT.",
        }

    prompt = _build_prompt(filename, doc_text)
    result = _stream_assist(prompt)

    if not result:
        return {"status": "ERROR", "details": "StreamAssist returned an empty response."}

    # Detect outcome from the report header table
    if "REVIEW NEEDED" in result:
        status = "REVIEW NEEDED"
    else:
        status = "VALID"

    return {"status": status, "details": result}
