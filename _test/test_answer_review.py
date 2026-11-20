#!/usr/bin/env python3
"""The answer review page: intake with its own key, and one card per question
carrying every fix the review suggested, applied by ticking.

The review's key can only add items.  An apply takes the ticked fixes in the
card's order, checks they still fit each against the records the earlier ones
leave, runs the impact check (api/review_impact.py, a separate process) on all
of them together, writes only if nothing else moves or an admin overrides with
initials, backs up the FAQ file first, and records which fixes were chosen and
which were not, with every changed record before and after.  One real check
runs (the air compressor question pointed at faq_1326 together with a faq_1154
typo, 20 November 2026); the override cases substitute a check that reports a
move, so they do not depend on what any one edit happens to move.

Works on a temporary copy of the seed; nothing in corpora/ is written.

    python3 _test/test_answer_review.py
"""
import base64
import json
import os
import re
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

    def card(item_id):
        return next(i for i in [json.loads(l) for l in open(m.ANSWER_REVIEW_PATH)] if i["id"] == item_id)

    def view(item_id):
        d = listing()
        return next((i for i in d["open"] + d["editor"] if i["id"] == item_id), None)

    def status(item_id):
        return {f["id"]: f["status"] for f in card(item_id)["fixes"]}

    def wait(item_id, limit=600):
        t = time.time()
        while time.time() - t < limit:
            if (card(item_id).get("check") or {}).get("state") != "checking":
                break
            time.sleep(0.5)
        return card(item_id)

    def rec(chunk_id):
        return next((e for e in m.FAQ_ALL if e.get("chunk_id") == chunk_id), None)

    def apply(item_id, **body):
        return client.post(f"/admin/answer-review/{item_id}/apply", json=body, headers=admin)

    def last_action(item_id, kind):
        return [a for a in card(item_id)["actions"] if a["action"] == kind][-1]

    q_air = "How does the air compressor work?"
    point = {"type": "point_to_faq", "faq_id": "faq_1326", "category": "wrong_answer",
             "reason": "About the daily routine; never mentions compressors."}
    draft = {"type": "new_faq", "title": "How did the air compressors work?", "note": "Stages, drive, cooling.",
             "category": "wrong_answer", "reason": "No FAQ says how they worked."}
    typo1 = {"type": "text_edit", "faq_id": "faq_1154", "field": "text",
             "old": "Either attacks could last many hours", "new": "Either kind of attack could last many hours",
             "category": "typo", "reason": "Grammar."}
    typo2 = {"type": "text_edit", "faq_id": "faq_1154", "field": "text",
             "old": "submerged - quieter and calmer – during", "new": "submerged, quieter and calmer, during",
             "category": "typo", "reason": "Matching punctuation."}
    air = {"question": q_air, "got": {"outcome": "record", "faq_id": "faq_1154"},
           "fixes": [point, draft, typo1, typo2]}
    quote = next(s for s in rec("faq_1344")["text"].replace("<p>", "").split(". ") if "600 feet" in s)
    factual = {"question": "How deep could a Balao-class submarine dive?",
               "got": {"outcome": "record", "faq_id": "faq_1344"},
               "fixes": [{"type": "factual", "faq_id": "faq_1344", "quote": quote, "concern": "Needs a source.",
                          "category": "factual", "reason": "Sources awaited."}]}

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

    got = post([dict(air, fixes=[]), dict(air, fix=point, fixes=None), dict(air, question="<b>How</b>?"),
                dict(air, got={"outcome": "maybe"}), dict(air, fixes=[point] * 11)]).json()
    check("a bad item is rejected whole, with its reason",
          [r["index"] for r in got["rejected"]] == [0, 1, 2, 3, 4] and not got["accepted"], got)
    bad_fixes = [
        dict(point, faq_id="faq_99999"),
        dict(typo1, new="Either attack—any attack"),
        dict(typo1, old="words that are not in the record"),
        dict(factual["fixes"][0], quote="a sentence the record never says"),
        dict(draft, title=rec("faq_1326")["title"]),
        dict(draft, category_title="No such category"),
        dict(point, faq_id="der_1"),
        dict(point, category="unhappy"),
    ]
    got = post([{"question": "A question with only bad fixes?", "got": {"outcome": "fallback"},
                 "fixes": bad_fixes}]).json()
    check("each bad fix is rejected with its reason, and an item with none left is not stored",
          [r.get("fix_index") for r in got["rejected"]] == list(range(len(bad_fixes)))
          and not got["accepted"], got)
    quoted = next(((e, q) for e in m.FAQ for q in re.findall(r"“([^”]{8,})”", e.get("text") or "")
                   if e["text"].count(q) == 1), None)
    check("the seed has a quotation to test with", quoted is not None)
    if quoted:
        quoted, inside = quoted
        got = post([dict(air, question="Quoted?", fixes=[dict(typo1, faq_id=quoted["chunk_id"],
                                                              old=inside, new=inside + "x")])]).json()
        check("a fix inside quoted material is refused",
              got["rejected"] and "quoted" in got["rejected"][0]["error"], got)

    got = post([dict(air, fixes=[point, dict(point, faq_id="faq_99999"), draft, typo1, typo2]), factual]).json()
    check("good fixes are kept when one beside them is bad",
          got["accepted"][0]["status"] == "new"
          and [f["status"] for f in got["accepted"][0]["fixes"]] == ["new"] * 4
          and [(r["index"], r["fix_index"]) for r in got["rejected"]] == [(0, 1)], got)
    air_id, fact_id = got["accepted"][0]["item_id"], got["accepted"][1]["item_id"]
    check("one card carries all four fixes, each with its own Why",
          [(f["id"], f["type"], f["reason"]) for f in card(air_id)["fixes"]]
          == [("f1", "point_to_faq", point["reason"]), ("f2", "new_faq", draft["reason"]),
              ("f3", "text_edit", typo1["reason"]), ("f4", "text_edit", typo2["reason"])])
    contact = post([dict(air, question=q_air + " Email me at jo@example.org", fixes=[point])]).json()
    stored = open(m.ANSWER_REVIEW_PATH).read()
    check("contact details are redacted at intake", "[email]" in stored and "jo@example.org" not in stored)
    client.post(f"/admin/answer-review/{contact['accepted'][0]['item_id']}/dismiss",
                json={"by": "T", "reason": "duplicate"}, headers=admin)

    again = post([dict(air, wordings=[q_air, "how do air compressors work"],
                       fixes=[point, dict(typo1, reason="Said again.")])], date="2026-11-21").json()
    check("the same question merges into its open card",
          again["accepted"][0]["item_id"] == air_id and again["accepted"][0]["status"] == "merged"
          and [f["status"] for f in again["accepted"][0]["fixes"]] == ["merged", "merged"], again)
    check("no fix is repeated, and the card carries both days and both wordings",
          len(card(air_id)["fixes"]) == 4 and card(air_id)["review_dates"] == ["2026-11-20", "2026-11-21"]
          and len(card(air_id)["wordings"]) == 2)

    with open(m.ASK_LOG_PATH, "w") as fh:
        for day in ("2026-11-20", "2026-11-20", "2026-11-21"):
            fh.write(json.dumps({"q": q_air, "faq_id": "faq_1154", "date": day}) + "\n")
    asked = view(air_id)["asked"]
    check("times asked is counted from the log", asked == {"date": "2026-11-21", "on_date": 1, "total": 3}, asked)

    d = listing()
    check("Open holds the air card; For the editor holds the factual card",
          [i["id"] for i in d["open"]] == [air_id] and [i["id"] for i in d["editor"]] == [fact_id],
          ([i["id"] for i in d["open"]], [i["id"] for i in d["editor"]]))
    v = next(f for f in view(air_id)["fixes"] if f["id"] == "f3")
    check("a text edit shows the passage before and after",
          v["before"]["text"][slice(*v["before"]["mark"])] == typo1["old"]
          and v["after"]["text"][slice(*v["after"]["mark"])] == typo1["new"], v.get("before"))

    # ── Apply refusals ───────────────────────────────────────────────────────
    check("Apply needs at least one ticked fix", apply(air_id, by="IG").status_code == 400)
    check("Apply refuses a fix not on the card", apply(air_id, by="IG", fix_ids=["f9"]).status_code == 400)
    check("a possible factual error has no Apply", apply(fact_id, by="IG", fix_ids=["f1"]).status_code == 400)
    got = apply(air_id, by="IG", fix_ids=["f1", "f2", "f3"])
    check("pointing to a FAQ and drafting a new one are alternatives: both at once is refused",
          got.status_code == 400 and "choose one answer fix" in got.text, got.text)
    clash = [dict(typo1, id="f1"), dict(typo1, id="f2", old="Either kind of attack", new="Each attack"),
             dict(typo1, id="f3", old="Either attacks", new="Both attacks")]
    reason = m._review_fits_all(clash, air_id)
    check("ticked fixes are checked in order, each against what the earlier ones leave",
          m._review_fits_all(clash[:2], air_id) is None and reason and reason.startswith("fix 3 of 3"), reason)

    # ── Apply two ticked fixes, with the real check ──────────────────────────
    before_1326, before_1154 = json.loads(json.dumps(rec("faq_1326"))), json.loads(json.dumps(rec("faq_1154")))
    check("Apply starts a check", apply(air_id, by="IG", fix_ids=["f1", "f3"]).status_code == 202)
    check("a second Apply while checking is refused", apply(air_id, by="IG", fix_ids=["f2"]).status_code == 409)
    wait(air_id)
    a = last_action(air_id, "applied") if any(x["action"] == "applied" for x in card(air_id)["actions"]) else {}
    check("applied when nothing else moves", a.get("moved") == [], (card(air_id).get("check") or {}))
    check("the check covered every title, phrasing and golden question", a.get("checked", 0) > 450, a.get("checked"))
    check("the question now lands on faq_1326", [t["ok"] for t in a.get("targets", [])] == [True], a.get("targets"))
    check("history records the chosen and the not chosen",
          [f["id"] for f in a.get("chosen", [])] == ["f1", "f3"]
          and [f["id"] for f in a.get("not_chosen", [])] == ["f2", "f4"], a)
    check("history records the answer fix picked", a.get("answer_fix") == "f1", a.get("answer_fix"))
    check("the card's fixes say so", status(air_id) == {"f1": "applied", "f2": "not_chosen",
                                                       "f3": "applied", "f4": "not_chosen"}, status(air_id))
    check("the card leaves Open", air_id not in [i["id"] for i in listing()["open"]])
    check("both records changed",
          q_air in (rec("faq_1326").get("phrasings") or [])
          and "Either kind of attack could last many hours" in rec("faq_1154")["text"])
    check("history keeps each record before and after",
          {c["chunk_id"]: (c["before"], c["after"]) for c in a.get("changes", [])}
          == {"faq_1326": (before_1326, rec("faq_1326")), "faq_1154": (before_1154, rec("faq_1154"))})
    check("one backup, and it is the file as it was",
          a.get("backup") and "phrasings" not in next(
              json.loads(l) for l in open(os.path.join(m.REVIEW_BACKUP_DIR, a["backup"]))
              if json.loads(l)["chunk_id"] == "faq_1326"), a.get("backup"))
    hits = m.retrieve(question_text=q_air, compartment_id="", playhead_time_ms=0)
    check("the live server answers it from faq_1326 at once", hits and hits[0][1]["chunk_id"] == "faq_1326")
    undo_rows = [h for h in listing()["history"] if h["item_id"] == air_id and h["can_undo"]]
    check("History offers Undo on that apply", [h["action"] for h in undo_rows] == ["applied"])

    # ── Undo ─────────────────────────────────────────────────────────────────
    got = client.post(f"/admin/answer-review/{air_id}/undo", json={"by": "IG"}, headers=admin)
    check("Undo restores both records", got.status_code == 200 and rec("faq_1326") == before_1326
          and rec("faq_1154") == before_1154, got.text)
    check("and reopens every option it closed", set(status(air_id).values()) == {"open"}, status(air_id))
    check("Undo twice is refused",
          client.post(f"/admin/answer-review/{air_id}/undo", json={}, headers=admin).status_code == 409)

    # ── Apply anyway, with a check that reports a move ───────────────────────
    real_check = m._review_run_check
    moved = [{"question": "How did the air system work?", "kinds": ["golden"], "before": "faq_1", "after": "faq_2"}]
    m._review_run_check = lambda item, fixes: {"checked": 519, "moved": moved, "targets": [],
                                               "golden": {"before": 84, "after": 83, "total": 127}, "seconds": 0.1}
    text_before = rec("faq_1154")["text"]
    check("override before any check is refused",
          apply(air_id, by="IG", fix_ids=["f4"], override=True).status_code == 409)
    apply(air_id, by="IG", fix_ids=["f4"])
    state = wait(air_id)["check"]
    check("a move stops the write", state["state"] == "moves" and rec("faq_1154")["text"] == text_before, state["state"])
    check("Apply anyway for different fixes is refused",
          apply(air_id, by="IG", fix_ids=["f3", "f4"], override=True).status_code == 409)
    check("Apply anyway without initials is refused", apply(air_id, fix_ids=["f4"], override=True).status_code == 400)
    check("Apply anyway with blank initials is refused",
          apply(air_id, by="  ", fix_ids=["f4"], override=True).status_code == 400)
    check("Apply anyway with initials goes ahead",
          apply(air_id, by="IG", fix_ids=["f4"], override=True).status_code == 202)
    wait(air_id)
    a = last_action(air_id, "applied")
    check("the history records the override, what moved, and the three not chosen",
          a["overridden"] is True and a["moved"] == moved and a["by"] == "IG"
          and [f["id"] for f in a["not_chosen"]] == ["f1", "f2", "f3"], a)
    check("and that no answer fix was picked", a.get("answer_fix") == "none", a.get("answer_fix"))
    check("the punctuation is fixed through the normal save",
          "submerged, quieter and calmer, during" in rec("faq_1154")["text"]
          and rec("faq_1154")["display_citation"].startswith("SubmarineDocent FAQ: "))
    rec("faq_1154")["text"] += " "
    got = client.post(f"/admin/answer-review/{air_id}/undo", json={"by": "IG"}, headers=admin)
    check("Undo is refused once the record changed since", got.status_code == 409, got.text)
    rec("faq_1154")["text"] = rec("faq_1154")["text"][:-1]
    m._review_run_check = real_check

    # ── Edit then apply ──────────────────────────────────────────────────────
    q2 = "What drove the air compressors?"
    got = post([{"question": q2, "got": {"outcome": "fallback"},
                 "fixes": [draft, dict(point, phrasing=q2)]}]).json()
    two = got["accepted"][0]["item_id"]
    edited = {"type": "new_faq", "title": "How did the high-pressure air compressors work?", "note": draft["note"]}
    check("Edit then apply keeps each fix's type",
          apply(two, by="IG", fix_ids=["f1"], edits={"f1": {"type": "point_to_faq", "faq_id": "faq_1326"}}).status_code == 400)
    check("an edited fix is validated like intake",
          apply(two, by="IG", fix_ids=["f1"], edits={"f1": dict(edited, title="A—B?")}).status_code == 400)
    apply(two, by="IG", fix_ids=["f1"], edits={"f1": edited})
    wait(two)
    a = last_action(two, "applied")
    new = rec(a["changes"][0]["chunk_id"]) if a["changes"] else None
    check("the draft is created under a draft prefix, with the edited title, marked for the editor",
          new and new["chunk_id"].startswith("der_review_") and new["title"] == edited["title"]
          and new.get("review_for") == "editor" and new.get("source") == "answer_review", new)
    check("the history keeps the fix as the review sent it",
          a["edited"] == {"f1": {k: v for k, v in draft.items() if k not in ("category", "reason")}}, a["edited"])
    check("drafts alone need no check", a["checked"] == 0)
    check("the draft is the answer fix picked", a.get("answer_fix") == "f1", a.get("answer_fix"))
    check("the unticked option is recorded as not chosen", [f["id"] for f in a["not_chosen"]] == ["f2"])
    check("a draft never answers visitors", new and all(e["chunk_id"] != new["chunk_id"] for e in m.FAQ))
    check("the draft waits under For the editor", two in [i["id"] for i in listing()["editor"]])
    got = client.post(f"/admin/answer-review/{two}/undo", json={"by": "IG"}, headers=admin)
    check("Undo removes an untouched draft", got.status_code == 200 and new and rec(new["chunk_id"]) is None, got.text)

    # ── Resolve, Dismiss, and what comes back ────────────────────────────────
    path = f"/admin/answer-review/{fact_id}/fixes/f1/resolve"
    check("Resolve needs a note", client.post(path, json={"by": "IG"}, headers=admin).status_code == 400)
    check("Resolve with a note",
          client.post(path, json={"by": "IG", "note": "Source requested."}, headers=admin).status_code == 200)
    check("a resolved factual card leaves For the editor", fact_id not in [i["id"] for i in listing()["editor"]])
    check("Dismiss needs a reason",
          client.post(f"/admin/answer-review/{two}/dismiss", json={"by": "IG"}, headers=admin).status_code == 400)
    client.post(f"/admin/answer-review/{two}/dismiss", json={"by": "IG", "reason": "test"}, headers=admin)
    a = last_action(two, "dismissed")
    check("Dismiss closes the whole card and lists its fixes",
          set(status(two).values()) == {"dismissed"} and [f["id"] for f in a["fixes"]] == ["f1", "f2"], a)
    again = post([{"question": q2, "got": {"outcome": "fallback"}, "fixes": [draft]}]).json()
    check("a dismissed fix does not come back",
          again["accepted"][0]["status"] == "nothing_new"
          and again["accepted"][0]["fixes"][0]["status"] == "already_dismissed", again)

    # ── A fix that stopped fitting ───────────────────────────────────────────
    later = post([{"question": "Later?", "got": {"outcome": "fallback"},
                   "fixes": [dict(typo1, new="Each attack could last many hours")]}]).json()
    item = later["accepted"][0]["item_id"]
    rec("faq_1154")["text"] = rec("faq_1154")["text"].replace("Either attacks", "Both kinds of attack")
    check("the page says it no longer fits", view(item)["fixes"][0]["fits"], view(item)["fixes"][0].get("fits"))
    apply(item, by="IG", fix_ids=["f1"])
    check("and Apply writes nothing", wait(item)["check"]["state"] == "no_longer_fits", card(item)["check"])

    shutil.rmtree(work, ignore_errors=True)
    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
