#!/usr/bin/env python3
"""The question log keeps the question, not the person, and the daily review
reads it with its own key.

Each line holds the question with emails and phone numbers replaced, the
record that answered (or short_query, fallback, refusal), museum_id, the day,
how the question arrived, and, for a fallback, the retrieval diagnostics.
Nothing that identifies a visitor.  The answer text is kept only when no
record answered, because only then was it assembled from the question's words.
A request carrying X-SubDocent-Test: 1 is never logged.

GET /asklog/recent returns the lines dated today or yesterday, given the key
in X-AskLog-Key; the admin password does not open it.

    CONTENT_ROOT=corpora python3 _test/test_ask_log_review.py
"""
import base64
import datetime
import json
import os
import sys
import tempfile

from seed_guard import load_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED = {"q", "faq_id", "museum_id", "date", "via", "source_id", "answer",
           "top_id", "top_score", "unexplained"}
# Answered from the 1946 manual on the seed, not from a record.
MANUAL_QUESTION = "What is the hydraulic accumulator?"

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    os.environ["ADMIN_USERNAME"] = "t"
    os.environ["ADMIN_PASSWORD"] = "t"
    sys.path.insert(0, REPO)
    m = load_app()
    from fastapi.testclient import TestClient

    log = os.path.join(tempfile.mkdtemp(prefix="asklogreview-"), "ask_log.jsonl")
    m.ASK_LOG_PATH = log
    client = TestClient(m.app)

    def rows():
        return [json.loads(l) for l in open(log)] if os.path.exists(log) else []

    def ask(question, test=False, **extra):
        before = len(rows())
        headers = {"X-SubDocent-Test": "1"} if test else {}
        resp = client.post("/ask", json={"question_text": question, **extra}, headers=headers).json()
        after = rows()
        return resp, (after[-1] if len(after) > before else None)

    title = next(e["title"] for e in m.FAQ if e["chunk_id"].startswith("faq_"))
    resp, r = ask(title)
    check("a record's answer is logged by its id", r and str(r.get("faq_id", "")).startswith("faq_"), r)
    check("a record's answer text is not stored", r and "answer" not in r, r)
    _, r = ask("My grandfather served on Cod. Email me at jo.smith@example.org or call 415-555-0123.")
    check("emails are redacted", r and "jo.smith" not in r["q"] and "[email]" in r["q"], r and r["q"])
    check("phone numbers are redacted", r and "555-0123" not in r["q"] and "[phone]" in r["q"], r and r["q"])
    check("hull numbers and years survive redaction",
          m._redact_contact("Did SS-383 patrol in 1944-1945?") == "Did SS-383 patrol in 1944-1945?")

    resp, r = ask(MANUAL_QUESTION)
    check("a manual answer is logged without an id, with its source",
          r and r.get("faq_id") is None and str(r.get("source_id", "")).startswith("fsm_"), r)
    check("and with the text the visitor was given",
          r and r.get("answer") and r["answer"] == resp.get("answer_short"), r)

    ask("torpedo")
    ask("What colour was the admiral's favourite teapot on Tuesdays?")
    every = rows()
    extra_fields = sorted({k for rec in every for k in rec} - ALLOWED)
    check("no field outside the allowed set", not extra_fields, extra_fields)
    check("the day only, no time", all(len(rec.get("date", "")) == 10 for rec in every), [rec.get("date") for rec in every])

    for question in (title, "torpedo", MANUAL_QUESTION, "What colour was the admiral's favourite teapot on Tuesdays?"):
        _, r = ask(question, test=True)
        check(f"test traffic not logged: {question[:40]}", r is None, r)

    # The endpoint.  Disabled with no key set.
    m.ASKLOG_KEY = ""
    check("disabled without ASKLOG_KEY", client.get("/asklog/recent").status_code == 503)

    m.ASKLOG_KEY = "k" * 43
    old = {"q": "An old question?", "faq_id": None, "museum_id": "",
           "date": (datetime.date.today() - datetime.timedelta(days=3)).isoformat()}
    yesterday = dict(old, q="Yesterday's question?",
                     date=(datetime.date.today() - datetime.timedelta(days=1)).isoformat())
    with open(log, "a") as fh:
        fh.write(json.dumps(old) + "\n" + json.dumps(yesterday) + "\n")

    check("no key: refused", client.get("/asklog/recent").status_code == 401)
    check("wrong key: refused", client.get("/asklog/recent", headers={"X-AskLog-Key": "k" * 42}).status_code == 401)
    admin = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}
    check("the admin password does not open it", client.get("/asklog/recent", headers=admin).status_code == 401)
    check("a key in the query string is ignored",
          client.get("/asklog/recent?key=" + "k" * 43).status_code == 401)

    got = client.get("/asklog/recent", headers={"X-AskLog-Key": "k" * 43})
    body = got.json() if got.status_code == 200 else {}
    qs = [e["q"] for e in body.get("entries", [])]
    check("right key: 200", got.status_code == 200, got.status_code)
    check("not cached", got.headers.get("cache-control") == "no-store", got.headers.get("cache-control"))
    check("today's and yesterday's lines returned", "Yesterday's question?" in qs and len(qs) == len(every) + 1, qs)
    check("older lines left out", "An old question?" not in qs, qs)
    check("count matches", body.get("count") == len(qs))
    key = {"X-AskLog-Key": "k" * 43}
    day = yesterday["date"]
    got = client.get(f"/asklog/recent?date={day}", headers=key).json()
    check("?date= returns exactly that day",
          [e["q"] for e in got["entries"]] == ["Yesterday's question?"] and got["from"] == got["to"] == day, got)
    got = client.get(f"/asklog/recent?date={datetime.date.today().isoformat()}", headers=key).json()
    check("?date= today leaves yesterday out",
          "Yesterday's question?" not in [e["q"] for e in got["entries"]] and got["count"] == len(every), got["count"])
    check("?date= an empty day returns none", client.get(f"/asklog/recent?date=2020-01-01", headers=key).json()["count"] == 0)
    for bad in ("yesterday", "2026-13-01", "2026-11-1", "20261119", ""):
        check(f"?date={bad!r} refused", client.get(f"/asklog/recent?date={bad}", headers=key).status_code == 400)
    check("?date= still needs the key", client.get(f"/asklog/recent?date={day}").status_code == 401)

    check("read-only: POST not allowed",
          client.post("/asklog/recent", headers={"X-AskLog-Key": "k" * 43}).status_code == 405)

    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
