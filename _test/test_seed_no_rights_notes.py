#!/usr/bin/env python3
"""The public seed carries no rights notes.

A rights note is the curator's record of a permission and can name the person
who gave it.  The live site keeps the notes; corpora/videos.jsonl keeps only
rights_status, which the rights gate reads, and the credit line.
scripts/refresh_seed.py drops the notes on the way out and refuses to stage if
one is left.

    python3 _test/test_seed_no_rights_notes.py
"""
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("refresh_seed", os.path.join(REPO, "scripts", "refresh_seed.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def has_rights_note(obj):
    if isinstance(obj, dict):
        return "rights_note" in obj or any(has_rights_note(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_rights_note(v) for v in obj)
    return False


def main():
    with open(os.path.join(REPO, "corpora", "videos.jsonl"), encoding="utf-8") as fh:
        videos = [json.loads(l) for l in fh if l.strip()]
    noted = [v.get("id") for v in videos if has_rights_note(v)]
    check(f"corpora/videos.jsonl: none of {len(videos)} records has a rights_note", not noted, noted[:5])
    check("rights_status stays, for the rights gate", all(v.get("rights_status") for v in videos),
          [v.get("id") for v in videos if not v.get("rights_status")][:5])

    live = [{"id": "vid_a", "rights_status": "granted", "rights_note": "Granted by A. Person by email.",
             "video_credit": "Courtesy Example", "video_credit_url": "https://example.org"},
            {"id": "vid_b", "rights_status": "not_required"}]
    out, note = rs.transform("videos.jsonl", [dict(r) for r in live])
    check("the refresh drops the note", not any("rights_note" in r for r in out), out)
    check("and keeps status and credit",
          out[0]["rights_status"] == "granted" and out[0]["video_credit"] == "Courtesy Example"
          and out[0]["video_credit_url"] == "https://example.org", out[0])
    check("and says how many it kept private", note == "1 rights note(s) kept private", note)

    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
