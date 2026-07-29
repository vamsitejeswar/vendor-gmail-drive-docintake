# Vendor Doc Intake — Deployment Guide

## Service Account Details

| Field | Value |
|---|---|
| Name | `vendor-gmail-drive-intake` |
| Email | `vendor-gmail-drive-intake@wohlig.iam.gserviceaccount.com` |
| Client ID | `100475576110807005072` |
| GCP Project | `wohlig` |

---

## Prerequisites Checklist

Before deploying, complete all of these:

- [ ] Download `service_account.json` from GCP Console → IAM & Admin → Service Accounts → vendor-gmail-drive-intake → **Keys tab → Add Key → JSON**
- [ ] Enable Domain-Wide Delegation on the service account (Details tab → Advanced settings → check the box)
- [ ] Authorize in Google Workspace Admin Console:
  - Go to admin.google.com → Security → Access and data control → API controls → **Manage Domain Wide Delegation**
  - Add new entry:
    - **Client ID**: `100475576110807005072`
    - **Scopes**: `https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/drive`
- [ ] Share the Drive root folder with `vendor-gmail-drive-intake@wohlig.iam.gserviceaccount.com` as **Editor**
- [ ] Update code (`gmail_reader.py`, `drive_uploader.py`) to use service account instead of OAuth

---

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `GMAIL_ADDRESS` | The inbox to read (impersonated user) | `vamsi.padmaraju@wohlig.com` |
| `DRIVE_ROOT_FOLDER_ID` | Google Drive folder ID for uploads | `1AbCdEfGhIjKlMnOpQrStUvWx` |
| `VENDOR_SENDER_WHITELIST` | Comma-separated allowed sender domains | `vendor1.com,vendor2.com` |
| `SERVICE_ACCOUNT_JSON` | Contents of service_account.json (stored as secret) | *(from Secret Manager)* |

---

## Deployment Steps (Google Cloud Console UI)

### Step 1 — Enable APIs

In GCP Console → **APIs & Services → Library**, enable:
- Gmail API
- Google Drive API
- Cloud Run API
- Cloud Scheduler API
- Secret Manager API
- Artifact Registry API

---

### Step 2 — Store Secret

1. Go to **Secret Manager** → **Create Secret**
2. Name: `service-account-json`
3. Upload your `service_account.json` file
4. Click **Create Secret**

---

### Step 3 — Build & Push Docker Image

Run this once from the project directory (only step that needs a terminal):

```bash
gcloud config set project wohlig

gcloud artifacts repositories create vendor-intake \
  --repository-format=docker \
  --location=asia-south1

gcloud builds submit --tag asia-south1-docker.pkg.dev/wohlig/vendor-intake/vendor-doc-intake:latest
```

---

### Step 4 — Create Cloud Run Job (UI)

1. Go to **Cloud Run** → **Jobs** tab → **Create Job**
2. Set:
   - **Container image URL**: `asia-south1-docker.pkg.dev/wohlig/vendor-intake/vendor-doc-intake:latest`
   - **Job name**: `vendor-doc-intake`
   - **Region**: `asia-south1` (Mumbai)
3. Expand **Container, variables & secrets**:
   - Add environment variables:
     - `GMAIL_ADDRESS` = `vamsi.padmaraju@wohlig.com`
     - `DRIVE_ROOT_FOLDER_ID` = your folder ID
     - `VENDOR_SENDER_WHITELIST` = your vendor domains
   - Add secret:
     - Secret: `service-account-json` → expose as env var `SERVICE_ACCOUNT_JSON`
4. Click **Create**
5. Click **Execute** to test manually

---

### Step 5 — Create Cloud Scheduler (UI)

1. Go to **Cloud Scheduler** → **Create Job**
2. Set:
   - **Name**: `vendor-doc-intake-scheduler`
   - **Region**: `asia-south1`
   - **Frequency**: `*/15 * * * *` *(every 15 minutes)*
   - **Timezone**: Asia/Kolkata
3. **Target type**: HTTP
4. **URL**:
   ```
   https://asia-south1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/wohlig/jobs/vendor-doc-intake:run
   ```
5. **HTTP method**: POST
6. **Auth header**: OAuth token → service account: `vendor-gmail-drive-intake@wohlig.iam.gserviceaccount.com`
7. Click **Create**

---

## How It Works

```
Every 15 minutes
  Cloud Scheduler
    → triggers Cloud Run Job via HTTP POST
        → script reads Gmail inbox (vamsi.padmaraju@wohlig.com)
        → finds unread emails with attachments from whitelisted vendors
        → uploads attachments to Google Drive (organized by vendor folder)
        → marks emails as read
        → exits
```

---

## Why Domain-Wide Delegation?

The service account is a robot identity with no Gmail inbox of its own.
Domain-Wide Delegation lets it **impersonate** `vamsi.padmaraju@wohlig.com`
so it can read that inbox server-side without a browser login.

It only reads the single email you specify in `GMAIL_ADDRESS` — not all
users in the org.

---

## Cost

- Service account: **Free**
- Gmail API: **Free**
- Drive API: **Free**
- Cloud Run Job (runs ~5s every 15 min): **< $1/month**
- Cloud Scheduler: **Free** (first 3 jobs/month free)
- Secret Manager: **Free** for low usage
