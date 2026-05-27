#!/usr/bin/env python3
"""Read-only diagnostics for legacy ``.xls`` (OLE compound): magic-byte counts vs Workbook stream.

Usage:
  python scripts/diag_legacy_xls.py /path/to/file.xls [--offsets N]

When ``olefile`` is installed, lists OLE streams with sizes and re-runs signatures on ``Workbook`` only.

Install:
  pip install olefile
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_all(blob: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    start = 0
    ln = len(needle)
    while True:
        j = blob.find(needle, start)
        if j < 0:
            break
        out.append(j)
        start = j + ln if ln else j + 1
    return out


def _emf_candidates(blob: bytes) -> int:
    sig = b"%\xe0\xfd\xff"
    n = 0
    pos = 0
    while True:
        i = blob.find(sig, pos)
        if i < 0:
            break
        if i + 8 <= len(blob):
            ver = int.from_bytes(blob[i + 4 : i + 8], "little")
            if ver == 1:
                n += 1
        pos = i + 2
    return n


def _stream_label(entry: list[str | bytes] | tuple[str | bytes, ...]) -> str:
    parts = []
    for p in entry:
        if isinstance(p, bytes):
            parts.append(p.decode(errors="replace").lstrip("\x05"))
        else:
            parts.append(str(p).lstrip("\x05"))
    return "/".join(parts) or "."


def _analyze(label: str, blob: bytes, max_offsets_ffd8: int) -> None:
    print(f"\n=== {label} len_B={len(blob)} ===")

    jpeg_lo = blob.count(b"\xff\xd8")
    jpeg_strict = blob.count(b"\xff\xd8\xff")
    png = blob.count(b"\x89PNG\r\n\x1a\n")
    bm_txt = blob.count(b"BM")
    wmf_hit = blob.count(b"\xd7\xcd\xc6\x9a")
    emf = _emf_candidates(blob)

    print(
        f"  jpeg_ff_d8×={jpeg_lo}  jpeg_ff_d8_ff×={jpeg_strict}  PNG×={png}  BM×={bm_txt}  "
        f"WMF_magic×={wmf_hit}  EMF_ver1_hints×={emf}"
    )

    if max_offsets_ffd8 <= 0:
        return

    offs = _find_all(blob, b"\xff\xd8")[:max_offsets_ffd8]
    print(f"  first FF D8 offsets (up to {max_offsets_ffd8}): {offs}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose raster signatures inside legacy .xls blobs.")
    parser.add_argument("path", type=Path, help="Path to .xls file")
    parser.add_argument(
        "--offsets",
        type=int,
        default=24,
        metavar="N",
        help="Print first N JPEG SOI offsets (0=disable)",
    )
    args = parser.parse_args()
    src = args.path.expanduser()

    if not src.is_file():
        print(f"Not a file: {src}", file=sys.stderr)
        return 2

    full = src.read_bytes()
    _analyze(f"whole file `{src.name}`", full, args.offsets)

    try:
        import olefile
    except ImportError:
        print("\n[olefile not installed — skip OLE stream isolation]")
        return 0

    if not olefile.isOleFile(src):
        print("\nNot an OLE compound (olefile rejects). Flat scan above is all.")
        return 0

    with olefile.OleFileIO(src) as ole:
        workbook_entry = None
        print("\nOle streams:")
        for ent in ole.listdir():
            label = _stream_label(ent)
            sz = ole.get_size(ent)
            marker = ""
            leaf = ""
            if ent and isinstance(ent[-1], str):
                leaf = ent[-1].lstrip("\x05")
            elif ent and isinstance(ent[-1], bytes):
                leaf = ent[-1].decode(errors="replace").lstrip("\x05")
            if leaf.upper() == "WORKBOOK":
                workbook_entry = list(ent)
                marker = "  ← workbook"
            print(f"   {label!s}  size_B={sz}{marker}")

        if workbook_entry is None:
            print("\n[No WORKBOOK leaf seen — workbook scan skipped]")
            return 0

        wb = ole.openstream(workbook_entry).read()
        _analyze("OLE stream Workbook body", wb, args.offsets)
    return 0


if __name__ == "__main__":
    sys.exit(main())
