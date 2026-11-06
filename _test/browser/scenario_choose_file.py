"""Choose file uploads into its slot and writes exactly one file.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in Dwight's browser on
Windows after any change to the editor's drag handling.
"""

import os

from harness import BUNDLED


def run(page, h):
    before = h.files()
    h.choose(page, "photo_captain")
    boat, captain = h.slots()
    written = h.written(before, h.files())
    h.check("captain slot has the upload", bool(captain) and captain != BUNDLED, captain)
    h.check("exactly one file written, the one the slot shows",
            bool(captain) and written == [os.path.basename(captain)], written)
    h.check("boat slot untouched", boat == BUNDLED, boat)
