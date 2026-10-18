#!/usr/bin/env python3
"""A new disk gets the bundled uploads; a disk in use never does.

_seed_upload_dir fills a missing or empty upload folder from the bundled copy
and leaves any folder that already holds a file alone, so an upload deleted on
the live site cannot come back from the seed.

    python3 _test/test_seed_upload_dir.py
"""
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def main():
    sys.path.insert(0, REPO)
    from api import main as m

    root = tempfile.mkdtemp(prefix="seedupload-")
    bundled = os.path.join(root, "bundled", "museum_uploads")
    write(os.path.join(bundled, "1", "1_photo.jpg"), b"seed")
    write(os.path.join(bundled, "2", "1_other.png"), b"seed2")

    missing = os.path.join(root, "disk_missing", "museum_uploads")
    m._seed_upload_dir(missing, bundled)
    check("missing folder is filled", os.path.exists(os.path.join(missing, "1", "1_photo.jpg"))
          and os.path.exists(os.path.join(missing, "2", "1_other.png")))

    empty = os.path.join(root, "disk_empty", "museum_uploads")
    os.makedirs(os.path.join(empty, "1"))
    m._seed_upload_dir(empty, bundled)
    check("empty folder (subfolders, no files) is filled", os.path.exists(os.path.join(empty, "1", "1_photo.jpg")))

    in_use = os.path.join(root, "disk_in_use", "museum_uploads")
    write(os.path.join(in_use, "1", "1_photo.jpg"), b"live")
    m._seed_upload_dir(in_use, bundled)
    check("folder in use: existing file not overwritten",
          open(os.path.join(in_use, "1", "1_photo.jpg"), "rb").read() == b"live")
    check("folder in use: deleted upload not brought back",
          not os.path.exists(os.path.join(in_use, "2", "1_other.png")))

    m._seed_upload_dir(os.path.join(root, "disk_x", "museum_uploads"), os.path.join(root, "nope"))
    check("no bundled folder: nothing created", not os.path.exists(os.path.join(root, "disk_x")))

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
