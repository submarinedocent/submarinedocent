#!/usr/bin/env python3
"""The seed refresh keeps private names out of the public corpora/.

refresh_seed.py applies a private list of find/replace pairs to every string in
every exported record and refuses to stage if a never_public string survives.
The real list lives in docs/internal/, outside this repository; this test uses
a made-up name.

    python3 _test/test_seed_redactions.py
"""
import importlib.util
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("refresh_seed", os.path.join(REPO, "scripts", "refresh_seed.py"))
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    path = os.path.join(tempfile.mkdtemp(prefix="redact-"), "list.json")
    with open(path, "w") as fh:
        json.dump({"replace": [{"find": "Example Films (Jane Q. Sample)", "replace": "Example Films"},
                               {"find": "Jane Q. Sample", "replace": "Example Films"}],
                   "never_public": ["Sample"]}, fh)
    pairs, never = rs.load_redactions(path)

    record = {"id": "vid_x", "video_credit": "Courtesy Example Films",
              "rights_note": "Permission of Example Films (Jane Q. Sample), granted by email. "
                             "Jane Q. Sample later approved.",
              "tags": ["Jane Q. Sample"], "nested": {"note": "Jane Q. Sample"}, "display_order": 3}
    [out], n = rs.redact([record], pairs)
    check("the name in parentheses goes, the company stays",
          out["rights_note"].startswith("Permission of Example Films, granted by email."), out["rights_note"])
    check("a bare name becomes the company", out["rights_note"].endswith("Example Films later approved."))
    check("lists and nested records are covered", out["tags"] == ["Example Films"] and out["nested"]["note"] == "Example Films")
    check("other fields untouched", out["video_credit"] == record["video_credit"] and out["display_order"] == 3)
    check("replacements counted", n == 4, n)
    check("the input record is not changed", "Jane Q. Sample" in record["rights_note"])
    check("nothing forbidden survives", not rs.forbidden_in(json.dumps(out), never))
    check("a missed form is caught, case ignored",
          rs.forbidden_in("approved by J. SAMPLE", never) == ["Sample"])

    missing = os.path.join(os.path.dirname(path), "absent.json")
    try:
        rs.load_redactions(missing)
        check("a missing list refuses to run", False, "no exit")
    except SystemExit:
        check("a missing list refuses to run", True)

    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
