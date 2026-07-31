# Vendor Document Intake

Watches a Gmail inbox for vendor emails with attachments and automatically uploads them to Google Drive. Runs every 15 minutes via Cloud Scheduler → Cloud Run Service. If the same filename is received again, it saves it as `_v2`, `_v3`, etc. — keeping a clear version trail per vendor.

## How it works

1. Cloud Scheduler triggers `POST /run` every 15 minutes
2. `main.py` checks the inbox for unread emails with attachments (filtered by sender whitelist)
3. Each sender gets their own subfolder in Drive named after their full email address (e.g. `praveen.kumar@wohlig.com`)
4. Attachments are uploaded to that folder — if the filename already exists, it's saved as `_v2`, `_v3`, and so on
5. Processed emails are marked as read so they aren't picked up again

## Architecture

```
Cloud Scheduler (*/15 * * * *)
    → POST /run
        → Cloud Run Service (vendor-doc-intake)
            → Gmail IMAP (temp_wohlig.praveen@verse.in)
            → Google Drive Shared Drive (service account)
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app — exposes `/run` and `/health` endpoints |
| `gmail_reader.py` | Fetches unread emails with attachments via IMAP + App Password |
| `drive_uploader.py` | Uploads attachments to Shared Drive with versioned filenames |
| `service_account.json` | Drive service account key (do not commit) |
| `Dockerfile` | Container definition for Cloud Run |
| `.env` | Local config — email, Drive folder ID, sender whitelist |

---

## One-Time Setup

### Step 1 — Enable Gmail IMAP

The Gmail account used to receive vendor emails must have IMAP enabled.

1. Open Gmail → click **Settings (gear icon)** → **See all settings**
2. Go to the **Forwarding and POP/IMAP** tab
3. Under **IMAP access** → select **Enable IMAP**
4. Click **Save Changes**

---

### Step 2 — Enable 2-Step Verification

App Passwords require 2-Step Verification to be turned on.

1. Go to **myaccount.google.com** → **Security**
2. Under **How you sign in to Google** → click **2-Step Verification**
3. Follow the steps to enable it

---

### Step 3 — Create Gmail App Password

App Password lets the script log in via IMAP without using your real password.

1. Go to **myaccount.google.com** → **Security**
2. Under **How you sign in to Google** → click **2-Step Verification** → scroll to the bottom
3. Click **App passwords**
4. Select app: **Mail** / Select device: **Other** → type a name (e.g. `vendor-intake`)
5. Click **Generate** → copy the 16-character password shown
6. Use this as `GMAIL_APP_PASSWORD` in `.env` or Secret Manager

---

### Step 4 — Create a Google Drive Shared Drive

A Shared Drive is required because service accounts cannot upload to personal My Drive.

1. Open **Google Drive** → left sidebar → click **Shared drives**
2. Click **+ New** at the top
3. Give it a name (e.g. `Vendor Documents`) → click **Create**
4. Open the Shared Drive → copy the folder ID from the URL:
   ```
   drive.google.com/drive/folders/<FOLDER_ID>
   ```
5. Use this as `DRIVE_ROOT_FOLDER_ID` in `.env`

---

### Step 5 — Add Contributors to the Shared Drive

To let team members view/edit the uploaded files:

1. Open the Shared Drive → click the **down arrow (▾)** next to its name → **Manage members**
2. Click **Add members**
3. Enter team member email addresses
4. Set role to **Contributor** (can upload/edit) or **Viewer** (read-only)
5. Click **Send**

---

### Step 6 — Add Service Account to the Shared Drive

The service account needs access to upload files to the Shared Drive.

1. Go to **GCP Console** → **IAM & Admin** → **Service Accounts**
2. Find your service account → copy its email (e.g. `vamsitest-vendor-gmail-drive-i@wohlig.iam.gserviceaccount.com`)
3. Open **Google Drive** → open the Shared Drive → click **▾** → **Manage members**
4. Click **Add members** → paste the service account email
5. Set role to **Contributor**
6. Click **Send**

---

## Local Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `.env`
```
GMAIL_ADDRESS=temp_wohlig.praveen@verse.in
GMAIL_APP_PASSWORD=<16-char app password from Step 3>

DRIVE_ROOT_FOLDER_ID=<Shared Drive folder ID from Step 4>

VENDOR_SENDER_WHITELIST=vendor@example.com,another@example.com

SERVICE_ACCOUNT_FILE=service_account.json
```

### 3. Run locally
```bash
python main.py
```

Server starts on `http://localhost:8080`. Trigger manually:
```bash
curl -X POST http://localhost:8080/run
```

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/run` | POST | Process unread vendor emails |
| `/health` | GET | Health check |

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for full Cloud Run + Cloud Scheduler setup.

---

## Example output

```json
{
  "status": "ok",
  "processed": 1,
  "uploads": [
    {
      "vendor": "praveen.kumar@wohlig.com",
      "filename": "Contract_Q3.pdf",
      "action": "created"
    }
  ]
}
```

If the same file comes in again:
```json
{ "action": "versioned", "filename": "Contract_Q3_v2.pdf" }
```
