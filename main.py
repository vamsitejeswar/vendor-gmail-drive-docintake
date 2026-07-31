import os
import re
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
from gmail_reader import fetch_new_vendor_emails, mark_as_processed
from drive_uploader import upload_vendor_attachment

app = FastAPI()


def vendor_name_from_email(from_address: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+", from_address)
    return match.group(0) if match else "unknown-vendor"


def run():
    emails = fetch_new_vendor_emails()

    if not emails:
        return {"status": "ok", "message": "No new vendor emails with attachments found.", "processed": 0}

    results = []
    for e in emails:
        vendor = vendor_name_from_email(e["from"])
        for filename, file_bytes in e["attachments"]:
            result = upload_vendor_attachment(vendor, filename, file_bytes)
            results.append({"vendor": vendor, "filename": result["filename"], "action": result["action"]})
        mark_as_processed(e["mail"], e["num"])

    return {"status": "ok", "processed": len(emails), "uploads": results}


@app.post("/run")
def trigger():
    result = run()
    return JSONResponse(content=result, status_code=200)


@app.get("/health")
def health():
    return JSONResponse(content={"status": "ok"}, status_code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
