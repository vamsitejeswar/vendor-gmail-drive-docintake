# Vendor Document Intake

Watches `legal-watcher@verse.in` for vendor emails with attachments. Validates each document against a legal runbook using Gemini AI, uploads to Google Drive (Verse Legal Contracts Explorer), and labels the email accordingly. Runs daily at 9 AM IST via Cloud Scheduler → Cloud Run.

## How it works

1. Cloud Scheduler triggers `POST /run` every day at 9 AM IST
2. Script reads all emails in the inbox — skips ones already labelled `uploaded-to-drive`
3. Each attachment is validated against the legal runbook using Gemini 2.5 Flash
4. **VALID** documents → uploaded to `valid-docs/` folder, labelled `valid-vendor`
5. **REVIEW NEEDED** documents → uploaded to `under-review-docs/` folder, labelled `review-vendor`
6. An analysis report (`.txt`) is saved inside an `analysis/` subfolder within the vendor's folder
7. Email is labelled `uploaded-to-drive` and marked unread
8. If new valid docs were found, the runbook is incrementally updated with any new patterns

## Architecture

```
Cloud Scheduler (0 9 * * * — daily 9 AM IST)
    → POST /run
        → Gmail IMAP — reads all emails, skips labelled ones
        → Gemini 2.5 Flash — validates each document against the runbook
        → Google Drive (Verse Legal Contracts Explorer)
            ├── valid-docs/         ← VALID documents, by vendor
            ├── under-review-docs/  ← REVIEW NEEDED documents, by vendor
            │     └── <vendor>/analysis/  ← analysis .txt files
            └── runbook/            ← validation_runbook.txt (auto-updated)
        → Gmail labels: uploaded-to-drive, valid-vendor / review-vendor
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app — `/run`, `/generate-runbook`, `/health` |
| `gmail_reader.py` | Fetches emails via IMAP + App Password, applies Gmail labels |
| `drive_uploader.py` | Uploads files to Shared Drive with versioned filenames |
| `agent_validator.py` | Validates documents against the runbook using Gemini |
| `runbook_generator.py` | Generates and incrementally updates the validation runbook |
| `service_account.json` | Drive service account key (do not commit) |
| `Dockerfile` | Container definition for Cloud Run |
| `.env` | Local config |

---

## One-Time Setup

### Step 1 — Enable Gmail IMAP

1. Open Gmail → **Settings** → **See all settings**
2. Go to **Forwarding and POP/IMAP** tab
3. Under **IMAP access** → **Enable IMAP** → **Save Changes**

### Step 2 — Create Gmail App Password

1. Go to **myaccount.google.com** → **Security** → **2-Step Verification**
2. Scroll to **App passwords** → generate one for Mail
3. Use this as `GMAIL_APP_PASSWORD`

### Step 3 — Create Drive Folders

Create a Shared Drive named **Verse Legal Contracts Explorer** with three subfolders:
- `under-review-docs`
- `valid-docs`
- `runbook`

Copy each folder ID from the URL and set them in `.env`.

### Step 4 — Add Service Account to Shared Drive

1. GCP Console → IAM & Admin → Service Accounts → copy service account email
2. Open Shared Drive → **Manage members** → add service account as **Content Manager**

---

## Local Setup

```bash
pip install -r requirements.txt
```

Configure `.env`:
```
GMAIL_ADDRESS=legal-watcher@verse.in
GMAIL_APP_PASSWORD=<app password>

DRIVE_ROOT_FOLDER_ID=<Shared Drive root ID>
DRIVE_INCOMING_FOLDER_ID=<under-review-docs folder ID>
DRIVE_VALIDATED_FOLDER_ID=<valid-docs folder ID>
DRIVE_RUNBOOK_FOLDER_ID=<runbook folder ID>

GCP_PROJECT=gemini-project-n1
GCP_LOCATION=us-central1
SERVICE_ACCOUNT_FILE=service_account.json
```

Run locally:
```bash
python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
```

Trigger manually:
```bash
curl -X POST http://localhost:8080/run
```

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/run` | POST | Process new vendor emails — validate, upload, label |
| `/run?sender=x@y.com` | POST | Process emails from a specific sender only |
| `/generate-runbook` | POST | Generate runbook from scratch using all valid docs in Drive |
| `/health` | GET | Health check |

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Cloud Run + Cloud Scheduler setup.

---

## Example output

```json
{
  "status": "ok",
  "processed": 3,
  "runbook_updated": true,
  "uploads": [
    {
      "vendor": "contracts@bmeg.in",
      "filename": "NDA_BMEG_2026.pdf",
      "action": "created",
      "validation": "VALID",
      "validation_details": "..."
    },
    {
      "vendor": "vendor@example.com",
      "filename": "MSA_v2.docx",
      "action": "versioned",
      "validation": "REVIEW NEEDED",
      "validation_details": "..."
    }
  ]
}
```
