import logging
import os
import re
import threading
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
import uvicorn
from gmail_reader import fetch_new_vendor_emails, mark_email
from drive_uploader import upload_vendor_attachment, upload_to_validated, upload_analysis_txt, DRIVE_VALIDATED_FOLDER_ID
from agent_validator import validate_document
from runbook_generator import generate_runbook, fetch_runbook, update_runbook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

_run_lock = threading.Lock()


def vendor_name_from_email(from_address: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+", from_address)
    return match.group(0) if match else "unknown-vendor"


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".svg"}


def run(sender: str | None = None):
    logger.info("Run started")
    emails = fetch_new_vendor_emails(sender_filter=sender)
    logger.info(f"Emails to process: {len(emails)}")
    if not emails:
        logger.info("No new emails")
        return

    runbook_text = fetch_runbook()
    new_valid_docs_list = []

    for e in emails:
        vendor = vendor_name_from_email(e["from"])
        logger.info(f"Processing email from {vendor} | attachments: {[f for f,_ in e['attachments']]}")
        any_valid = False
        for filename, file_bytes in e["attachments"]:
            ext = os.path.splitext(filename)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                logger.info(f"  Skipping validation for image: {filename} — uploading to Drive directly")
                upload_vendor_attachment(vendor, filename, file_bytes)
                continue

            logger.info(f"  Validating: {filename}")
            if runbook_text:
                validation = validate_document(filename, file_bytes, runbook_text)
            else:
                validation = {"status": "REVIEW NEEDED", "details": "No runbook found. Run /generate-runbook first."}

            is_valid = validation["status"] == "VALID"
            logger.info(f"  Result: {validation['status']} — {filename}")
            if is_valid:
                any_valid = True
                upload_to_validated(vendor, filename, file_bytes)
                upload_analysis_txt(vendor, filename, validation["details"], DRIVE_VALIDATED_FOLDER_ID)
                new_valid_docs_list.append((filename, file_bytes))
            else:
                upload_vendor_attachment(vendor, filename, file_bytes)
                upload_analysis_txt(vendor, filename, validation["details"])

        logger.info(f"  Marking email — valid: {any_valid}")
        mark_email(e["num"], any_valid)

    if new_valid_docs_list:
        logger.info(f"Updating runbook with {len(new_valid_docs_list)} valid docs")
        update_runbook(new_valid_docs_list)
    logger.info("Run complete")


@app.post("/run")
def trigger(sender: str = Query(default=None)):
    if not _run_lock.acquire(blocking=False):
        return JSONResponse(content={"status": "ok", "message": "Run already in progress"}, status_code=200)

    def background():
        try:
            run(sender=sender)
        finally:
            _run_lock.release()

    threading.Thread(target=background, daemon=False).start()
    return JSONResponse(content={"status": "ok", "message": "Processing started"}, status_code=202)


@app.post("/generate-runbook")
def trigger_generate_runbook():
    result = generate_runbook()
    return JSONResponse(content=result, status_code=200)


@app.get("/health")
def health():
    return JSONResponse(content={"status": "ok"}, status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
