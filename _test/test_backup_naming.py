#!/usr/bin/env python3
"""Two backups in the same second keep both files.

scripts/backup_site.py names a backup by the second it was taken.  A before and
after backup of one admin edit can land in the same second, and on 19 October
2026 the second overwrote the first.  claim_name() must never overwrite: a
taken name falls through to -2, -3 and so on.

    python3 _test/test_backup_naming.py
"""
import importlib.util
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    spec = importlib.util.spec_from_file_location("backup_site", os.path.join(REPO, "scripts", "backup_site.py"))
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)

    d = tempfile.mkdtemp(prefix="backupnaming-")
    stamp = "2026-10-19_071247"
    outs = []
    for content in (b"before", b"after", b"third"):
        tmp = os.path.join(d, f".part-{content.decode()}")
        with open(tmp, "wb") as fh:
            fh.write(content)
        outs.append(bs.claim_name(tmp, d, stamp))

    names = [os.path.basename(o) for o in outs]
    check("first backup keeps the plain name", names[0] == f"submarinedocent-{stamp}.tar.gz", names[0])
    check("same-second backups get -2 and -3",
          names[1:] == [f"submarinedocent-{stamp}-2.tar.gz", f"submarinedocent-{stamp}-3.tar.gz"], str(names))
    check("nothing was overwritten",
          [open(o, "rb").read() for o in outs] == [b"before", b"after", b"third"])
    check("temporary files are gone", not [f for f in os.listdir(d) if f.startswith(".part-")])

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
