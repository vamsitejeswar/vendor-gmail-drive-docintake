"""
Direct runbook generator — fetches emails from IMAP and calls Gemini Enterprise
StreamAssist directly, skipping the Drive upload step.

Usage (from repo root):
    source venv/bin/activate
    python group_email_poller/direct_runbook.py

Env vars required (in group_email_poller/.env):
    GCP_PROJECT, GCP_LOCATION, GROUP_EMAIL, GROUP_MEMBER_EMAIL,
    GROUP_MEMBER_APP_PASSWORD, DRIVE_GROUP_EMAILS_FOLDER_ID,
    SERVICE_ACCOUNT_FILE,
    DISCOVERY_ENGINE_ID   (e.g. 15240278634370897504)
    DISCOVERY_ASSISTANT_ID (default: default_assistant)
"""

import io
import logging
import os
import sys
import time

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from google.cloud import discoveryengine_v1beta as discoveryengine
from googleapiclient.http import MediaIoBaseUpload

from drive_writer import _build_thread_txt, _get_drive_service
from poller import fetch_group_email_threads_bulk

# ── Constants ─────────────────────────────────────────────────────────────────
RUNBOOK_FILENAME = "group_email_runbook.txt"
RUNBOOK_FOLDER_NAME = "_runbook"
GROUP_EMAILS_FOLDER_ID = os.getenv("DRIVE_GROUP_EMAILS_FOLDER_ID", "")

GENERATION_PROMPT = """
You are a procurement analyst for Verse Innovation Private Ltd.

You have been given vendor emails, contracts, proposals, quotations, invoices, SOWs, NDAs,
purchase orders, and other documents exchanged with external vendors via the group email
contracts@verse.in.

Analyze ALL documents and email threads provided. Extract real patterns only — do not invent
clauses or terms not evidenced in the documents.

Produce a structured Vendor Procurement Runbook in EXACTLY this format:

---

# Vendor Procurement Runbook for Verse Innovation Private Ltd.

**Purpose:** [One paragraph describing what this runbook covers and how it should be used.]

**KEY PRINCIPLE — Validate Proportionately:**
[One paragraph: which clauses apply to which document types; when to flag vs. suggest; how to handle unknown document types.]

**OVERRIDING RULE — VALID vs. REVIEW NEEDED:**
[Bullet points: when to mark VALID, when to mark REVIEW NEEDED, what never triggers REVIEW NEEDED.]

---

## 1. ACCEPTED DOCUMENT TYPES

[List every document type observed across all vendor threads and docs. Group into:]

**A. Core Transactional Agreements:**
[Numbered list with document type name and one-line description. At minimum, identify and include any of these seen in the data:]
1. Master Service Agreement (MSA) — overarching framework governing all vendor services
2. Non-Disclosure Agreement (NDA / MNDA) — confidentiality obligations, standalone or mutual
3. Statement of Work (SOW) — project-specific scope, deliverables, timelines, fees
4. Consulting / Professional Services Agreement — engagement of individual consultants or firms
5. Software / SaaS License Agreement — subscription or perpetual license for software platforms
6. Maintenance & Support Agreement — post-delivery support, bug fixes, SLAs
7. Payment Processing / Fintech Agreement — applicable for payment gateway, UPI, NBFC vendors
8. Employment / Independent Contractor Agreement — engagement of freelancers or contract staff
[Add any others observed in the source documents.]

**B. Supplementary / Specific Agreements:**
[Numbered list. At minimum, identify and include any of these seen in the data:]
1. Amendment / Addendum — modification to an existing agreement
2. Order Form / Work Order — transaction-level authorisation under an MSA or SaaS agreement
3. IP Assignment Agreement — formal transfer of intellectual property rights to Verse
4. Data Processing Agreement (DPA) — data controller–processor terms per DPDPA / GDPR
5. Escrow Agreement — source code or payment escrow arrangements
6. Reseller / Distribution Agreement — vendor authorised to resell or distribute Verse products/services
7. Letter of Intent (LoI) / Term Sheet — pre-contractual intent, binding vs. non-binding clauses
[Add any others observed in the source documents.]

**C. Pre-Contractual / Supporting Documents:**
[Numbered list. At minimum, identify and include any of these seen in the data:]
1. Proposal / Quotation — vendor's commercial offer, pricing, and scope
2. Purchase Order (PO) — Verse's formal purchase authorisation
3. Invoice — vendor's payment demand; check alignment with PO/SOW
4. Capability Deck / Company Profile — vendor background, not contractually binding
5. Compliance Certificate / Regulatory Filing — RBI, SEBI, NPCI, GST registration proofs
6. Bank Details Form / KYC Documents — vendor payment information
7. Other / Unknown Document Type — treat as supplementary; apply general clauses only; flag for manual classification.

---

## 2. REQUIRED CLAUSES (by document type)

[Start with an APPLICABILITY GUIDE — a bulleted list mapping document types to which clause groups apply (full set, lightweight, confidentiality-focus only, document-specific only).]

### A. General Clauses (Applicable to most Contractual Agreements)

[For each clause: name in bold, Verse's expectation, acceptable variations, what triggers a flag.]

Include at minimum:
- Parties Identification
- Effective Date & Term
- Definitions
- Scope of Services/Work/Deliverables
- Payment Terms / Consideration
- Taxes (GST, TDS, withholding)
- Confidentiality
- Intellectual Property Rights (IPR)
- Representations & Warranties
- Indemnification
- Limitation of Liability
- Termination (for cause, without cause, for convenience)
- Effects of Termination (survival, transition, return of materials)
- Relationship of Parties (independent contractor, not employee/agent)
- Governing Law & Jurisdiction
- Dispute Resolution
- Force Majeure
- Assignment
- Notices
- Entire Agreement / Amendment / Severability
- Acceptance Testing & Criteria (for deliverable-based engagements)
- Key Personnel (identification, replacement rights)
- Change Request / Variation Order Process (how scope changes are approved and priced)
- Exit Management / Transition Obligations (knowledge transfer, data handover, wind-down SLA)
- Liquidated Damages / Penalties (for delay or SLA breach, where applicable)
- Business Continuity & Disaster Recovery (for mission-critical services)
- Regulatory Compliance (RBI, SEBI, NPCI, PCI-DSS where applicable to vendor's service type)
- Source Code Escrow (for software/SaaS vendors — release triggers, escrow agent)
- Anti-Bribery / Code of Conduct
- Publicity / Reference Restriction
- Survival Clause (which obligations survive termination)

### B. Specific Clauses (by Document Type)

[One subsection per distinct document type observed, e.g.:]
#### B1. [Document Type]
[Required clauses specific to this type.]
...

---

## 3. STANDARD TERMS VERSE ACCEPTS

[Structured list of Verse's preferred positions, grouped by topic. For each topic, state the preferred position AND the boundary of what is acceptable vs. what triggers a flag:]

- **Payment Terms:** preferred net-30 or net-45; currency in INR unless cross-border; GST/TDS handled per applicable law; disputed invoice mechanism (written notice, hold period); late payment interest cap; advance payment ceiling as % of contract value.

- **Notice Periods:** termination without cause — 30 days minimum; termination for material breach — 15 days cure period then 7 days notice; security incidents — immediate notification (within 24–48 hours); force majeure — notice within 5 business days of triggering event; all notices in writing to designated contacts.

- **Governing Law / Jurisdiction:** Indian law (preferred); courts of Mumbai or Bengaluru (preferred); Delhi or other Indian metro courts (acceptable); foreign law only acceptable for international vendors with mutual agreement and mandatory Indian arbitration fallback.

- **Liability Caps:** Verse's aggregate cap — 3× fees paid in prior 12 months (preferred) or total contract value; exclusion of indirect, consequential, punitive, and loss-of-profit damages (mutual); vendor uncapped categories — fraud, wilful misconduct, IP infringement, confidentiality breach, data breach, death/personal injury caused by vendor.

- **IP Ownership Terms:** all work product and deliverables commissioned by Verse vest in Verse upon full payment; vendor retains pre-existing IP and tools; Verse gets a perpetual, royalty-free licence to vendor's platform/tools embedded in deliverables; no vendor right to use Verse's brand, name, or logo without prior written consent; IP warranty — deliverables do not infringe third-party rights.

- **Confidentiality Terms:** mutual NDA obligations; confidentiality period — term plus 3 years post-termination (preferred), minimum 2 years; standard carve-outs — publicly known, independently developed, legally compelled disclosure (with advance notice to disclosing party); return or certified destruction of confidential materials within 15 days of termination; no disclosure to subcontractors without equivalent NDA.

- **Data Protection / Privacy:** compliance with India DPDPA 2023 and applicable state/sector regulations; vendor acts as data processor; explicit restriction on using Verse data for training AI/ML models; data breach notification to Verse within 24 hours of discovery; data residency — India (preferred) or as agreed; data deletion/return within 30 days of contract end; vendor maintains reasonable security safeguards (ISO 27001 or equivalent preferred).

- **Warranties & Representations:** mutual authority to enter the agreement; services will be performed in a professional and workmanlike manner; deliverables will conform to agreed specifications for 90 days post-delivery; no infringement of third-party IP; vendor has all necessary licences, permits, and regulatory approvals; vendor personnel have required qualifications; no material misrepresentation in proposals/SOWs.

- **Indemnification:** mutual indemnification for breach of representations, warranties, and confidentiality; vendor indemnifies Verse for third-party IP infringement claims arising from deliverables; vendor indemnifies for data breaches caused by vendor negligence; indemnification process — prompt notice, reasonable cooperation, Verse's right to control defence; indemnification cap aligned with liability cap except for IP and data breach claims.

- **Audit Rights:** Verse's right to audit vendor's records relevant to contract performance and billing — at least 12 months' transaction records; reasonable advance notice (10 business days); audit frequency — once per contract year unless triggered by dispute; vendor must cooperate and provide access to relevant personnel and systems; audit costs borne by Verse unless material discrepancy found.

- **Non-Solicitation:** mutual restriction on soliciting or hiring the other party's employees directly involved in the engagement; duration — contract term plus 12 months post-termination; acceptable carve-out for general public advertising not targeted at the other party's employees.

- **Dispute Resolution:** good-faith negotiation — 30 days; escalation to senior management — additional 15 days; arbitration — preferred over litigation; arbitration seat — Mumbai or Bengaluru; language — English; arbitration rules — Indian Arbitration and Conciliation Act 1996; number of arbitrators — one for disputes < ₹1 crore, three for disputes ≥ ₹1 crore; interim injunctive relief available in courts notwithstanding arbitration clause.

- **Assignment & Change of Control:** neither party may assign rights or obligations without prior written consent; acceptable exception — assignment within the same group/holding company with 30 days prior notice; change of control of vendor (acquisition, merger) requires Verse's prior written consent or right to terminate without penalty within 60 days of notice.

- **Subcontracting:** vendor may not subcontract core deliverables without Verse's prior written consent; approved subcontractor list must be maintained and shared; vendor remains fully liable for acts and omissions of subcontractors; subcontractors must be bound by equivalent confidentiality and data protection obligations.

- **Insurance:** vendor must maintain adequate professional indemnity (errors & omissions) insurance for the contract term and 2 years post-termination; general commercial liability insurance; cyber liability insurance for engagements involving personal data; minimum coverage amounts to be specified in the SOW/contract schedule; Verse may request certificates of insurance on reasonable notice.

- **Term & Renewal:** initial term clearly stated; auto-renewal — acceptable with minimum 30–60 days prior written notice to opt out; renewal price increases — capped at CPI/WPI or agreed % (preferred ≤ 10% annually); Verse's right to renegotiate SLAs and pricing at each renewal; perpetual/evergreen contracts without break rights are a flag.

- **SLA / Service Levels:** uptime commitments (for SaaS/tech vendors) — minimum 99.5% monthly; agreed response and resolution times by incident severity; SLA credits as % of monthly fees for breaches — not sole remedy; Verse's right to terminate for repeated SLA failures (3+ breaches in a rolling 6-month period); exclusions to SLA — scheduled maintenance with advance notice, force majeure, Verse-caused issues.

- **Publicity & Press Releases:** vendor may not issue press releases, case studies, or marketing materials referencing Verse without prior written approval; no use of Verse's brand, logo, or trade name; Verse may reference vendor's name as a service provider in standard disclosures; mutual right to decline reference requests.

- **Compliance & Anti-Bribery:** vendor confirms compliance with all applicable anti-corruption laws (Prevention of Corruption Act, FCPA if applicable); vendor must not offer gifts, payments, or kickbacks to Verse employees; mandatory reporting obligation for any compliance violations; Verse's right to terminate for cause on confirmed violations; vendor must have its own code of conduct and compliance programme.

- **Force Majeure:** defined events — natural disasters, war, government orders, pandemics; obligations suspended for the duration of the event; notice required within 5 business days; either party's right to terminate if force majeure continues beyond 60 days; vendor must maintain a business continuity plan for critical services; force majeure does not excuse payment obligations for services already rendered.

---

## 4. RED FLAGS

[Numbered list. Each item: bold title, description of what triggers the flag, and — where applicable — note what does NOT trigger the flag (missing clause ≠ active violation).]

Include at minimum:
1. IP Ownership Vests in Vendor for Commissioned Work — vendor retains rights to work Verse paid for
2. Active AI Model Training with Verse Data — vendor uses Verse's data to train or improve its AI/ML models
3. Vendor Liability Cap too Low or Exempted for Critical Breaches — cap < 1× annual fees, or key categories exempted
4. Verse Liability Cap too High — Verse exposed to uncapped or disproportionately large liability
5. Unilateral Amendments by Vendor — vendor reserves right to change terms without Verse's consent
6. Payment Terms Unfavorable to Verse — advance > 50% with no milestone trigger, net < 15 days, non-INR without justification
7. Subcontracting Actively Permitted Without Consent — vendor can freely subcontract core services without Verse's prior approval
8. Exclusivity Demanded by Vendor — Verse restricted from engaging other vendors for same/similar services
9. Active Bribery / Corruption Violations — vendor explicitly solicits or permits kickbacks, gifts, or facilitation payments
10. Vague or Undefined Scope of Services — no clear deliverables, milestones, or acceptance criteria; creates unlimited obligation
11. Perpetual Auto-Renewal Without Exit Right — contract renews indefinitely with no Verse opt-out right or excessive penalty for exit
12. Excessive Termination / Exit Penalties — early termination fees disproportionate to remaining contract value (> 3 months fees)
13. Unilateral Price Escalation Without Cap — vendor can raise prices at will without Verse's approval or a contractual cap
14. Broad Reverse Indemnification — Verse required to indemnify vendor for vendor's own acts, negligence, or third-party claims
15. Vendor IP Lien on Deliverables — vendor withholds delivery or access to completed work pending full payment with no milestone-based release
16. Data Portability Restriction / Vendor Lock-In — vendor restricts Verse's ability to export, migrate, or access its own data on termination
17. Third-Party Beneficiary Rights to Vendor Affiliates — vendor's affiliates gain enforcement rights against Verse without Verse's consent
18. Missing or Inadequate Data Protection Terms — no DPDPA compliance, no breach notification obligation, no data deletion/return on exit
19. Non-Compete Imposed on Verse — Verse restricted from operating in markets or building products without vendor consent
[Continue with any additional red flags evidenced in the documents.]

---

## 4.5 SUGGESTIONS ONLY (NEVER RED FLAG)

[Numbered list of items that must ALWAYS go in SUGGESTIONS with a recommended fix, and must NEVER trigger REVIEW NEEDED. For each item: state the missing or weak clause, the suggested fix, and why it is a suggestion and not a flag. Include at minimum:]

1. Missing Anti-Bribery Clause — suggest adding standard prevention-of-corruption language; not a flag if no active violation exists.
2. Missing Non-Solicitation Clause — suggest mutual 12-month post-termination restriction; not a flag as it is a protective add-on.
3. Missing AI Prohibition Clause — suggest adding explicit restriction on using Verse data for AI/ML training; flag only if active training is evidenced.
4. Missing or Generic Data Security Specifics — suggest specifying security standards (ISO 27001, SOC 2) and breach notification timelines; not a flag if no active data risk.
5. Missing Publicity / Reference Restriction — suggest adding no-press-release clause; not a flag if vendor has not published anything.
6. Missing Assignment Restriction — suggest adding prior-written-consent requirement; not a flag if no assignment has occurred.
7. Missing Arbitration Clause — suggest adding Indian Arbitration and Conciliation Act 1996 clause; courts are still available without it.
8. Unfilled Administrative Fields — template brackets, blank dates, TBD fees; suggest completing; not a flag on a draft.
9. Missing Boilerplate (severability, waiver, entire agreement) — suggest adding standard provisions; does not affect core commercial terms.
10. Missing Force Majeure — suggest adding standard clause; not a flag absent an actual force majeure event.
11. Missing Insurance Clause — suggest specifying PI/GL/cyber coverage requirements in SOW schedule; not a flag if vendor is low-risk.
12. Missing SLA / Service Level Commitments — suggest defining uptime, response, and resolution times for service contracts; not a flag on non-service agreements.
13. Missing Acceptance Testing Criteria — suggest defining acceptance milestones for deliverable-based engagements; not a flag on subscription/SaaS contracts.
14. Missing Exit Management / Transition Obligations — suggest adding knowledge transfer and data handover period; not a flag unless vendor has refused to cooperate.
15. Missing Key Personnel Clause — suggest identifying critical vendor staff and requiring Verse's approval for replacement; not a flag on low-complexity engagements.
16. Governing Law / Jurisdiction Non-Indian — suggest adding Indian law and arbitration fallback; NEVER a red flag on its own for international vendors.
17. Missing Survival Clause — suggest listing clauses that survive termination (confidentiality, IP, indemnity, governing law); not a flag as survival may be implied.
18. Missing Source Code Escrow for Software Vendors — suggest escrow arrangement for business-critical software; not a flag unless vendor insolvency risk is high.

---

## 5. VALIDATION CHECKLIST

[Step-by-step checklist in exactly this structure. Each step must be actionable and reference the correct Red Flag (R-#) or Suggestion (S-#) codes:]

**Phase 1: Document Intake & Classification**
1. Identify document type → classify into Section 1 group (A / B / C).
2. Check if all parties are named with full legal entity names and registered addresses.
3. Verify effective date and contract term are explicitly stated (not blank/TBD).
4. Check for execution — signatures, authorised signatories, dates; if draft, note as pre-execution.
5. Check for consistency with related documents (e.g., PO amount matches SOW; amendment references correct base agreement).
6. If document type is unknown, classify as Section 1-C "Other" and apply General Clauses only.

**Phase 2: Core Clause Validation**
[For each clause below: Check → if present and acceptable → VALID; if missing → add to Suggestions (S-#); if present but problematic → apply Red Flag (R-#) and mark REVIEW NEEDED.]
1. Scope of Services/Work — defined and specific? If vague → R-10 (Vague Scope).
2. Payment Terms — net days, currency, advance % → if > 50% advance with no milestone trigger → R-6.
3. IP Ownership — work product vests in Verse on payment? If vests in vendor → R-1.
4. Confidentiality — mutual obligations, duration ≥ 2 years? If missing → S-1 area; if actively leaking data → H-1.
5. Data Protection — DPDPA compliance, breach notification, no AI training? If AI training permitted → R-2; if missing entirely → R-18.
6. Liability Cap — Verse's cap ≤ 3× fees? Vendor uncapped for fraud/IP/data breach? If Verse cap too high → R-4; vendor cap too low → R-3.
7. Termination — both for cause and without cause? Cure period ≥ 15 days? If no termination right for Verse → H-2.
8. Governing Law — Indian law preferred; non-Indian acceptable for international vendors with arbitration fallback → if non-Indian with no fallback → S-16 (never R-#).
9. Dispute Resolution — arbitration preferred; if litigation only → S-7.
10. Assignment — prior written consent required? If unrestricted assignment → R-7 area; if missing → S-6.
11. Subcontracting — prior consent required? If freely permitted → R-7.
12. Exclusivity — is Verse restricted from other vendors? If yes → R-8.
13. Anti-Bribery — present? If missing → S-1; if active violation evidenced → R-10.
14. Force Majeure — present? If missing → S-10.
15. Auto-Renewal — Verse's opt-out right within notice window? If perpetual lock-in → R-11.
16. Price Escalation — capped or requires mutual consent? If unilateral → R-13.
17. Indemnification — mutual? Verse not indemnifying vendor's own acts? If broad reverse indemnification → R-14.
18. Data Portability — Verse can export its data on termination? If restricted → R-16.

**Phase 3: Document-Specific Clause Validation**
[For each document type group, validate the document-type-specific clauses from Section 2B:]
- MSA / Framework Agreement: check scope of services applicability, order of precedence over SOWs/POs.
- SOW / Work Order: verify milestone schedule, acceptance criteria, deliverable definitions, change request process.
- NDA: check duration, definition of confidential information, return/destruction obligation, permitted disclosures.
- SaaS / License Agreement: check licence scope (users, seats, geography), uptime SLA, data portability, auto-renewal terms.
- Invoice / PO: verify amount matches SOW/Quote, GST/TDS treatment, payment due date.
- Amendment: verify it references the correct base agreement, dated correctly, signed by same or higher authority.
- DPA: verify DPDPA 2023 alignment, data categories, processing purposes, sub-processor restrictions.

**Phase 4: Final Red Flag Check & Overall Assessment**
1. Consolidate all R-# flags raised in Phases 2–3.
2. Consolidate all S-# suggestions raised.
3. Cross-check: does any combination of clauses create an aggregate risk not captured by individual flags?
4. Apply OVERRIDING RULE: if any R-# is raised → Overall Status = REVIEW NEEDED; if only S-# → VALID with suggestions.
5. Complete the Summary template below.

**Summary of Validation Results:**
- Overall Status: [VALID / REVIEW NEEDED]
- Total Red Flags: [Number]
- Total Suggestions: [Number]
- List of Specific Flags (with R-# codes and one-line description of each)
- List of Suggestions (with S-# codes and recommended fix for each)

---
**Disclaimer:** [Standard disclaimer that this runbook does not replace legal review.]

---

Extract every pattern from the documents provided. Use real clause language and real terms observed
in the vendor emails and attachments. Do not invent anything not present in the source material.
"""

MERGE_PROMPT = """
You are a procurement analyst for Verse Innovation Private Ltd.

Below are multiple partial vendor procurement runbooks, each generated from a different batch of
Verse's vendor email threads and documents.

Merge them into ONE unified, deduplicated Vendor Procurement Runbook.
Keep all unique patterns, clause types, standard terms, and red flags found across all batches.
Remove duplicates. Organize clearly.

The final runbook MUST follow this exact section structure — no deviation:

# Vendor Procurement Runbook for Verse Innovation Private Ltd.
**Purpose:** ...
**KEY PRINCIPLE — Validate Proportionately:** ...
**OVERRIDING RULE — VALID vs. REVIEW NEEDED:** ...

## 1. ACCEPTED DOCUMENT TYPES
  A. Core Transactional Agreements
  B. Supplementary / Specific Agreements
  C. Pre-Contractual / Supporting Documents

## 2. REQUIRED CLAUSES (by document type)
  APPLICABILITY GUIDE
  ### A. General Clauses
  ### B. Specific Clauses (one subsection per document type)

## 3. STANDARD TERMS VERSE ACCEPTS
  (Grouped by topic — Payment Terms, Notice Periods, Governing Law, Liability Caps, IP Ownership,
   Confidentiality, Data Protection/Privacy, Warranties, Indemnification, Audit Rights,
   Non-Solicitation, Dispute Resolution, Assignment & Change of Control, Subcontracting,
   Insurance, Term & Renewal, SLA/Service Levels, Publicity, Compliance/Anti-Bribery, Force Majeure)

## 4. RED FLAGS
  (Numbered list R-1 through R-19+; each with active-violation trigger and what does NOT trigger it)

## 4.5 SUGGESTIONS ONLY (NEVER RED FLAG)
  (Numbered list S-1 through S-18+; each with missing clause, suggested fix, and why it is a suggestion)

## 5. VALIDATION CHECKLIST
  Phase 1 (Intake & Classification) / Phase 2 (Core Clause Validation) /
  Phase 3 (Document-Specific Validation) / Phase 4 (Final Red Flag Check) / Summary template

**Disclaimer:** ...
"""


# ── Drive helpers (no LLM — StreamAssist only) ────────────────────────────────

def _get_or_create_runbook_folder(service) -> str:
    resp = service.files().list(
        q=(
            f"'{GROUP_EMAILS_FOLDER_ID}' in parents and "
            f"name = '{RUNBOOK_FOLDER_NAME}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={
            "name": RUNBOOK_FOLDER_NAME,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [GROUP_EMAILS_FOLDER_ID],
        },
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return folder["id"]


def _save_runbook_to_drive(service, content: str) -> None:
    folder_id = _get_or_create_runbook_folder(service)
    resp = service.files().list(
        q=(
            f"'{folder_id}' in parents and "
            f"name = '{RUNBOOK_FILENAME}' and "
            f"trashed = false"
        ),
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    for old in resp.get("files", []):
        try:
            service.files().delete(fileId=old["id"], supportsAllDrives=True).execute()
            logger.info(f"Deleted old runbook: {old['id']}")
        except Exception as e:
            logger.warning(f"Could not delete old runbook {old['id']}: {e}")
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/plain",
        resumable=True,
    )
    f = service.files().create(
        body={"name": RUNBOOK_FILENAME, "parents": [folder_id]},
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    logger.info(f"Runbook saved to Drive: {f['id']}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("direct_runbook")

PROJECT_ID = os.getenv("GCP_PROJECT", "gemini-project-n1")
ENGINE_ID    = os.getenv("DISCOVERY_ENGINE_ID", "gemini-enterprise-legal-app")
ASSISTANT_ID = os.getenv("DISCOVERY_ASSISTANT_ID", "default_assistant")
AGENT_ID     = "2431253715885581897"  # Legal Watcher Contracts Analysis Agent
BATCH_SIZE = 50
MAX_PROMPT_BYTES = 2_000_000  # 2MB — keeps prompts small enough to avoid 504 deadline exceeded


def _get_client():
    logger.info("Using Application Default Credentials (temp_wohlig.praveen@verse.in)")
    return discoveryengine.AssistantServiceClient()


def _assistant_name() -> str:
    return (
        f"projects/852267154002/locations/global"
        f"/collections/default_collection"
        f"/engines/{ENGINE_ID}/assistants/{ASSISTANT_ID}"
    )


def _extract_pdf_text(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
    except Exception:
        return ""


def _extract_docx_text(file_bytes: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


def _extract_text(filename: str, file_bytes: bytes) -> str:
    if not file_bytes:
        return ""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return _extract_pdf_text(file_bytes)
    elif ext in (".doc", ".docx"):
        return _extract_docx_text(file_bytes)
    elif ext in (".txt", ".csv", ".md"):
        return file_bytes.decode("utf-8", errors="ignore").strip()
    return ""


def _stream_assist(client, prompt: str) -> str:
    assistant = _assistant_name()
    logger.info(f"  StreamAssist → {assistant}")
    request = discoveryengine.StreamAssistRequest(
        name=assistant,
        query=discoveryengine.Query(text=prompt),
    )
    full_text = ""
    chunk_count = 0
    for chunk in client.stream_assist(request=request):
        chunk_count += 1
        try:
            for reply in chunk.answer.replies:
                text = reply.grounded_content.content.text
                if text:
                    full_text += text
                    if chunk_count % 10 == 1:
                        logger.info(f"  Streaming... {len(full_text):,} chars received so far")
        except Exception as e:
            logger.debug(f"  Chunk parse skip: {e}")
    logger.info(f"  Stream complete — {chunk_count} chunks, {len(full_text):,} chars total")
    return full_text.strip()


def _strip_surrogates(text: str) -> str:
    """Remove lone UTF-16 surrogate characters that cannot be encoded to UTF-8."""
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _build_batch_prompt(threads: list) -> tuple:
    """Returns (prompt_str, remaining_threads). If all threads fit, remaining is empty."""
    parts = [GENERATION_PROMPT, "\n\n--- VENDOR EMAIL THREADS AND DOCUMENTS ---\n"]
    current_size = sum(len(p.encode("utf-8", errors="replace")) for p in parts)
    threads_added = 0

    for thread in threads:
        vendor = thread['vendor']
        subject = thread['subject']
        attachments = thread.get("attachments", [])

        thread_parts = [f"\n\n=== THREAD: {subject} | VENDOR: {vendor} ===\n"]
        thread_parts.append(_build_thread_txt(thread))

        added_attachments = 0
        for filename, file_bytes in attachments:
            text = _extract_text(filename, file_bytes)
            if text:
                text = _strip_surrogates(text)
                thread_parts.append(f"\n[Attachment: {filename}]\n{text}")
                added_attachments += 1
                logger.info(f"    + attachment: {filename} ({len(text):,} chars)")
            else:
                logger.info(f"    - skipped (no text extracted): {filename}")

        thread_size = sum(len(p.encode("utf-8", errors="replace")) for p in thread_parts)
        if current_size + thread_size > MAX_PROMPT_BYTES:
            if threads_added == 0:
                # Thread alone exceeds limit — force-add it to avoid infinite loop
                logger.warning(
                    f"  Thread too large ({thread_size:,} bytes) but forcing it in to avoid infinite loop"
                )
            else:
                logger.warning(
                    f"  Size limit reached ({current_size:,} bytes) — "
                    f"{threads_added}/{len(threads)} threads fit; {len(threads) - threads_added} will be processed in next sub-batch"
                )
                break

        parts.extend(thread_parts)
        current_size += thread_size
        threads_added += 1
        logger.info(
            f"  Thread: [{vendor}] {subject[:50]} | "
            f"emails={len(thread.get('emails', []))} attachments={added_attachments}/{len(attachments)} "
            f"| total size: {current_size:,} bytes"
        )

    remaining = threads[threads_added:]
    return "\n".join(parts), remaining


CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "direct_runbook_checkpoints")


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def _save_checkpoint_key(key: str, text: str):
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    path = os.path.join(CHECKPOINT_DIR, f"batch_{key}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info(f"  Checkpoint saved: batch_{key}.txt")


def _load_checkpoints():
    """Returns {batch_num: text} for single-sub batches and {key: text} for multi-sub batches.
    Also returns set of batch_nums that have at least one checkpoint (for skip logic)."""
    if not os.path.exists(CHECKPOINT_DIR):
        return {}, set()
    checkpoints = {}
    completed_batches = set()
    for fname in sorted(os.listdir(CHECKPOINT_DIR)):
        if fname.startswith("batch_") and fname.endswith(".txt"):
            key = fname[len("batch_"):-len(".txt")]
            with open(os.path.join(CHECKPOINT_DIR, fname), encoding="utf-8") as f:
                checkpoints[key] = f.read()
            # Extract the base batch number (e.g. "5_2" → 5, "3_1" → 3)
            base = int(key.split("_")[0])
            completed_batches.add(base)
    if checkpoints:
        logger.info(f"Loaded {len(checkpoints)} existing checkpoints ({len(completed_batches)} batches) — will skip those batches")
    return checkpoints, completed_batches


def generate_direct_runbook(max_batches: int = 0):
    client = _get_client()
    drive_service = _get_drive_service()

    checkpoints, completed_batches = _load_checkpoints()
    batch_runbooks = dict(checkpoints)

    total_threads = 0
    batch_num = 0
    run_start = time.time()

    logger.info(
        f"\n{'='*60}\n"
        f"  DIRECT RUNBOOK GENERATION (StreamAssist)\n"
        f"  Engine: {ENGINE_ID} | Assistant: {ASSISTANT_ID}\n"
        f"  Max batches: {'all' if not max_batches else max_batches}\n"
        f"  Resuming from: {len(checkpoints)} saved checkpoints\n"
        f"{'='*60}"
    )

    for batch in fetch_group_email_threads_bulk(batch_size=BATCH_SIZE, skip_batches=completed_batches):
        batch_num += 1
        total_threads += len(batch)

        if batch_num in completed_batches:
            logger.info(f"\nBatch {batch_num}: SKIPPED (checkpoint exists)")
            if max_batches and batch_num >= max_batches:
                break
            continue

        logger.info(
            f"\nBatch {batch_num}: {len(batch)} threads "
            f"(total so far: {total_threads}) | "
            f"elapsed: {_fmt_duration(time.time() - run_start)}"
        )

        remaining = list(batch)
        sub = 0
        while remaining:
            sub += 1
            prompt, remaining = _build_batch_prompt(remaining)
            label = f"{batch_num}.{sub}" if sub > 1 else str(batch_num)
            logger.info(f"  Sub-batch {label}: calling StreamAssist ({len(prompt):,} chars), {len(remaining)} threads overflow to next sub-batch...")

            call_start = time.time()
            text = ""
            try:
                text = _stream_assist(client, prompt)
            except Exception as e:
                logger.error(f"  Batch {label} StreamAssist failed: {e} — skipping sub-batch")

            if text:
                key = f"{batch_num}_{sub}"
                batch_runbooks[key] = text
                _save_checkpoint_key(key, text)
                logger.info(
                    f"  Sub-batch {label} done in {_fmt_duration(time.time() - call_start)} "
                    f"— {len(text):,} chars generated"
                )
            else:
                logger.warning(f"  Sub-batch {label}: empty/failed, skipping")

        if max_batches and batch_num >= max_batches:
            logger.info(f"  Reached max_batches={max_batches}, stopping.")
            break

    if not batch_runbooks:
        return {"status": "error", "message": "No content generated from any batch."}

    def _sort_key(k):
        parts = str(k).split("_")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)

    sorted_runbooks = [batch_runbooks[k] for k in sorted(batch_runbooks, key=_sort_key)]

    if len(sorted_runbooks) == 1:
        final_runbook = sorted_runbooks[0]
    else:
        logger.info(f"\nMerging {len(sorted_runbooks)} batch runbooks via StreamAssist...")
        merge_parts = [MERGE_PROMPT]
        for i, rb in enumerate(sorted_runbooks, 1):
            merge_parts.append(f"\n\n--- BATCH {i} ---\n\n{rb}")
        merge_prompt = "\n".join(merge_parts)

        merge_start = time.time()
        final_runbook = _stream_assist(client, merge_prompt)
        logger.info(f"Merge done in {_fmt_duration(time.time() - merge_start)}")

    logger.info("Saving runbook to Drive...")
    _save_runbook_to_drive(drive_service, final_runbook)
    logger.info("Runbook saved to Drive successfully.")

    total_time = _fmt_duration(time.time() - run_start)
    logger.info(
        f"\n{'='*60}\n"
        f"  DIRECT RUNBOOK COMPLETE\n"
        f"  Threads processed : {total_threads}\n"
        f"  Batches           : {batch_num}\n"
        f"  Total time        : {total_time}\n"
        f"  Saved to Drive    : {RUNBOOK_FOLDER_NAME}/{RUNBOOK_FILENAME}\n"
        f"{'='*60}"
    )

    return {
        "status": "ok",
        "message": f"Runbook generated from {total_threads} threads across {batch_num} batches in {total_time}.",
        "folder": RUNBOOK_FOLDER_NAME,
        "file": RUNBOOK_FILENAME,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-batches", type=int, default=0, help="Limit batches (0 = all)")
    args = parser.parse_args()
    result = generate_direct_runbook(max_batches=args.max_batches)
    print(result)
