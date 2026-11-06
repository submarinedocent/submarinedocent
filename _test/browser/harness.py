"""Shared setup for the Lost Boats photo-slot browser scenarios.

Starts the site on a temporary disk, never production, and opens the Lost
Boats editor on O-9 the way the site's editor found it on 2 November 2026: the boat photo
in the boat slot and the captain slot empty.  Works on Linux and Windows:
paths come from os.path and tempfile, and the server is a subprocess, not a
shell line.

Not covered here: a real operating-system drag (a picture dragged from
Explorer, Finder or another window, or a drag whose data the OS builds).
Playwright cannot perform one.  A person has to check that, in the editor's
browser on Windows, after any change to the editor's drag handling.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
O9_ID = 11
BUNDLED = "images/extracted/O-9_SS-70_boat.jpg"
# Any tracked JPEG will do as the file a curator picks; this one is A-7's.
UPLOAD_SOURCE = os.path.join(REPO, "web", "images", "extracted", "A-7_SS-8_boat.jpg")
# A second picture, a different size from UPLOAD_SOURCE, so the page can tell
# which of the two a slot is showing.
PORTRAIT = os.path.join(REPO, "web", "images", "extracted", "Argonaut_SS-166_captain.jpg")
# The name an upload into O-9's boat slot is written under.
O9_BOAT_UPLOAD = "USS_O_9_SS_70_boat.jpg"
USER = PASSWORD = "t"
_AUTH = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
# Long enough for a save to round-trip and the editor to redraw.
SETTLE = 1.2


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Harness:
    def __init__(self):
        self.disk = tempfile.mkdtemp(prefix="lostboat-browser-")
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.upload_dir = os.path.join(self.disk, "eternal_patrol_images")
        self.failures = []
        self.checks = 0
        self.server = None

    # -- server -----------------------------------------------------------
    def start(self):
        env = {**os.environ, "SUBDOCENT_DATA_DIR": self.disk, "CONTENT_ROOT": "corpora",
               "ADMIN_USERNAME": USER, "ADMIN_PASSWORD": PASSWORD,
               "RESEND_API_KEY": "", "MAIL_FROM": "", "HISTORIAN_EMAIL": "",
               # The app prints emoji at startup; on Windows, output sent to a
               # file is cp1252 unless Python runs in UTF-8 mode.
               "PYTHONUTF8": "1"}
        self.log = open(os.path.join(self.disk, "server.log"), "w", encoding="utf-8")
        self.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=REPO, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.server.poll() is not None:
                break
            try:
                urllib.request.urlopen(self.base + "/health", timeout=5)
                return
            except (urllib.error.URLError, OSError):
                time.sleep(1)
        self.stop()
        with open(os.path.join(self.disk, "server.log"), encoding="utf-8", errors="replace") as f:
            print(f.read()[-3000:])
        sys.exit("server did not start")

    def stop(self):
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill()
        if getattr(self, "log", None):
            self.log.close()

    def cleanup(self):
        shutil.rmtree(self.disk, ignore_errors=True)

    # -- O-9 on the server ------------------------------------------------
    def _request(self, path, data=None, method="GET"):
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": _AUTH, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def reset_o9(self):
        """O-9 as the site's editor found it, and an empty upload folder."""
        self._request(f"/admin/eternal-patrol/{O9_ID}", method="PUT", data=json.dumps(
            {"photo_boat": BUNDLED, "photo_captain": None, "image1": None, "image1_subtitle": None,
             "cause": "Foundered"}).encode())
        if os.path.isdir(self.upload_dir):
            for name in os.listdir(self.upload_dir):
                os.remove(os.path.join(self.upload_dir, name))

    def o9(self):
        return next(b for b in self._request("/admin/eternal-patrol") if b["id"] == O9_ID)

    def slots(self):
        b = self.o9()
        return b.get("photo_boat"), b.get("photo_captain")

    def files(self):
        """File name -> modification time, so an overwrite counts as a write."""
        if not os.path.isdir(self.upload_dir):
            return {}
        return {n: os.stat(os.path.join(self.upload_dir, n)).st_mtime_ns for n in os.listdir(self.upload_dir)}

    @staticmethod
    def written(before, after):
        return sorted(n for n in after if before.get(n) != after[n])

    def place(self, field, name, source):
        """Put source on the disk as name and point field at it.

        This is how O-9's boat slot stood on production on 3 November 2026: its
        file had the name an upload into that slot is written under.
        """
        os.makedirs(self.upload_dir, exist_ok=True)
        shutil.copyfile(source, os.path.join(self.upload_dir, name))
        self._request(f"/admin/eternal-patrol/{O9_ID}", method="PUT", data=json.dumps(
            {field: f"images/extracted/{name}"}).encode())

    def holding(self, source):
        """Upload-folder files whose bytes are source's."""
        with open(source, "rb") as f:
            want = f.read()
        found = []
        for name in sorted(os.listdir(self.upload_dir)):
            with open(os.path.join(self.upload_dir, name), "rb") as f:
                if f.read() == want:
                    found.append(name)
        return found

    # -- the editor -------------------------------------------------------
    def open_editor(self, browser):
        page = browser.new_page(http_credentials={"username": USER, "password": PASSWORD},
                                viewport={"width": 1400, "height": 1700})
        page.on("dialog", lambda d: d.accept())
        self._select_o9(page)
        return page

    def _select_o9(self, page):
        page.goto(self.base + "/web/edit_lost_boats.html")
        page.wait_for_selector(".boat-item")
        page.fill("#boat-search", "O-9")
        page.click(f".boat-item[data-id='{O9_ID}']")
        page.wait_for_selector("#photo-boat-frame img")

    def reopen(self, page):
        """Load the editor again, after a change made behind its back."""
        self._select_o9(page)
        time.sleep(SETTLE)

    def drop_file(self, page, dst, path):
        """Replay a picture dropped onto frame dst from outside the page."""
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        page.evaluate("""([dst, data, name]) => {
          const bytes = Uint8Array.from(atob(data), c => c.charCodeAt(0));
          const dt = new DataTransfer();
          dt.items.add(new File([bytes], name, {type: 'image/jpeg'}));
          const target = document.getElementById(dst);
          for (const type of ['dragenter', 'dragover', 'drop']) {
            target.dispatchEvent(new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
          }
        }""", [dst, data, os.path.basename(path)])
        time.sleep(SETTLE)

    def shown(self, page, frame):
        """(width, height) of the picture frame shows, and of the file the server
        now holds at that address, fetched past every cache."""
        return page.evaluate("""async frame => {
          const img = document.querySelector('#' + frame + ' img');
          if (!img) return null;
          await img.decode().catch(() => {});
          const blob = await (await fetch(img.src, {cache: 'no-store'})).blob();
          const bmp = await createImageBitmap(blob);
          return [[img.naturalWidth, img.naturalHeight], [bmp.width, bmp.height]];
        }""", frame)

    def check_shows_server_file(self, page, frame, label):
        got = self.shown(page, frame)
        self.check(label, bool(got) and got[0] == got[1], got and f"shows {got[0]}, server has {got[1]}")

    def drag(self, page, src, dst, with_file=False):
        """Drag the photo in frame src onto frame dst.

        with_file=False is Playwright's own mouse drag.  with_file=True replays
        the events a browser sends when it hands the picture over as a file,
        which is what the editor's browser did; it does not prove that a given
        browser on a given OS builds the drop that way.
        """
        if not with_file:
            page.drag_and_drop(f"#{src} img", f"#{dst}")
        else:
            page.evaluate("""async ([src, dst]) => {
              const img = document.querySelector('#' + src + ' img');
              const blob = await (await fetch(img.src)).blob();
              const dt = new DataTransfer();
              dt.items.add(new File([blob], 'photo.jpg', {type: blob.type}));
              dt.setData('text/uri-list', img.src);
              const fire = (el, type) => el.dispatchEvent(
                new DragEvent(type, {dataTransfer: dt, bubbles: true, cancelable: true}));
              const target = document.getElementById(dst);
              fire(img, 'dragstart');
              fire(target, 'dragenter');
              fire(target, 'dragover');
              fire(target, 'drop');
              fire(img, 'dragend');
            }""", [src, dst])
        time.sleep(SETTLE)

    def choose(self, page, field, path=UPLOAD_SOURCE):
        with page.expect_file_chooser() as chooser:
            page.click(f".slot-choose[data-field-name='{field}']")
        chooser.value.set_files(path)
        time.sleep(SETTLE)

    # -- reporting --------------------------------------------------------
    def check(self, label, ok, detail=""):
        self.checks += 1
        print(f"    {'PASS' if ok else 'FAIL'}  {label}{'' if ok else '  ' + str(detail)}")
        if not ok:
            self.failures.append(label)
