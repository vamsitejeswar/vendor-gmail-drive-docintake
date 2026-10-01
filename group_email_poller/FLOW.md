# Group Email Poller — System Flow

### How it works at Verse

```
Someone sends email TO contracts@verse.in
              │
              ▼
    All group members receive it
    in their own individual inboxes
    (e.g. legal@verse.in, vamsi@verse.in, etc.) 
              │
              ▼
    Team member replies — two ways:

    Way 1: Reply from contracts@verse.in directly
           → Vendor sees reply from contracts@verse.in
           → Captured in contracts@verse.in Sent folder

    Way 2: Reply from personal email (vamsi@verse.in)
           and CC contracts@verse.in
           → Vendor sees reply from vamsi@verse.in
           → CC copy lands in contracts@verse.in Inbox
```

### Reply Scenarios

| How team replies | Sent from | Captured in contracts@verse.in? |
|---|---|---|
| Logs into `contracts@verse.in` and replies | `contracts@verse.in` | ✅ Yes — in Sent folder |
| Replies from personal email (`vamsi@verse.in`) | `vamsi@verse.in` | ❌ No — not captured |
| Replies from personal email but **CCs `contracts@verse.in`** | `vamsi@verse.in` | ✅ Yes — lands in Inbox as CC |

### What the Poller Captures

The poller reads **Inbox + Sent** of `contracts@verse.in`:

| Source | What it contains |
|---|---|
| **Inbox** | Vendor emails (To), team replies CC'd to `contracts@verse.in`, vendor follow-ups |
| **Sent** | Emails sent directly from `contracts@verse.in` by team members |

**Case 1 — Team replies from `contracts@verse.in` directly:**
Full thread captured via Inbox (incoming) + Sent (outgoing).

**Case 2 — Team replies from personal email and CCs `contracts@verse.in`:**
Full thread captured via Inbox alone — CC emails land in the inbox, no Sent folder needed.

---

## Overview

Polls the `contracts@verse.in` shared Gmail inbox, extracts email threads and attachments, and stores them in the Verse Legal Contracts Explorer shared Drive.

---

## Flow Diagram

```
POST /poll-group-emails
Cloud Run Service
        │
        ▼
┌────────────────────────────────────────┐
│  test_contract@verse.in                │
│  Google Group — NO inbox               │
│  Emails forwarded to members' inboxes  │
└────────────────────────────────────────┘
        │
        │  We poll the MEMBER's inbox instead
        ▼
┌───────────────────────────────────────┐
│  IMAP Connect                         │
│  temp_wohlig.praveen@verse.in         │
│  Gmail App Password                   │
└───────────────┬───────────────────────┘
                │
                ▼
   ┌────────────────────────────────────┐
   │  Fetch emails from 2 places        │
   ├────────────────────────────────────┤
   │  INBOX — filter TO/CC              │
   │          test_contract@verse.in    │
   │                                    │
   │  SENT  — filter TO/CC              │
   │          test_contract@verse.in    │
   └───────────────┬────────────────────┘
                   │
                   ▼
   Merge + deduplicate by Message-ID
                   │
                   ▼
   Group into threads using
   Message-ID / In-Reply-To / References
                   │
                   ▼
   ┌──────────────────┐
   │  For each thread │
   └────────┬─────────┘
            │
            ▼
   Extract email data:
   - From / To / CC
   - Subject / Date
   - Body (plain text)
   - Attachments (PDF, DOCX, etc.)
            │
            ▼
   Identify vendor name
   from sender domain
            │
            ├──────────────────────────────┐
            │                              │
            ▼                              ▼
   Save thread as                 Save attachments
   thread.txt                     (PDF, DOCX, etc.)
            │                              │
            └─────────────┬────────────────┘
                          │
                          ▼
             Upload to Google Drive
             └── group-emails/
                 └── <Vendor Name>/
                     └── <Subject>_<Date>/
                         ├── thread.txt
                         └── <attachment>
```

---

## Drive Folder Structure

```
Verse Legal Contracts Explorer (Shared Drive)
├── under-review-docs/
├── valid-docs/
└── group-emails/                  ← NEW
    └── <Vendor Name>/
        ├── <Subject>_<Date>.txt   ← full email thread as text
        └── <Attachment>.pdf       ← raw file from email
```

---

## Trigger Options

| Trigger | Detail |
|---|---|
| Cloud Scheduler | Same job as the existing pipeline — run daily at 9 AM IST |
| Manual | POST /poll-group-emails on Cloud Run |

---

## Components

| File | Purpose |
|---|---|
| `main.py` | FastAPI app — `POST /poll-group-emails` (runs in the background, returns 202) and `GET /health` |
| `poller.py` | IMAP connection, fetch emails, parse body + attachments, group into threads. Only `.pdf`, `.doc`, `.docx` and `.txt` attachments are kept |
| `drive_writer.py` | Upload email text and attachments to Drive under `group-emails/`; duplicate filenames get a version suffix |
| `runbook_generator.py` | Builds the group-email runbook from the threads already stored in Drive, using Gemini 2.5 Flash on Vertex AI |
| `direct_runbook.py` | Builds the same runbook straight from IMAP with Gemini Enterprise StreamAssist, skipping the Drive upload step |
| `group_email_runbook.txt` | Output runbook (local copy of what is saved to Drive) |
| `direct_runbook_checkpoints/` | Per-batch results written by `direct_runbook.py` so an interrupted run can resume |

---

## Group Email Runbook

A procurement-style runbook is generated from the vendor threads, attachments and quotations in the group mailbox. It is saved as `group_email_runbook.txt` in the `_runbook` folder under `group-emails/` in Drive.

| Script | How it gets the emails | LLM | Resume |
|---|---|---|---|
| `runbook_generator.py` | Reads the thread files already uploaded to Drive, in batches of 50 | Gemini 2.5 Flash (Vertex AI) | No checkpoints — a re-run starts over; `update_runbook()` adds patterns from new docs |
| `direct_runbook.py` | Reads IMAP directly, in batches | Gemini Enterprise StreamAssist | Re-run; finished batches are loaded from `direct_runbook_checkpoints/` |

Run `direct_runbook.py` from the repo root:
```bash
source venv/bin/activate
python group_email_poller/direct_runbook.py              # all batches
python group_email_poller/direct_runbook.py --max-batches 3   # limit batches
```

---

## Environment Variables

Stored in `group_email_poller/.env`:

| Variable | Value |
|---|---|
| `GROUP_EMAIL` | `test_contract@verse.in` |
| `GROUP_MEMBER_EMAIL` | `temp_wohlig.praveen@verse.in` |
| `GROUP_MEMBER_APP_PASSWORD` | Gmail App Password for the member account |
| `DRIVE_GROUP_EMAILS_FOLDER_ID` | `0AOHQl782zGzxUk9PVA` |
| `SERVICE_ACCOUNT_FILE` | `../service_account.json` |
| `GCP_PROJECT` / `GCP_LOCATION` | `gemini-project-n1` / `us-central1` (runbook generation) |
| `DISCOVERY_ENGINE_ID` / `DISCOVERY_ASSISTANT_ID` | Gemini Enterprise engine and assistant used by `direct_runbook.py` (assistant defaults to `default_assistant`) |
| `EXCLUDED_EMAILS` / `EXCLUDED_DOMAINS` | Optional, comma-separated senders or domains the poller skips |

---

## Sample Output

### Drive Folder Structure (Example)

```
Verse Legal Contracts Explorer (Shared Drive)
└── group-emails/
    │
    ├── Sur Half Cutting Films LLP/
    │   │
    │   ├── Re_ Consultancy Agreement - Sur Half Cutting Films_2025-06-10/
    │   │   ├── thread.txt
    │   │   └── VerSe_Sur Half Cutting Films_Consultancy Agreement.docx
    │   │
    │   └── Re_ Payment Terms Discussion - Sur Half_2025-07-02/
    │       └── thread.txt
    │
    ├── Acme Analytics Pvt Ltd/
    │   │
    │   └── Re_ NDA - Acme Analytics_2025-05-21/
    │       ├── thread.txt
    │       └── NDA_Acme_Analytics_Signed.pdf
    │
    └── XYZ Media Solutions/
        │
        └── Fw_ MSA Draft - XYZ Media_2025-08-01/
            ├── thread.txt
            ├── MSA_XYZ_Media_v1.pdf
            └── MSA_XYZ_Media_v2_revised.pdf
```

---

### Sample thread.txt Content

```
================================================================
THREAD : Re: Consultancy Agreement - Sur Half Cutting Films
VENDOR : Sur Half Cutting Films LLP
EMAILS : 4 messages
================================================================

----------------------------------------------------------------
[1/4] SENT
Date    : Mon, 02 Jun 2025 10:15:32 +0530
From    : contracts@verse.in
To      : surhalf@gmail.com
CC      : legal@verse.in
Subject : Consultancy Agreement - Sur Half Cutting Films

Hi Team,

Please find attached the draft Consultancy Agreement for your review.
Kindly revert with your comments at the earliest.

Regards,
Verse Innovation Legal Team

Attachments: VerSe_Sur Half Cutting Films_Consultancy Agreement.docx
----------------------------------------------------------------

[2/4] RECEIVED
Date    : Tue, 03 Jun 2025 14:42:10 +0530
From    : surhalf@gmail.com
To      : contracts@verse.in
CC      : —
Subject : Re: Consultancy Agreement - Sur Half Cutting Films

Thank you for sharing the agreement. We have a few comments on
Clause 5 (Payment Terms) and Clause 9 (Governing Law). We will
revert with the marked document by end of week.

Best regards,
Sur Half Cutting Films LLP
----------------------------------------------------------------

[3/4] SENT
Date    : Thu, 05 Jun 2025 09:30:00 +0530
From    : contracts@verse.in
To      : surhalf@gmail.com
CC      : legal@verse.in
Subject : Re: Consultancy Agreement - Sur Half Cutting Films

Hi,

Noted your comments. We are open to discussing Clause 5.
Governing Law must remain Bengaluru, Karnataka as per our
standard terms. Please share the marked document.

Regards,
Verse Innovation Legal Team
----------------------------------------------------------------

[4/4] RECEIVED
Date    : Fri, 06 Jun 2025 17:10:45 +0530
From    : surhalf@gmail.com
To      : contracts@verse.in
CC      : —
Subject : Re: Consultancy Agreement - Sur Half Cutting Films

Please find attached the signed agreement. We agree to all terms.

Attachments: VerSe_Sur Half Cutting Films_Consultancy Agreement_Signed.pdf
----------------------------------------------------------------
```

---

### Naming Rules

| Item | Format | Example |
|---|---|---|
| Vendor folder | Legal name from email sender/domain | `Sur Half Cutting Films LLP` |
| Thread folder | `<Subject>_<Date of first email>` | `Re_ Consultancy Agreement - Sur Half_2025-06-02` |
| Thread file | Fixed name | `thread.txt` |
| Attachments | Original filename from email | `NDA_Acme_Analytics_Signed.pdf` |
| Duplicate attachment | Versioned | `NDA_Acme_Analytics_Signed_v2.pdf` |
