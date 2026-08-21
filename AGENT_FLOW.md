# Legal Watcher — System Flow

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

## How the Drive Connection Works

| Item | Detail |
|---|---|
| Agent Platform | Vertex AI Agent Builder (Gemini Enterprise) |
| Drive Access | Folder ID hardcoded in agent instructions |
| Runbook Folder ID | `1W1KZT7AF2vj-_2wc9Aj7I0uKd7q66Qv6` |
| under-review-docs ID | `1vy6VIDz_HWmdTESbm-ve_rf8Y7iBW7X7` |
| valid-docs ID | `1y6WmPhTZxVkWlaS_4Je0NHOwlmWbFkuP` |
| Shared Drive | Verse Legal Contracts Explorer |

## Why the Folder ID is Hardcoded

The Drive Connector in Gemini Enterprise connects only to the signed-in user's personal Google Drive — not to a shared drive. Since `validation_runbook.txt` lives in the **Verse Legal Contracts Explorer shared drive**, the folder ID is embedded directly in the agent instructions. The agent uses its built-in Google Drive tool to fetch the runbook from that exact folder on every request.
