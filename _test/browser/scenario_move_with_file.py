"""The same move with a drop that carries the picture as a file, as the editor's
browser delivered it on 2 November 2026.  Still a move: nothing uploads.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

from harness import BUNDLED


def run(page, h):
    before = h.files()
    h.drag(page, "photo-boat-frame", "photo-captain-frame", with_file=True)
    boat, captain = h.slots()
    h.check("boat slot empty", boat is None, boat)
    h.check("captain slot has the photo", captain == BUNDLED, captain)
    h.check("no file written", not h.written(before, h.files()), h.written(before, h.files()))
