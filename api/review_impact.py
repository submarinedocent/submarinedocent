"""The answer review page's impact check, run in a process of its own.

    python -m api.review_impact job.json out.json

job.json carries a fix, the item id, the item's wordings and the FAQ file the
server writes.  This loads the app from that same file, answers every FAQ title,
every phrasing, every golden visitor question and the item's wordings, applies
the fix in memory through the same code a real apply uses (api.main._review_write
with the save kept in memory), recomputes the corpus statistics as a restart
would, and answers them all again.  out.json says what moved.

Why a separate process: retrieval reads module globals (FAQ, the BM25
statistics), so measuring a changed corpus inside the server would change what
visitors get while it ran.  Here nothing is shared and nothing is written.

Why every question and not those sharing a word with the change: a text edit
changes the corpus-wide average record length, which touches every score.  The
tokenizer is cached within this process only (it is a pure function of its
input), which brings the whole set to well under a minute.
"""
import functools
import json
import os
import sys


def _questions(m, job):
    """[(question, kinds)] in a stable order, each question once."""
    rows = {}

    def add(q, kind):
        q = (q or "").strip()
        if q:
            rows.setdefault(q, []).append(kind)

    for rec in m.FAQ:
        if str(rec.get("chunk_id", "")).startswith(("faq_", "fix_")):
            add(rec.get("title"), f"title of {rec['chunk_id']}")
            for p in m._record_phrasings(rec):
                add(p, f"phrasing of {rec['chunk_id']}")
    golden = os.path.join(m.BASE_DIR, "_test", "golden_visitor_questions.jsonl")
    if os.path.exists(golden):
        with open(golden, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    add(json.loads(line)["question"], "golden")
    for w in job.get("wordings") or []:
        add(w, "this item")
    if job["fix"]["type"] == "point_to_faq":
        add(job["fix"]["phrasing"], "this item")
    return list(rows.items())


def _answer(m, q):
    """The record a visitor typing q would get, the way the CI tests read it."""
    if m._is_short_query(q):
        return "short_query"
    hits = m.retrieve(question_text=q, compartment_id="", playhead_time_ms=0, top_k=8)
    resp = m.synthesize_extractive(question_text=q, hits=hits) if hits else {}
    if not hits or (resp.get("refusal") or {}).get("is_refusal"):
        return "no answer"
    return resp.get("faq_id") or hits[0][1].get("chunk_id") or "no answer"


def _golden_score(m, answers):
    golden = os.path.join(m.BASE_DIR, "_test", "golden_visitor_questions.jsonl")
    if not os.path.exists(golden):
        return None
    with open(golden, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    ok = 0
    for row in rows:
        got = answers.get(row["question"].strip())
        accept = set(row["accept"])
        if got in accept or (got == "no answer" and "refusal" in accept):
            ok += 1
    return ok, len(rows)


def main(job_path, out_path):
    import time
    started = time.time()
    try:
        os.nice(10)   # visitors' answers come first
    except (AttributeError, OSError):
        pass
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    from api import main as m
    if os.path.realpath(m.FAQ_PATH) != os.path.realpath(job["faq_path"]):
        sys.exit(f"loaded {m.FAQ_PATH}, but the server writes {job['faq_path']}")

    original = m.tokenize
    cached = functools.lru_cache(maxsize=None)(lambda text, keep_soft: tuple(original(text, keep_soft)))
    m.tokenize = lambda text, keep_soft=True: list(cached(text, keep_soft))

    questions = _questions(m, job)
    before = {q: _answer(m, q) for q, _ in questions}

    def save_in_memory():
        for entry in m.FAQ_ALL:
            entry["text"] = m._normalize_faq_html(entry.get("text", ""))
        m.FAQ = m._retrievable_faq(m.FAQ_ALL)

    m._save_faq_corpus = save_in_memory
    m._review_write(job["fix"], job["item_id"])
    m._avg_chunk_tokens = None          # statistics as the next restart builds them
    after = {q: _answer(m, q) for q, _ in questions}

    fix = job["fix"]
    own = {q for q, kinds in questions if "this item" in kinds}
    moved = [{"question": q, "kinds": kinds, "before": before[q], "after": after[q]}
             for q, kinds in questions if q not in own and before[q] != after[q]]
    target = None
    if fix["type"] == "point_to_faq":
        target = {"question": fix["phrasing"], "faq_id": fix["faq_id"],
                  "before": before[fix["phrasing"]], "after": after[fix["phrasing"]],
                  "ok": after[fix["phrasing"]] == fix["faq_id"],
                  "wordings": [{"question": q, "before": before[q], "after": after[q]}
                               for q in sorted(own) if q != fix["phrasing"]]}
    golden_before, golden_after = _golden_score(m, before), _golden_score(m, after)
    result = {"checked": len(questions), "moved": moved, "target": target,
              "golden": ({"before": golden_before[0], "after": golden_after[0], "total": golden_before[1]}
                         if golden_before else None),
              "seconds": round(time.time() - started, 1)}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
