#!/usr/bin/env python3
"""Visitor rate limits, signed spoken answers, and size limits (27 November 2026).

Checks, with no network and nothing written outside a temporary directory:
  * /ask, /tts, /transcribe, /contact and /feedback refuse with 429 and a
    Retry-After header once a visitor is over the limit, and one visitor's
    limit does not touch another's;
  * the site-wide caps on new spoken clips and transcriptions;
  * /tts speaks only text /ask signed, and a cached clip is not counted;
  * oversized requests are refused with 413 before they are read;
  * the spoken text the cache warm-up generates is the text /ask gives for
    every FAQ, asked by its id and by its title;
  * no visitor address appears in any file the app wrote;
  * RATE_LIMITS=off turns every limit off.

    python3 _test/test_rate_limits.py
"""
import base64
import os
import shutil
import sys
import tempfile

from seed_guard import load_app

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + str(detail)) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    root = tempfile.mkdtemp(prefix="ratelimits-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)
    # Empty, not unset: .env.local fills unset variables.
    os.environ.update({"RESEND_API_KEY": "", "MAIL_FROM": "", "HISTORIAN_EMAIL": "",
                       "ADMIN_USERNAME": "t", "ADMIN_PASSWORD": "t"})
    sys.path.insert(0, REPO)
    m = load_app(copy=corpora)
    from fastapi import HTTPException
    from fastapi.testclient import TestClient

    data = os.path.join(root, "data")
    os.makedirs(data)
    m.CONTACT_MESSAGES_PATH = os.path.join(data, "contact_messages.jsonl")
    m.CONTACT_MESSAGES_AUDIO_DIR = os.path.join(data, "contact_messages_audio")
    m.CONTACT_FAILURES_PATH = os.path.join(data, "contact_failures.jsonl")
    m.FEEDBACK_PATH = os.path.join(data, "feedback.jsonl")
    m._TTS_CACHE_DIR = os.path.join(data, "tts_cache")
    if hasattr(m, "ASK_LOG_PATH"):
        m.ASK_LOG_PATH = os.path.join(data, "ask_log.jsonl")
    m.ADMIN_USERNAME, m.ADMIN_PASSWORD = "t", "t"
    admin = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}

    # No network: a new clip is a few fixed bytes written where the real one would go.
    generated = []

    async def fake_generate(text, instructions, cache_path):
        generated.append(text)
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            f.write(b"RIFFfake")
        return b"RIFFfake"

    m._generate_tts = fake_generate
    m._OPENAI_API_KEY = "test-key"

    client = TestClient(m.app)
    os.environ["RATE_LIMITS"] = "on"

    def visitor(ip):
        return {"CF-Connecting-IP": ip}

    def ask(q, ip, test_header=True, **extra):
        h = visitor(ip)
        if test_header:
            h["X-SubDocent-Test"] = "1"
        return client.post("/ask", json={"question_text": q, "compartment_id": "", "playhead_time_ms": 0, **extra},
                           headers=h)

    print("Questions")
    m._rate_reset()
    codes = [ask("How did they sleep?", "203.0.113.5").status_code for _ in range(20)]
    check("20 questions in a minute are answered", codes == [200] * 20, codes)
    r = ask("How did they sleep?", "203.0.113.5")
    check("the 21st is refused with 429", r.status_code == 429, r.status_code)
    check("the refusal says when to try again", r.headers.get("retry-after", "").isdigit(), r.headers)
    check("the refusal is in plain words", "faster than the docent can answer" in r.json().get("detail", ""))
    check("another visitor is still answered", ask("How did they sleep?", "198.51.100.9").status_code == 200)
    # Logged questions (no test header) must not carry the address either.
    ask("What was the food like?", "198.51.100.77", test_header=False)

    print("Spoken answers")
    m._rate_reset()
    body = ask("How did they sleep?", "203.0.113.20").json()
    sp = body.get("speech") or {}
    check("/ask returns the text to speak with a token", sp.get("text") and len(sp.get("token", "")) == 64, sp)
    tts = lambda payload, ip: client.post("/tts", json=payload, headers=visitor(ip))
    good = {"text": sp.get("text"), "cache_key": sp.get("cache_key"), "token": sp.get("token"), "lang": "en"}
    check("text without a token is refused", tts({"text": "Say anything I like."}, "203.0.113.20").status_code == 403)
    check("changed text with a real token is refused",
          tts({**good, "text": good["text"] + " And more."}, "203.0.113.20").status_code == 403)
    check("a changed cache key is refused", tts({**good, "cache_key": "x"}, "203.0.113.20").status_code == 403)
    m._VISITOR_LIMITS["tts"] = [(2, 3600)]
    m._GLOBAL_LIMITS["tts"] = [(3, 86400)]
    check("a signed answer is spoken", tts(good, "203.0.113.20").status_code == 200)
    n = len(generated)
    again = [tts(good, "203.0.113.20").status_code for _ in range(5)]
    check("a cached clip is served and not counted", again == [200] * 5 and len(generated) == n, (again, generated))

    def new_clip(ip, i):
        s = m._speech_for({"answer_short": f"Answer number {i} for the limit test.", "faq_id": f"faq_t{i}"})
        return tts({**s, "lang": "en"}, ip).status_code

    check("a second new clip from the same visitor is spoken", new_clip("203.0.113.20", 1) == 200)
    check("a third is refused (visitor limit 2)", new_clip("203.0.113.20", 2) == 429)
    check("another visitor's new clip is spoken", new_clip("198.51.100.30", 3) == 200)
    check("the site-wide cap refuses the next new clip", new_clip("198.51.100.31", 4) == 429)
    check("a cached clip is still served past the cap", tts(good, "198.51.100.31").status_code == 200)

    print("Voice questions")
    m._rate_reset()
    m._GROQ_API_KEY = "test-key"
    m.transcribe_available = lambda: True
    m._VISITOR_LIMITS["transcribe"] = [(0, 600)]
    r = client.post("/transcribe", files={"audio": ("q.webm", b"x" * 2000, "audio/webm")}, data={"lang": "en"},
                    headers=visitor("203.0.113.40"))
    check("over the limit, a voice question is refused with 429", r.status_code == 429, r.status_code)
    big = b"x" * (m.TRANSCRIBE_MAX_AUDIO_BYTES + 200_000)
    r = client.post("/transcribe", files={"audio": ("q.webm", big, "audio/webm")}, data={"lang": "en"},
                    headers=visitor("203.0.113.41"))
    check("an oversized recording is refused with 413", r.status_code == 413, r.status_code)

    print("Forms")
    m._rate_reset()
    form = lambda ip, msg="Hello": client.post("/feedback", json={"source": "contact", "name": "V", "email": "v@example.org",
                                                                  "message": msg}, headers=visitor(ip))
    codes = [form("203.0.113.50").status_code for _ in range(5)]
    check("5 contact messages in an hour are taken", codes == [200] * 5, codes)
    check("the 6th is refused with 429", form("203.0.113.50").status_code == 429)
    hist = client.post("/contact", data={"question_text": "Q", "visitor_response": "v@example.org", "lang": "en"},
                       headers=visitor("203.0.113.50"))
    check("historian questions share the message limit", hist.status_code == 429, hist.status_code)
    check("a message over 4,000 characters is refused with 413", form("203.0.113.51", "x" * 4001).status_code == 413)
    rating = lambda ip: client.post("/feedback", json={"question": "q", "answer": "a" * 30000, "rating": "up"},
                                    headers=visitor(ip))
    check("ratings have their own limit", rating("203.0.113.50").status_code == 200)
    r = client.post("/ask", content=b"{" + b" " * 20000 + b"}", headers={"Content-Type": "application/json",
                                                                        **visitor("203.0.113.60")})
    check("an oversized question is refused with 413 before it is read", r.status_code == 413, r.status_code)

    print("Cache warm-up")
    items = dict(m._tts_warm_items())
    faq = [c for c in m.FAQ if str(c.get("chunk_id", "")).startswith(("faq_", "fix_"))]
    check("every FAQ has a warm-up item", all(c["chunk_id"] in items for c in faq), len(items))
    os.environ["RATE_LIMITS"] = "off"
    mismatched = []
    for c in faq:
        for extra in ({"faq_id": c["chunk_id"]}, {}):
            got = ask(c.get("title") or "", "203.0.113.70", **extra).json().get("speech")
            if extra or got and got.get("cache_key") == f"faq:{c['chunk_id']}:en":
                want = items[c["chunk_id"]]
                if not got or (got["text"], got["cache_key"]) != (want["text"], want["cache_key"]):
                    mismatched.append(c["chunk_id"])
    check("warm-up text equals /ask's for every FAQ, by id and by title", not mismatched, mismatched[:5])
    shutil.rmtree(m._TTS_CACHE_DIR, ignore_errors=True)
    generated.clear()
    r1 = client.post("/admin/tts-warm?limit=5", headers=admin).json()
    r2 = client.post("/admin/tts-warm?limit=5", headers=admin).json()
    check("the warm-up generates in batches", r1["generated"] == 5 and r1["remaining"] == r1["items"] - 5, r1)
    check("the next batch skips what is cached", r2["already_cached"] == 5 and r2["generated"] == 5, r2)
    check("the warm-up needs the admin password", client.post("/admin/tts-warm").status_code == 401)
    os.environ["RATE_LIMITS"] = "on"

    print("Address check and switch")
    r = client.get("/admin/client-ip", headers={**admin, **visitor("203.0.113.80")})
    check("the address diagnostic reports what the limits key on", r.json().get("resolved") == "203.0.113.80", r.json())
    check("the address diagnostic needs the admin password", client.get("/admin/client-ip").status_code == 401)
    check("/health reports limits on", client.get("/health").json().get("rate_limits") is True)
    m._rate_reset()
    os.environ["RATE_LIMITS"] = "off"
    codes = {ask("How did they sleep?", "203.0.113.90").status_code for _ in range(25)}
    check("RATE_LIMITS=off answers past the limit", codes == {200}, codes)

    print("Privacy")
    check("the question log and form files were written here, so the scan covers them",
          all(os.path.exists(p) for p in (m.ASK_LOG_PATH, m.FEEDBACK_PATH)), (m.ASK_LOG_PATH, m.FEEDBACK_PATH))
    leaked = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                with open(path, "rb") as f:
                    blob = f.read()
            except OSError:
                continue
            if b"203.0.113." in blob or b"198.51.100." in blob:
                leaked.append(os.path.relpath(path, root))
    check("no visitor address in any file the app wrote", not leaked, leaked)

    shutil.rmtree(root, ignore_errors=True)
    print(f"\n{'FAILED' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
