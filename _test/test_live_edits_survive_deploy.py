#!/usr/bin/env python3
"""A deploy never overwrites content edited on the live site.

Lost boats, their uploaded photos and the Medal of Honor list are edited on the
live site, and visitor feedback is written there, so all four live on the
persistent disk (30 October 2026).  Until then
they were read from the bundled corpora/ and web/ copies, which every deploy
replaces.  This test plays two deploys against a temporary disk: edits and an
upload made after the first must still be served after the second, a photo in
git must still be served from the bundle, and the repository's own files must
not be touched.

    python3 _test/test_live_edits_survive_deploy.py
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


# Runs inside a fresh interpreter, so each call is a fresh deploy reading the disk.
DEPLOY = r'''
import base64, json, sys
sys.path.insert(0, sys.argv[1])
from api import main as m
from fastapi.testclient import TestClient
c = TestClient(m.app)
auth = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}
out = {"persistent": m._persistent_disk_available}
if not out["persistent"] or not m._ETERNAL_PATROL_PATH.startswith(m._RENDER_DATA_DIR):
    # Not on the temporary disk: writing now would edit the repository's own files.
    print("RESULT " + json.dumps(out)); sys.exit(0)
boat = next(b for b in c.get("/api/eternal-patrol").json() if b["boat_number"] == "SS-8")
if sys.argv[2] == "edit":
    out["put_boat"] = c.put(f"/admin/eternal-patrol/{boat['id']}", json={"prior_history": "Edited live."}, headers=auth).status_code
    out["put_moh"] = c.put("/admin/moh-recipients/1", json={"citation_summary": "Edited live."}, headers=auth).status_code
    out["upload"] = c.post(f"/admin/eternal-patrol/{boat['id']}/upload-image", data={"field_name": "photo_boat"},
                           files={"image": ("new.jpg", b"uploaded-on-live-site", "image/jpeg")}, headers=auth).status_code
    out["feedback_post"] = c.post("/feedback", json={"source": "contact", "message": "Sent live.", "email": "v@example.org"}).status_code
boat = next(b for b in c.get("/api/eternal-patrol").json() if b["boat_number"] == "SS-8")
out["prior_history"] = boat.get("prior_history")
out["photo_boat"] = boat.get("photo_boat")
out["moh"] = next(e for e in c.get("/api/moh-recipients").json() if e["id"] == 1)["citation_summary"]
r = c.get("/web/" + boat["photo_boat"])
out["photo_status"], out["photo_bytes"] = r.status_code, r.content.decode("latin-1")
other = next(b for b in c.get("/api/eternal-patrol").json() if b["boat_number"] == "SS-238")
r = c.get("/web/" + other["photo_boat"])
out["bundled_status"], out["bundled_len"] = r.status_code, len(r.content)
r = c.get("/feedback/list", headers=auth)
fb = r.json() if r.status_code == 200 else None
fb = fb if isinstance(fb, list) else (fb or {}).get("entries", [])
out["feedback"] = [e.get("message") for e in fb]
import io, tarfile
r = c.get("/admin/backup", headers=auth)
names = tarfile.open(fileobj=io.BytesIO(r.content), mode="r:gz").getnames() if r.status_code == 200 else []
out["backup_feedback"] = [n for n in names if n.endswith("feedback.jsonl")]
out["contact_failures_on_disk"] = m.CONTACT_FAILURES_PATH.startswith(m._RENDER_DATA_DIR + "/")
print("RESULT " + json.dumps(out))
'''


def deploy(disk, mode):
    env = {**os.environ, "SUBDOCENT_DATA_DIR": disk, "ADMIN_USERNAME": "t", "ADMIN_PASSWORD": "t"}
    # The default corpora, as production runs.  Set, not unset: .env.local fills
    # an unset CONTENT_ROOT, and on 30 Oct 2026 that sent this test's writes
    # into corpora_local.
    env["CONTENT_ROOT"] = "corpora"
    p = subprocess.run([sys.executable, "-c", DEPLOY, REPO, mode], env=env, capture_output=True, text=True, cwd=REPO)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        print(p.stdout[-2000:], p.stderr[-2000:])
        sys.exit("deploy run failed")
    return json.loads(line[len("RESULT "):])


def digest(*paths):
    h = hashlib.sha256()
    for path in paths:
        if os.path.isdir(path):
            for root, _, files in sorted(os.walk(path)):
                for name in sorted(files):
                    with open(os.path.join(root, name), "rb") as f:
                        h.update(name.encode() + f.read())
        else:
            with open(path, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def main():
    tracked = [os.path.join(REPO, "corpora", "eternal_patrol.jsonl"),
               os.path.join(REPO, "corpora", "moh_recipients.jsonl"),
               os.path.join(REPO, "web", "images", "extracted")]
    before = digest(*tracked)
    feedback_before = os.path.exists(os.path.join(REPO, "feedback.jsonl"))
    disk = tempfile.mkdtemp(prefix="livedeploy-")

    first = deploy(disk, "edit")
    check("first deploy runs on the disk", first["persistent"] is True)
    if "put_boat" not in first:
        check("lost boats read from the disk", False, "they read the bundled copy, which a deploy replaces")
        sys.exit("stopped before writing anything")
    check("edits, upload and feedback accepted",
          (first["put_boat"], first["put_moh"], first["upload"], first["feedback_post"]) == (200, 200, 200, 200), str(first))
    check("feedback written to the disk", os.path.exists(os.path.join(disk, "feedback.jsonl")))
    check("lost-boat file seeded onto the disk", os.path.exists(os.path.join(disk, "eternal_patrol.jsonl")))
    check("Medal of Honor file seeded onto the disk", os.path.exists(os.path.join(disk, "moh_recipients.jsonl")))
    check("upload written to the disk", os.path.isdir(os.path.join(disk, "eternal_patrol_images"))
          and os.listdir(os.path.join(disk, "eternal_patrol_images")))

    second = deploy(disk, "read")
    check("lost-boat edit survives a deploy", second["prior_history"] == "Edited live.", str(second["prior_history"]))
    check("Medal of Honor edit survives a deploy", second["moh"] == "Edited live.", str(second["moh"]))
    check("uploaded photo survives a deploy and is served",
          second["photo_status"] == 200 and second["photo_bytes"] == "uploaded-on-live-site",
          f"{second['photo_status']} {second['photo_boat']}")
    check("photo in git still served from the bundle", second["bundled_status"] == 200 and second["bundled_len"] > 1000,
          f"{second['bundled_status']} {second['bundled_len']}")
    check("feedback survives a deploy", second["feedback"] == ["Sent live."], str(second["feedback"]))
    check("unsent historian messages are kept on the disk", second["contact_failures_on_disk"] is True)
    check("backup holds feedback once", second["backup_feedback"] == ["data/feedback.jsonl"], str(second["backup_feedback"]))
    check("repository files untouched", digest(*tracked) == before)
    check("no feedback file in the app directory", not os.path.exists(os.path.join(REPO, "feedback.jsonl")) or feedback_before)

    import shutil
    shutil.rmtree(disk, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
