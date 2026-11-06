#!/usr/bin/env python3
"""Both visitor forms keep every message and email the historian about it.

Historian messages (POST /contact) are kept in contact_messages.jsonl before any
send is tried, with any recording beside them.  Contact-form messages (POST
/feedback, source "contact") are kept in feedback.jsonl and now emailed too:
storing a message without telling anyone is not enough (Irving, 31 October
2026).  A message from either form that is not emailed (no credentials, no
recipient, or a failed send) is also listed, with the reason, in
contact_failures.jsonl.  Replaces test_contact_failures_kept.py (30 October).
Mail goes through Resend's HTTP API since 2 November 2026; every send below
goes to a stand-in, never to Resend.

    python3 _test/test_contact_messages.py
"""
import base64
import json
import os
import sys
import tempfile

import httpx

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


class _Sent:
    """Stands in for Resend: records each email's JSON instead of posting it."""
    sent = []
    on_send = None

    @classmethod
    def post(cls, payload):
        if cls.on_send:
            cls.on_send()
        cls.sent.append(payload)
        return {"id": f"test-{len(cls.sent)}"}


def _refused(payload):
    raise OSError("connection refused")


def rows(path):
    return [json.loads(l) for l in open(path)] if os.path.exists(path) else []


def main():
    # Empty, not unset: .env.local fills unset variables and may hold a real
    # mail key.  Every send below goes to a stand-in.
    os.environ.update({"RESEND_API_KEY": "", "MAIL_FROM": "", "HISTORIAN_EMAIL": ""})
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    tmp = tempfile.mkdtemp(prefix="contactmsgs-")
    m.CONTACT_MESSAGES_PATH = os.path.join(tmp, "contact_messages.jsonl")
    m.CONTACT_MESSAGES_AUDIO_DIR = os.path.join(tmp, "contact_messages_audio")
    m.CONTACT_FAILURES_PATH = os.path.join(tmp, "contact_failures.jsonl")
    m.FEEDBACK_PATH = os.path.join(tmp, "feedback.jsonl")
    client = TestClient(m.app)
    real = m._resend_post
    msgs = lambda: rows(m.CONTACT_MESSAGES_PATH)
    fails = lambda: rows(m.CONTACT_FAILURES_PATH)

    def historian(q, audio=None, contact="reach me at v@example.org"):
        files = {"audio": ("q.webm", audio, "audio/webm")} if audio else None
        return client.post("/contact", data={"question_text": q, "visitor_response": contact,
                                             "lang": "en"}, files=files)

    def contact_form(message, email="v@example.org"):
        return client.post("/feedback", json={"source": "contact", "name": "Visitor", "email": email, "message": message})

    def sending(fn):
        _Sent.sent = []
        m._resend_post = _Sent.post
        try:
            return fn()
        finally:
            m._resend_post = real
            _Sent.on_send = None

    def failing(fn, how=_refused):
        m._resend_post = how
        try:
            return fn()
        finally:
            m._resend_post = real

    print("Historian messages")
    m.RESEND_API_KEY, m.MAIL_FROM, m.HISTORIAN_EMAIL = "", "", ""
    res = historian("No email configured?")
    check("kept when email is not configured", msgs()[-1].get("question") == "No email configured?")
    check("listed as unsent, with the reason", fails()[-1].get("form") == "historian"
          and "RESEND_API_KEY" in fails()[-1].get("reason", "") and fails()[-1].get("visitor_response") == "reach me at v@example.org",
          str(fails()[-1:]))
    check("reports logged", res.json().get("status") == "logged")

    m.RESEND_API_KEY, m.MAIL_FROM, m.HISTORIAN_EMAIL = "re_test", "Site <notify@example.org>", ""
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
    _Sent.on_send = lambda: seen_at_send.append(any(r.get("question") == "Sent fine?" for r in msgs()))
    res = sending(lambda: historian("Sent fine?", audio=b"RIFF-two"))
    check("kept before the send was tried", seen_at_send == [True], str(seen_at_send))
    att = (_Sent.sent[0].get("attachments") or [{}])[0] if _Sent.sent else {}
    check("emailed to the historian with its recording", res.json().get("status") == "sent" and len(_Sent.sent) == 1
          and _Sent.sent[0]["to"] == ["h@example.org"] and _Sent.sent[0]["from"] == "Site <notify@example.org>"
          and att.get("filename") == "question.webm"
          and base64.b64decode(att.get("content", "")) == b"RIFF-two", str(_Sent.sent[:1])[:300])
    check("a sent message is kept but not listed as unsent", msgs()[-1].get("question") == "Sent fine?" and len(fails()) == before_fails)
    # The contact box is free text.  Only a value that passes the contact
    # form's address check becomes the Reply-To; anything else stays in the body.
    check("free-text contact info gets no Reply-To", _Sent.sent and "reply_to" not in _Sent.sent[0], str(_Sent.sent[:1])[:200])
    sending(lambda: historian("Reply to me?", contact="v@example.org"))
    check("contact info that is an address becomes the Reply-To",
          _Sent.sent and _Sent.sent[0].get("reply_to") == "v@example.org", str(_Sent.sent[:1])[:200])
    sending(lambda: historian("Two lines?", contact="v@example.org\nBcc: x@example.org"))
    check("contact info with a newline gets no Reply-To", _Sent.sent and "reply_to" not in _Sent.sent[0])

    print("Contact-form messages")
    res = sending(lambda: contact_form("A question about Cod."))
    sent = _Sent.sent[0] if _Sent.sent else None
    body = sent["text"] if sent else ""
    check("kept in feedback", rows(m.FEEDBACK_PATH)[-1].get("message") == "A question about Cod.")
    check("emailed to HISTORIAN_EMAIL", sent is not None and sent["to"] == ["h@example.org"]
          and sent["subject"] == "submarinedocent.org contact form")
    check("email carries name, address and message", "Visitor" in body and "v@example.org" in body and "A question about Cod." in body, body)
    check("reply goes to the visitor", sent is not None and sent.get("reply_to") == "v@example.org")
    check("visitor sees ok; nothing listed as unsent", res.json() == {"status": "ok"} and len(fails()) == before_fails)

    res = sending(lambda: contact_form("Header trick.", email="v@example.org\nBcc: x@example.org"))
    sent = _Sent.sent[0] if _Sent.sent else None
    check("a malformed address gets no Reply-To and adds no field",
          sent is not None and "reply_to" not in sent and "bcc" not in sent and res.json() == {"status": "ok"})

    res = failing(lambda: contact_form("Mail is down."))
    check("failed send: kept in feedback", rows(m.FEEDBACK_PATH)[-1].get("message") == "Mail is down.")
    check("failed send: listed as unsent, with the message", fails()[-1].get("form") == "contact_form"
          and fails()[-1].get("message") == "Mail is down." and fails()[-1].get("reason", "").startswith("send failed"),
          str(fails()[-1:]))
    check("failed send: visitor still sees ok", res.json() == {"status": "ok"})

    def rejected(payload):  # Resend refuses the email, e.g. an unverified sender
        req = httpx.Request("POST", m.RESEND_URL)
        httpx.Response(422, text='{"message":"domain not verified"}', request=req).raise_for_status()

    res = failing(lambda: contact_form("Resend says no."), how=rejected)
    check("Resend refusal: listed as unsent with its status and reply",
          fails()[-1].get("message") == "Resend says no."
          and fails()[-1].get("reason", "").startswith("send failed: HTTP 422")
          and "domain not verified" in fails()[-1].get("reason", ""), str(fails()[-1:]))
    check("Resend refusal: visitor still sees ok", res.json() == {"status": "ok"})
    failing(lambda: contact_form("No id back."), how=lambda payload: {})
    check("a reply without a message id counts as not sent",
          fails()[-1].get("message") == "No id back." and "no id" in fails()[-1].get("reason", ""))

    m.MAIL_FROM = ""
    contact_form("Not configured.")
    check("unconfigured: listed as unsent", fails()[-1].get("message") == "Not configured." and "MAIL_FROM" in fails()[-1].get("reason", ""))
    m.MAIL_FROM = "Site <notify@example.org>"

    before_fails = len(fails())
    sending(lambda: client.post("/feedback", json={"source": "tour", "question": "Q", "answer": "A", "rating": "up"}))
    check("a tour rating sends no email", _Sent.sent == [] and len(fails()) == before_fails)

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
        _Sent.sent = []
        m._resend_post = _Sent.post
        msgs_before, fails_before = len(msgs()), len(fails())
        for i in range(m.NOTIFY_CAP_PER_HOUR):
            (historian if i % 2 else contact_form)(f"Within the cap {i}")
        check(f"{m.NOTIFY_CAP_PER_HOUR} messages in an hour, {m.NOTIFY_CAP_PER_HOUR} emails",
              len(_Sent.sent) == m.NOTIFY_CAP_PER_HOUR, str(len(_Sent.sent)))
        r1 = historian("Past the cap: historian")
        r2 = contact_form("Past the cap: contact form")
        contact_form("Past the cap: third")
        check("no email past the cap", len(_Sent.sent) == m.NOTIFY_CAP_PER_HOUR, str(len(_Sent.sent)))
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
        check("notifications resume the next hour", len(_Sent.sent) == m.NOTIFY_CAP_PER_HOUR + 1)
        timers[0].fn(*timers[0].args)
        summary = _Sent.sent[-1]
        text = summary["text"]
        check("one 'paused, N waiting' email with the real count",
              summary["subject"] == "submarinedocent.org notifications paused: 3 messages waiting"
              and "3 more messages" in text and "contact_failures.jsonl" in text, summary["subject"])
        timers[0].fn(*timers[0].args)
        check("the summary is sent once", len(_Sent.sent) == m.NOTIFY_CAP_PER_HOUR + 2)
    finally:
        m.threading.Timer = real_timer
        m._resend_post = real
        m._notify_now = m.time.time

    print("The request Resend receives")
    seen = {}

    class _Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "abc"}

    real_post = m.httpx.post
    m.httpx.post = lambda url, **kw: (seen.update(url=url, **kw), _Reply())[1]
    try:
        m.RESEND_API_KEY = "re_test"
        reason = m._send_site_email("Subject", "Body", reply_to="v@example.org")
    finally:
        m.httpx.post = real_post
    check("posts JSON to Resend's emails endpoint with the key", reason == ""
          and seen.get("url") == "https://api.resend.com/emails"
          and seen.get("headers", {}).get("Authorization") == "Bearer re_test"
          and seen.get("json", {}).get("text") == "Body" and seen.get("timeout") == 30, str(seen)[:300])

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
