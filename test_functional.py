import io
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_raw_email(from_addr="vendor@example.com", subject="Contract", filename="doc.pdf", payload=b"data"):
    import email
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["Subject"] = subject
    part = MIMEBase("application", "octet-stream")
    part.set_payload(payload)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment", filename=filename)
    msg.attach(part)
    return msg.as_bytes()


# ── 1. Health endpoint ─────────────────────────────────────────────────────────

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_returns_ok_status():
    resp = client.get("/health")
    assert resp.json() == {"status": "ok"}


# ── 2. /run with no emails ────────────────────────────────────────────────────

def test_run_no_emails_returns_200():
    with patch("main.fetch_new_vendor_emails", return_value=[]):
        resp = client.post("/run")
    assert resp.status_code == 200


def test_run_no_emails_returns_zero_processed():
    with patch("main.fetch_new_vendor_emails", return_value=[]):
        resp = client.post("/run")
    assert resp.json()["processed"] == 0


def test_run_no_emails_message():
    with patch("main.fetch_new_vendor_emails", return_value=[]):
        resp = client.post("/run")
    assert "No new vendor emails" in resp.json()["message"]


# ── 3. /run with emails ───────────────────────────────────────────────────────

def test_run_processes_emails():
    mail_mock = MagicMock()
    emails = [{"from": "v@example.com", "attachments": [("a.pdf", b"data")], "num": b"1", "mail": mail_mock}]
    upload_result = {"action": "created", "file_id": "abc", "filename": "a.pdf"}
    with patch("main.fetch_new_vendor_emails", return_value=emails), \
         patch("main.upload_vendor_attachment", return_value=upload_result), \
         patch("main.mark_as_processed"):
        resp = client.post("/run")
    assert resp.json()["processed"] == 1


def test_run_returns_upload_filenames():
    mail_mock = MagicMock()
    emails = [{"from": "v@example.com", "attachments": [("contract.pdf", b"data")], "num": b"1", "mail": mail_mock}]
    upload_result = {"action": "created", "file_id": "abc", "filename": "contract.pdf"}
    with patch("main.fetch_new_vendor_emails", return_value=emails), \
         patch("main.upload_vendor_attachment", return_value=upload_result), \
         patch("main.mark_as_processed"):
        resp = client.post("/run")
    assert resp.json()["uploads"][0]["filename"] == "contract.pdf"


def test_run_calls_mark_as_processed():
    mail_mock = MagicMock()
    emails = [{"from": "v@example.com", "attachments": [("a.pdf", b"data")], "num": b"1", "mail": mail_mock}]
    upload_result = {"action": "created", "file_id": "abc", "filename": "a.pdf"}
    with patch("main.fetch_new_vendor_emails", return_value=emails), \
         patch("main.upload_vendor_attachment", return_value=upload_result), \
         patch("main.mark_as_processed") as mock_mark:
        client.post("/run")
    mock_mark.assert_called_once()


def test_run_multiple_attachments():
    mail_mock = MagicMock()
    emails = [{"from": "v@example.com", "attachments": [("a.pdf", b"d1"), ("b.pdf", b"d2")], "num": b"1", "mail": mail_mock}]
    upload_result = {"action": "created", "file_id": "abc", "filename": "x.pdf"}
    with patch("main.fetch_new_vendor_emails", return_value=emails), \
         patch("main.upload_vendor_attachment", return_value=upload_result), \
         patch("main.mark_as_processed"):
        resp = client.post("/run")
    assert len(resp.json()["uploads"]) == 2


# ── 4. Gmail reader ───────────────────────────────────────────────────────────

def test_skip_already_labelled_email():
    from gmail_reader import fetch_new_vendor_emails, PROCESSED_LABEL

    mail_mock = MagicMock()
    mail_mock.search.return_value = (None, [b"1"])
    mail_mock.fetch.side_effect = [
        (None, [(b"1 (X-GM-LABELS (contractsexplorer-processed-doc))", b"")]),
    ]

    with patch("gmail_reader.imaplib.IMAP4_SSL") as mock_imap:
        mock_imap.return_value = mail_mock
        mail_mock.login.return_value = ("OK", [])
        mail_mock.select.return_value = ("OK", [])
        mail_mock.create.return_value = ("OK", [])
        mail_mock.search.return_value = (None, [b"1"])
        label_response = (None, [(b'1 (X-GM-LABELS (contractsexplorer-processed-doc))', b"")])
        mail_mock.fetch.return_value = label_response
        results = fetch_new_vendor_emails()

    assert results == []


def test_fetch_email_with_attachment():
    from gmail_reader import fetch_new_vendor_emails

    raw = _make_raw_email(filename="invoice.pdf", payload=b"pdfdata")
    mail_mock = MagicMock()

    with patch("gmail_reader.imaplib.IMAP4_SSL") as mock_imap:
        mock_imap.return_value = mail_mock
        mail_mock.login.return_value = ("OK", [])
        mail_mock.select.return_value = ("OK", [])
        mail_mock.create.return_value = ("OK", [])
        mail_mock.search.return_value = (None, [b"1"])
        mail_mock.fetch.side_effect = [
            (None, [b"no-label"]),
            (None, [(b"1", raw)]),
        ]
        results = fetch_new_vendor_emails()

    assert len(results) == 1
    assert results[0]["attachments"][0][0] == "invoice.pdf"


def test_mark_as_processed_adds_label():
    from gmail_reader import mark_as_processed, PROCESSED_LABEL

    mail_mock = MagicMock()
    mark_as_processed(mail_mock, b"1")
    mail_mock.store.assert_any_call(b"1", "+X-GM-LABELS", PROCESSED_LABEL)


def test_mark_as_processed_keeps_unread():
    from gmail_reader import mark_as_processed

    mail_mock = MagicMock()
    mark_as_processed(mail_mock, b"1")
    mail_mock.store.assert_any_call(b"1", "-FLAGS", "\\Seen")


def test_empty_inbox_returns_empty_list():
    from gmail_reader import fetch_new_vendor_emails

    mail_mock = MagicMock()
    with patch("gmail_reader.imaplib.IMAP4_SSL") as mock_imap:
        mock_imap.return_value = mail_mock
        mail_mock.login.return_value = ("OK", [])
        mail_mock.select.return_value = ("OK", [])
        mail_mock.create.return_value = ("OK", [])
        mail_mock.search.return_value = (None, [b""])
        results = fetch_new_vendor_emails()

    assert results == []


# ── 5. Drive uploader ─────────────────────────────────────────────────────────

def test_upload_creates_vendor_subfolder():
    from drive_uploader import upload_vendor_attachment

    service_mock = MagicMock()
    service_mock.files().list().execute.return_value = {"files": []}
    service_mock.files().create().execute.side_effect = [
        {"id": "folder-id"},
        {"id": "file-id"},
    ]

    with patch("drive_uploader._get_drive_service", return_value=service_mock):
        result = upload_vendor_attachment("vendor@x.com", "doc.pdf", b"data")

    assert result["action"] == "created"


def test_upload_versions_duplicate_filename():
    from drive_uploader import upload_vendor_attachment

    service_mock = MagicMock()
    # subfolder exists
    service_mock.files().list().execute.side_effect = [
        {"files": [{"id": "folder-id"}]},
        {"files": [{"id": "existing"}]},
        {"files": []},
    ]
    service_mock.files().create().execute.return_value = {"id": "new-file-id"}

    with patch("drive_uploader._get_drive_service", return_value=service_mock):
        result = upload_vendor_attachment("vendor@x.com", "doc.pdf", b"data")

    assert result["action"] == "versioned"
    assert "_v2" in result["filename"]


def test_vendor_name_extracted_from_email():
    from main import vendor_name_from_email
    assert vendor_name_from_email("Vendor Name <vendor@example.com>") == "vendor@example.com"


def test_vendor_name_plain_email():
    from main import vendor_name_from_email
    assert vendor_name_from_email("vendor@example.com") == "vendor@example.com"


def test_vendor_name_unknown_fallback():
    from main import vendor_name_from_email
    assert vendor_name_from_email("no-email-here") == "unknown-vendor"
