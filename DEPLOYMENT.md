# Vendor Doc Intake — Deployment Guide

## Infrastructure Details

| Resource | Value |
|---|---|
| GCP Project | `gemini-project-n1` |
| Region | `asia-south1` (Mumbai) |
| Cloud Run Service | `vendor-doc-intake` |
| Service URL | `https://vendor-doc-intake-852267154002.asia-south1.run.app` |
| Cloud Scheduler Job | `vendor-doc-intake-scheduler` |
| Scheduler Frequency | Every 12 hours (`0 */12 * * *`) |
| Gmail Account | `temp_wohlig.praveen@verse.in` (IMAP + App Password) |
| Drive Folder ID | `0AGnLnp0RVgZhUk9PVA` (Shared Drive) |
| Drive Service Account | `vamsitest-vendor-gmail-drive-i@wohlig.iam.gserviceaccount.com` |

---

## Secrets in Secret Manager

| Secret Name | Description |
|---|---|
| `gmail-app-password` | 16-char Gmail App Password for `temp_wohlig.praveen@verse.in` |
| `drive-service-account-json` | Contents of `service_account.json` for Drive access |

---

## Environment Variables (Cloud Run)

| Variable | Value |
|---|---|
| `GMAIL_ADDRESS` | `temp_wohlig.praveen@verse.in` |
| `DRIVE_ROOT_FOLDER_ID` | `0AGnLnp0RVgZhUk9PVA` |
| `GMAIL_APP_PASSWORD` | From Secret Manager → `gmail-app-password` |
| `SERVICE_ACCOUNT_JSON` | From Secret Manager → `drive-service-account-json` |

---

## Redeployment (when code changes)

Run from the project directory:

```bash
gcloud config set project gemini-project-n1
gcloud config set account temp_wohlig.praveen@verse.in

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
Every 12 hours
  Cloud Scheduler (vendor-doc-intake-scheduler)
    → POST https://vendor-doc-intake-852267154002.asia-south1.run.app/run
        → Cloud Run Service reads ALL emails in Gmail inbox via IMAP
        → skips emails already labelled "contractsexplorer-processed-doc"
        → for new emails with attachments → uploads to Shared Drive (organized by sender folder)
        → adds label "contractsexplorer-processed-doc" to processed emails
        → marks processed emails as unread
        → returns JSON response
```

---

## Manual Trigger

To run immediately without waiting for the scheduler:

```bash
# Via Cloud Scheduler UI → Force run
# Or via curl (requires auth):
gcloud auth print-identity-token | xargs -I{} curl -X POST \
  -H "Authorization: Bearer {}" \
  https://vendor-doc-intake-852267154002.asia-south1.run.app/run
```

---

## Cost Estimate

| Service | Cost |
|---|---|
| Cloud Run Service | ~free (scales to zero, billed per request) |
| Cloud Scheduler | Free (first 3 jobs/month free) |
| Container storage | ~free for low usage |
| Secret Manager | Free for low usage |
| Gmail API (IMAP) | Free |
| Drive API | Free |
