# Vendor Document Intake

Watches a Gmail inbox for vendor emails with attachments and automatically uploads them to Google Drive. If the same filename is received again, it saves it as `_v2`, `_v3`, etc. — keeping a clear version trail per vendor.

## How it works

1. `main.py` checks the inbox for unread emails with attachments (filtered by sender whitelist)
2. Each sender gets their own subfolder in Drive named after their full email address (e.g. `praveen.kumar@wohlig.com`)
3. Attachments are uploaded to that folder — if the filename already exists, it's saved as `_v2`, `_v3`, and so on
4. Processed emails are marked as read so they aren't picked up again

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — run this |
| `gmail_reader.py` | Fetches unread emails with attachments via Gmail API (OAuth2) |
| `drive_uploader.py` | Uploads attachments to Drive with versioned filenames |
| `credentials.json` | OAuth2 client credentials from GCP Console (do not commit) |
| `token.json` | Auto-generated after first login (do not commit or delete) |
| `.env` | Your config — email, Drive folder ID, sender whitelist |

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. OAuth2 credentials (`credentials.json`)
1. Go to [GCP Console](https://console.cloud.google.com) → APIs & Services → Library → enable **Gmail API** and **Drive API**
2. APIs & Services → Credentials → **Create Credentials → OAuth 2.0 Client ID**
3. Application type: **Desktop app**
4. Download the JSON → rename to `credentials.json` → place in this folder

### 3. Configure `.env`
```
GMAIL_ADDRESS=you@wohlig.com
GMAIL_CREDENTIALS_FILE=credentials.json

DRIVE_ROOT_FOLDER_ID=<folder ID from Drive URL>

VENDOR_SENDER_WHITELIST=vendor@example.com,another@example.com
```

- `DRIVE_ROOT_FOLDER_ID` — open the target Drive folder, copy the ID from the URL: `drive.google.com/drive/folders/<ID>`
- `VENDOR_SENDER_WHITELIST` — comma-separated sender emails to process; leave blank to accept all

### 4. First run (one-time browser login)
```bash
python main.py
```
A browser window opens → sign in → click **Allow** → `token.json` is saved. All future runs are silent.

## Running

```bash
python main.py
```

Example output:
```
Processing 1 email(s)...

From: Praveen Kumar <praveen.kumar@wohlig.com>  (vendor folder: praveen.kumar@wohlig.com)
Subject: Q3 Contract Update
  -> Created new file: Contract_Q3.pdf
----------------------------------------
```

If the same file comes in again:
```
  -> File exists, saved as: Contract_Q3_v2.pdf
```
