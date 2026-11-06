"""Remove a photo, then put a new one in the same slot: the slot shows the new
photo, and the removed file is still on the disk.

On 3 November 2026 O-9's boat slot held a file under the name an upload into
that slot is written under.  After Remove, the new photo was written under that
same name, over the removed file, and the editor kept showing the picture it
already held for that address, so the old photo seemed to come back.  Both
routes in are checked: a picture dropped from the computer, and Choose file.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

import time

from harness import O9_BOAT_UPLOAD, PORTRAIT, SETTLE, UPLOAD_SOURCE


def run(page, h):
    h.place("photo_boat", O9_BOAT_UPLOAD, PORTRAIT)
    h.reopen(page)

    page.click(".slot-remove[data-field-name='photo_boat']")
    time.sleep(SETTLE)
    h.drop_file(page, "photo-boat-frame", UPLOAD_SOURCE)
    boat, _ = h.slots()
    h.check("dropped file: boat slot has a photo", bool(boat), boat)
    h.check_shows_server_file(page, "photo-boat-frame", "dropped file: boat slot shows the new photo")
    h.check("dropped file: the removed photo is still on the disk", bool(h.holding(PORTRAIT)), h.files())

    page.click(".slot-remove[data-field-name='photo_boat']")
    time.sleep(SETTLE)
    h.choose(page, "photo_boat", PORTRAIT)
    h.check_shows_server_file(page, "photo-boat-frame", "Choose file: boat slot shows the new photo")
    h.check("Choose file: the removed photo is still on the disk", bool(h.holding(UPLOAD_SOURCE)), h.files())
