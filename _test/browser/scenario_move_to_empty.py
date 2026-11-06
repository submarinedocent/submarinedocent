"""Drag the boat photo onto the empty captain slot: it moves, nothing uploads.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""
from harness import BUNDLED


def run(page, h):
    before = h.files()
    h.drag(page, "photo-boat-frame", "photo-captain-frame")
    boat, captain = h.slots()
    h.check("boat slot empty", boat is None, boat)
    h.check("captain slot has the photo", captain == BUNDLED, captain)
    h.check("no file written", not h.written(before, h.files()), h.written(before, h.files()))

