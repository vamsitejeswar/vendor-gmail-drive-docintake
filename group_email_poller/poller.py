import email
import imaplib
import logging
import os
import re
import time
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

logger = logging.getLogger(__name__)

GROUP_EMAIL = os.getenv("GROUP_EMAIL", "test_contract@verse.in")
MEMBER_EMAIL = os.getenv("GROUP_MEMBER_EMAIL", "")
MEMBER_APP_PASSWORD = os.getenv("GROUP_MEMBER_APP_PASSWORD", "")
# Only these attachment types are stored — everything else (images, etc.) is skipped
ALLOWED_ATTACHMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
INTERNAL_DOMAIN = "verse.in"

# Batch sizes for IMAP — reduces round trips from 13000 to ~130
IMAP_HEADER_BATCH = 100   # headers fetched per IMAP command
IMAP_BODY_BATCH = 50      # full RFC822 bodies fetched per IMAP command
IMAP_BATCH_DELAY = 0.1    # seconds between batches — avoids Gmail rate limiting

# Emails/domains to skip entirely — set in .env (comma-separated)
_EXCLUDED_EMAILS = {e.strip().lower() for e in os.getenv("EXCLUDED_EMAILS", "").split(",") if e.strip()}
_EXCLUDED_DOMAINS = {d.strip().lower() for d in os.getenv("EXCLUDED_DOMAINS", "").split(",") if d.strip()}


def _is_excluded(address: str) -> bool:
    addr = address.lower()
    if any(ex in addr for ex in _EXCLUDED_EMAILS):
        return True
    if any(f"@{d}" in addr for d in _EXCLUDED_DOMAINS):
        return True
    return False


def _connect():
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(MEMBER_EMAIL, MEMBER_APP_PASSWORD)
    return mail


def _decode_header_value(value: str) -> str:
    parts = decode_header(value or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return " ".join(decoded).strip()


def _extract_body(msg) -> str:
    body = ""
    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = part.get_content_disposition()
        if content_type == "text/plain" and disposition != "attachment":
            raw = part.get_payload(decode=True)
            if raw and not body:
                body = raw.decode("utf-8", errors="ignore")
    return body.strip()


def _extract_attachments(msg) -> list:
    attachments = []
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            filename = part.get_filename()
            if not filename:
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
                logger.debug(f"  Skipping attachment (not PDF/DOC/TXT): {filename}")
                continue
            file_bytes = part.get_payload(decode=True)
            if file_bytes:
                attachments.append((filename, file_bytes))
    return attachments


def _get_real_from(msg) -> str:
    for header in ("Reply-To", "X-Original-Sender", "X-Google-Original-From"):
        val = msg.get(header, "")
        if val:
            return _decode_header_value(val)
    return _decode_header_value(msg.get("From", ""))


def _extract_vendor_name(emails: list) -> str:
    for e in emails:
        match = re.search(r"([\w.+-]+@[\w.-]+)", e.get("from", ""))
        if match:
            full_email = match.group(1).lower()
            domain = full_email.split("@")[1]
            if INTERNAL_DOMAIN not in domain:
                return full_email  # e.g. ishita.shah@dentsu.com
    return "unknown-vendor"


def _group_into_threads(emails: list) -> dict:
    threads = {}
    id_to_subject = {}

    for e in emails:
        msg_id = e.get("message_id", "").strip()
        in_reply_to = e.get("in_reply_to", "").strip()
        references = e.get("references", "").strip()
        subject = e.get("subject", "No Subject")

        thread_key = None

        if references:
            for ref in references.split():
                if ref in id_to_subject:
                    thread_key = id_to_subject[ref]
                    break

        if not thread_key and in_reply_to and in_reply_to in id_to_subject:
            thread_key = id_to_subject[in_reply_to]

        if not thread_key:
            clean_subject = re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()
            thread_key = clean_subject or subject

        if msg_id:
            id_to_subject[msg_id] = thread_key

        if thread_key not in threads:
            threads[thread_key] = []
        threads[thread_key].append(e)

    for key in threads:
        threads[key].sort(key=lambda x: x.get("date", ""))

    return threads


# ── Batched header fetch ──────────────────────────────────────────────────────

def _parse_header(raw_bytes, num, mailbox, direction) -> dict | None:
    try:
        msg = email.message_from_bytes(raw_bytes)
        return {
            "num": num,
            "mailbox": mailbox,
            "direction": direction,
            "message_id": msg.get("Message-ID", "").strip(),
            "in_reply_to": msg.get("In-Reply-To", "").strip(),
            "references": msg.get("References", "").strip(),
            "from": _get_real_from(msg),
            "to": _decode_header_value(msg.get("To", "")),
            "cc": _decode_header_value(msg.get("Cc", "")),
            "subject": _decode_header_value(msg.get("Subject", "No Subject")),
            "date": msg.get("Date", ""),
        }
    except Exception as e:
        logger.warning(f"Header parse failed for num {num}: {e}")
        return None


def _batch_fetch_headers(connect_fn, nums: list, imap_folder: str, direction: str) -> list:
    """
    Fetch BODY[HEADER] for a list of message numbers in batches of IMAP_HEADER_BATCH.
    Manages its own IMAP connection — reconnects proactively every 50 batches and
    on any SSL/connection failure, so long header fetches never die mid-run.
    """
    results = []
    total_batches = (len(nums) + IMAP_HEADER_BATCH - 1) // IMAP_HEADER_BATCH
    mail = connect_fn()
    RECONNECT_EVERY = 50  # proactively reconnect every N batches to keep session fresh

    for i in range(0, len(nums), IMAP_HEADER_BATCH):
        batch = nums[i: i + IMAP_HEADER_BATCH]
        batch_str = b",".join(batch)
        batch_num = i // IMAP_HEADER_BATCH + 1

        # Proactive reconnect to prevent Gmail from dropping a long-lived connection
        if batch_num > 1 and (batch_num - 1) % RECONNECT_EVERY == 0:
            logger.info(f"  Proactive IMAP reconnect at batch {batch_num}/{total_batches}...")
            try:
                mail.logout()
            except Exception:
                pass
            time.sleep(1)
            mail = connect_fn()

        if batch_num % 10 == 0 or batch_num == 1 or batch_num == total_batches:
            logger.info(f"  Header batch {batch_num}/{total_batches} ({len(batch)} emails)...")

        try:
            _, msg_data = mail.fetch(batch_str, "(BODY[HEADER])")
            for item in msg_data:
                if not isinstance(item, tuple):
                    continue
                info = item[0].decode(errors="ignore") if isinstance(item[0], bytes) else item[0]
                m = re.match(r"(\S+)", info)
                num = m.group(1).encode() if m else batch[0]
                h = _parse_header(item[1], num, imap_folder, direction)
                if h:
                    results.append(h)
        except Exception as e:
            logger.warning(f"Header batch {batch_num} failed: {e} — reconnecting and retrying one by one")
            try:
                mail.logout()
            except Exception:
                pass
            time.sleep(2)
            mail = connect_fn()
            for num in batch:
                try:
                    _, msg_data = mail.fetch(num, "(BODY[HEADER])")
                    raw = msg_data[0]
                    if isinstance(raw, tuple):
                        h = _parse_header(raw[1], num, imap_folder, direction)
                        if h:
                            results.append(h)
                except Exception as e2:
                    logger.warning(f"  Single fetch failed for {num}: {e2} — reconnecting for next")
                    try:
                        mail.logout()
                    except Exception:
                        pass
                    time.sleep(1)
                    mail = connect_fn()

        if IMAP_BATCH_DELAY:
            time.sleep(IMAP_BATCH_DELAY)

    try:
        mail.logout()
    except Exception:
        pass

    return results


def _fetch_inbox_headers(mail) -> list:
    try:
        mail.select("INBOX")
    except Exception:
        return []

    seen_nums = set()
    all_nums = []
    for criteria in [f'TO "{GROUP_EMAIL}"', f'CC "{GROUP_EMAIL}"']:
        try:
            _, nums = mail.search(None, criteria)
            for n in (nums[0].split() if nums[0] else []):
                if n not in seen_nums:
                    seen_nums.add(n)
                    all_nums.append(n)
        except Exception:
            pass

    logger.info(f"Inbox: {len(all_nums)} matching emails — fetching headers in batches of {IMAP_HEADER_BATCH}...")

    def connect_inbox():
        m = _connect()
        m.select("INBOX")
        return m

    return _batch_fetch_headers(connect_inbox, all_nums, "INBOX", "RECEIVED")


def _fetch_sent_headers(mail) -> list:
    for sent_folder in ('"[Gmail]/Sent Mail"', "Sent", '"[Gmail]/Sent"'):
        try:
            status, _ = mail.select(sent_folder)
            if status != "OK":
                continue

            matching_nums: set = set()
            for criteria in [f'TO "{GROUP_EMAIL}"', f'CC "{GROUP_EMAIL}"', f'FROM "{GROUP_EMAIL}"']:
                try:
                    _, nums = mail.search(None, criteria)
                    for n in (nums[0].split() if nums[0] else []):
                        matching_nums.add(n)
                except Exception:
                    pass

            all_nums = list(matching_nums)
            logger.info(f"Sent: {len(all_nums)} matching emails (SEARCH filtered) — fetching headers in batches of {IMAP_HEADER_BATCH}...")
            _sent_folder = sent_folder

            def connect_sent():
                m = _connect()
                m.select(_sent_folder)
                return m

            results = _batch_fetch_headers(connect_sent, all_nums, _sent_folder, "SENT")
            logger.info(f"Sent: {len(results)} headers parsed")
            return results
        except Exception:
            continue
    return []


# ── Batched body fetch ────────────────────────────────────────────────────────

def _fetch_bodies_for_mailbox(mail, mailbox: str, nums: list) -> dict:
    """
    Fetch RFC822 for a list of nums in one mailbox in batches of IMAP_BODY_BATCH.
    Returns {num: parsed_email_message}.
    """
    bodies = {}
    try:
        mail.select(mailbox)
    except Exception as e:
        logger.warning(f"Cannot select {mailbox}: {e}")
        return bodies

    total_batches = (len(nums) + IMAP_BODY_BATCH - 1) // IMAP_BODY_BATCH
    for i in range(0, len(nums), IMAP_BODY_BATCH):
        batch = nums[i: i + IMAP_BODY_BATCH]
        batch_str = b",".join(batch)
        batch_num = i // IMAP_BODY_BATCH + 1

        try:
            _, msg_data = mail.fetch(batch_str, "(RFC822)")
            for item in msg_data:
                if not isinstance(item, tuple):
                    continue
                try:
                    info = item[0].decode(errors="ignore") if isinstance(item[0], bytes) else item[0]
                    m = re.match(r"(\S+)", info)
                    num = m.group(1).encode() if m else batch[0]
                    bodies[num] = email.message_from_bytes(item[1])
                except Exception as e:
                    logger.warning(f"Body parse failed for one item in batch {batch_num}: {e} — skipping")
        except Exception as e:
            logger.warning(f"Body batch {batch_num}/{total_batches} failed: {e} — retrying one by one")
            for num in batch:
                try:
                    _, msg_data = mail.fetch(num, "(RFC822)")
                    raw = msg_data[0]
                    if isinstance(raw, tuple):
                        bodies[num] = email.message_from_bytes(raw[1])
                except Exception as e2:
                    logger.warning(f"  Single body fetch failed for {num}: {e2} — skipping")

        if IMAP_BATCH_DELAY:
            time.sleep(IMAP_BATCH_DELAY)

    return bodies


def _enrich_with_body(header: dict, msg) -> dict:
    return {
        **header,
        "body": _extract_body(msg),
        "attachments": _extract_attachments(msg),
    }


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_group_email_threads() -> list:
    """Fetch all threads (full body) — for small inboxes."""
    mail = _connect()
    inbox_headers = _fetch_inbox_headers(mail)
    sent_headers = _fetch_sent_headers(mail)

    seen_ids = set()
    all_headers = []
    for h in inbox_headers + sent_headers:
        mid = h.get("message_id", "").strip()
        if mid and mid in seen_ids:
            continue
        if mid:
            seen_ids.add(mid)
        combined = " ".join([h.get("from", ""), h.get("to", ""), h.get("cc", "")])
        if _is_excluded(combined):
            logger.info(f"  EXCLUDED: {h.get('from', '')} — {h.get('subject', '')}")
            continue
        all_headers.append(h)

    threads = _group_into_threads(all_headers)

    by_mailbox: dict[str, list] = {}
    for h in all_headers:
        by_mailbox.setdefault(h["mailbox"], []).append(h["num"])

    body_map: dict[tuple, object] = {}
    for mailbox, nums in by_mailbox.items():
        bodies = _fetch_bodies_for_mailbox(mail, mailbox, nums)
        for num, msg in bodies.items():
            body_map[(mailbox, num)] = msg

    mail.logout()

    result = []
    for subject, emails in threads.items():
        full_emails = []
        all_attachments = []
        for h in emails:
            msg = body_map.get((h["mailbox"], h["num"]))
            if msg:
                full_email = _enrich_with_body(h, msg)
            else:
                full_email = {**h, "body": "", "attachments": []}
            full_emails.append(full_email)
            all_attachments.extend(full_email["attachments"])

        vendor = _extract_vendor_name(full_emails)
        first_date = full_emails[0].get("date", "")[:10].replace(" ", "-")
        result.append({
            "subject": subject,
            "vendor": vendor,
            "date": first_date,
            "emails": full_emails,
            "attachments": all_attachments,
        })

    return result


def fetch_group_email_threads_bulk(batch_size: int = 50, skip_batches: set = None):
    """
    Generator for bulk processing of large inboxes (13,000+ emails).

    Phase 1: one IMAP connection — batch-fetch all headers (100 per IMAP command).
    Phase 2: group into threads in memory.
    Phase 3: fresh IMAP connection per thread-batch — batch-fetch full bodies (50 per command).
              Batches in skip_batches get no body fetch — yields [] instantly.

    For 13,000 emails this reduces IMAP round trips from ~13,000 to ~130.
    Reconnecting per batch prevents idle timeout drops on long runs.
    """
    # ── Phase 1: header fetch ────────────────────────────────────────────────
    logger.info("Phase 1: fetching headers (batched)...")
    mail = _connect()
    try:
        inbox_headers = _fetch_inbox_headers(mail)
        sent_headers = _fetch_sent_headers(mail)
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    seen_ids: set = set()
    all_headers = []
    excluded_count = 0
    for h in inbox_headers + sent_headers:
        mid = h.get("message_id", "").strip()
        if mid and mid in seen_ids:
            continue
        if mid:
            seen_ids.add(mid)
        combined = " ".join([h.get("from", ""), h.get("to", ""), h.get("cc", "")])
        if _is_excluded(combined):
            excluded_count += 1
            continue
        all_headers.append(h)

    logger.info(
        f"Headers: {len(all_headers)} unique emails "
        f"({excluded_count} excluded by EXCLUDED_EMAILS/EXCLUDED_DOMAINS)"
    )

    # ── Phase 2: group ───────────────────────────────────────────────────────
    logger.info(f"Phase 2: grouping {len(all_headers)} emails into threads...")
    threads = _group_into_threads(all_headers)
    thread_list = list(threads.items())
    total = len(thread_list)
    total_batches = (total + batch_size - 1) // batch_size
    logger.info(f"Found {total} threads — processing in {total_batches} batches of {batch_size}")

    # ── Phase 3: body fetch per batch (fresh connection, batched RFC822) ─────
    for batch_start in range(0, total, batch_size):
        batch = thread_list[batch_start: batch_start + batch_size]
        batch_num = batch_start // batch_size + 1

        if skip_batches and batch_num in skip_batches:
            logger.info(f"Batch {batch_num}/{total_batches}: skipping body fetch (checkpoint exists)")
            yield []
            continue

        logger.info(f"Batch {batch_num}/{total_batches}: fetching bodies for {len(batch)} threads...")

        by_mailbox: dict[str, list] = {}
        for _, email_headers in batch:
            for h in email_headers:
                by_mailbox.setdefault(h["mailbox"], []).append(h["num"])

        mail = _connect()
        body_map: dict[tuple, object] = {}
        try:
            for mailbox, nums in by_mailbox.items():
                bodies = _fetch_bodies_for_mailbox(mail, mailbox, nums)
                for num, msg in bodies.items():
                    body_map[(mailbox, num)] = msg
        finally:
            try:
                mail.logout()
            except Exception:
                pass

        enriched = []
        for subject, email_headers in batch:
            full_emails = []
            all_attachments = []
            for h in email_headers:
                msg = body_map.get((h["mailbox"], h["num"]))
                if msg:
                    full_email = _enrich_with_body(h, msg)
                else:
                    full_email = {**h, "body": "", "attachments": []}
                full_emails.append(full_email)
                all_attachments.extend(full_email["attachments"])

            vendor = _extract_vendor_name(full_emails)
            first_date = full_emails[0].get("date", "")[:10].replace(" ", "-")
            enriched.append({
                "subject": subject,
                "vendor": vendor,
                "date": first_date,
                "emails": full_emails,
                "attachments": all_attachments,
            })

        yield enriched

    logger.info("All batches complete.")
