#!/usr/bin/env python3
"""A historian message that is not emailed is kept in full on the disk.

POST /contact emails the historian.  When email is not configured, has no
recipient, or the send fails, the whole message (and any recording) goes to
contact_failures.jsonl, so a failure loses nothing (30 October 2026).  A
message that is sent is not kept there.

    python3 _test/test_contact_failures_kept.py
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


class _FailingSMTP:
    def __init__(self, *a, **k):
        raise OSError("connection refused")


class _SendingSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        _SendingSMTP.sent.append(msg)


def main():
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    tmp = tempfile.mkdtemp(prefix="contactfail-")
    m.CONTACT_FAILURES_PATH = os.path.join(tmp, "contact_failures.jsonl")
    m.CONTACT_FAILURES_AUDIO_DIR = os.path.join(tmp, "contact_failures_audio")
    client = TestClient(m.app)
    rows = lambda: [json.loads(l) for l in open(m.CONTACT_FAILURES_PATH)] if os.path.exists(m.CONTACT_FAILURES_PATH) else []

    def post(q, audio=None):
        files = {"audio": ("q.webm", audio, "audio/webm")} if audio else None
        return client.post("/contact", data={"question_text": q, "visitor_response": "reach me at v@example.org", "lang": "en"}, files=files)

    m.SMTP_USER, m.SMTP_PASS, m.HISTORIAN_EMAIL = "", "", ""
    post("No email configured?")
    r = rows()[-1] if rows() else {}
    check("unconfigured email keeps the message", r.get("question") == "No email configured?"
          and r.get("visitor_response") == "reach me at v@example.org" and "SMTP" in r.get("reason", ""), str(r))

    m.SMTP_USER, m.SMTP_PASS, m.HISTORIAN_EMAIL = "u", "p", ""
    post("No recipient?")
    check("missing recipient keeps the message", rows()[-1].get("reason") == "HISTORIAN_EMAIL not set")

    m.HISTORIAN_EMAIL = "h@example.org"
    real = m.smtplib.SMTP
    m.smtplib.SMTP = _FailingSMTP
    try:
        res = post("Send fails?", audio=b"RIFF-recording")
    finally:
        m.smtplib.SMTP = real
    r = rows()[-1]
    check("failed send keeps the message", r.get("question") == "Send fails?" and r.get("reason", "").startswith("send failed"), str(r))
    check("failed send still reports an error", res.json().get("status") == "error")
    audio = os.path.join(m.CONTACT_FAILURES_AUDIO_DIR, r.get("audio_file") or "-")
    check("recording kept beside it", os.path.exists(audio) and open(audio, "rb").read() == b"RIFF-recording")
    check("full email body kept", "No email configured?" not in r.get("body", "") and "Send fails?" in r.get("body", ""))

    before = len(rows())
    m.smtplib.SMTP = _SendingSMTP
    try:
        res = post("Sent fine?", audio=b"RIFF-two")
    finally:
        m.smtplib.SMTP = real
    check("a sent message is emailed with its recording", res.json().get("status") == "sent" and len(_SendingSMTP.sent) == 1
          and any(p.get_filename() == "question.webm" for p in _SendingSMTP.sent[0].walk()))
    check("a sent message is not kept as a failure", len(rows()) == before)

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
