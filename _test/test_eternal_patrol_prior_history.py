#!/usr/bin/env python3
"""A lost boat carries an optional Prior History (29 October 2026).

The editor saves it, the public list returns it, and a new boat starts with it
empty.  The pages show the section after Loss Narrative (Irving,
30 October 2026), only when it has text.

    python3 _test/test_eternal_patrol_prior_history.py

Runs against a temporary copy of the real corpora. It writes, so it must never
be pointed at corpora/ itself.
"""
import base64
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    root = tempfile.mkdtemp(prefix="epprior-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)
    os.environ["CONTENT_ROOT"] = corpora
    os.environ["ADMIN_USERNAME"] = "t"
    os.environ["ADMIN_PASSWORD"] = "t"
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    auth = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}
    public = lambda bid: next((b for b in client.get("/api/eternal-patrol").json() if b["id"] == bid), None)

    boat = client.get("/api/eternal-patrol").json()[0]
    bid = boat["id"]
    before = dict(boat)

    r = client.put(f"/admin/eternal-patrol/{bid}", json={"prior_history": "  Five patrols before her loss.  "}, headers=auth)
    check("prior_history saved", r.status_code == 200, r.text[:200])
    after = public(bid) or {}
    check("public list returns it, trimmed", after.get("prior_history") == "Five patrols before her loss.", str(after.get("prior_history")))
    check("other fields untouched",
          all(after.get(k) == v for k, v in before.items() if k != "prior_history"))

    with open(os.path.join(corpora, "eternal_patrol.jsonl"), encoding="utf-8") as f:
        check("written to the corpus file", "Five patrols before her loss." in f.read())

    r = client.post("/admin/eternal-patrol", json={"name": "Prior history test"}, headers=auth)
    new_id = ((r.json() or {}).get("boat") or {}).get("id") if r.status_code == 200 else None
    check("new boat starts with empty prior_history", new_id is not None and (public(new_id) or {}).get("prior_history") == "", r.text[:200])

    for page in ("web/faqs.html", "web/eternal-patrol.html"):
        with open(os.path.join(REPO, page), encoding="utf-8") as f:
            s = f.read()
        c, l, p = (s.find(">Construction<"), s.find(">Loss Narrative<"), s.find(">Prior History<"))
        check(f"{page}: Prior History follows Loss Narrative", -1 < c < l < p, f"{c} {l} {p}")

    with open(os.path.join(REPO, "web/edit_lost_boats.html"), encoding="utf-8") as f:
        s = f.read()
    check("editor has the field", 'id="field-prior_history"' in s and "'prior_history'," in s)

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
