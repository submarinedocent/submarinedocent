#!/usr/bin/env python3
"""Staging is never indexed; production always can be.

A host with "staging" in its name gets X-Robots-Tag: noindex, nofollow on every
response, pages, API and redirects alike.  The production host never does
unless SITE_NOINDEX is set.

    python3 _test/test_noindex_staging.py
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    os.environ.pop("SITE_NOINDEX", None)
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    paths = ["/health", "/web/museums.html", "/api/museums", "/cod"]
    for host in ("submarinedocent-staging.onrender.com", "staging.submarinedocent.org"):
        for path in paths:
            r = client.get(path, headers={"host": host}, follow_redirects=False)
            check(f"{host}{path} carries noindex",
                  r.headers.get("x-robots-tag") == "noindex, nofollow",
                  f"status {r.status_code}, header {r.headers.get('x-robots-tag')!r}")
    r = client.get("/health", headers={"host": "x.example", "x-forwarded-host": "submarinedocent-staging.onrender.com"})
    check("staging behind a proxy (x-forwarded-host) carries noindex", r.headers.get("x-robots-tag") == "noindex, nofollow")

    for host in ("submarinedocent.org", "www.submarinedocent.org", "localhost"):
        for path in paths:
            r = client.get(path, headers={"host": host}, follow_redirects=False)
            check(f"{host}{path} has no noindex", "x-robots-tag" not in r.headers,
                  f"header {r.headers.get('x-robots-tag')!r}")

    m.SITE_NOINDEX = True
    r = client.get("/health", headers={"host": "submarinedocent.org"})
    check("SITE_NOINDEX forces noindex on any host", r.headers.get("x-robots-tag") == "noindex, nofollow")
    m.SITE_NOINDEX = False

    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
