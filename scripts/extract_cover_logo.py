#!/usr/bin/env python3
"""Extract cover logo PNG from assets/images/logo 360 pdf.pdf."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "assets/images/logo 360 pdf.pdf"
OUT_PNG = ROOT / "assets/images/logo_360_cover.png"


def extract_logo_png(pdf_path: Path = PDF_PATH, out_path: Path = OUT_PNG) -> Path:
    """
    Render the logo region from the PDF cover page.

    The source PDF splits the logo into several stacked image strips; extracting
    a single embedded raster leaves a visible horizontal seam. Rendering the
    union bounding box of all placements produces one continuous logo.
    """
    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise SystemExit("Install pymupdf: pip3 install pymupdf") from e

    doc = fitz.open(pdf_path)
    page = doc[0]

    clip = None
    for img in page.get_images(full=True):
        for rect in page.get_image_rects(img[0]):
            clip = rect if clip is None else clip | rect

    if clip is None:
        clip = page.rect

    # ~288 dpi; enough for print cover without huge HTML payload.
    matrix = fitz.Matrix(4, 4)
    pix = page.get_pixmap(matrix=matrix, clip=clip, alpha=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))
    doc.close()
    return out_path


def main() -> int:
    if not PDF_PATH.exists():
        print(f"Missing: {PDF_PATH}", file=sys.stderr)
        return 1
    out = extract_logo_png()
    print(f"Saved → {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
