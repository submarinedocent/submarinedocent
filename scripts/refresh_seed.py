#!/usr/bin/env python3
"""
scripts/refresh_seed.py  —  make refresh-seed

Refresh the bundled corpora/ seed from what the live site is actually
serving, and stage the result without committing.

WHY THIS EXISTS
---------------
corpora/ is a seed, not the live content.  On Render the editable corpora
live on a persistent disk at /data, seeded from corpora/ on first boot and
authoritative from then on, so a curator's edits never reach this repository
by themselves.  The two drift apart silently and continuously.  On
18 September 2026 the gap had reached 67 records, and the bundled copy still
contained material that had been withdrawn from the live site three weeks
earlier.

WHAT IT DOES
------------
  * pulls the deployment's own corpora via GET /admin/backup
  * FAQ corpus: keeps only faq_ and fix_ records.  der_ and pam_ chunks are
    unreviewed drafts; they cannot answer a visitor on the live site and are
    not published here either, because nobody has read them
  * museums.jsonl: clears any tour_url, which still points at a withdrawn
    page that 404s
  * videos.jsonl: drops every rights_note.  A rights note is the curator's
    record of a permission and can name the person who gave it; the full
    notes stay on the live site and in its backups.  The credit line and
    rights_status stay, because the site's rights gate reads rights_status
  * applies the private redaction list (docs/internal/seed-redactions.json)
    to every string in every record, so a personal name the live site keeps
    in a rights note does not reach this public repository, then refuses to
    stage if any of the list's forbidden strings is still in corpora/
  * refreshes every other corpus the deployment holds a copy of
  * prints a per-file diff and validates the result
  * stages the changes and stops, so a person reads the diff before it
    becomes history

It never commits and never pushes.

USAGE
-----
    export SUBDOCENT_BASE_URL=https://submarinedocent.org
    export ADMIN_USERNAME=... ADMIN_PASSWORD=...
    make refresh-seed              # or: --dry-run to look without writing

Credentials come from the environment only, never from arguments, which
would put them in shell history and process listings.
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPORA = os.path.join(REPO, "corpora")

ANSWERABLE_PREFIXES = ("faq_", "fix_")
DEFAULT_BASE_URL = "https://submarinedocent.org"

# Files that live on /data but must never enter corpora/.
NEVER_SEED = frozenset({"ask_log.jsonl", "feedback.jsonl", "contact_messages.jsonl",
                        "contact_failures.jsonl", "answer_review.jsonl"})

# Personal names the live site keeps (in a rights note, say) and the public seed
# does not.  The list is private: a list of names to keep out of this repository
# cannot itself be in it.  docs/internal/ is a separate private repository.
#   {"replace": [{"find": "...", "replace": "..."}], "never_public": ["..."]}
REDACTIONS_PATH = os.path.join(REPO, "docs", "internal", "seed-redactions.json")


def load_redactions(path=REDACTIONS_PATH):
    """([(find, replace)], [never_public]) from the private list."""
    if not os.path.exists(path):
        sys.exit(f"{os.path.relpath(path, REPO)} not found.  It lists the personal names the "
                 "seed must not carry; without it nothing can be checked, so nothing is written.")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    pairs = [(r["find"], r["replace"]) for r in data.get("replace", [])]
    never = [str(n) for n in data.get("never_public", []) if str(n).strip()]
    return pairs, never


def redact(value, pairs):
    """(value with every pair applied to every string in it, replacements made)."""
    if isinstance(value, str):
        n = 0
        for find, repl in pairs:
            if find in value:
                n += value.count(find)
                value = value.replace(find, repl)
        return value, n
    if isinstance(value, list):
        out, n = [], 0
        for item in value:
            item, k = redact(item, pairs)
            out.append(item)
            n += k
        return out, n
    if isinstance(value, dict):
        out, n = {}, 0
        for key, item in value.items():
            item, k = redact(item, pairs)
            out[key] = item
            n += k
        return out, n
    return value, 0


def forbidden_in(text, never):
    """The never_public strings found in text, ignoring case."""
    low = text.lower()
    return [n for n in never if n.lower() in low]


def env(name, default=None):
    v = os.getenv(name, "").strip()
    if not v and default is None:
        sys.exit(f"{name} is not set. Export it; this script never takes it as an argument.")
    return v or default


def fetch_backup(base, auth):
    req = urllib.request.Request(base.rstrip("/") + "/admin/backup")
    req.add_header("Authorization", "Basic " + auth)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            if r.status != 200:
                sys.exit(f"GET /admin/backup returned {r.status}")
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"GET /admin/backup returned {e.code}: {e.read()[:200]!r}")
    except Exception as e:
        sys.exit(f"GET /admin/backup failed: {type(e).__name__}: {e}")


def load_jsonl_text(text):
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def key_of(record):
    return str(record.get("chunk_id") or record.get("id") or "")


def transform(filename, records):
    """Per-file rules. Returns (records, note)."""
    if filename == "dieselsubs_faq_corpus.jsonl":
        kept = [r for r in records if key_of(r).startswith(ANSWERABLE_PREFIXES)]
        return kept, f"{len(records) - len(kept)} unreviewed drafts withheld"
    if filename == "videos.jsonl":
        n = 0
        for r in records:
            if "rights_note" in r:
                del r["rights_note"]
                n += 1
        return records, (f"{n} rights note(s) kept private" if n else "")
    if filename == "museums.jsonl":
        n = 0
        for r in records:
            if (r.get("tour_url") or "").strip():
                r["tour_url"] = None
                n += 1
        return records, (f"{n} withdrawn tour_url cleared" if n else "")
    return records, ""


def rewrite_inventory_counts(counts):
    """Update the record counts in corpora/README.md from what was just written.

    The inventory table states a record count per file. Hand-maintained, it goes
    stale the first time a refresh lands and nobody remembers to edit it -- and a
    stale count in the file that documents provenance is worse than no count,
    because a reader has no way to tell it is wrong. Rewriting it here means the
    number can only ever be what the corpus actually holds.

    Matches the leading `filename` cell and replaces the count cell after it.
    Rows naming several files, or none, are left alone.
    """
    path = os.path.join(CORPORA, "README.md")
    if not os.path.exists(path):
        return []
    text = open(path, encoding="utf-8").read()
    changed = []
    for filename, n in sorted(counts.items()):
        # | `name.jsonl` | 123 | ...   ->   | `name.jsonl` | <new> | ...
        rx = re.compile(r"(^\|\s*`" + re.escape(filename) + r"`\s*\|\s*)([\d,]+)(\s*\|)",
                        re.M)
        m = rx.search(text)
        if not m:
            continue
        was = m.group(2)
        now = f"{n:,}"
        if was != now:
            text = rx.sub(lambda mo: mo.group(1) + now + mo.group(3), text, count=1)
            changed.append((filename, was, now))
    if changed:
        open(path, "w", encoding="utf-8").write(text)
    return changed


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.getenv("SUBDOCENT_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would change; write and stage nothing")
    args = ap.parse_args()

    # A refresh tangled up with hand edits is unreviewable: the diff stops
    # saying which change came from the live site and which came from a person.
    dirty = git("status", "--porcelain", "corpora")
    if dirty and not args.dry_run:
        print("corpora/ has uncommitted changes:\n" +
              "\n".join("  " + l for l in dirty.splitlines()))
        sys.exit("\nCommit or stash them first, so this refresh is the only thing in the diff.")

    pairs, never = load_redactions()

    auth = base64.b64encode(
        f"{env('ADMIN_USERNAME')}:{env('ADMIN_PASSWORD')}".encode()).decode()
    print(f"source : {args.base_url}")
    blob = fetch_backup(args.base_url, auth)
    print(f"         {len(blob):,} bytes\n")

    changed, unshipped, rows, leaks = [], [], [], []
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        members = {os.path.basename(m.name): m for m in tar.getmembers()
                   if m.name.endswith(".jsonl")}
        for filename in sorted(members):
            if filename in NEVER_SEED:
                continue  # operational data that must never enter corpora/
            local = os.path.join(CORPORA, filename)
            if not os.path.exists(local):
                unshipped.append(filename)
                continue
            live = load_jsonl_text(tar.extractfile(members[filename]).read().decode("utf-8"))
            live, note = transform(filename, live)
            live, redacted = redact(live, pairs)
            if redacted:
                note = "; ".join(x for x in (note, f"{redacted} private name(s) redacted") if x)
            if forbidden_in(json.dumps(live, ensure_ascii=False), never):
                leaks.append(filename)
            have = load_jsonl_text(open(local, encoding="utf-8").read())

            live_keys, have_keys = {key_of(r) for r in live}, {key_of(r) for r in have}
            added, removed = live_keys - have_keys, have_keys - live_keys
            by_key = {key_of(r): r for r in have}
            edited = sum(1 for r in live
                         if key_of(r) in have_keys and by_key[key_of(r)] != r)

            if not (added or removed or edited):
                rows.append((filename, len(have), len(live), 0, 0, 0, "unchanged"))
                continue
            rows.append((filename, len(have), len(live), len(added), len(removed), edited, note))
            changed.append((filename, local, live, sorted(added)[:4], sorted(removed)[:4]))

    print(f"{'FILE':<34}{'WAS':>6}{'NOW':>6}{'+':>5}{'-':>5}{'~':>5}  NOTE")
    for f, was, now, a, r, e, note in rows:
        print(f"  {f:<32}{was:>6}{now:>6}{a:>5}{r:>5}{e:>5}  {note}")
    if unshipped:
        print("\non the live disk but not shipped in corpora/ (ignored):")
        for f in unshipped:
            print(f"  {f}")

    if leaks:
        # Before anything is written, dry run included: the redaction list's
        # pairs did not cover a name its never_public list forbids.
        sys.exit("\nREFUSED: a private name survives redaction in " + ", ".join(leaks) +
                 ".  Add a replace pair to docs/internal/seed-redactions.json.  Nothing written.")

    if not changed:
        print("\nAlready in step with the live site. Nothing to do.")
        return

    for f, _p, _recs, added, removed in changed:
        if added or removed:
            print(f"\n  {f}")
            if added:
                print(f"    added   : {', '.join(added)}{' ...' if len(added) == 4 else ''}")
            if removed:
                print(f"    removed : {', '.join(removed)}{' ...' if len(removed) == 4 else ''}")

    if args.dry_run:
        print("\nDRY RUN. Nothing written.")
        return

    for filename, local, records, _a, _r in changed:
        with open(local, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Validate what was just written, not what we meant to write.
    faq_path = os.path.join(CORPORA, "dieselsubs_faq_corpus.jsonl")
    cat_path = os.path.join(CORPORA, "dieselsubs_faq_categories.jsonl")
    problems = []
    if os.path.exists(faq_path):
        faq = load_jsonl_text(open(faq_path, encoding="utf-8").read())
        stowaways = [key_of(r) for r in faq if not key_of(r).startswith(ANSWERABLE_PREFIXES)]
        if stowaways:
            problems.append(f"{len(stowaways)} unreviewed record(s) in the FAQ corpus: "
                            f"{', '.join(stowaways[:5])}")
        if os.path.exists(cat_path):
            # FAQ records name their category as a string, so the two files are a
            # matched pair: refresh one without the other and every record points
            # at a category that does not exist.
            defined = {(c.get("title") or c.get("name") or "").strip()
                       for c in load_jsonl_text(open(cat_path, encoding="utf-8").read())}
            used = {(r.get("category") or "").strip() for r in faq if (r.get("category") or "").strip()}
            missing = sorted(used - defined)
            if missing:
                problems.append(f"category referenced but not defined: {', '.join(missing)}")
            print(f"\ncategory integrity: {len(used)} referenced, {len(defined)} defined, "
                  f"{'none dangling' if not missing else 'DANGLING'}")

    videos_path = os.path.join(CORPORA, "videos.jsonl")
    if os.path.exists(videos_path):
        noted = [key_of(r) for r in load_jsonl_text(open(videos_path, encoding="utf-8").read())
                 if "rights_note" in r]
        if noted:
            problems.append(f"{len(noted)} video(s) in the seed carry a rights_note: {', '.join(noted[:5])}")

    # Every seed file, not only the ones written now: a name that reached
    # corpora/ by hand is as public as one this refresh would have added.
    for filename in sorted(os.listdir(CORPORA)):
        if filename.endswith(".jsonl"):
            found = forbidden_in(open(os.path.join(CORPORA, filename), encoding="utf-8").read(), never)
            if found:
                problems.append(f"{filename} holds {len(found)} string(s) from the private "
                                "never_public list")

    if problems:
        print("\nVALIDATION FAILED — files written but NOT staged:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)

    # The inventory table's counts are derived, so derive them.
    counts = {}
    for filename in sorted(os.listdir(CORPORA)):
        if filename.endswith(".jsonl"):
            counts[filename] = sum(
                1 for l in open(os.path.join(CORPORA, filename), encoding="utf-8")
                if l.strip())
    retouched = rewrite_inventory_counts(counts)
    if retouched:
        print("\ncorpora/README.md inventory counts updated:")
        for filename, was, now in retouched:
            print(f"  {filename:<38} {was} -> {now}")

    paths = [os.path.relpath(p, REPO) for _f, p, _r, _a, _rm in changed]
    if retouched:
        paths.append(os.path.join("corpora", "README.md"))
    subprocess.run(["git", "-C", REPO, "add", *paths], check=True)
    print(f"\nStaged {len(paths)} file(s). Nothing committed.")
    print("Read the diff, then commit:\n  git diff --cached corpora/")


if __name__ == "__main__":
    main()
