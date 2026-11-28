"""Tests run against the seed corpus, and nothing else.

The app fills unset variables from .env.local at import, and a CONTENT_ROOT
there points a test at a working corpus instead of corpora/.  On 16 November
2026 that made eight tests fail on a maintainer's machine while CI, which has
no .env.local, passed them.

    from seed_guard import load_app
    m = load_app()               # the seed itself, read only
    m = load_app(copy=corpora)   # a temporary copy of the seed the test writes to

load_app() refuses to run when the real environment names any other corpus,
sets CONTENT_ROOT before the app can fill it, imports the app, and checks the
corpus it actually loaded.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEED = os.path.join(REPO, "corpora")


def load_app(copy=None):
    want = os.path.realpath(copy or SEED)
    if copy is None:
        asked = os.environ.get("CONTENT_ROOT", "").strip()
        if asked and os.path.realpath(os.path.join(REPO, asked)) != want:
            sys.exit(f"refusing to run: CONTENT_ROOT={asked!r}; these tests run against the seed "
                     f"corpus ({SEED}) only.  Unset CONTENT_ROOT or set it to corpora.")
    if os.environ.get("SAMPLE_CONTENT_MODE", "").strip().lower() in ("1", "true", "yes", "on"):
        sys.exit("refusing to run: SAMPLE_CONTENT_MODE is on; these tests run against the seed corpus only.")
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    os.environ["CONTENT_ROOT"] = want
    # Every in-process request comes from the one test client, so the visitor
    # rate limits would refuse a test after its twentieth question.  They are
    # off here unless a test asks for them; _test/test_rate_limits.py turns
    # them on.
    os.environ.setdefault("RATE_LIMITS", "off")
    from api import main as m
    loaded = os.path.realpath(m.CORPORA_DIR)
    if loaded != want or m.SAMPLE_CONTENT_MODE:
        sys.exit(f"refusing to run: the app loaded {loaded}, not {want}.")
    return m
