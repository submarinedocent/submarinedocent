#!/usr/bin/env python3
"""A record's era is a fixed vocabulary: ww2 or cold_war.

First-hand stories from after 1945 go in "Stories and More" with era cold_war
(19 October 2026).  The era is set on create, can be changed on edit, survives
acceptance, and anything outside the vocabulary is refused.

    python3 _test/test_faq_era.py

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
    root = tempfile.mkdtemp(prefix="faqera-")
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
    entry = lambda cid: next((e for e in m.FAQ_ALL if e["chunk_id"] == cid), None)

    r = client.post("/admin/faq", json={"chunk_id": "der_era_test", "title": "Era test story",
                                        "text": "<p>A story.</p>", "era": "cold_war", "boat": "SS-426"}, headers=auth)
    check("draft created with era cold_war and boat SS-426", r.status_code == 200, r.text[:200])
    check("era stored as cold_war", (entry("der_era_test") or {}).get("era") == "cold_war")

    r = client.post("/admin/faq", json={"chunk_id": "der_era_bad", "title": "Bad era",
                                        "text": "<p>x</p>", "era": "1968"}, headers=auth)
    check("free-text era refused", r.status_code == 400 and entry("der_era_bad") is None, f"got {r.status_code}")

    r = client.post("/admin/faq", json={"chunk_id": "der_era_default", "title": "Default era",
                                        "text": "<p>x</p>"}, headers=auth)
    check("era defaults to ww2", (entry("der_era_default") or {}).get("era") == "ww2")

    r = client.put("/admin/faq/der_era_default", json={"era": "cold_war"}, headers=auth)
    check("era changed on edit", r.status_code == 200 and entry("der_era_default")["era"] == "cold_war")
    r = client.put("/admin/faq/der_era_default", json={"era": "Cold War"}, headers=auth)
    check("edit with unknown era refused", r.status_code == 400 and entry("der_era_default")["era"] == "cold_war")

    r = client.post("/admin/faq/der_era_test/accept", json={}, headers=auth)
    new_id = (r.json() or {}).get("new_id") if r.status_code == 200 else None
    check("acceptance keeps cold_war", new_id and (entry(new_id) or {}).get("era") == "cold_war", r.text[:200])

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
