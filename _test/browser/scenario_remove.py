"""Remove empties the slot and keeps the file on the disk.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

import os
import time

from harness import SETTLE


def run(page, h):
    h.choose(page, "photo_captain")
    _, uploaded = h.slots()
    page.click(".slot-remove[data-field-name='photo_captain']")
    time.sleep(SETTLE)
    _, captain = h.slots()
    h.check("captain slot empty", captain is None, captain)
    h.check("file kept on the disk", bool(uploaded) and os.path.basename(uploaded) in h.files(), uploaded)
