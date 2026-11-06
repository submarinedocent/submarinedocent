#!/usr/bin/env python3
"""Lost-boat photo slots: move, swap and remove lose nothing.

On 2 November 2026 the site's editor dragged O-9's captain photo from the boat
slot to the captain slot and got two copies, and could not empty a slot. The
editor now moves a photo with one PUT naming both slots, swaps when the target
is full, and removes by setting the slot to null. A moved photo keeps its file
name, so the upload that follows must not write over it. This test plays those
steps against a temporary disk.

    python3 _test/test_lost_boat_photos.py
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STEPS = r'''
import base64, json, os, sys
sys.path.insert(0, sys.argv[1])
from api import main as m
from fastapi.testclient import TestClient
c = TestClient(m.app)
auth = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}
out = {"on_disk": m._persistent_disk_available and m._ETERNAL_PATROL_PATH.startswith(m._RENDER_DATA_DIR)}
if not out["on_disk"]:
    print("RESULT " + json.dumps(out)); sys.exit(0)
boat = next(b for b in c.get("/api/eternal-patrol").json() if b["boat_number"] == "SS-8")
url = f"/admin/eternal-patrol/{boat['id']}"

def upload(field, data):
    r = c.post(url + "/upload-image", data={"field_name": field},
               files={"image": ("p.jpg", data, "image/jpeg")}, headers=auth)
    return r.json()["path"] if r.status_code == 200 else f"HTTP {r.status_code}"

def put(changes):
    r = c.put(url, json=changes, headers=auth)
    return r.json()["boat"] if r.status_code == 200 else {"status": r.status_code}

def served(path):
    r = c.get("/web/" + path)
    return r.content.decode("latin-1") if r.status_code == 200 else f"HTTP {r.status_code}"

# The captain's photo uploaded into the boat slot, as O-9 was.
wrong = upload("photo_boat", b"captain-portrait")
put({"photo_captain": None})
# Drag to the captain slot: one PUT, both slots.
b = put({"photo_captain": wrong, "photo_boat": None})
out["move"] = [b.get("photo_boat"), b.get("photo_captain") == wrong]
# Upload the real boat photo; then a new captain photo, whose slot name is
# the one the moved file already has unless it was uploaded to the boat slot.
boat_path = upload("photo_boat", b"boat-photo")
out["boat_upload_kept_captain"] = served(wrong)
cap_path = upload("photo_captain", b"new-captain")
out["captain_upload_new_name"] = cap_path != boat_path
out["captain_upload_kept_boat"] = served(boat_path)
# Swap: both slots full.
b = put({"photo_boat": cap_path, "photo_captain": boat_path})
out["swap"] = [served(b["photo_boat"]), served(b["photo_captain"])]
# An upload into the slot now holding the boat-named file keeps the other.
again = upload("photo_captain", b"another")
out["after_swap_upload"] = [again != b["photo_boat"], served(b["photo_boat"])]
# Remove: the slot empties, the file stays.
b = put({"photo_boat": None})
out["remove"] = [b.get("photo_boat"), os.path.exists(os.path.join(m._ETERNAL_PATROL_UPLOAD_DIR, os.path.basename(cap_path)))]
print("RESULT " + json.dumps(out))
'''

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    disk = tempfile.mkdtemp(prefix="lostboatphotos-")
    env = {**os.environ, "SUBDOCENT_DATA_DIR": disk, "ADMIN_USERNAME": "t", "ADMIN_PASSWORD": "t",
           "CONTENT_ROOT": "corpora"}
    p = subprocess.run([sys.executable, "-c", STEPS, REPO], env=env, capture_output=True, text=True, cwd=REPO)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
    if line is None:
        print(p.stdout[-2000:], p.stderr[-2000:])
        sys.exit("run failed")
    out = json.loads(line[len("RESULT "):])
    check("runs on the temporary disk", out["on_disk"] is True)
    if not out["on_disk"]:
        sys.exit("stopped before writing anything")
    check("drag moves: boat slot empty, captain slot has the photo", out["move"] == [None, True], str(out["move"]))
    check("boat upload leaves the moved captain photo intact", out["boat_upload_kept_captain"] == "captain-portrait",
          out["boat_upload_kept_captain"])
    check("captain upload gets its own file name", out["captain_upload_new_name"] is True)
    check("captain upload leaves the boat photo intact", out["captain_upload_kept_boat"] == "boat-photo",
          out["captain_upload_kept_boat"])
    check("swap exchanges the two photos", out["swap"] == ["new-captain", "boat-photo"], str(out["swap"]))
    check("upload after a swap overwrites nothing", out["after_swap_upload"] == [True, "new-captain"],
          str(out["after_swap_upload"]))
    check("remove empties the slot and keeps the file", out["remove"] == [None, True], str(out["remove"]))

    import shutil
    shutil.rmtree(disk, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
