#!/usr/bin/env python3
"""The answer review page: intake with its own key, and Apply, Edit then apply,
Dismiss, Resolve, Undo and Apply anyway on each kind of fix.

The review's key can only add items.  An apply re-checks that the fix fits,
runs the impact check (api/review_impact.py, a separate process), writes only
if nothing else moves or an admin overrides with initials, backs up the FAQ
file first and records the record before and after.  One real check runs (the
air compressor question pointed at faq_1326, 20 November 2026); the override
cases substitute a check that reports a move, so they do not depend on what
any one edit happens to move.

Works on a temporary copy of the seed; nothing in corpora/ is written.

    python3 _test/test_answer_review.py
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time

from seed_guard import SEED, load_app

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    work = tempfile.mkdtemp(prefix="answerreview-")
    copy = os.path.join(work, "corpora")
    shutil.copytree(SEED, copy)
    m = load_app(copy=copy)
    from fastapi.testclient import TestClient

    m.ADMIN_USERNAME, m.ADMIN_PASSWORD = "t", "t"
    m.ASK_LOG_PATH = os.path.join(work, "ask_log.jsonl")
    m.ANSWER_REVIEW_PATH = os.path.join(work, "answer_review.jsonl")
    m.REVIEW_BACKUP_DIR = os.path.join(work, "review_backups")
    key = "r" * 43
    client = TestClient(m.app)
    admin = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}
    review = {"X-Review-Key": key}

    def post(items, date="2026-11-20", headers=review):
        return client.post("/answer-review/items", json={"review_date": date, "items": items}, headers=headers)

    def listing():
        return client.get("/admin/answer-review", headers=admin).json()

    def find(item_id):
        d = listing()
        return next((i for i in d["open"] + d["editor"] if i["id"] == item_id), None)

    def wait(item_id, limit=600):
        t = time.time()
        while time.time() - t < limit:
            i = find(item_id)
            if not i or (i.get("check") or {}).get("state") != "checking":
                return i
            time.sleep(0.5)
        return find(item_id)

    def rec(chunk_id):
        return next((e for e in m.FAQ_ALL if e.get("chunk_id") == chunk_id), None)

    def apply(item_id, **body):
        return client.post(f"/admin/answer-review/{item_id}/apply", json=body, headers=admin)

    air = {"question": "How does the air compressor work?", "got": {"outcome": "record", "faq_id": "faq_1154"},
           "category": "wrong_answer", "reason": "About the daily routine; never mentions compressors.",
           "fix": {"type": "point_to_faq", "faq_id": "faq_1326"}}
    typo = {"question": "How does the air compressor work?", "got": {"outcome": "record", "faq_id": "faq_1154"},
            "category": "typo", "reason": "Grammar.",
            "fix": {"type": "text_edit", "faq_id": "faq_1154", "field": "text",
                    "old": "Either attacks could last many hours",
                    "new": "Either kind of attack could last many hours"}}
    draft = {"question": "How does the air compressor work?", "got": {"outcome": "record", "faq_id": "faq_1154"},
             "category": "wrong_answer", "reason": "No FAQ covers compressors.",
             "fix": {"type": "new_faq", "title": "How did the air compressors work?", "note": "Stages, drive, cooling."}}
    quote = next(s for s in rec("faq_1344")["text"].replace("<p>", "").split(". ") if "600 feet" in s)
    factual = {"question": "How deep could a Balao-class submarine dive?", "got": {"outcome": "record", "faq_id": "faq_1344"},
               "category": "factual", "reason": "Sources awaited.",
               "fix": {"type": "factual", "faq_id": "faq_1344", "quote": quote, "concern": "Needs a source."}}

    # ── Intake and its key ───────────────────────────────────────────────────
    m.ANSWER_REVIEW_KEY = ""
    check("intake disabled without ANSWER_REVIEW_KEY", post([air]).status_code == 503)
    m.ANSWER_REVIEW_KEY = key
    check("no key: refused", post([air], headers={}).status_code == 401)
    check("wrong key: refused", post([air], headers={"X-Review-Key": "x" * 43}).status_code == 401)
    check("the admin password does not open intake", post([air], headers=admin).status_code == 401)
    check("the review key does not open the admin listing",
          client.get("/admin/answer-review", headers=review).status_code == 401)
    check("the review key cannot apply",
          client.post("/admin/answer-review/ar_x/apply", json={}, headers=review).status_code == 401)
    check("the review key cannot read items back", client.get("/answer-review/items", headers=review).status_code == 405)
    check("review_date must be a date", post([air], date="yesterday").status_code == 400)
    check("at most 50 items", post([air] * 51).status_code == 400)
    big = client.post("/answer-review/items", content=b"{" + b" " * 200_001 + b"}", headers=review)
    check("a body over 200 KB is refused", big.status_code == 413, big.status_code)

    bad = [
        dict(air, fix={"type": "point_to_faq", "faq_id": "faq_99999"}),
        dict(air, question="<b>How</b> does it work?"),
        dict(typo, fix=dict(typo["fix"], new="Either attack—any attack")),
        dict(typo, fix=dict(typo["fix"], old="words that are not in the record")),
        dict(factual, fix=dict(factual["fix"], quote="a sentence the record never says")),
        dict(draft, fix=dict(draft["fix"], title=rec("faq_1326")["title"])),
        dict(draft, fix=dict(draft["fix"], category="No such category")),
        dict(air, fix={"type": "point_to_faq", "faq_id": "der_1"}),
    ]
    got = post(bad).json()
    check("each bad item is rejected with its reason", len(got["rejected"]) == len(bad) and not got["accepted"], got)
    import re
    quoted = next(((e, q) for e in m.FAQ for q in re.findall(r"“([^”]{8,})”", e.get("text") or "")
                   if e["text"].count(q) == 1), None)
    check("the seed has a quotation to test with", quoted is not None)
    if quoted:
        quoted, inside = quoted
        got = post([dict(typo, fix={"type": "text_edit", "faq_id": quoted["chunk_id"], "field": "text",
                                    "old": inside, "new": inside + "x"})]).json()
        check("a fix inside quoted material is refused", got["rejected"] and "quoted" in got["rejected"][0]["error"], got)

    contact = dict(air, question="How does the air compressor work? Email me at jo@example.org")
    got = post([air, typo, draft, factual, contact]).json()
    check("good items accepted", [a["status"] for a in got["accepted"]] == ["new"] * 5 and not got["rejected"], got)
    ids = {name: a["item_id"] for name, a in zip(("air", "typo", "draft", "factual", "contact"), got["accepted"])}
    stored = [json.loads(l) for l in open(m.ANSWER_REVIEW_PATH)]
    check("contact details are redacted at intake",
          any("[email]" in s["question"] for s in stored) and not any("jo@example.org" in json.dumps(s) for s in stored))
    again = post([air], date="2026-11-21").json()
    check("the same question and fix merges instead of repeating",
          again["accepted"] == [{"index": 0, "item_id": ids["air"], "status": "merged"}], again)
    check("the merged item carries both days", find(ids["air"])["review_dates"] == ["2026-11-20", "2026-11-21"])
    client.post(f"/admin/answer-review/{ids['contact']}/dismiss", json={"by": "T", "reason": "duplicate"}, headers=admin)

    # Times asked comes from the log, not from the review.
    with open(m.ASK_LOG_PATH, "w") as fh:
        for day in ("2026-11-20", "2026-11-20", "2026-11-21"):
            fh.write(json.dumps({"q": "How does the air compressor work?", "faq_id": "faq_1154", "date": day}) + "\n")
    asked = find(ids["air"])["asked"]
    check("times asked is counted from the log", asked == {"date": "2026-11-21", "on_date": 1, "total": 3}, asked)

    d = listing()
    check("Open holds the three fixes; For the editor holds the factual item",
          {i["id"] for i in d["open"]} == {ids["air"], ids["typo"], ids["draft"]}
          and [i["id"] for i in d["editor"]] == [ids["factual"]], (d["open"], d["editor"]))
    view = find(ids["typo"])
    check("a text edit shows the passage before and after",
          view["before"]["text"][slice(*view["before"]["mark"])] == typo["fix"]["old"]
          and view["after"]["text"][slice(*view["after"]["mark"])] == typo["fix"]["new"], view.get("before"))

    # ── Apply with the real check: point to a better FAQ ────────────────────
    before_1326 = json.loads(json.dumps(rec("faq_1326")))
    check("Apply starts a check", apply(ids["air"], by="IG").status_code == 202)
    check("a second Apply while checking is refused", apply(ids["air"], by="IG").status_code == 409)
    wait(ids["air"])
    hist = [h for h in listing()["history"] if h["item_id"] == ids["air"]]
    h = hist[0] if hist else {}
    check("applied when nothing else moves", h.get("action") == "applied" and h.get("moved") == [], h.get("moved"))
    check("the check covered every title, phrasing and golden question", h.get("checked", 0) > 450, h.get("checked"))
    check("the question now lands on faq_1326", (h.get("target") or {}).get("ok") is True, h.get("target"))
    check("the phrasing is on faq_1326", "How does the air compressor work?" in (rec("faq_1326").get("phrasings") or []))
    check("and in the file, not just in memory",
          any(json.loads(l)["chunk_id"] == "faq_1326" and "phrasings" in json.loads(l)
              for l in open(m.FAQ_PATH)))
    hits = m.retrieve(question_text="How does the air compressor work?", compartment_id="", playhead_time_ms=0)
    check("the live server answers it from faq_1326 at once", hits and hits[0][1]["chunk_id"] == "faq_1326",
          hits and hits[0][1]["chunk_id"])
    check("history keeps the record before and after", h.get("before") == before_1326 and h.get("after") == rec("faq_1326"))
    check("history names a backup that exists",
          h.get("backup") and os.path.exists(os.path.join(m.REVIEW_BACKUP_DIR, h["backup"])), h.get("backup"))
    check("the backup is the file as it was before the apply",
          "phrasings" not in next(json.loads(l) for l in open(os.path.join(m.REVIEW_BACKUP_DIR, h["backup"]))
                                  if json.loads(l)["chunk_id"] == "faq_1326"))
    check("recorded who applied it", h.get("by") == "IG")

    # ── Undo ─────────────────────────────────────────────────────────────────
    got = client.post(f"/admin/answer-review/{ids['air']}/undo", json={"by": "IG"}, headers=admin)
    check("Undo restores the record", got.status_code == 200 and rec("faq_1326") == before_1326, got.text)
    check("and the item is open again", find(ids["air"])["status"] == "open")
    check("Undo of an item with nothing applied is refused",
          client.post(f"/admin/answer-review/{ids['air']}/undo", json={}, headers=admin).status_code == 409)

    # ── Apply anyway, with a check that reports a move ───────────────────────
    real_check = m._review_run_check
    moved = [{"question": "How did the air system work?", "kinds": ["golden"], "before": "faq_1", "after": "faq_2"}]
    m._review_run_check = lambda item, fix: {"checked": 519, "moved": moved, "target": None,
                                             "golden": {"before": 84, "after": 83, "total": 127}, "seconds": 0.1}
    text_before = rec("faq_1154")["text"]
    check("override before any check is refused", apply(ids["typo"], by="IG", override=True).status_code == 409)
    apply(ids["typo"], by="IG")
    state = wait(ids["typo"])["check"]
    check("a move stops the write", state["state"] == "moves" and rec("faq_1154")["text"] == text_before, state["state"])
    check("Apply anyway without initials is refused", apply(ids["typo"], override=True).status_code == 400)
    check("Apply anyway with blank initials is refused", apply(ids["typo"], by="  ", override=True).status_code == 400)
    check("Apply anyway with initials goes ahead", apply(ids["typo"], by="IG", override=True).status_code == 202)
    wait(ids["typo"])
    h = next(h for h in listing()["history"] if h["item_id"] == ids["typo"])
    check("the history records the override and what moved",
          h["overridden"] is True and h["moved"] == moved and h["by"] == "IG", h)
    check("the typo is fixed through the normal save",
          "Either kind of attack could last many hours" in rec("faq_1154")["text"]
          and rec("faq_1154")["display_citation"].startswith("SubmarineDocent FAQ: "))
    rec("faq_1154")["text"] += " "
    got = client.post(f"/admin/answer-review/{ids['typo']}/undo", json={"by": "IG"}, headers=admin)
    check("Undo is refused once the record changed since", got.status_code == 409, got.text)
    rec("faq_1154")["text"] = rec("faq_1154")["text"][:-1]
    m._review_run_check = real_check

    # ── Edit then apply: new FAQ draft ───────────────────────────────────────
    edited = dict(draft["fix"], title="How did the high-pressure air compressors work?")
    check("Edit then apply keeps the fix's type",
          apply(ids["draft"], by="IG", fix={"type": "point_to_faq", "faq_id": "faq_1326"}).status_code == 400)
    check("an edited fix is validated like intake",
          apply(ids["draft"], by="IG", fix=dict(edited, title="A—B?")).status_code == 400)
    apply(ids["draft"], by="IG", fix=edited)
    wait(ids["draft"])
    h = next(h for h in listing()["history"] if h["item_id"] == ids["draft"])
    new = rec(h["chunk_id"])
    check("the draft is created under a draft prefix", h["chunk_id"].startswith("der_review_") and new, h["chunk_id"])
    check("with the edited title, marked for the editor",
          new and new["title"] == edited["title"] and new.get("review_for") == "editor"
          and new.get("source") == "answer_review", new)
    check("the history keeps the fix as the review sent it", h.get("edited_from") == draft["fix"], h.get("edited_from"))
    check("a draft never answers visitors", all(e["chunk_id"] != h["chunk_id"] for e in m.FAQ))
    check("the draft waits under For the editor", any(i["id"] == ids["draft"] for i in listing()["editor"]))
    got = client.post(f"/admin/answer-review/{ids['draft']}/undo", json={"by": "IG"}, headers=admin)
    check("Undo removes an untouched draft", got.status_code == 200 and rec(h["chunk_id"]) is None, got.text)

    # ── Factual, Dismiss, Resolve ────────────────────────────────────────────
    check("a possible factual error has no Apply", apply(ids["factual"], by="IG").status_code == 400)
    check("Resolve needs a note",
          client.post(f"/admin/answer-review/{ids['factual']}/resolve", json={"by": "IG"}, headers=admin).status_code == 400)
    check("Resolve with a note", client.post(f"/admin/answer-review/{ids['factual']}/resolve",
                                             json={"by": "IG", "note": "Source requested."}, headers=admin).status_code == 200)
    check("Dismiss needs a reason",
          client.post(f"/admin/answer-review/{ids['air']}/dismiss", json={"by": "IG"}, headers=admin).status_code == 400)
    client.post(f"/admin/answer-review/{ids['air']}/dismiss", json={"by": "IG", "reason": "test"}, headers=admin)
    again = post([air]).json()
    check("a dismissed item does not come back", again["accepted"][0]["status"] == "already_dismissed", again)
    check("nothing open is left but the draft", [i["id"] for i in listing()["open"]] == [ids["draft"]])

    # ── A fix that stopped fitting ───────────────────────────────────────────
    later = post([dict(typo, fix=dict(typo["fix"], old="Either kind of attack", new="Each kind of attack"))]).json()
    rec("faq_1154")["text"] = rec("faq_1154")["text"].replace("Either kind of attack", "Both kinds of attack")
    item = later["accepted"][0]["item_id"]
    check("the page says it no longer fits", find(item)["fits"], find(item).get("fits"))
    apply(item, by="IG")
    state = wait(item)["check"]
    check("and Apply writes nothing", state["state"] == "no_longer_fits", state)

    shutil.rmtree(work, ignore_errors=True)
    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
