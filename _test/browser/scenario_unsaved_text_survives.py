"""Unsaved text in the form survives a move and an upload, and still counts as
unsaved.

Not covered: a real operating-system file drag (from Explorer, Finder or another
window).  Playwright cannot make one; a person checks it in the editor's own
browser after any change to the editor's drag handling.
"""

def run(page, h):
    page.fill("#field-cause", "Unsaved edit")
    h.drag(page, "photo-boat-frame", "photo-captain-frame")
    h.check("text kept after a move", page.input_value("#field-cause") == "Unsaved edit",
            page.input_value("#field-cause"))
    h.check("still unsaved after a move", page.is_enabled("#save-boat-btn"))
    h.choose(page, "photo_boat")
    h.check("text kept after an upload", page.input_value("#field-cause") == "Unsaved edit",
            page.input_value("#field-cause"))
    h.check("still unsaved after an upload", page.is_enabled("#save-boat-btn"))
    h.check("text not saved to the server", h.o9().get("cause") == "Foundered", h.o9().get("cause"))
