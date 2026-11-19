#!/usr/bin/env python3
"""What's New: a "say" override rewords a commit on the public page only.

    python3 _test/test_whats_new_say.py

Builds a throwaway git repository with a week of commits and points the
generator at it, so the test needs neither this repository's history nor a
deep checkout.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import whats_new  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    root = tempfile.mkdtemp(prefix="whatsnew-")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}

    def git(*args, when=None):
        e = dict(env)
        if when:
            e["GIT_AUTHOR_DATE"] = e["GIT_COMMITTER_DATE"] = when.isoformat()
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                               env=e, check=True).stdout.strip()

    def commit(path, text, subject, when):
        full = os.path.join(root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a", encoding="utf-8") as fh:
            fh.write(text)
        git("add", path)
        git("commit", "-q", "-m", subject, when=when)
        return git("rev-parse", "--short=7", "HEAD")

    start = datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc)
    git("init", "-q")
    commit("README", "x\n", "First commit", start - timedelta(days=3))
    worded = commit("web/museums.html", "<p>a</p>\n", "Museum pages offer their FAQs' videos", start + timedelta(days=1))
    twice = commit("corpora/videos.jsonl", '{"id": "v1"}\n', "Seed refresh: videos", start + timedelta(days=2))
    plain = commit("web/faqs.html", "<p>b</p>\n", "FAQ page: wider answers", start + timedelta(days=3))
    hidden = commit("web/glossary.html", "<p>c</p>\n", "Glossary: spacing", start + timedelta(days=4))

    overrides = os.path.join(root, "overrides.txt")
    with open(overrides, "w", encoding="utf-8") as fh:
        fh.write(f"# a comment\nhide {hidden}  Not news.\n"
                 f"say {worded} Museum pages now show their answers' videos.\n"
                 f"say {twice} First visitor sentence.\nsay {twice} Second visitor sentence.\n"
                 f"say {hidden} Must not appear.\n")

    whats_new.REPO = root
    whats_new.OVERRIDES_FILE = overrides
    public, everything = whats_new.build_entry(start, start + timedelta(days=7))
    lines = [(c["sha"], c["summary"]) for g in public["groups"] for c in g["changes"]]

    check("a say line replaces the subject",
          (worded, "Museum pages now show their answers' videos.") in lines, lines)
    check("the subject is gone from the public page",
          not any(s == "Museum pages offer their FAQs' videos" for _, s in lines), lines)
    check("two say lines give two bullets, each linked to the commit",
          [s for sha, s in lines if sha == twice] == ["First visitor sentence.", "Second visitor sentence."], lines)
    check("a commit without a say line keeps its subject", (plain, "FAQ page: wider answers") in lines, lines)
    check("say does not bring back a hidden commit", not any(sha == hidden for sha, _ in lines), lines)
    check("commits listed still counts commits, not bullets", public["commits_listed"] == 3, public["commits_listed"])

    admin = {c["sha"]: c for c in everything["commits"]}
    check("the admin changelog keeps the subject",
          admin[worded]["summary"] == "Museum pages offer their FAQs' videos", admin[worded])
    check("and records the public wording",
          admin[worded].get("public_wording") == ["Museum pages now show their answers' videos."], admin[worded])
    check("a hidden commit records no public wording", "public_wording" not in admin[hidden], admin[hidden])

    shutil.rmtree(root, ignore_errors=True)
    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
