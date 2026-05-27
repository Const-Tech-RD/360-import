"""Merge product descriptions from a sidecar TSV into catalog CSV rows."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DESCRIPTIONS_PATH = Path("data/product_descriptions.tsv")

# Excel/paste name -> CSV ``Producto`` when names differ.
DESCRIPTION_ALIASES: dict[str, str] = {
    "Gemignani aceite de trufas blanca  250 gr x 6": "Gemignani aceite de trufas 250 gr x 6",
    "TOMATES PELADO LA TORRENTE 2500 gr x 6": "TOMATES PELADO LA TORRENTE",
    "MOLINA DALLAGIOVANNA FARINA PASTA GOLD TIPO 00 25 KG": "MOLINA DALLA GIOVANNA FARINA PASTA GOLD TIPO 00 25 KG",
    "MOLINA DALLAGIOVANNA SEMOLA RIMACINATA 25 KG": "MOLINA DALLA GIOVANNA SEMOLA RIMACINATA 25 KG",
    "MOLINO DALLAGIOVANNA SEMOLA EXTRA 25 KG": "MOLINO DALLA GIOVANNA SEMOLA EXTRA 25 KG",
    "MOLINO DALLAGIOVANNA GRANITO 5 KG": "MOLINO DALLA GIOVANNA GRANITO 5 KG",
}


def _normalize_producto(name: str) -> str:
    return (name or "").strip().casefold()


def _resolve_target_producto(paste_name: str) -> str:
    key = paste_name.strip()
    return DESCRIPTION_ALIASES.get(key, key)


@dataclass
class DescriptionMergeReport:
    applied: int = 0
    unmatched_keys: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.applied > 0 or bool(self.unmatched_keys)


def load_description_map(path: Path | None = None) -> dict[str, str]:
    """Load ``Producto`` -> ``Descripción`` from TSV; keys are normalized for lookup."""
    path = path or DEFAULT_DESCRIPTIONS_PATH
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            producto = (row.get("Producto") or "").strip()
            desc = (row.get("Descripción") or row.get("Descripcion") or "").strip()
            if not producto or not desc:
                continue
            target = _resolve_target_producto(producto)
            result[_normalize_producto(target)] = desc
    return result


def apply_descriptions(
    rows: list[dict],
    description_map: dict[str, str] | None = None,
    *,
    descriptions_path: Path | None = None,
) -> tuple[list[dict], DescriptionMergeReport]:
    """
    Set ``Descripción`` on rows whose ``Producto`` matches the map.
    Only non-empty sidecar values are applied; existing CSV text is kept if no match.
    """
    if description_map is None:
        description_map = load_description_map(descriptions_path)

    report = DescriptionMergeReport()
    if not description_map:
        return rows, report

    matched_keys: set[str] = set()
    out: list[dict] = []
    for row in rows:
        r = dict(row)
        key = _normalize_producto(r.get("Producto", ""))
        desc = description_map.get(key)
        if desc:
            r["Descripción"] = desc
            report.applied += 1
            matched_keys.add(key)
        out.append(r)

    for norm_key, desc in description_map.items():
        if norm_key not in matched_keys:
            # Recover display name from map values isn't stored; use first alias hit
            report.unmatched_keys.append(norm_key)

    return out, report
