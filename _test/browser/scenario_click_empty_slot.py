"""Clicking an empty slot opens the file chooser.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

def run(page, h):
    with page.expect_file_chooser(timeout=3000) as chooser:
        page.click("#photo-captain-frame")
    h.check("file chooser opened", chooser.value is not None)
