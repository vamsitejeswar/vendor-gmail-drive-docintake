import logging
import os
import re
import threading
from fastapi import FastAPI, Query, UploadFile, File
from fastapi.responses import JSONResponse, StreamingResponse
import io
import uvicorn
from gmail_reader import fetch_new_vendor_emails, mark_email
from drive_uploader import upload_vendor_attachment, upload_to_validated, upload_analysis_txt, upload_redlined_docx, DRIVE_VALIDATED_FOLDER_ID
from agent_validator import validate_document
from runbook_generator import generate_runbook, fetch_runbook, update_runbook, refresh_redlined_index
from redline_generator import generate_redlined_docx

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

            # Generate redlined DOCX for DOCX files regardless of outcome
            redlined = generate_redlined_docx(filename, file_bytes, validation["details"])

            if is_valid:
                any_valid = True
                upload_to_validated(vendor, filename, file_bytes)
                upload_analysis_txt(vendor, filename, validation["details"], DRIVE_VALIDATED_FOLDER_ID)
                if redlined:
                    upload_redlined_docx(vendor, filename, redlined, DRIVE_VALIDATED_FOLDER_ID)
                    logger.info(f"  Redlined DOCX uploaded for: {filename}")
                    refresh_redlined_index()
                new_valid_docs_list.append((filename, file_bytes))
            else:
                upload_vendor_attachment(vendor, filename, file_bytes)
                upload_analysis_txt(vendor, filename, validation["details"])
                if redlined:
                    upload_redlined_docx(vendor, filename, redlined)
                    logger.info(f"  Redlined DOCX uploaded for: {filename}")
                    refresh_redlined_index()

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


@app.post("/redline")
async def redline(file: UploadFile = File(...)):
    filename = file.filename or "document.docx"
    file_bytes = await file.read()

    validation = validate_document(filename, file_bytes)
    if validation["status"] == "ERROR":
        return JSONResponse(content={"error": validation["details"]}, status_code=400)

    redlined = generate_redlined_docx(filename, file_bytes, validation["details"])
    if not redlined:
        return JSONResponse(
            content={"error": "Could not generate redlined DOCX. File may not be a valid DOCX or no annotations were found."},
            status_code=422,
        )

    stem = os.path.splitext(filename)[0]
    download_name = f"{stem}_redlined.docx"
    return StreamingResponse(
        io.BytesIO(redlined),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@app.get("/find-redlined")
def find_redlined(q: str = Query(..., description="Document name or keywords to search for")):
    """Search Drive for a redlined doc by name. Used by the GE agent as a tool."""
    from drive_uploader import _get_drive_service
    try:
        service = _get_drive_service()
        safe_q = q.replace("'", "\\'")
        results = service.files().list(
            q=f"name contains '_redlined' and trashed = false",
            fields="files(id, name, webViewLink)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            orderBy="modifiedTime desc",
            pageSize=50,
        ).execute()
        files = results.get("files", [])
        # Score by keyword overlap with query
        keywords = [w.lower() for w in re.split(r"[\s_\-]+", q) if len(w) > 2]
        scored = []
        for f in files:
            name_lower = f["name"].lower()
            score = sum(1 for kw in keywords if kw in name_lower)
            if score > 0:
                scored.append((score, f))
        scored.sort(key=lambda x: -x[0])
        if scored:
            best = scored[0][1]
            return JSONResponse(content={
                "found": True,
                "filename": best["name"],
                "link": best["webViewLink"],
                "download_link": f"https://drive.google.com/uc?id={best['id']}&export=download",
            })
        return JSONResponse(content={"found": False, "message": "No matching redlined document found."})
    except Exception as e:
        logger.error(f"find-redlined error: {e}")
        return JSONResponse(content={"found": False, "message": str(e)}, status_code=500)


@app.get("/health")
def health():
    return JSONResponse(content={"status": "ok"}, status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
