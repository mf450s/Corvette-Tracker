"""Favicon (Tab-Bar-Logo) für den Corvette Tracker.

Vereinfachtes Corvette-Emblem: rote Flagge mit Chevrolet-Bowtie, gekreuzt mit
schwarz-weißer Schachbrett-Flagge. Als Inline-SVG-Data-URI eingebettet, damit
es ohne statisches File-Serving funktioniert — in der dynamischen WebApp UND
im statischen Export (kein 404-Risiko durch einen fehlenden /favicon.svg).

Bewusst handgezeichnet statt Marken-Asset: muss bei 16 px noch lesbar sein.
"""

from __future__ import annotations

from urllib.parse import quote

FAVICON_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">\
<g transform="rotate(-8 28 30)">\
<rect x="8" y="16" width="20" height="14" rx="1" fill="#dc2626"/>\
<path d="M11 19 L17 23 L11 27 Z" fill="#e4e4e7"/>\
<path d="M25 19 L19 23 L25 27 Z" fill="#e4e4e7"/>\
<rect x="16.6" y="21.6" width="2.8" height="2.8" fill="#e4e4e7"/>\
</g>\
<g transform="rotate(8 36 30)">\
<rect x="36" y="16" width="20" height="14" rx="1" fill="#18181b"/>\
<g fill="#fafafa">\
<rect x="38" y="18" width="8" height="5"/>\
<rect x="46" y="18" width="8" height="5"/>\
<rect x="38" y="23" width="8" height="5"/>\
<rect x="46" y="23" width="8" height="5"/>\
</g>\
</g>\
<line x1="28" y1="30" x2="39" y2="54" stroke="#71717a" stroke-width="3.5" stroke-linecap="round"/>\
<line x1="36" y1="30" x2="25" y2="54" stroke="#71717a" stroke-width="3.5" stroke-linecap="round"/>\
</svg>"""


def favicon_data_uri() -> str:
    """SVG-Favicon als URL-encodierte Data-URI.

    quote() encodiert u.a. ``#`` (würde sonst als URL-Fragment enden) und
    Leerzeichen — die Data-URI ist damit in HTML-Attributen und f-Strings
    sicher einsetzbar.
    """
    return "data:image/svg+xml," + quote(FAVICON_SVG, safe="")
