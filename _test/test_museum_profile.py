#!/usr/bin/env python3
"""Museum page profile fields: stored when valid, refused whole when not.

The museum page template renders a museum's tagline, about and museum text,
patrol list and highlights from its row in museums.jsonl.  A bad value is
refused before anything changes, so a museum is never left half-edited.

    python3 _test/test_museum_profile.py

Runs against a temporary copy of the real corpora. It writes, so it must never
be pointed at corpora/ itself.
"""
import base64
import json
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
    root = tempfile.mkdtemp(prefix="museumprofile-")
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

    museum = next(x for x in m._load_museums() if x.get("slug"))
    mid = int(museum["id"])

    def stored():
        with open(os.path.join(corpora, "museums.jsonl")) as fh:
            for line in fh:
                row = json.loads(line)
                if int(row.get("id") or 0) == mid:
                    return row
        return None

    good = {
        "hull_number": "SS-999",
        "boat_class": "Test",
        "tagline": "A test boat.",
        "about": "First paragraph.\n\nSecond paragraph.",
        "museum_text": "Open sometimes.",
        "patrols_source": "A source",
        "patrols_source_url": "https://example.org/source",
        "patrols": [{"dates": "1943", "area": "Somewhere", "result": "Something", "key": True},
                    {"label": "Patrol 2", "result": "Nothing"}],
        "highlights": [{"kind": "callout", "title": "Big", "text": "Words."},
                       {"title": "Small", "text": "Card."}],
    }
    r = client.put(f"/admin/museums/{mid}", json=good, headers=auth)
    check("valid profile accepted", r.status_code == 200, f"got {r.status_code} {r.text[:200]}")
    row = stored()
    check("profile written to museums.jsonl", row.get("tagline") == "A test boat." and len(row.get("patrols") or []) == 2)
    check("patrol label defaults to its position", row["patrols"][0]["label"] == "Patrol 1", str(row["patrols"][0]))
    check("patrol key kept as a boolean", row["patrols"][0]["key"] is True and row["patrols"][1]["key"] is False)
    check("highlight kind defaults to card", row["highlights"][1]["kind"] == "card")
    check("existing fields untouched", row.get("name") == museum.get("name") and row.get("slug") == museum.get("slug"))

    public = next(x for x in client.get("/api/museums").json() if int(x["id"]) == mid)
    check("public API carries the profile", public.get("hull_number") == "SS-999" and public.get("highlights"))

    before = json.dumps(stored(), sort_keys=True)
    bad_cases = [
        ("javascript source link", {"tagline": "changed", "patrols_source_url": "javascript:alert(1)"}),
        ("patrols not a list", {"tagline": "changed", "patrols": "seven"}),
        ("empty patrol", {"tagline": "changed", "patrols": [{"label": "Patrol 1"}]}),
        ("unknown highlight kind", {"tagline": "changed", "highlights": [{"kind": "banner", "title": "x"}]}),
        ("highlight without title", {"tagline": "changed", "highlights": [{"text": "x"}]}),
        ("tagline too long", {"tagline": "x" * 301}),
        ("about not a string", {"tagline": "changed", "about": ["a"]}),
    ]
    for label, body in bad_cases:
        r = client.put(f"/admin/museums/{mid}", json=body, headers=auth)
        check(f"refused: {label}", r.status_code == 400, f"got {r.status_code}")
    check("refused writes left the museum unchanged", json.dumps(stored(), sort_keys=True) == before)

    r = client.put(f"/admin/museums/{mid}", json={"patrols": [], "tagline": ""}, headers=auth)
    row = stored()
    check("empty values clear fields", r.status_code == 200 and row.get("patrols") == [] and row.get("tagline") == "")
    check("other profile fields kept when not sent", row.get("hull_number") == "SS-999" and row.get("highlights"))

    r = client.put(f"/admin/museums/{mid}", json={"tagline": "x"})
    check("profile write needs admin credentials", r.status_code in (401, 403), f"got {r.status_code}")

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
