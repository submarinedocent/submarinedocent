"""Remove shows only on slots that hold a photo.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's browser on
Windows after any change to the editor's drag handling.
"""

def run(page, h):
    shown = [b.get_attribute("data-field-name") for b in page.locator(".slot-remove").all() if b.is_visible()]
    h.check("Remove shown only on the boat slot", shown == ["photo_boat"], shown)
