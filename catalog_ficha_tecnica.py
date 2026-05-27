"""Merge technical sheet (ficha técnica) URLs from a sidecar TSV into catalog rows."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_FICHA_PATH = Path("data/product_ficha_tecnica.tsv")


def _normalize_producto(name: str) -> str:
    return (name or "").strip().casefold()


@dataclass
class FichaMergeReport:
    applied: int = 0
    unmatched_keys: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.applied > 0 or bool(self.unmatched_keys)


def load_ficha_map(path: Path | None = None) -> dict[str, str]:
    """Load ``Producto`` -> ``Ficha_Tecnica_URL`` from TSV; keys are normalized."""
    path = path or DEFAULT_FICHA_PATH
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            producto = (row.get("Producto") or "").strip()
            url = (row.get("Ficha_Tecnica_URL") or "").strip()
            if not producto or not url:
                continue
            result[_normalize_producto(producto)] = url
    return result


def apply_ficha_tecnica(
    rows: list[dict],
    ficha_map: dict[str, str] | None = None,
    *,
    ficha_path: Path | None = None,
) -> tuple[list[dict], FichaMergeReport]:
    """Set ``Ficha_Tecnica_URL`` on rows whose ``Producto`` matches the map."""
    if ficha_map is None:
        ficha_map = load_ficha_map(ficha_path)

    report = FichaMergeReport()
    if not ficha_map:
        return rows, report

    matched_keys: set[str] = set()
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        key = _normalize_producto(r.get("Producto", ""))
        url = ficha_map.get(key)
        if url:
            r["Ficha_Tecnica_URL"] = url
            report.applied += 1
            matched_keys.add(key)
        out.append(r)

    for norm_key in ficha_map:
        if norm_key not in matched_keys:
            report.unmatched_keys.append(norm_key)

    return out, report
