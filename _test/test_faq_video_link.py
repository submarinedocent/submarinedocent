#!/usr/bin/env python3
"""A FAQ's video comes from the video library, by id.

The FAQ stores video_id, and its own start time and caption.  The library
supplies the address, credit and rights each time the video is shown, so a
rights change there reaches every answer that plays the video.  A FAQ that
carries its own copy of a video (faq_1088, from before the library link) keeps
working until someone replaces it.

    python3 _test/test_faq_video_link.py

Runs against a temporary copy of the real corpora. It writes, so it must never
be pointed at corpora/ itself.
"""
import base64
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{('  ' + detail) if not ok else ''}")
    if not ok:
        failures.append(label)


def main():
    root = tempfile.mkdtemp(prefix="faqvideo-")
    corpora = os.path.join(root, "corpora")
    shutil.copytree(os.path.join(REPO, "corpora"), corpora)

    os.environ["CONTENT_ROOT"] = corpora
    os.environ["ADMIN_USERNAME"] = "t"
    os.environ["ADMIN_PASSWORD"] = "t"
    sys.path.insert(0, REPO)
    from api import main as m
    from fastapi.testclient import TestClient

    client = TestClient(m.app)
    auth = {"Authorization": "Basic " + base64.b64encode(b"t:t").decode()}

    def stored(chunk_id):
        with open(os.path.join(corpora, "dieselsubs_faq_corpus.jsonl")) as fh:
            for line in fh:
                rec = json.loads(line)
                if rec["chunk_id"] == chunk_id:
                    return rec
        return None

    def page_video(chunk_id):
        for group in client.get("/api/faqs").json():
            for f in group["faqs"]:
                if f["id"] == chunk_id:
                    return f["video"]
        return "missing"

    def ask_video(title):
        r = client.post("/ask", json={"question_text": title})
        return r.json().get("video") if r.status_code == 200 else f"HTTP {r.status_code}"

    library = [json.loads(l) for l in open(m.VIDEOS_PATH) if l.strip()]

    def set_library(rows):
        with open(m.VIDEOS_PATH, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    video = next(v for v in library if "youtube" in v.get("video_url", "") and m._rights_cleared(v))
    yt = m._YT_ID_RE.search(video["video_url"]).group(1)

    target = next(e for e in m.FAQ_ALL if e["chunk_id"] == "faq_1094")
    cid, title = target["chunk_id"], target["title"]
    check("target starts with no video", page_video(cid) is None and ask_video(title) is None)

    r = client.put(f"/admin/faq/{cid}", json={"title": "Changed?", "video_id": "vid_nope"}, headers=auth)
    check("unknown video id refused", r.status_code == 400, f"got {r.status_code}")
    check("refused save changes nothing", stored(cid)["title"] == title and m.FAQ_ALL[m.FAQ_ALL.index(target)]["title"] == title)

    r = client.put(f"/admin/faq/{cid}", json={"video_id": video["id"], "video_start": "x"}, headers=auth)
    check("unreadable start refused", r.status_code == 400, f"got {r.status_code}")

    draft = next((e for e in m.FAQ_ALL if not e["chunk_id"].startswith(("faq_", "fix_"))), None)
    if draft:
        r = client.put(f"/admin/faq/{draft['chunk_id']}", json={"video_id": video["id"]}, headers=auth)
        check("a draft takes no video", r.status_code == 400 and "video_id" not in stored(draft["chunk_id"]),
              f"got {r.status_code}")

    r = client.put(f"/admin/faq/{cid}", json={"video_id": video["id"], "video_start": 85,
                                              "video_caption": "A caption."}, headers=auth)
    rec = stored(cid)
    check("library video stored by id", r.status_code == 200 and rec.get("video_id") == video["id"], repr(rec.get("video_id")))
    check("start and caption stored on the FAQ", rec.get("video_start") == 85 and rec.get("video_caption") == "A caption.")
    check("no copy of the library's fields", not any(k in rec for k in ("video_url", "video_credit", "rights_status")))

    v = page_video(cid)
    check("FAQ page plays the library video from 85 s",
          bool(v) and yt in v["embed_url"] and "start=85" in v["embed_url"], repr(v))
    check("caption is the FAQ's", bool(v) and v["caption"] == "A caption.")
    check("credit is the library's", bool(v) and v["credit"] == (video.get("video_credit") or "").strip(), repr(v and v["credit"]))
    a = ask_video(title)
    check("Ask the Docent plays it too", isinstance(a, dict) and yt in a["embed_url"], repr(a))

    client.put(f"/admin/faq/{cid}", json={"text": target["text"]}, headers=auth)
    check("a save without video_id keeps the video", stored(cid).get("video_id") == video["id"])

    withdrawn = [dict(row, rights_status="withheld") if row["id"] == video["id"] else row for row in library]
    set_library(withdrawn)
    check("rights withdrawn in the library: FAQ page shows nothing", page_video(cid) is None)
    check("rights withdrawn in the library: Ask shows nothing", ask_video(title) is None)
    set_library([row for row in library if row["id"] != video["id"]])
    check("video gone from the library: nothing shown", page_video(cid) is None)
    set_library(library)
    check("rights restored: shown again", bool(page_video(cid)))

    scoped = next(e for e in m.FAQ_ALL if e["chunk_id"].startswith("faq_") and e.get("museum_id"))
    sid, museum = scoped["chunk_id"], scoped["museum_id"]
    client.put(f"/admin/faq/{sid}", json={"video_id": video["id"]}, headers=auth)
    r = client.put(f"/admin/faq/{sid}", json={"video_id": ""}, headers=auth)
    rec = stored(sid)
    check("empty video_id removes the video", r.status_code == 200 and not any(
        k in rec for k in ("video_id", "video_start", "video_caption", "video_url")), repr(rec.get("video_id")))
    check("removing a video keeps the museum scope", rec.get("museum_id") == museum, repr(rec.get("museum_id")))

    old = page_video("faq_1088")
    check("faq_1088's own copy of its video still plays", bool(old) and "clay_decker" in old["embed_url"], repr(old))
    decker = next(row for row in library if "clay_decker_escaping" in row.get("video_url", ""))
    client.put("/admin/faq/faq_1088", json={"video_id": decker["id"]}, headers=auth)
    rec = stored("faq_1088")
    new = page_video("faq_1088")
    check("choosing a library video replaces the copy",
          rec.get("video_id") == decker["id"] and "video_url" not in rec and "rights_status" not in rec)
    check("and the same video still plays", bool(new) and new["embed_url"] == old["embed_url"], repr(new))

    listed = next(e for e in client.get("/admin/faqs", headers=auth).json() if e["chunk_id"] == cid)
    check("the editor's list carries video_id", listed.get("video_id") == video["id"])

    shutil.rmtree(root, ignore_errors=True)
    print(f"{'FAIL' if failures else 'ok'}: {len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
