#!/usr/bin/env python3
"""Get Involved page: /get-involved redirects to the page, which is served,
linked from the shared nav and the welcome page, and stores nothing.

The museum short-URL route (/{museum_slug}) is a catch-all for single-segment
paths, so this also proves /get-involved is answered before it.

    python3 _test/test_get_involved_route.py
"""
import os
import re
import shutil
import sys
import tempfile

from seed_guard import load_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "/web/get-involved.html"

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return f.read()


def main():
    root = tempfile.mkdtemp(prefix="getinvolved-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)
    sys.path.insert(0, REPO)
    m = load_app(copy=corpora)
    from fastapi.testclient import TestClient

    client = TestClient(m.app)

    def target(path):
        r = client.get(path, follow_redirects=False)
        return r.status_code, r.headers.get("location")

    check("/get-involved redirects to the page", target("/get-involved") == (307, PAGE), str(target("/get-involved")))
    check("/get-involved.html redirects to the page", target("/get-involved.html") == (307, PAGE), str(target("/get-involved.html")))
    check("recording=1 is carried", target("/get-involved?recording=1") == (307, PAGE + "?recording=1"),
          str(target("/get-involved?recording=1")))
    r = client.get(PAGE)
    check("page is served", r.status_code == 200, str(r.status_code))

    page = read("web/get-involved.html")
    check("page has no form", "<form" not in page.lower())
    check("contact is the mailto link", 'href="mailto:irving@submarinedocent.org"' in page)
    text = re.sub(r"<[^>]+>", " ", page)
    check("page text has no em dash", "—" not in text and "&mdash;" not in page)
    check("page does not mention Pampanito", "pampanito" not in page.lower())
    check("shared nav links the page", "'/web/get-involved.html'" in read("web/site-header.js")
          and "${INVOLVED_HREF}" in read("web/site-header.js"))
    check("welcome page links the page", 'href="/web/get-involved.html"' in read("web/welcome.html"))
    # The FAQ count is read from /health, never written into the page.
    check("FAQ count is not hard-coded", not re.search(r"more than\s+\d", text), re.findall(r"more than\s+\d+", text))
    check("FAQ count has its no-script wording", '<span id="faqCount">hundreds of</span>' in page)
    check("/health reports the FAQ count the page reads", isinstance(client.get("/health").json().get("faq_chunks"), int))

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
