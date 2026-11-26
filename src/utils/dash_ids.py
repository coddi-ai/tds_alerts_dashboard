"""Text from the data (a unit, a component, an essay...) inside the id of a clickable Dash element.

Dash writes a non-ASCII character of a pattern-matching id escaped (`\\u00f3`) on the server but not in the
browser, so the two spellings of the same id never match: the callback receives the click without its
value and ignores it, and the element silently does nothing. ENEX names its transmissions
"transmisión" and its hydraulics "sistema hidráulico", so those cells were dead.

`id_text` writes the text so that it is plain ASCII, and `from_id_text` reads it back. Only what has to
change changes: printable ASCII is left exactly as it is (so every id that worked before is
byte-for-byte the same), a non-ASCII character becomes its UTF-8 percent escape, and a literal `%`
becomes `%25` so that the round trip is exact for any text.

    {"type": "fleet-cell", "unit": "RXLB0001", "component": id_text("transmisión")}
    -> component == "transmisi%C3%B3n"         ...         from_id_text(clicked["component"]) == "transmisión"

A callback must read such a part back with `from_id_text`; the value it was written from is what the
data (and every lookup in it) uses.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

# Printable ASCII, except "%" (the escape character itself).
_SAFE = "".join(chr(code) for code in range(0x20, 0x7F) if chr(code) != "%")


def id_text(value) -> str:
    """`value` as ASCII-only text for use inside an element id; ASCII text is returned unchanged."""
    return quote(str(value), safe=_SAFE)


def from_id_text(value) -> str:
    """The text `id_text` was given."""
    return unquote(str(value))
