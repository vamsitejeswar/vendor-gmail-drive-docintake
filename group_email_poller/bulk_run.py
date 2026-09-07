"""
Bulk run: fetch all group email threads, upload to Drive, then generate runbook.

Usage (from repo root):
    source venv/bin/activate
    python group_email_poller/bulk_run.py

Options:
    --batch-size N        Threads per IMAP fetch batch (default: 50)
    --skip-upload         Skip email upload — only generate runbook from existing Drive docs
    --skip-runbook        Upload emails but skip runbook generation
    --pause               Pause a running bulk_run (creates bulk_run.pause file)
    --resume              Resume a paused bulk_run (removes bulk_run.pause file)

Pause/Resume:
    While running: python group_email_poller/bulk_run.py --pause
    To continue:   python group_email_poller/bulk_run.py --resume

Resume after crash: re-run the same command — already-uploaded threads are skipped
automatically via the Drive index built at startup.
"""

import argparse
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from poller import fetch_group_email_threads_bulk
from drive_writer import build_existing_threads_index, thread_key, upload_thread_to_drive
from runbook_generator import generate_runbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bulk_run")

# Sentinel file: create to pause, delete to resume
PAUSE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bulk_run.pause")


def _check_pause(total_threads: int, label: str):
    """Block here until the pause file is gone. Logs on enter/exit."""
    if not os.path.exists(PAUSE_FILE):
        return
    logger.info(
        f"\n{'='*60}\n"
        f"  ⏸  PAUSED at thread #{total_threads} — {label}\n"
        f"  To resume: python group_email_poller/bulk_run.py --resume\n"
        f"  (or: rm bulk_run.pause)\n"
        f"{'='*60}"
    )
    while os.path.exists(PAUSE_FILE):
        time.sleep(5)
    logger.info(
        f"\n{'='*60}\n"
        f"  ▶  RESUMED — continuing from thread #{total_threads}\n"
        f"{'='*60}"
    )


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def run_upload(batch_size: int):
    logger.info("Building Drive index of already-uploaded threads...")
    existing = build_existing_threads_index()

    total_uploaded = 0
    total_skipped = 0
    total_errors = 0
    total_threads = 0
    batch_num = 0
    run_start = time.time()

    for batch in fetch_group_email_threads_bulk(batch_size=batch_size):
        batch_num += 1
        batch_start = time.time()
        batch_uploaded = 0
        batch_skipped = 0
        batch_errors = 0

        logger.info(
            f"\n{'='*60}\n"
            f"  BATCH {batch_num} — {len(batch)} threads\n"
            f"  Progress so far: {total_threads} threads processed "
            f"| {total_uploaded} uploaded | {total_skipped} skipped | {total_errors} errors\n"
            f"  Elapsed: {_fmt_duration(time.time() - run_start)}\n"
            f"{'='*60}"
        )

        for i, thread in enumerate(batch, 1):
            total_threads += 1
            subject = thread.get("subject", "—")
            vendor = thread.get("vendor", "—")
            n_emails = len(thread.get("emails", []))
            n_docs = len(thread.get("attachments", []))
            label = f"[{vendor}] {subject[:55]}"

            # Pause if requested (blocks here until resumed)
            _check_pause(total_threads, label)

            logger.info(
                f"  [{i}/{len(batch)}] thread #{total_threads} — "
                f"{label} | emails={n_emails} docs={n_docs}"
            )

            try:
                if thread_key(thread) in existing:
                    logger.info(f"    → SKIP (already in Drive)")
                    total_skipped += 1
                    batch_skipped += 1
                    continue

                result = upload_thread_to_drive(thread)
                existing.add(thread_key(thread))
                total_uploaded += 1
                batch_uploaded += 1
                doc_names = result["attachments"] if result["attachments"] else ["none"]
                logger.info(f"    → UPLOADED ✓ | docs: {', '.join(doc_names)}")

            except Exception as e:
                import traceback
                total_errors += 1
                batch_errors += 1
                logger.error(f"    → ERROR (skipping, will not retry): {e}")
                logger.error(traceback.format_exc())
                logger.error(f"    CHECKPOINT: last attempted thread #{total_threads} — {label}")

        batch_elapsed = time.time() - batch_start
        total_elapsed = time.time() - run_start
        threads_per_sec = total_threads / total_elapsed if total_elapsed > 0 else 0

        logger.info(
            f"\n  Batch {batch_num} done in {_fmt_duration(batch_elapsed)} — "
            f"uploaded={batch_uploaded} skipped={batch_skipped} errors={batch_errors}\n"
            f"  Running total: {total_threads} processed | "
            f"{total_uploaded} uploaded | {total_skipped} skipped | {total_errors} errors\n"
            f"  Speed: {threads_per_sec:.1f} threads/sec | "
            f"Elapsed: {_fmt_duration(total_elapsed)}"
        )

    logger.info(
        f"\n{'='*60}\n"
        f"  UPLOAD COMPLETE\n"
        f"  Threads processed : {total_threads}\n"
        f"  Uploaded          : {total_uploaded}\n"
        f"  Skipped (exists)  : {total_skipped}\n"
        f"  Errors            : {total_errors}\n"
        f"  Total time        : {_fmt_duration(time.time() - run_start)}\n"
        f"{'='*60}"
    )
    return total_uploaded, total_skipped, total_errors


def run_runbook():
    logger.info(
        f"\n{'='*60}\n"
        f"  RUNBOOK GENERATION\n"
        f"{'='*60}"
    )
    start = time.time()
    result = generate_runbook()
    elapsed = time.time() - start
    if result["status"] == "ok":
        logger.info(
            f"  Runbook done in {_fmt_duration(elapsed)}\n"
            f"  {result['message']}"
        )
    else:
        logger.error(f"  Runbook failed: {result['message']}")


def main(batch_size: int = 50, skip_upload: bool = False, skip_runbook: bool = False):
    logger.info(
        f"\n{'='*60}\n"
        f"  GROUP EMAIL BULK RUN\n"
        f"  batch_size={batch_size} | skip_upload={skip_upload} | skip_runbook={skip_runbook}\n"
        f"{'='*60}"
    )
    overall_start = time.time()

    if not skip_upload:
        run_upload(batch_size)
    else:
        logger.info("Skipping email upload (--skip-upload)")

    if not skip_runbook:
        run_runbook()
    else:
        logger.info("Skipping runbook generation (--skip-runbook)")

    logger.info(
        f"\n{'='*60}\n"
        f"  ALL DONE — total time: {_fmt_duration(time.time() - overall_start)}\n"
        f"{'='*60}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bulk upload group emails + generate runbook")
    parser.add_argument("--batch-size", type=int, default=50, help="Threads per IMAP batch (default: 50)")
    parser.add_argument("--skip-upload", action="store_true", help="Skip email upload, only generate runbook")
    parser.add_argument("--skip-runbook", action="store_true", help="Upload emails but skip runbook generation")
    parser.add_argument("--pause", action="store_true", help="Pause a running bulk_run (creates bulk_run.pause)")
    parser.add_argument("--resume", action="store_true", help="Resume a paused bulk_run (removes bulk_run.pause)")
    args = parser.parse_args()

    if args.pause:
        open(PAUSE_FILE, "w").close()
        print(f"PAUSED — created {PAUSE_FILE}")
        print("Run with --resume when ready to continue.")
        sys.exit(0)

    if args.resume:
        if os.path.exists(PAUSE_FILE):
            os.remove(PAUSE_FILE)
            print(f"RESUMED — removed {PAUSE_FILE}")
        else:
            print("Not paused (no pause file found). Run is already running or finished.")
        sys.exit(0)

    main(batch_size=args.batch_size, skip_upload=args.skip_upload, skip_runbook=args.skip_runbook)
