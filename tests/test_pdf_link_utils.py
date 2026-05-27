from pathlib import Path

import pytest

from pdf_link_utils import set_pdf_uri_links_new_window


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("fitz") is None,
    reason="pymupdf not installed",
)
def test_set_pdf_uri_links_new_window_adds_flag(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    pdf = tmp_path / "links.pdf"
    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(72, 72, 200, 90)
    page.insert_link(
        {
            "kind": fitz.LINK_URI,
            "from": rect,
            "uri": "https://drive.google.com/file/d/abc/view",
        }
    )
    doc.save(pdf)
    doc.close()

    n = set_pdf_uri_links_new_window(pdf, uri_contains="drive.google.com")
    assert n == 1

    doc2 = fitz.open(pdf)
    xref = doc2[0].get_links()[0]["xref"]
    assert "/NewWindow true" in doc2.xref_object(xref)
    doc2.close()
