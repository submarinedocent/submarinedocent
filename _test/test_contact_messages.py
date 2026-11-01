#!/usr/bin/env python3
"""Both visitor forms keep every message and email the historian about it.

Historian messages (POST /contact) are kept in contact_messages.jsonl before any
send is tried, with any recording beside them.  Contact-form messages (POST
/feedback, source "contact") are kept in feedback.jsonl and now emailed too:
storing a message without telling anyone is not enough (Irving, 31 October
2026).  A message from either form that is not emailed (no credentials, no
recipient, or a failed send) is also listed, with the reason, in
contact_failures.jsonl.  Replaces test_contact_failures_kept.py (30 October).

    python3 _test/test_contact_messages.py
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
    on_send = None

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
        if _SendingSMTP.on_send:
            _SendingSMTP.on_send()
        _SendingSMTP.sent.append(msg)


def rows(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def main():
    # Empty, not unset: .env.local fills unset variables and holds the real mail
    # account.  Every send below goes to a stand-in SMTP class.
    os.environ.update({"SMTP_USER": "", "SMTP_PASS": "", "HISTORIAN_EMAIL": ""})
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    tmp = tempfile.mkdtemp(prefix="contactmsgs-")
    m.CONTACT_MESSAGES_PATH = os.path.join(tmp, "contact_messages.jsonl")
    m.CONTACT_MESSAGES_AUDIO_DIR = os.path.join(tmp, "contact_messages_audio")
    m.CONTACT_FAILURES_PATH = os.path.join(tmp, "contact_failures.jsonl")
    m.FEEDBACK_PATH = os.path.join(tmp, "feedback.jsonl")
    client = TestClient(m.app)
    real = m.smtplib.SMTP
    msgs = lambda: rows(m.CONTACT_MESSAGES_PATH)
    fails = lambda: rows(m.CONTACT_FAILURES_PATH)

    def historian(q, audio=None):
        files = {"audio": ("q.webm", audio, "audio/webm")} if audio else None
        return client.post("/contact", data={"question_text": q, "visitor_response": "reach me at v@example.org",
                                             "lang": "en"}, files=files)

    def contact_form(message, email="v@example.org"):
        return client.post("/feedback", json={"source": "contact", "name": "Visitor", "email": email, "message": message})

    def sending(fn):
        _SendingSMTP.sent = []
        m.smtplib.SMTP = _SendingSMTP
        try:
            return fn()
        finally:
            m.smtplib.SMTP = real
            _SendingSMTP.on_send = None

    def failing(fn):
        m.smtplib.SMTP = _FailingSMTP
        try:
            return fn()
        finally:
            m.smtplib.SMTP = real

    print("Historian messages")
    m.SMTP_USER, m.SMTP_PASS, m.HISTORIAN_EMAIL = "", "", ""
    res = historian("No email configured?")
    check("kept when email is not configured", msgs()[-1].get("question") == "No email configured?")
    check("listed as unsent, with the reason", fails()[-1].get("form") == "historian"
          and "SMTP" in fails()[-1].get("reason", "") and fails()[-1].get("visitor_response") == "reach me at v@example.org",
          str(fails()[-1:]))
    check("reports logged", res.json().get("status") == "logged")

    m.SMTP_USER, m.SMTP_PASS, m.HISTORIAN_EMAIL = "u", "p", ""
    historian("No recipient?")
    check("missing recipient listed as unsent", fails()[-1].get("reason") == "HISTORIAN_EMAIL not set")

    m.HISTORIAN_EMAIL = "h@example.org"
    res = failing(lambda: historian("Send fails?", audio=b"RIFF-recording"))
    kept, unsent = msgs()[-1], fails()[-1]
    check("failed send: message kept", kept.get("question") == "Send fails?")
    check("failed send: listed as unsent", unsent.get("reason", "").startswith("send failed") and unsent.get("id") == kept.get("id"))
    check("failed send: reports an error", res.json().get("status") == "error")
    audio = os.path.join(m.CONTACT_MESSAGES_AUDIO_DIR, kept.get("audio_file") or "-")
    check("recording kept once, named by both lines", os.path.exists(audio) and open(audio, "rb").read() == b"RIFF-recording"
          and unsent.get("audio_file") == kept.get("audio_file"))
    check("full email body kept", "Send fails?" in unsent.get("body", "") and "No email configured?" not in unsent.get("body", ""))

    before_fails = len(fails())
    seen_at_send = []
    _SendingSMTP.on_send = lambda: seen_at_send.append(any(r.get("question") == "Sent fine?" for r in msgs()))
    res = sending(lambda: historian("Sent fine?", audio=b"RIFF-two"))
    check("kept before the send was tried", seen_at_send == [True], str(seen_at_send))
    check("emailed to the historian with its recording", res.json().get("status") == "sent" and len(_SendingSMTP.sent) == 1
          and _SendingSMTP.sent[0]["To"] == "h@example.org"
          and any(p.get_filename() == "question.webm" for p in _SendingSMTP.sent[0].walk()))
    check("a sent message is kept but not listed as unsent", msgs()[-1].get("question") == "Sent fine?" and len(fails()) == before_fails)

    print("Contact-form messages")
    res = sending(lambda: contact_form("A question about Cod."))
    sent = _SendingSMTP.sent[0] if _SendingSMTP.sent else None
    body = sent.get_payload()[0].get_payload() if sent else ""
    check("kept in feedback", rows(m.FEEDBACK_PATH)[-1].get("message") == "A question about Cod.")
    check("emailed to HISTORIAN_EMAIL", sent is not None and sent["To"] == "h@example.org"
          and sent["Subject"] == "submarinedocent.org contact form")
    check("email carries name, address and message", "Visitor" in body and "v@example.org" in body and "A question about Cod." in body, body)
    check("reply goes to the visitor", sent is not None and sent["Reply-To"] == "v@example.org")
    check("visitor sees ok; nothing listed as unsent", res.json() == {"status": "ok"} and len(fails()) == before_fails)

    res = sending(lambda: contact_form("Header trick.", email="v@example.org\nBcc: x@example.org"))
    sent = _SendingSMTP.sent[0] if _SendingSMTP.sent else None
    check("a malformed address gets no Reply-To and adds no header",
          sent is not None and sent["Reply-To"] is None and sent["Bcc"] is None and res.json() == {"status": "ok"})

    res = failing(lambda: contact_form("Mail is down."))
    check("failed send: kept in feedback", rows(m.FEEDBACK_PATH)[-1].get("message") == "Mail is down.")
    check("failed send: listed as unsent, with the message", fails()[-1].get("form") == "contact_form"
          and fails()[-1].get("message") == "Mail is down." and fails()[-1].get("reason", "").startswith("send failed"),
          str(fails()[-1:]))
    check("failed send: visitor still sees ok", res.json() == {"status": "ok"})

    m.SMTP_USER = ""
    contact_form("Not configured.")
    check("unconfigured: listed as unsent", fails()[-1].get("message") == "Not configured." and "SMTP" in fails()[-1].get("reason", ""))
    m.SMTP_USER = "u"

    before_fails = len(fails())
    sending(lambda: client.post("/feedback", json={"source": "tour", "question": "Q", "answer": "A", "rating": "up"}))
    check("a tour rating sends no email", _SendingSMTP.sent == [] and len(fails()) == before_fails)

    print("Hourly cap, both forms together")
    clock = [1_700_000_000 // 3600 * 3600 + 3600 + 60.0]  # one minute into a fresh hour
    m._notify_now = lambda: clock[0]
    timers = []

    class _Timer:  # records the scheduled summary instead of waiting an hour
        def __init__(self, delay, fn, args=()):
            self.delay, self.fn, self.args, self.daemon = delay, fn, args, False

        def start(self):
            timers.append(self)

    real_timer = m.threading.Timer
    m.threading.Timer = _Timer
    try:
        _SendingSMTP.sent = []
        m.smtplib.SMTP = _SendingSMTP
        msgs_before, fails_before = len(msgs()), len(fails())
        for i in range(m.NOTIFY_CAP_PER_HOUR):
            (historian if i % 2 else contact_form)(f"Within the cap {i}")
        check(f"{m.NOTIFY_CAP_PER_HOUR} messages in an hour, {m.NOTIFY_CAP_PER_HOUR} emails",
              len(_SendingSMTP.sent) == m.NOTIFY_CAP_PER_HOUR, str(len(_SendingSMTP.sent)))
        r1 = historian("Past the cap: historian")
        r2 = contact_form("Past the cap: contact form")
        contact_form("Past the cap: third")
        check("no email past the cap", len(_SendingSMTP.sent) == m.NOTIFY_CAP_PER_HOUR, str(len(_SendingSMTP.sent)))
        check("every held message still kept", msgs()[-1].get("question") == "Past the cap: historian"
              and rows(m.FEEDBACK_PATH)[-1].get("message") == "Past the cap: third")
        held = fails()[fails_before:]
        check("each held message listed as unsent with the cap reason", len(held) == 3
              and all(h.get("reason", "").startswith("notification cap") for h in held), str([h.get("reason") for h in held]))
        check("visitors see their usual reply", r2.json() == {"status": "ok"} and r1.json().get("status") == "logged")
        check("one summary scheduled, for the top of the next hour",
              len(timers) == 1 and abs(timers[0].delay - 3540) < 1 and timers[0].daemon, str([(t.delay, t.daemon) for t in timers]))

        # A message in the new hour before the summary fires must not lose the count.
        clock[0] += 3600
        contact_form("Next hour, first")
        check("notifications resume the next hour", len(_SendingSMTP.sent) == m.NOTIFY_CAP_PER_HOUR + 1)
        timers[0].fn(*timers[0].args)
        summary = _SendingSMTP.sent[-1]
        text = summary.get_payload()[0].get_payload()
        check("one 'paused, N waiting' email with the real count",
              summary["Subject"] == "submarinedocent.org notifications paused: 3 messages waiting"
              and "3 more messages" in text and "contact_failures.jsonl" in text, summary["Subject"])
        timers[0].fn(*timers[0].args)
        check("the summary is sent once", len(_SendingSMTP.sent) == m.NOTIFY_CAP_PER_HOUR + 2)
    finally:
        m.threading.Timer = real_timer
        m.smtplib.SMTP = real
        m._notify_now = m.time.time

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
