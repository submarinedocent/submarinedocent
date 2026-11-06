"""Dragging onto a full slot swaps the two photos and writes no file.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's own
browser after any change to the editor's drag handling.
"""

from harness import BUNDLED


def run(page, h):
    h.choose(page, "photo_captain")
    _, uploaded = h.slots()
    before = h.files()
    h.drag(page, "photo-boat-frame", "photo-captain-frame")
    boat, captain = h.slots()
    h.check("boat slot has the captain photo", boat == uploaded, boat)
    h.check("captain slot has the boat photo", captain == BUNDLED, captain)
    h.check("no file written", not h.written(before, h.files()), h.written(before, h.files()))
