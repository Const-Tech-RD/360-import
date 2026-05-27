"""Drop-in catalog exclusions: omit rows from CSV export/PDF without changing source CSV indexes."""
from __future__ import annotations

# Exact ``Producto`` field as in CSV (strip applied at match).
EXCLUDED_CATALOG_PRODUCTO: frozenset[str] = frozenset(
    {
        "GR RIGATONI TRAFILADO AL BRONZO 500 GR X 24",
        "LATTERIA SORESINA QUESO PECORINO ROMANO 250 GR X 15",
    }
)


def is_product_excluded_from_catalog(row: dict) -> bool:
    return (row.get("Producto") or "").strip() in EXCLUDED_CATALOG_PRODUCTO


def filter_catalog_rows_for_export(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not is_product_excluded_from_catalog(r)]
