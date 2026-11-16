#!/usr/bin/env python3
"""No public response carries a rights field.

rights_note is the curator's record of a permission and can name the person who
gave it.  Until 16 November 2026 /api/videos served it and the video card printed
it under each video.  Rights notes and statuses are for the admin screens; the
credit line a rights holder requires goes out as the video's credit.

    python3 _test/test_public_no_rights_fields.py
"""
import json
import os
import shutil
import sys
import tempfile

from seed_guard import REPO, load_app

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def rights_keys(obj, path="", found=None):
    found = [] if found is None else found
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.startswith("rights"):
                found.append(f"{path}.{k}")
            rights_keys(v, f"{path}.{k}", found)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            rights_keys(v, f"{path}[{i}]", found)
    return found


def main():
    # The public seed carries no rights notes, so this copy gets them back, as
    # the live site's records have them, or the check would prove nothing.
    root = tempfile.mkdtemp(prefix="publicrights-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)
    path = os.path.join(corpora, "videos.jsonl")
    with open(path, encoding="utf-8") as fh:
        videos = [json.loads(l) for l in fh if l.strip()]
    with open(path, "w", encoding="utf-8") as fh:
        for v in videos:
            v["rights_note"] = f"Granted by A. Person by email ({v.get('id')})."
            fh.write(json.dumps(v, ensure_ascii=False) + "\n")

    m = load_app(copy=corpora)
    from fastapi.testclient import TestClient
    client = TestClient(m.app)
    test = {"X-SubDocent-Test": "1"}

    check("the records served from do carry rights notes, so the check means something",
          all(v.get("rights_note") for v in m._load_videos_raw()))

    museums = client.get("/api/museums").json()
    ids = sorted({str(x.get("id") or "") for x in (museums if isinstance(museums, list) else [])} - {""})
    paths = ["/api/videos", "/api/faqs", "/api/glossary", "/api/eternal-patrol", "/api/boats",
             "/api/faq-categories", "/api/incidents", "/api/moh-recipients", "/api/museums", "/health"]
    paths += [f"/api/videos?museum_id={i}" for i in ids] + [f"/api/faqs?museum_id={i}" for i in ids]
    paths += [f"/api/museums/{i}/pages" for i in ids]
    for p in paths:
        r = client.get(p, headers=test)
        found = rights_keys(r.json()) if r.status_code == 200 else None
        check(f"{p}: no rights fields", r.status_code == 200 and not found, found if found else r.status_code)

    for faq in [e for e in m.FAQ if e.get("video_url") or e.get("video_id") or e.get("related_links")]:
        r = client.post("/ask", json={"question_text": faq["title"]}, headers=test)
        found = rights_keys(r.json()) if r.status_code == 200 else None
        check(f"/ask {faq['chunk_id']}: no rights fields", r.status_code == 200 and not found,
              found if found else r.status_code)

    shutil.rmtree(root, ignore_errors=True)
    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
