"""Seed script integration test via subprocess (isolated DB)."""
from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def test_seed_loads_products(tmp_path: Path):
    csv_path = tmp_path / "products.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Producto", "Producto_Base", "Presentacion", "Unidades_por_Caja",
                "Descripción", "Proveedor", "Categoria", "Imagenes",
            ],
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerow({
            "Producto": "Prod A",
            "Producto_Base": "A",
            "Presentacion": "1kg",
            "Unidades_por_Caja": "10",
            "Descripción": "Desc A",
            "Proveedor": "Prov",
            "Categoria": "cat1",
            "Imagenes": "FALSE",
        })

    db_path = tmp_path / "catalog.db"
    uploads = tmp_path / "uploads"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(ROOT),
    }

    code = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from scripts.seed_catalog import seed_from_csv
from web.config import UPLOADS_DIR
import scripts.seed_catalog as sc
sc.UPLOADS_DIR = Path({str(uploads)!r})
sc.CSV_FINAL = Path({str(csv_path)!r})
n = seed_from_csv(Path({str(csv_path)!r}))
print(n)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout

    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    from web.models import Product

    db = Session()
    try:
        p = db.scalar(select(Product).where(Product.producto == "Prod A"))
        assert p is not None
        assert p.descripcion == "Desc A"
    finally:
        db.close()
