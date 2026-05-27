#!/usr/bin/env python3
"""Import product descriptions from an Excel paste (TSV) into data/product_descriptions.tsv."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog_descriptions import (  # noqa: E402
    DEFAULT_DESCRIPTIONS_PATH,
    apply_descriptions,
    load_description_map,
)

DEFAULT_CSV = ROOT / "productos_con_imagenes.csv"


def parse_paste_rows(text: str) -> list[tuple[str, str]]:
    """
    Parse tab-separated paste: Producto, Descripción, Proveedor, Categoria.
    Keeps rows where description (column 2) is non-empty.
    """
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        producto = parts[0].strip()
        desc = parts[1].strip()
        if not producto or not desc:
            continue
        # Skip brand-only blocks (no typical product packaging pattern)
        if producto.isupper() and len(parts) == 2 and " " not in producto[10:]:
            continue
        out.append((producto, desc))
    return out


def write_descriptions_tsv(rows: list[tuple[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["Producto", "Descripción"])
        for producto, desc in rows:
            writer.writerow([producto, desc])


def load_catalog_productos(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Producto + Descripción from a TSV paste into the sidecar file.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="TSV file to read (default: stdin)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_DESCRIPTIONS_PATH,
        help=f"Output sidecar path (default: {DEFAULT_DESCRIPTIONS_PATH})",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="Catalog CSV for match report",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing sidecar (new rows override by Producto key)",
    )
    args = parser.parse_args()

    if args.input:
        text = args.input.read_text(encoding="utf-8-sig")
    else:
        text = sys.stdin.read()

    new_rows = parse_paste_rows(text)
    if not new_rows:
        print("No rows with non-empty Descripción found.", file=sys.stderr)
        return 1

    if args.merge and args.output.exists():
        existing = load_description_map(args.output)
        # Rebuild from existing file preserving order is hard; merge dict then write
        merged: dict[str, str] = {}
        with open(args.output, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                p = (row.get("Producto") or "").strip()
                d = (row.get("Descripción") or row.get("Descripcion") or "").strip()
                if p and d:
                    merged[p] = d
        for p, d in new_rows:
            merged[p] = d
        new_rows = list(merged.items())

    write_descriptions_tsv(new_rows, args.output)
    print(f"Wrote {len(new_rows)} description(s) → {args.output}")

    if args.csv.exists():
        catalog = load_catalog_productos(args.csv)
        _, report = apply_descriptions(catalog, load_description_map(args.output))
        print(f"Matched in catalog: {report.applied}")
        if report.unmatched_keys:
            print(f"Unmatched in catalog: {len(report.unmatched_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
