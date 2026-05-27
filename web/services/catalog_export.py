"""Export catalog from database to PDF."""
from __future__ import annotations

import asyncio
import csv
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog_descriptions import apply_descriptions
from catalog_exclude import filter_catalog_rows_for_export
from catalog_ficha_tecnica import apply_ficha_tecnica
from generate_pdf import build_pages, html_to_pdf, load_products, render_html
from pdf_link_utils import set_pdf_uri_links_new_window
from web.config import PDF_OUTPUT, ROOT_DIR, TEMPLATE_PATH
from web.models import Product


def products_to_rows(products: list[Product]) -> list[dict]:
    rows = [p.to_catalog_dict() for p in products if not p.excluido]
    # Strip internal key before export helpers
    clean = []
    for r in rows:
        d = {k: v for k, v in r.items() if not k.startswith("_")}
        clean.append(d)
    rows, _ = apply_descriptions(clean)
    rows, _ = apply_ficha_tecnica(rows)
    return filter_catalog_rows_for_export(rows)


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        raise ValueError("No products to export")
    fieldnames = [
        "Producto", "Producto_Base", "Presentacion", "Unidades_por_Caja",
        "Descripción", "Proveedor", "Categoria", "Imagenes", "Ficha_Tecnica_URL",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            out = dict(row)
            if not out.get("Imagenes"):
                out["Imagenes"] = "FALSE"
            # Resolve image paths relative to ROOT_DIR for encode_image
            im = out.get("Imagenes", "FALSE")
            if im and im != "FALSE" and not Path(im).is_absolute():
                full = ROOT_DIR / "uploads" / im
                if full.exists():
                    out["Imagenes"] = str(full.relative_to(ROOT_DIR)).replace("\\", "/")
                elif (ROOT_DIR / im).exists():
                    out["Imagenes"] = im.replace("\\", "/")
            writer.writerow(out)


def generate_catalog_pdf(db: Session) -> Path:
    products = list(db.scalars(select(Product).order_by(Product.categoria, Product.producto)))
    rows = products_to_rows(products)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8-sig") as tmp:
        tmp_path = Path(tmp.name)
    write_csv(rows, tmp_path)

    try:
        # Patch load path: generate uses paths from CSV relative to cwd
        loaded = load_products(tmp_path)
        pages = build_pages(loaded)
        html = render_html(pages, TEMPLATE_PATH)
        asyncio.run(html_to_pdf(html, PDF_OUTPUT))
        set_pdf_uri_links_new_window(PDF_OUTPUT, uri_contains="drive.google.com")
    finally:
        tmp_path.unlink(missing_ok=True)

    return PDF_OUTPUT
