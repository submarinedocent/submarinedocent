#!/usr/bin/env python3
"""Run every Lost Boats photo-slot scenario in one browser engine.

    python _test/browser/run.py --browser chromium|firefox|webkit

Each scenario_*.py in this folder exposes run(page, h) and gets a fresh page
with O-9 reset.  Adding a scenario means adding a file.  Prints one line per
check and a total, and exits non-zero on any failure.

Not covered: a real operating-system file drag.  See harness.py.
"""
import argparse
import glob
import importlib.util
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from harness import Harness  # noqa: E402


def scenarios():
    for path in sorted(glob.glob(os.path.join(HERE, "scenario_*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield name, mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", required=True, choices=["chromium", "firefox", "webkit"])
    ap.add_argument("--channel", default=None, help="e.g. chrome, to use an installed Chrome")
    args = ap.parse_args()
    # A Windows console cannot print every character a traceback may hold.
    sys.stdout.reconfigure(errors="replace")

    from playwright.sync_api import sync_playwright

    h = Harness()
    h.start()
    ran = 0
    try:
        with sync_playwright() as p:
            engine = getattr(p, args.browser)
            browser = engine.launch(channel=args.channel) if args.channel else engine.launch()
            print(f"{args.browser} {browser.version}")
            for name, mod in scenarios():
                print(f"  {name}")
                h.reset_o9()
                page = h.open_editor(browser)
                try:
                    mod.run(page, h)
                except Exception:
                    h.check(f"{name} ran to the end", False, traceback.format_exc(limit=3))
                finally:
                    page.close()
                ran += 1
            browser.close()
    finally:
        h.stop()
        h.cleanup()
    print(f"\n{args.browser}: {ran} scenarios, {h.checks} checks, {len(h.failures)} failed")
    sys.exit(1 if h.failures or not ran else 0)


if __name__ == "__main__":
    main()
