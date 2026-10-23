#!/usr/bin/env python3
"""The visitor log says how each question arrived: clicked or typed.

/ask logs "via": "click" when the page sent a record id (a balloon, a museum
chip, a suggestion after a short question) and "via": "typed" otherwise
(22 October 2026).  museum_id is logged as before, and a request carrying
X-SubDocent-Test: 1 is never logged.

    CONTENT_ROOT=corpora python3 _test/test_ask_log_via.py
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


def main():
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    log = os.path.join(tempfile.mkdtemp(prefix="asklogvia-"), "ask_log.jsonl")
    m.ASK_LOG_PATH = log
    client = TestClient(m.app)
    base = {"compartment_id": "", "playhead_time_ms": 0}

    def ask(body, test=False):
        headers = {"X-SubDocent-Test": "1"} if test else {}
        client.post("/ask", json={**base, **body}, headers=headers)
        rows = [json.loads(l) for l in open(log)] if os.path.exists(log) else []
        return rows[-1] if rows else None

    title = next(e["title"] for e in m.FAQ if e["chunk_id"].startswith("faq_"))
    fid = next(e["chunk_id"] for e in m.FAQ if e["title"] == title)

    r = ask({"question_text": "How long were patrols?"})
    check("typed question logs via typed", r and r.get("via") == "typed", str(r))
    check("main-site question logs an empty museum_id", r and r.get("museum_id") == "", str(r))

    r = ask({"question_text": title, "faq_id": fid})
    check("balloon click logs via click", r and r.get("via") == "click" and r.get("faq_id") == fid, str(r))

    r = ask({"question_text": "How long were patrols?", "faq_id": "faq_does_not_exist"})
    check("stale balloon id still logs via click", r and r.get("via") == "click", str(r))

    r = ask({"question_text": title, "faq_id": fid, "museum_id": "10"})
    check("museum chip logs via click and museum_id 10", r and r.get("via") == "click" and r.get("museum_id") == "10", str(r))

    r = ask({"question_text": "torpedoes"})
    check("short question logs via typed", r and r.get("faq_id") == "short_query" and r.get("via") == "typed", str(r))

    r = ask({"question_text": "What is a submarine?"})
    check("refusal logs via typed", r and r.get("faq_id") in ("refusal", "fallback") and r.get("via") == "typed", str(r))

    before = sum(1 for _ in open(log))
    ask({"question_text": "How long were patrols?"}, test=True)
    check("test-header request is not logged", sum(1 for _ in open(log)) == before)

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
