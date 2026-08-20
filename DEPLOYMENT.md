# Vendor Doc Intake — Deployment Guide

## Infrastructure Details

| Resource | Value |
|---|---|
| GCP Project | `gemini-project-n1` |
| Region | `asia-south1` (Mumbai) |
| Cloud Run Service | `vendor-doc-intake` |
| Service URL | `https://vendor-doc-intake-852267154002.asia-south1.run.app` |
| Cloud Scheduler Job | `vendor-doc-intake-scheduler` |
| Scheduler Frequency | Every day at 9 AM IST (`0 9 * * *`) |
| Scheduler Timeout | 60s (returns 202 immediately, processes in background) |
| Gmail Account | `legal-watcher@verse.in` |
| Drive | Verse Legal Contracts Explorer (Shared Drive) |
| Drive Root ID | `0ABX-6SqT0zlrUk9PVA` |
| Drive Service Account | `vendor-email-drive-doc@gemini-project-n1.iam.gserviceaccount.com` |
| Gemini Model | `gemini-2.5-flash` (Vertex AI, `us-central1`) |

---

## Drive Folder IDs

| Folder | ID |
|---|---|
| Root (Shared Drive) | `0ABX-6SqT0zlrUk9PVA` |
| `under-review-docs` | `1vy6VIDz_HWmdTESbm-ve_rf8Y7iBW7X7` |
| `valid-docs` | `1y6WmPhTZxVkWlaS_4Je0NHOwlmWbFkuP` |
| `runbook` | `1W1KZT7AF2vj-_2wc9Aj7I0uKd7q66Qv6` |

---

## Secrets in Secret Manager

| Secret Name | Description |
|---|---|
| `gmail-app-password` | Gmail App Password for `legal-watcher@verse.in` |
| `drive-service-account-json` | Contents of `service_account.json` |

---

## Environment Variables (Cloud Run)

| Variable | Value |
|---|---|
| `GMAIL_ADDRESS` | `legal-watcher@verse.in` |
| `GMAIL_APP_PASSWORD` | From Secret Manager → `gmail-app-password` |
| `DRIVE_ROOT_FOLDER_ID` | `0ABX-6SqT0zlrUk9PVA` |
| `DRIVE_INCOMING_FOLDER_ID` | `1vy6VIDz_HWmdTESbm-ve_rf8Y7iBW7X7` |
| `DRIVE_VALIDATED_FOLDER_ID` | `1y6WmPhTZxVkWlaS_4Je0NHOwlmWbFkuP` |
| `DRIVE_RUNBOOK_FOLDER_ID` | `1W1KZT7AF2vj-_2wc9Aj7I0uKd7q66Qv6` |
| `GCP_PROJECT` | `gemini-project-n1` |
| `GCP_LOCATION` | `us-central1` |
| `SERVICE_ACCOUNT_JSON` | From Secret Manager → `drive-service-account-json` |

---

## Redeployment (when code changes)

```bash
gcloud config set project gemini-project-n1
gcloud config set account vamsi.padmaraju@wohlig.com

gcloud builds submit \
  --tag asia-south1-docker.pkg.dev/gemini-project-n1/vendor-intake/vendor-doc-intake:latest \
  --region=asia-south1

gcloud run deploy vendor-doc-intake \
  --image asia-south1-docker.pkg.dev/gemini-project-n1/vendor-intake/vendor-doc-intake:latest \
  --region asia-south1
```

---

## How It Works

```
Every day at 9 AM IST
  Cloud Scheduler → POST /run → Cloud Run
      → Gmail IMAP: fetch all unprocessed emails with attachments
      → Gemini 2.5 Flash: validate each doc against validation_runbook.txt
      → VALID → upload to valid-docs/<vendor>/ + analysis subfolder
      → REVIEW NEEDED → upload to under-review-docs/<vendor>/ + analysis subfolder
      → Gmail: label uploaded-to-drive + valid-vendor / review-vendor
      → If any new valid docs: incrementally update runbook
```

---

## Manual Trigger

```bash
gcloud auth print-identity-token | xargs -I{} curl -X POST \
  -H "Authorization: Bearer {}" \
  https://vendor-doc-intake-852267154002.asia-south1.run.app/run
```

---

## Cost Estimate

| Service | Cost |
|---|---|
| Cloud Run | ~free (scales to zero, billed per request) |
| Cloud Scheduler | Free (first 3 jobs/month) |
| Vertex AI (Gemini) | ~$0.075 per 1M input tokens (Flash) |
| Secret Manager | Free for low usage |
| Gmail IMAP | Free |
| Drive API | Free |
