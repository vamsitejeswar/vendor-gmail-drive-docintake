# Legal Watcher — System Flow

Watches `legal-watcher@verse.in` for vendor emails with attachments. Each document is validated against the legal runbook using Gemini 2.5 Flash (Vertex AI), uploaded to Google Drive (Verse Legal Contracts Explorer), turned into a redlined DOCX when it is a contract, and the email is labelled. Runs daily at 9 AM IST via Cloud Scheduler → Cloud Run.

A separate, manual path lets the legal team use Gemini Enterprise agents: one validates an uploaded contract, one returns the link to a redlined contract.

---

## Flow Diagram

```
AUTOMATED — every day, 9 AM IST
────────────────────────────────
Cloud Scheduler ──► POST /run ──► Cloud Run (verse-contracts-explorer)
                                        │
                                        ▼
                               Gmail IMAP — legal-watcher@verse.in
                               unprocessed emails with attachments
                                        │
                      ┌─────────────────┴─────────────────┐
                      ▼                                   ▼
                 image file                         PDF / DOCX / TXT
                 upload to Drive,                          │
                 no validation                             ▼
                                              Gemini 2.5 Flash (Vertex AI)
                                              validates against the runbook
                                              (validation_runbook.txt in GCS)
                                                           │
                                       ┌───────────────────┴───────────────────┐
                                       ▼                                       ▼
                                   ✅ VALID                            ⚠️ REVIEW NEEDED
                                       │                                       │
                                       ▼                                       ▼
                               valid-docs/<vendor>/                under-review-docs/<vendor>/
                                 ├─ original file                      ├─ original file
                                 └─ analysis/                          └─ analysis/
                                     ├─ <name>_analysis.txt                ├─ <name>_analysis.txt
                                     └─ <name>_redlined.docx               └─ <name>_redlined.docx
                                       │                                       │
                                       └───────────────────┬───────────────────┘
                                                           ▼
                                  every uploaded file is shared with the verse.in domain
                                                           │
                                                           ▼
                                  redlined_index.txt rebuilt in GCS (see "Redlined Documents")
                                                           │
                                                           ▼
                                  Gmail labels: uploaded-to-drive + valid-vendor / review-vendor
                                                           │
                                                           ▼
                                  VALID docs only: runbook updated with any new patterns


MANUAL — Gemini Enterprise agents
─────────────────────────────────
Legal Watcher Contracts Analysis Agent   user uploads a contract in chat → agent reads
                                         validation_runbook.txt → structured analysis report
Verse Redlined Docs Finder               user asks for a redlined doc by name → agent returns its link
```

---

## How It Works

1. Cloud Scheduler triggers `POST /run` every day at 9 AM IST (returns 202 at once; work runs in the background).
2. The script reads the inbox and skips emails already labelled `uploaded-to-drive`.
3. Image attachments (`.png`, `.jpg`, etc.) are uploaded to Drive directly — no validation.
4. Every other attachment is validated by Gemini 2.5 Flash using the prompt in `agent_instructions.md` plus the runbook text from GCS.
5. **VALID** → uploaded to `valid-docs/`, email labelled `valid-vendor`. **REVIEW NEEDED** → uploaded to `under-review-docs/`, email labelled `review-vendor`.
6. The analysis report (`<name>_analysis.txt`) is saved in an `analysis/` subfolder of the vendor's folder.
7. For DOCX files, a redlined copy (`<name>_redlined.docx`) is generated and saved in the same `analysis/` folder.
8. Each uploaded file is shared read-only with the `verse.in` domain, so links open for anyone at Verse.
9. After a redlined file is uploaded, `redlined_index.txt` in GCS is rebuilt.
10. The email is labelled `uploaded-to-drive` and marked unread.
11. If any VALID documents were found, the runbook is updated incrementally with their new patterns.

---

## Redlined DOCX

`redline_generator.py` annotates the original contract. It does not change the original wording.

| Source in the analysis report | What is added to the DOCX |
|---|---|
| Section 3 clause with status `REVIEW NEEDED`, found in the document | The clause paragraph gets a **red background**, and a **yellow note** is added directly below it (Verse standard vs. what this document says) |
| Section 3 clause with `REVIEW NEEDED` that the document does not contain or does not address | A yellow note at the end of the document, under a "MISSING CLAUSES — VERSE LEGAL REVIEW" divider |
| Section 4 missing clauses | A yellow note at the end of the document, under the same divider |

Finding the paragraph for a clause, in order: quoted text from the "This Document" line, a clause number mentioned there, then whole-word keywords for that clause type. Headings and titles are never highlighted, and one paragraph is highlighted at most once.

Only `.doc` / `.docx` files are redlined. PDFs and other types get the analysis only.

---

## Redlined Documents (lookup for the agents)

Redlined files live in Drive. To let a Gemini Enterprise agent return a link, the pipeline rebuilds one file in GCS after every redline upload (`refresh_redlined_index()` in `runbook_generator.py`):

| GCS object | Content |
|---|---|
| `redlined_index.txt` | One block per redlined contract: `Redlined contract: <name>` and `The redlined version of the contract <name> is available at this link: <link>` |

The file is rebuilt in full each time, so deleted or renamed redlined files disappear from it. Links are Google Docs links with the `ouid` tracking parameter removed. `verse_redlined_doc_connector` reads this single file.

**Known limitation.** The agent's "Ingestion Search Tool" matches meaning, and it did not return text from inside this small single file during testing. If agent lookups still fail, the fallback is to paste the list of names and links into the Redlined Docs Finder agent's instructions.

---

## Files

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — `/run`, `/generate-runbook`, `/redline`, `/find-redlined`, `/health` |
| `gmail_reader.py` | Fetches emails via IMAP + App Password, applies Gmail labels |
| `drive_uploader.py` | Uploads originals, analysis reports and redlined files to the Shared Drive with versioned filenames, and shares them with `verse.in` |
| `agent_validator.py` | Validates one document with Gemini 2.5 Flash (Vertex AI) using `agent_instructions.md` and the runbook |
| `agent_instructions.md` | The validation prompt and report format used by the pipeline |
| `redline_generator.py` | Builds the redlined DOCX from the analysis report |
| `runbook_generator.py` | Generates and incrementally updates `validation_runbook.txt` in GCS; rebuilds `redlined_index.txt` |
| `new_instruction.md` | Instructions for the Gemini Enterprise agent: the validation report format plus the redlined-document lookup rules |
| `group_email_poller/` | Separate service that archives group-mailbox threads to Drive — see `group_email_poller/FLOW.md` |
| `Dockerfile` | Container for Cloud Run (copies the pipeline modules and `agent_instructions.md`) |
| `service_account.json` | Drive service account key (do not commit) |
| `.env` | Local config (do not commit) |

---

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/run` | POST | Process new vendor emails — validate, upload, redline, label |
| `/run?sender=x@y.com` | POST | Process emails from a specific sender only |
| `/generate-runbook` | POST | Generate the runbook from scratch using all valid docs in Drive |
| `/redline` | POST | Upload a DOCX (multipart `file`); returns the redlined DOCX as a download |
| `/find-redlined?q=<words>` | GET | Search Drive for a redlined file by name keywords; returns its link |
| `/health` | GET | Health check |

---

## Storage

### Google Drive (Verse Legal Contracts Explorer, shared drive)

| Folder | ID |
|---|---|
| Root | `0ABX-6SqT0zlrUk9PVA` |
| `under-review-docs` | `1vy6VIDz_HWmdTESbm-ve_rf8Y7iBW7X7` |
| `valid-docs` | `1y6WmPhTZxVkWlaS_4Je0NHOwlmWbFkuP` |
| `runbook` (Drive copy) | `1W1KZT7AF2vj-_2wc9Aj7I0uKd7q66Qv6` |

### Cloud Storage

| Item | Value |
|---|---|
| Bucket | `verse-contracts-runbook-us` (US multi-region) |
| Override | `GCS_RUNBOOK_BUCKET` env var (default is the bucket above) |
| Objects | `validation_runbook.txt`, `redlined_index.txt` |

The bucket must be in the US multi-region. Gemini Enterprise connectors use a KMS key in region `us`, and an `asia-south1` bucket fails to sync with "Cloud KMS region 'us' not available for use with GCS region 'ASIA_SOUTH1'".

---

## Gemini Enterprise Setup

Project `gemini-project-n1`, app `gemini-enterprise-legal-app`, region `us`.

| Item | Detail |
|---|---|
| `verse_validation_runbook_connector` | Cloud Storage connector → `gs://verse-contracts-runbook-us/validation_runbook.txt` (File, Documents, periodic daily sync) |
| `verse_redlined_doc_connector` | Cloud Storage connector → `gs://verse-contracts-runbook-us/redlined_index.txt` (File, Documents, periodic daily sync) |
| Legal Watcher Contracts Analysis Agent | Uses the validation connector; instructions in `new_instruction.md` |
| Verse Redlined Docs Finder | Uses the redlined connector; returns a redlined document's link |

After a pipeline run, click **Manual Sync** on the connector (or wait for the daily sync) so the agent sees new files.

Permissions the connectors need:
- `service-852267154002@gcp-sa-discoveryengine.iam.gserviceaccount.com` — `Storage Object Viewer` on the bucket
- Both `service-852267154002@gcp-sa-discoveryengine.iam.gserviceaccount.com` and `service-852267154002@gs-project-accounts.iam.gserviceaccount.com` — `Cloud KMS CryptoKey Encrypter/Decrypter` on key `GE_Connectors` (key ring `ge_connectors`, location `us`)

The Gemini Enterprise agents are chat-only. They cannot edit a DOCX or return a modified file, which is why redlining is done by the pipeline and the agent only returns a link.

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

| Resource | Value |
|---|---|
| GCP project | `gemini-project-n1` |
| Region | `asia-south1` |
| Cloud Run service | `verse-contracts-explorer` |
| Service URL | `https://verse-contracts-explorer-852267154002.asia-south1.run.app` |
| Cloud Scheduler job | `verse-contracts-explorer-scheduler`, daily 9 AM IST (`0 9 * * *`), 60 s timeout |
| Drive service account | `vendor-email-drive-doc@gemini-project-n1.iam.gserviceaccount.com` |
| Gemini model | `gemini-2.5-flash` on Vertex AI (`us-central1`) |
| Secrets (Secret Manager) | `gmail-app-password` → `GMAIL_APP_PASSWORD`; `drive-service-account-json` → `SERVICE_ACCOUNT_JSON` |

Cloud Run environment variables: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `DRIVE_ROOT_FOLDER_ID`, `DRIVE_INCOMING_FOLDER_ID`, `DRIVE_VALIDATED_FOLDER_ID`, `DRIVE_RUNBOOK_FOLDER_ID`, `GCP_PROJECT`, `GCP_LOCATION`, `SERVICE_ACCOUNT_JSON`, and optionally `GCS_RUNBOOK_BUCKET`.

Redeploy after a code change:
```bash
gcloud config set project gemini-project-n1
gcloud run deploy verse-contracts-explorer --source . --region asia-south1
```

If a source deploy does not start a new revision, change any environment variable to force one:
```bash
gcloud run services update verse-contracts-explorer --region asia-south1 --update-env-vars DEPLOY_TS=$(date +%s)
```

Trigger a run by hand:
```bash
gcloud auth print-identity-token | xargs -I{} curl -X POST \
  -H "Authorization: Bearer {}" \
  https://verse-contracts-explorer-852267154002.asia-south1.run.app/run
```
