# Legal Watcher — System Flow

Watches `legal-watcher@verse.in` for vendor emails with attachments. Validates each document against a legal runbook using Gemini AI, uploads to Google Drive (Verse Legal Contracts Explorer), and labels the email accordingly. Runs daily at 9 AM IST via Cloud Scheduler → Cloud Run.

---

## Flow Diagram

```
                        ┌──────────────────────────────────────────────────┐
                        │              VERSE LEGAL CONTRACTS EXPLORER        │
                        │                  (Shared Google Drive)             │
                        └──────────────────────────────────────────────────┘
                                              │
                  ┌───────────────────────────┼───────────────────────────┐
                  │                           │                           │
                  ▼                           ▼                           ▼
     ┌────────────────────┐     ┌─────────────────────┐     ┌────────────────────┐
     │   under-review-docs│     │     runbook/          │     │    valid-docs/     │
     │   (unchecked docs) │     │  validation_runbook   │     │  (accepted docs)   │
     │   + analysis/      │     │       .txt            │     │  + analysis/       │
     └────────────────────┘     └──────────┬────────────┘     └────────────────────┘
                                           │
                          ┌────────────────┴────────────────┐
                          │                                  │
                          ▼                                  ▼
             AUTOMATED — 9 AM IST Cron             MANUAL — Agent Builder
             ─────────────────────────             ──────────────────────
             Cloud Scheduler                       Vertex AI Agent Builder
                  │                                Gemini Enterprise
                  ▼                                         │
             POST /run                                      │
             Cloud Run Service                    Legal team opens agent
             (verse-contracts-explorer)           and uploads vendor contract
                  │                                         │
                  ▼                                         ▼
             Gmail IMAP                           Agent fetches runbook
             legal-watcher@verse.in              from hardcoded legal watcher Drive
             Fetch unprocessed emails             folder ID in instructions
             with attachments                              │
                  │                                        ▼
                  ▼                               Agent reads contract
             Gemini 2.5 Flash                    + validates against
             validates each attachment           validation_runbook.txt
             against runbook                               │
                  │                                        ▼
                  ▼                               Returns structured report:
             ┌────────────┐                       · Document Overview
             │  OUTCOME   │                       · Clause-by-Clause Analysis
             └─────┬──────┘                       · Missing Clauses
                   │                              · Non-Standard Clauses
          ┌────────┴────────┐                     · Suggestions
          │                 │
          ▼                 ▼
       ✅ VALID        ⚠️ REVIEW NEEDED
          │                 │
          ▼                 ▼
   Copy to              Stays in
   valid-docs/          under-review-docs/
   + analysis/          + analysis/
          │                 │
          ▼                 ▼
   Gmail label:        Gmail label:
   uploaded-to-drive   uploaded-to-drive
   valid-vendor        review-vendor
          │
          ▼
   Runbook updated
   incrementally with
   new valid doc patterns
```

---

## How It Works

1. Cloud Scheduler triggers `POST /run` every day at 9 AM IST
2. Script reads all emails in the inbox — skips ones already labelled `uploaded-to-drive`
3. Image attachments (`.png`, `.jpg`, etc.) are uploaded to Drive directly — no validation
4. Each contract attachment is validated against the legal runbook using Gemini 2.5 Flash
5. **VALID** documents → uploaded to `valid-docs/` folder, labelled `valid-vendor`
6. **REVIEW NEEDED** documents → uploaded to `under-review-docs/` folder, labelled `review-vendor`
7. An analysis report (`.txt`) is saved inside an `analysis/` subfolder within the vendor's folder
8. Email is labelled `uploaded-to-drive` and marked unread
9. If new valid docs were found, the runbook is incrementally updated with any new patterns

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — `/run`, `/generate-runbook`, `/health` |
| `gmail_reader.py` | Fetches emails via IMAP + App Password, applies Gmail labels |
| `drive_uploader.py` | Uploads files to Shared Drive with versioned filenames |
| `agent_validator.py` | Validates documents against the runbook using Gemini |
| `runbook_generator.py` | Generates and incrementally updates the validation runbook |
| `service_account.json` | Drive service account key (do not commit) |
| `Dockerfile` | Container definition for Cloud Run |
| `.env` | Local config |

---

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/run` | POST | Process new vendor emails — validate, upload, label |
| `/run?sender=x@y.com` | POST | Process emails from a specific sender only |
| `/generate-runbook` | POST | Generate runbook from scratch using all valid docs in Drive |
| `/health` | GET | Health check |

---

## Drive Connection

| Item | Detail |
|---|---|
| Agent Platform | Vertex AI Agent Builder (Gemini Enterprise) |
| Drive Access | Folder ID hardcoded in agent instructions |
| Runbook Folder ID | `1W1KZT7AF2vj-_2wc9Aj7I0uKd7q66Qv6` |
| under-review-docs ID | `1vy6VIDz_HWmdTESbm-ve_rf8Y7iBW7X7` |
| valid-docs ID | `1y6WmPhTZxVkWlaS_4Je0NHOwlmWbFkuP` |
| Shared Drive | Verse Legal Contracts Explorer |

The Drive Connector in Gemini Enterprise connects only to the signed-in user's personal Google Drive — not to a shared drive. Since `validation_runbook.txt` lives in the **Verse Legal Contracts Explorer shared drive**, the folder ID is embedded directly in the agent instructions. The agent uses its built-in Google Drive tool to fetch the runbook from that exact folder on every request.

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

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for Cloud Run + Cloud Scheduler setup.
