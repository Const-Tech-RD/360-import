#!/usr/bin/env python3
"""Seed database from productos_final.csv and sidecar TSV files."""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog_descriptions import load_description_map  # noqa: E402
from catalog_exclude import EXCLUDED_CATALOG_PRODUCTO  # noqa: E402
from catalog_ficha_tecnica import load_ficha_map  # noqa: E402
from generate_pdf import normalize_catalog_image_path  # noqa: E402
from web.config import CSV_FINAL, UPLOADS_DIR  # noqa: E402

EXTRACTED_IMAGES = ROOT / "extracted_images"


def _copy_image(rel_path: str) -> str | None:
    """Copy image from extracted_images to uploads/; return relative uploads path."""
    if not rel_path or rel_path == "FALSE":
        return None
    norm = normalize_catalog_image_path(rel_path)
    src = ROOT / norm
    if not src.exists():
        return None
    dest = UPLOADS_DIR / norm
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(src, dest)
    return norm


def seed_from_csv(csv_path: Path = CSV_FINAL, *, clear: bool = True) -> int:
    if not csv_path.exists():
        raise SystemExit(f"Missing CSV: {csv_path}")

    from web.database import SessionLocal, init_db
    from web.models import Product

    init_db()
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    desc_map = load_description_map()
    ficha_map = load_ficha_map()

    db = SessionLocal()
    try:
        if clear:
            db.query(Product).delete()
            db.commit()

        count = 0
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                producto = (row.get("Producto") or "").strip()
                if not producto:
                    continue
                key = producto.casefold()
                imagen_csv = (row.get("Imagenes") or "").strip()
                imagen_path = _copy_image(imagen_csv)

                descripcion = (row.get("Descripción") or "").strip()
                if not descripcion:
                    descripcion = desc_map.get(key, "")

                ficha = ficha_map.get(key, "")

                p = Product(
                    producto=producto,
                    producto_base=(row.get("Producto_Base") or "").strip(),
                    presentacion=(row.get("Presentacion") or "").strip(),
                    unidades_por_caja=(row.get("Unidades_por_Caja") or "").strip(),
                    descripcion=descripcion,
                    proveedor=(row.get("Proveedor") or "").strip(),
                    categoria=(row.get("Categoria") or "").strip(),
                    imagen_path=imagen_path,
                    ficha_tecnica_url=ficha,
                    excluido=producto in EXCLUDED_CATALOG_PRODUCTO,
                )
                db.add(p)
                count += 1

        db.commit()
        return count
    finally:
        db.close()


def main() -> int:
    n = seed_from_csv()
    print(f"Seeded {n} products into database")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
