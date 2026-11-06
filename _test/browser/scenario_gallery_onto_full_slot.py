"""Dragging Image 1 onto a full boat slot swaps the two: the boat slot gets
Image 1's photo and Image 1 gets the boat slot's.  Nothing is written, and each
slot shows the file the server holds for it.

This is what the site's editor saw on 3 November 2026 when the boat slot's
photo went to Image 1.  The swap is intended, so that a drop never throws a
photo away.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

from harness import BUNDLED


def run(page, h):
    h.choose(page, "image1")
    uploaded = h.o9().get("image1")
    before = h.files()
    h.drag(page, "gallery-image1-frame", "photo-boat-frame")
    b = h.o9()
    h.check("boat slot has Image 1's photo", bool(uploaded) and b.get("photo_boat") == uploaded, b.get("photo_boat"))
    h.check("Image 1 has the boat slot's photo", b.get("image1") == BUNDLED, b.get("image1"))
    h.check("no file written", not h.written(before, h.files()), h.written(before, h.files()))
    h.check_shows_server_file(page, "photo-boat-frame", "boat slot shows its file")
    h.check_shows_server_file(page, "gallery-image1-frame", "Image 1 shows its file")
