import os
import re
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
from gmail_reader import fetch_new_vendor_emails, mark_as_processed, mark_as_valid_vendor, mark_as_review_vendor
from drive_uploader import upload_vendor_attachment, upload_to_validated, upload_analysis_txt, DRIVE_VALIDATED_FOLDER_ID
from agent_validator import validate_document
from runbook_generator import generate_runbook, fetch_runbook

app = FastAPI()


def vendor_name_from_email(from_address: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+", from_address)
    return match.group(0) if match else "unknown-vendor"


def run():
    emails = fetch_new_vendor_emails()
    if not emails:
        return {"status": "ok", "message": "No new vendor emails with attachments found.", "processed": 0}

    runbook_text = fetch_runbook()

    results = []
    for e in emails:
        vendor = vendor_name_from_email(e["from"])
        for filename, file_bytes in e["attachments"]:
            result = upload_vendor_attachment(vendor, filename, file_bytes)

            if runbook_text:
                validation = validate_document(filename, file_bytes, runbook_text)
            else:
                validation = {"status": "REVIEW NEEDED", "details": "No runbook found. Run /generate-runbook first."}

            upload_analysis_txt(vendor, filename, validation["details"])

            if validation["status"] == "VALID":
                mark_as_valid_vendor(e["mail"], e["num"])
                upload_to_validated(vendor, filename, file_bytes)
                upload_analysis_txt(vendor, filename, validation["details"], DRIVE_VALIDATED_FOLDER_ID)
            else:
                mark_as_review_vendor(e["mail"], e["num"])

            results.append({
                "vendor": vendor,
                "filename": result["filename"],
                "action": result["action"],
                "validation": validation["status"],
                "validation_details": validation["details"],
            })

        mark_as_processed(e["mail"], e["num"])

    return {"status": "ok", "processed": len(emails), "uploads": results}


@app.post("/run")
def trigger():
    result = run()
    return JSONResponse(content=result, status_code=200)


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
