#!/usr/bin/env python3
"""Museum short URLs: /cod redirects to the museum page, carrying recording only.

?recording=1 or 0 is the screen-recording switch (web/recording-mode.js); the
redirect must pass it on, and must pass nothing else from the query string.

    python3 _test/test_museum_slug_redirect.py
"""
import os
import shutil
import sys
import tempfile

from seed_guard import load_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    root = tempfile.mkdtemp(prefix="museumslug-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)
    sys.path.insert(0, REPO)
    m = load_app(copy=corpora)
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    museum = next(x for x in m._load_museums() if x.get("slug"))
    slug, base = museum["slug"], f"/web/museums.html?museum={museum['id']}"

    def target(query=""):
        r = client.get(f"/{slug}{query}", follow_redirects=False)
        return r.status_code, r.headers.get("location")

    check("plain slug redirects to the museum page", target() == (307, base), str(target()))
    check("recording=1 is carried", target("?recording=1") == (307, base + "&recording=1"), str(target("?recording=1")))
    check("recording=0 is carried", target("?recording=0") == (307, base + "&recording=0"), str(target("?recording=0")))
    check("other recording values dropped", target("?recording=yes") == (307, base), str(target("?recording=yes")))
    check("other parameters dropped", target("?x=1&museum=2") == (307, base), str(target("?x=1&museum=2")))
    check("unknown slug is a 404", client.get("/no-such-museum-slug", follow_redirects=False).status_code == 404)

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
