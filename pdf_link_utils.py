"""Post-process catalog PDF so external links open in a new window/tab."""
from __future__ import annotations

from pathlib import Path


def set_pdf_uri_links_new_window(pdf_path: Path, *, uri_contains: str = "") -> int:
    """
    Set ``/NewWindow true`` on URI link annotations (PDF readers often ignore HTML target=_blank).

    Returns the number of links updated.
    """
    try:
        import fitz
    except ImportError:
        return 0

    doc = fitz.open(pdf_path)
    updated = 0
    for page in doc:
        for lnk in page.get_links():
            uri = lnk.get("uri") or ""
            if not uri or lnk.get("kind") != fitz.LINK_URI:
                continue
            if uri_contains and uri_contains not in uri:
                continue
            xref = lnk.get("xref")
            if not xref:
                continue
            obj = doc.xref_object(xref)
            if "/NewWindow" in obj:
                continue
            needle = f"/URI ({uri})"
            if needle not in obj:
                continue
            new_obj = obj.replace(needle, f"{needle}\n    /NewWindow true")
            doc.update_object(xref, new_obj)
            updated += 1

    if updated:
        doc.saveIncr()
    doc.close()
    return updated
