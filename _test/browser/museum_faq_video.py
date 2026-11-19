#!/usr/bin/env python3
"""A museum page offers its FAQs' videos the way the FAQ page does.

    python _test/browser/museum_faq_video.py --browser chromium|firefox|webkit

Starts the site on a temporary disk, never production, attaches a library
video to one of Cod's FAQs, and opens /cod at a phone width and a desktop
width.  The entry shows a "Watch this account" button with the FAQ's caption
and the library's credit, no player is requested from the video host until it
is clicked, and the click puts the player in the answer at the FAQ's start time
without widening the page.  An entry without a video shows no button.

YouTube itself is never reached: requests to it are answered with an empty
page, so the test does not depend on the video host.  Whether the clip
actually plays is checked by a person, or by hand in Chrome, after a deploy.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import REPO, Harness  # noqa: E402

COD_MUSEUM_ID = "10"
START = 85
CAPTION = "A caption for the museum page."
VIEWPORTS = {"phone": {"width": 390, "height": 844}, "desktop": {"width": 1280, "height": 900}}


def seed_rows(name):
    with open(os.path.join(REPO, "corpora", name), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", required=True, choices=["chromium", "firefox", "webkit"])
    ap.add_argument("--channel", default=None, help="e.g. chrome, to use an installed Chrome")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    from playwright.sync_api import sync_playwright

    cod = [r for r in seed_rows("dieselsubs_faq_corpus.jsonl")
           if r["chunk_id"].startswith("faq_") and str(r.get("museum_id") or "") == COD_MUSEUM_ID]
    with_video, without_video = cod[0]["chunk_id"], cod[1]["chunk_id"]
    video = next(v for v in seed_rows("videos.jsonl")
                 if "youtube.com/watch?v=" in v.get("video_url", "")
                 and v.get("rights_status") in ("granted", "not_required"))
    yt = video["video_url"].split("watch?v=", 1)[1].split("&", 1)[0]
    want_src = f"https://www.youtube-nocookie.com/embed/{yt}?rel=0&start={START}&autoplay=1"

    h = Harness()
    h.start()
    try:
        h._request(f"/admin/faq/{with_video}", method="PUT", data=json.dumps(
            {"video_id": video["id"], "video_start": START, "video_caption": CAPTION}).encode())
        # The other entry is cleared in case the seed ever gives it a video.
        h._request(f"/admin/faq/{without_video}", method="PUT",
                   data=json.dumps({"video_id": ""}).encode())
        with sync_playwright() as p:
            engine = getattr(p, args.browser)
            browser = engine.launch(channel=args.channel) if args.channel else engine.launch()
            print(f"{args.browser} {browser.version}")
            for label, viewport in VIEWPORTS.items():
                print(f"  /cod at {label} width ({viewport['width']}px)")
                page = browser.new_page(viewport=viewport)
                to_host = []

                def video_host(route):
                    to_host.append(route.request.url)
                    route.fulfill(status=200, content_type="text/html", body="<html></html>")

                page.route("**/*youtube*.com/**", video_host)
                page.route("**/*ytimg.com/**", video_host)
                page.goto(h.base + "/cod")
                item = page.locator(f".faq-item[data-faq='{with_video}']")
                item.wait_for(state="attached", timeout=20000)
                other = page.locator(f".faq-item[data-faq='{without_video}']")

                h.check("entry with a video has the button", item.locator(".faq-video-play").count() == 1)
                captions = item.locator(".faq-video-caption").all_text_contents()
                h.check("caption is the FAQ's", captions == [CAPTION], captions)
                credit = (video.get("video_credit") or "").strip()
                if credit:
                    credits = item.locator(".faq-video-credit").all_text_contents()
                    h.check("credit is the library's", credits == [credit], credits)
                h.check("entry without a video has no button", other.locator(".faq-video").count() == 0)
                h.check("no player before the click", page.locator(".faq-video iframe").count() == 0)
                # Thumbnails for the page's Compartment Tours come from the
                # video host already; what must wait for the click is the player.
                players = [u for u in to_host if "/embed/" in u]
                h.check("no player requested before the click", not players, players)

                item.locator(".faq-q").click()
                item.locator(".faq-video-play").click()
                frame = item.locator(".faq-video iframe")
                frame.wait_for(state="attached", timeout=10000)
                src = frame.get_attribute("src")
                h.check("player opens at the FAQ's start", src == want_src, src)
                h.check("button gone once the player is in", item.locator(".faq-video-play").count() == 0)
                box = frame.bounding_box()
                answer = item.locator(".faq-answer").bounding_box()
                h.check("player inside the answer",
                        bool(box and answer) and box["x"] >= answer["x"] - 1
                        and box["x"] + box["width"] <= answer["x"] + answer["width"] + 1, (box, answer))
                wide = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
                h.check("page does not scroll sideways", wide <= 0, f"{wide}px too wide")
                page.close()
            browser.close()
    finally:
        h.stop()
        h.cleanup()
    print(f"\n{args.browser}: {h.checks} checks, {len(h.failures)} failed")
    sys.exit(1 if h.failures or not h.checks else 0)


if __name__ == "__main__":
    main()
