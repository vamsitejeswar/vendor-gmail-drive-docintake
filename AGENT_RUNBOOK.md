# Vendor Document Validation — Runbook

## Flow

```
New vendor email arrives
    → Gmail poller uploads doc to "unchecked-docs" Drive folder
    → marks email as "contractsexplorer-processed-doc" in Gmail

Human reviews the doc + email conversation
    → if valid → manually adds "valid-vendor" label in Gmail
    → manually moves doc to "valid-docs" Drive folder

Agent Builder (when legal team needs to validate a new doc)
    → KB = "valid-docs" folder + email conversations
    → user uploads doc or pastes Drive link
    → agent compares against KB → returns result
```

---

## Part 1 — Drive Setup (One-time)

Create two folders inside the Shared Drive (`0ADa82r0wcOhiUk9PVA`):

| Folder | Purpose |
|---|---|
| `unchecked-docs/` | All new docs uploaded by the Gmail poller |
| `valid-docs/` | Manually validated docs — Agent Builder KB source |

1. Open the Shared Drive
2. Create folder: `unchecked-docs`
3. Create folder: `valid-docs`
4. Copy the folder ID of `unchecked-docs` from the URL

---

## Part 2 — Code Change (One change only)

In `.env`, replace `DRIVE_ROOT_FOLDER_ID` with the `unchecked-docs` folder ID:

```
DRIVE_ROOT_FOLDER_ID=<unchecked-docs folder id>
```

No other code changes needed. The poller already uploads by sender subfolder and marks emails as `contractsexplorer-processed-doc` — it will now upload into `unchecked-docs/` instead of the root.

Redeploy:

```bash
gcloud config set project gemini-project-n1

gcloud builds submit \
  --tag asia-south1-docker.pkg.dev/gemini-project-n1/vendor-intake/vendor-doc-intake:latest \
  --region=asia-south1

gcloud run deploy vendor-doc-intake \
  --image asia-south1-docker.pkg.dev/gemini-project-n1/vendor-intake/vendor-doc-intake:latest \
  --region asia-south1
```

---

## Part 3 — Human Validation Step

After the poller runs:

1. Open Gmail → find emails labelled `contractsexplorer-processed-doc`
2. Open the email → read the conversation thread + open the doc from Drive
3. If the doc is valid:
   - In Gmail → manually add label `valid-vendor` to the email
   - In Drive → move the doc from `unchecked-docs/<vendor>/` to `valid-docs/<vendor>/`
4. If not valid → leave it in `unchecked-docs/`, do not add label

---

## Part 4 — Agent Builder Setup (One-time)

### Step 1 — Create Data Store from valid-docs folder

1. GCP Console → **Agent Builder** → **Data Stores** → **+ Create data store**
2. Source: **Google Drive**
3. Select the `valid-docs` folder
4. Name: `verse-valid-vendor-docs`
5. Click **Create**

### Step 2 — Create Data Store from email conversations

> Agent Builder cannot connect to Gmail directly. To include email conversations in the KB, save the email thread (copy-paste body) as a `.txt` file into a Drive folder called `email-threads/` and add it as a second data store.

1. Create folder `email-threads/` in the Shared Drive
2. For each validated vendor email → save the thread as `<vendor>-thread.txt` in that folder
3. Agent Builder → **Data Stores** → **+ Create data store**
4. Source: **Google Drive** → select `email-threads/` folder
5. Name: `verse-vendor-email-threads`

### Step 3 — Create the Agent

1. Agent Builder → **Apps** → **+ Create app** → select **Agent**
2. Name: `vendor-doc-validator`
3. Region: `us-central1`
4. Add tools:
   - Data store → `verse-valid-vendor-docs`
   - Data store → `verse-vendor-email-threads`

### Step 4 — Set Agent Instructions

```
You are a legal document validator for Verse Innovation Private Ltd.

Your knowledge base contains:
- Previously validated and accepted vendor contracts (valid-docs folder)
- Email conversations from those vendor engagements (email-threads folder)

When the user uploads a document or shares a Google Drive link:
1. Identify the document type (NDA, MSA, SOW, PO, Service Agreement)
2. Check for standard clauses: payment terms, termination, liability cap, IP ownership, confidentiality, governing law
3. Compare against similar validated docs and email conversations in the knowledge base
4. Flag any missing or non-standard clauses

Respond in this format:

Document Type: <type>
Vendor: <name or domain>
Result: VALID | REVIEW NEEDED | ESCALATE
Reason: <one sentence>
Missing Clauses: <list or None>
Non-Standard Clauses: <list or None>
Compared Against: <which KB docs or threads you referenced>
```

---

## Part 5 — Using the Agent

1. Open Agent Builder → `vendor-doc-validator` → **Preview**
2. Upload the new vendor doc or paste the Google Drive link
3. Ask: `Validate this document`
4. Agent searches the KB (valid-docs + email threads) and returns the result

---

## Summary

| Step | What | Who | Where |
|---|---|---|---|
| 1 | Create unchecked-docs and valid-docs folders | Vamsi | Google Drive |
| 2 | Update DRIVE_ROOT_FOLDER_ID in .env to unchecked-docs | Vamsi | Code + Redeploy |
| 3 | Poller auto-uploads new docs to unchecked-docs | Automated | Cloud Run |
| 4 | Human reviews doc + email → moves to valid-docs + adds valid-vendor label | Legal team | Gmail + Drive |
| 5 | Create Agent Builder data stores (valid-docs + email-threads) | Vamsi | GCP Console |
| 6 | Create Agent Builder agent with instructions | Vamsi | GCP Console |
| 7 | Legal team uses agent to validate new incoming docs | Legal team | Agent Builder |






┌─────────────────────────────────────────────────────────┐
│                    RUNBOOK (KB)                          │
│  Generated from valid-docs/ + email conversations        │
│  Stored as a Google Doc in Drive                         │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
AUTOMATED (9 AM cron)      MANUAL (Agent Builder)
        │                         │
New email arrives          Legal team uploads doc
→ upload to unchecked-docs  or pastes Drive link
→ Gemini validates doc      → Agent validates against
  against runbook              runbook
→ if VALID:                 → returns result
    → copy to valid-docs/
    → add valid-vendor label
→ if REVIEW NEEDED/ESCALATE:
    → stays in unchecked-docs/
    → human reviews manually

Two things to implement:

1. /generate-runbook — reads all valid-docs/ + email threnbook → saves to Drive
2. agent_validator.py — cron job calls this → validates doc against the runbook → auto-labels and moves if VALID  