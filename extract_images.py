from __future__ import annotations

import colorsys
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

try:
    import olefile
except ImportError:  # pragma: no cover
    olefile = None  # type: ignore[misc]

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}


def extract_from_docx(src_path: Path, out_dir: Path) -> list[Path]:
    """Extract embedded images from a .docx (OOXML) file into ``out_dir``."""
    return extract_from_zip(src_path, out_dir, "word/media/")


def extract_from_xlsx(src_path: Path, out_dir: Path) -> list[Path]:
    """Extract embedded images from .xlsx (OOXML workbook) into ``out_dir``."""
    return extract_from_zip(src_path, out_dir, "xl/media/")


def extract_from_zip(src_path: Path, out_dir: Path, media_prefix: str) -> list[Path]:
    """Extract images from a ZIP-based Office doc (docx or xlsx)."""
    extracted = []
    try:
        with zipfile.ZipFile(src_path) as z:
            for name in z.namelist():
                if not name.startswith(media_prefix):
                    continue
                relative = name[len(media_prefix):]
                if not relative or '/' in relative:
                    continue  # skip subdirectories
                ext = Path(name).suffix.lower()
                if ext not in IMAGE_EXTS:
                    continue
                raw = z.read(name)
                # Same Riso Scotti trademark blob is embedded in xlsx/docx media (~33KB).
                if ext in _LOGO_SUFFIXES and is_xls_trademark_logo_blob_size(len(raw)):
                    continue
                idx = len(extracted)
                out_name = f"{src_path.stem}_{idx}{ext}"
                out_path = out_dir / out_name
                out_path.write_bytes(raw)
                extracted.append(out_path)
    except Exception as e:
        print(f"  Warning: could not read {src_path.name}: {e}")
    return extracted


MIN_IMAGE_BYTES = 500  # skip tiny blobs that are likely thumbnails or artifacts

# Legacy .xls embed a Riso Scotti trademark blob beside real photos. It appears
# as JPEG ~33390–33406 B (and similar PNG sizes). Do NOT use a wide 30–35KB band:
# real docx thumbs (e.g. ~31KB pasta, ~33KB Viander) must be kept.
XLS_TRADEMARK_LOGO_MIN = 33_000
XLS_TRADEMARK_LOGO_MAX = 33_500


def is_xls_trademark_logo_blob_size(size: int) -> bool:
    """True if byte length matches embedded trademark logos from .xls scans."""
    return XLS_TRADEMARK_LOGO_MIN <= size <= XLS_TRADEMARK_LOGO_MAX


_LOGO_SUFFIXES = {'.png', '.jpg', '.jpeg'}


def _is_user_local_upload_path(path: Path) -> bool:
    """True for sidebar uploads under a ``user_upload`` folder (not OLE/.xls extraction)."""
    try:
        return 'user_upload' in {p.lower() for p in path.resolve().parts}
    except OSError:
        return False


def should_ignore_xls_trademark_logo_file(path: Path) -> bool:
    """Skip extracted files that match the .xls Scotti-logo size signature."""
    if _is_user_local_upload_path(path):
        return False
    if path.suffix.lower() not in _LOGO_SUFFIXES:
        return False
    try:
        return is_xls_trademark_logo_blob_size(path.stat().st_size)
    except OSError:
        return True


def should_skip_truncated_xls_jpeg(path: Path) -> bool:
    """Drop .xls JPEGs that decode but look corrupt (grey trunc, banding, colour glitches)."""
    if _is_user_local_upload_path(path):
        return False
    if path.suffix.lower() not in ('.jpg', '.jpeg'):
        return False
    try:
        return _jpeg_likely_decode_corrupt(path.read_bytes())
    except OSError:
        return True


# Back-compat for older imports
def should_ignore_extracted_png(path: Path) -> bool:
    return should_ignore_xls_trademark_logo_file(path)


JPEG_SOI = b'\xff\xd8\xff'
JPEG_EOI = b'\xff\xd9'

PNG_START = b'\x89PNG\r\n\x1a\n'
PNG_END = b'IEND\xaeB`\x82'

BMP_SIG = b'BM'
MAX_EMBEDDED_BMP_BYTES = 80 * 1024 * 1024


def _jpeg_slice_decodes_fully(blob: bytes) -> bool:
    """True if Pillow can decode the full JPEG bitstream (catches truncation)."""
    if Image is None or len(blob) < MIN_IMAGE_BYTES:
        return False
    try:
        with Image.open(BytesIO(blob)) as im:
            im.load()
        return True
    except Exception:
        return False


def _jpeg_row_uniform_band_score(im: Image.Image, w: int, h: int) -> int:
    """Count row groups with almost no horizontal variation (solid bands / glitch stripes)."""
    xs = range(0, w, max(1, w // 60))
    score = 0
    y = 0
    while y < h:
        row_std: list[int] = []
        for yy in range(y, min(y + 3, h)):
            vals = [im.getpixel((x, yy)) for x in xs]
            rs = [v[0] for v in vals]
            gs = [v[1] for v in vals]
            bs = [v[2] for v in vals]
            row_std.append(max(max(rs) - min(rs), max(gs) - min(gs), max(bs) - min(bs)))
        if max(row_std) < 8:
            score += 1
        y += 5
    return score


def _jpeg_sample_high_sat_and_extreme(im: Image.Image, w: int, h: int) -> tuple[float, float]:
    """Return (pct high HSV saturation, pct near-black/near-white extreme pixels)."""
    high_sat = 0
    extreme = 0
    total = 0
    y_step = max(1, h // 90)
    x_step = max(1, w // 90)
    for y in range(0, h, y_step):
        for x in range(0, w, x_step):
            R, G, B = im.getpixel((x, y))
            r, g, b = R / 255.0, G / 255.0, B / 255.0
            total += 1
            _h, s, v = colorsys.rgb_to_hsv(r, g, b)
            if s > 0.75 and v > 0.35:
                high_sat += 1
            if max(R, G, B) > 245 and min(R, G, B) < 40:
                extreme += 1
    if total == 0:
        return 0.0, 0.0
    return 100.0 * high_sat / total, 100.0 * extreme / total


def _jpeg_bottom_neon_fill_fraction(im: Image.Image, w: int, h: int) -> float:
    """Share of sampled pixels in the lower ~40% that look like decoder lime/green fills."""
    if h < 180 or w < 180:
        return 0.0
    y0 = max(1, int(h * 0.60))
    y_step = max(1, (h - y0) // 42)
    x_step = max(1, w // 55)
    fill_like = 0
    total = 0
    for y in range(y0, h, y_step):
        for x in range(0, w, x_step):
            R, G, B = im.getpixel((x, y))
            total += 1
            mx = max(R, G, B)
            if mx < 155:
                continue
            spread = mx - min(R, G, B)
            # Lime decoder fill: very green-heavy vs red/blue (Chromium Pillow glitches).
            if G >= mx and spread >= 70 and G >= 185 and R <= 120 and B <= 130:
                fill_like += 1
                continue
            # Neon cyan/teal glitch band
            if B >= mx and spread >= 55 and G >= 170 and B >= 178 and R <= 118:
                fill_like += 1
    if total == 0:
        return 0.0
    return fill_like / total


def _jpeg_bottom_wide_glitch_pixel_fraction(im: Image.Image, w: int, h: int) -> float:
    """Pixels in the bottom band matching **severe** MCU/lime slabs (not normal package green ink).

    Looser dominance ``G/max`` catches entire legal pack shots; kept for decoder-style **electric**
    channels + high chroma separation only.
    """
    if h < 180 or w < 180:
        return 0.0
    y0 = max(1, int(h * 0.60))
    y_step = max(1, (h - y0) // 42)
    x_step = max(1, w // 55)
    hit = 0
    total = 0
    for y in range(y0, h, y_step):
        for x in range(0, w, x_step):
            R, G, B = im.getpixel((x, y))
            total += 1
            r, g, b = R / 255.0, G / 255.0, B / 255.0
            hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
            if val < 0.15:
                continue
            mx = max(R, G, B)
            mn = min(R, G, B)
            spread = mx - mn
            if mx < 165 or spread < 52:
                continue
            # Compressed neon lime / acid green slabs.
            if G >= mx - 2 and G >= 180 and R <= 140 and B <= 145 and spread >= 62:
                hit += 1
                continue
            # Electric blue decode band.
            if B >= mx - 2 and B >= 180 and spread >= 65 and R <= 145 and G <= 160:
                hit += 1
                continue
            # Hue-saturated glitch block (narrower than naive full green–cyan sweep).
            if spread >= 82 and sat >= 0.50 and val >= 0.35 and (
                (0.20 <= hue <= 0.50) or (0.52 <= hue <= 0.74)
            ):
                hit += 1
                continue
            # Bit-slip rainbow / extreme separation (JPEG tail garbage).
            if spread >= 95 and mx >= 200 and sat >= 0.45:
                hit += 1
    if total == 0:
        return 0.0
    return hit / total


def _jpeg_bottom_combined_glitch_fraction(im: Image.Image, w: int, h: int) -> float:
    """Lower is better: max of strict-neon and wide electric-chroma bottom detectors."""
    return max(
        _jpeg_bottom_neon_fill_fraction(im, w, h),
        _jpeg_bottom_wide_glitch_pixel_fraction(im, w, h),
    )


def _jpeg_bottom_row_uniformity(im: Image.Image, w: int, h: int) -> tuple[float, int, int]:
    """Avg row RGB spread over bottom slice, plus flat-row count and sampled row count."""
    y0 = max(1, int(h * 0.58))
    xs = range(0, w, max(1, w // 60))
    flat_rows = 0
    sampled = 0
    spread_accum = 0.0
    step_y = max(4, max(1, (h - y0) // 48))
    for y in range(y0, h, step_y):
        row_spreads: list[int] = []
        for yy in range(y, min(y + 2, h)):
            vals = [im.getpixel((x, yy)) for x in xs]
            rs = [v[0] for v in vals]
            gs = [v[1] for v in vals]
            bs = [v[2] for v in vals]
            row_std = max(max(rs) - min(rs), max(gs) - min(gs), max(bs) - min(bs))
            row_spreads.append(row_std)
        spread = sum(row_spreads) / len(row_spreads) if row_spreads else 0
        sampled += 1
        spread_accum += spread
        if spread < 12:
            flat_rows += 1
    avg_spread = spread_accum / sampled if sampled else 0.0
    return avg_spread, flat_rows, sampled


def _jpeg_bottom_large_glitch(im: Image.Image, w: int, h: int) -> bool:
    """Huge OLE JPEG corrupt pattern: saturated flat fill dominates the band below mid-height."""
    if max(w, h) < 800 or min(w, h) < 380:
        return False
    neon_frac = _jpeg_bottom_neon_fill_fraction(im, w, h)
    wide_frac = _jpeg_bottom_wide_glitch_pixel_fraction(im, w, h)
    combined = max(neon_frac, wide_frac)
    avg_spread, flat_rows, sampled = _jpeg_bottom_row_uniformity(im, w, h)
    flat_ratio = flat_rows / sampled if sampled else 0.0

    # Strong lime/cyan slab + uniformity (large images only — avoids rejecting small thumbnails).
    if neon_frac >= 0.42 and avg_spread < 18.5 and flat_ratio >= 0.22:
        return True
    if neon_frac >= 0.54:
        return True
    if neon_frac >= 0.28 and avg_spread < 13.5 and flat_ratio >= 0.32:
        return True
    # Electric green/blue MCU bands (common “green preview” failure) + flat horizontal rows.
    if wide_frac >= 0.30 and flat_ratio >= 0.20 and avg_spread < 22.0:
        return True
    if wide_frac >= 0.36 and flat_ratio >= 0.16:
        return True
    if combined >= 0.40 and avg_spread < 20.0 and flat_ratio >= 0.18:
        return True
    return False


def _jpeg_likely_decode_corrupt(blob: bytes) -> bool:
    """Detect JPEGs that Pillow loads but look wrong (common with damaged .xls embeds)."""
    if Image is None or len(blob) < MIN_IMAGE_BYTES:
        return False
    try:
        with Image.open(BytesIO(blob)) as im:
            im = im.convert('RGB')
            im.load()
    except Exception:
        return True
    w, h = im.size
    if h < 120 or w < 120:
        return False

    bottom_glitch_frac = _jpeg_bottom_combined_glitch_fraction(im, w, h)
    large_sheet = len(blob) >= 65_536 and max(w, h) >= 800

    # Decoder lime slab on catalogue-sized OLE rasters (misaligned JPEG in .xls).
    if max(w, h) >= 800 and min(w, h) >= 380 and _jpeg_bottom_large_glitch(im, w, h):
        return True

    step = max(1, w // 55)

    def luma_std(y0: int, y1: int) -> float:
        vals: list[float] = []
        ystep = max(1, (y1 - y0) // 24)
        for y in range(y0, y1, ystep):
            for x in range(0, w, step):
                r, g, b = im.getpixel((x, y))
                vals.append(0.299 * r + 0.587 * g + 0.114 * b)
        if len(vals) < 8:
            return 0.0
        m = sum(vals) / len(vals)
        return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5

    top = luma_std(0, max(1, h // 6))
    mid = luma_std(h // 3, int(h * 0.5))
    bot = luma_std(int(h * 0.86), h)
    # Bright busy upper label + matte lower margin reads like an OLE splice glitch, but catalogue
    # pack shots often have a neon-free flat base (table, shadow). Exempt huge clean-bottom sheets.
    if top > 15.0 and mid < 8.0 and bot < 8.0:
        if not (large_sheet and bottom_glitch_frac < 0.10):
            return True
    if top > 15.0 and bot < 1.0:
        if not (large_sheet and bottom_glitch_frac < 0.10):
            return True

    bands = _jpeg_row_uniform_band_score(im, w, h)
    hs_pct, ex_pct = _jpeg_sample_high_sat_and_extreme(im, w, h)
    # Full-spread catalogue photos (.xls) can show high sat / band scores; soften when the
    # bottom-half does NOT look like a decoder fill and blob size matches a typical photo embed.
    if bands > 45 and (hs_pct > 18.0 or ex_pct >= 5.0):
        if not (large_sheet and bottom_glitch_frac < 0.10):
            return True
        # Pack shots (Scottish rice boxes, pasta sleeves) have huge stripe/band counts
        # across the printed label — do NOT mark corrupt on band count alone for large sane sheets.
        if bottom_glitch_frac > 0.16:
            return True

    if hs_pct > 40.0 and not (large_sheet and bottom_glitch_frac < 0.08):
        return True
    if ex_pct > 35.0 and not (large_sheet and bottom_glitch_frac < 0.06):
        return True
    # Horizontal banding glitches without neon extremes (e.g. Arborio 5kg vacuum .xls):
    if (
        36 <= bands <= 56
        and hs_pct < 12.0
        and ex_pct < 5.0
        and min(w, h) <= 1100
        and max(w, h) <= 1300
    ):
        return True
    return False


def _jpeg_ole_rank_tuple(blob: bytes) -> tuple[float, float, int, float, int] | None:
    """Lower is visually better among decoded JPEG blobs; appended -len(blob) prefers larger stream."""
    if len(blob) < MIN_IMAGE_BYTES or is_xls_trademark_logo_blob_size(len(blob)):
        return None
    if Image is None:
        if _jpeg_slice_decodes_fully(blob):
            return (0.0, 0.0, 0, 0.0, -len(blob))
        return None
    if not _jpeg_slice_decodes_fully(blob) or _jpeg_likely_decode_corrupt(blob):
        return None
    try:
        with Image.open(BytesIO(blob)) as im:
            im_r = im.convert('RGB')
            im_r.load()
            w, h = im.size
            combined = _jpeg_bottom_combined_glitch_fraction(im_r, w, h)
            neon = _jpeg_bottom_neon_fill_fraction(im_r, w, h)
            bands = _jpeg_row_uniform_band_score(im_r, w, h)
            hs_pct, _ = _jpeg_sample_high_sat_and_extreme(im_r, w, h)
            return (combined, neon, bands, hs_pct, -len(blob))
    except Exception:
        return None


def _all_jpeg_so_starts(data: bytes) -> list[int]:
    out: list[int] = []
    i = 0
    while True:
        j = data.find(JPEG_SOI, i)
        if j < 0:
            break
        out.append(j)
        i = j + 2
    return out


def _jpeg_eoi_end_indices(data: bytes, start: int, until: int) -> list[int]:
    """Byte offsets (exclusive) after each ``FF D9`` in ``data[start:until]``."""
    ends: list[int] = []
    pos = start + 3
    while pos < until:
        j = data.find(JPEG_EOI, pos, until)
        if j == -1:
            break
        ends.append(j + 2)
        pos = j + 2
    return ends


def _trim_jpeg_after_last_eoi(blob: bytes) -> bytes:
    """Drop padding after the final ``FF D9`` when the file still decodes."""
    j = blob.rfind(JPEG_EOI)
    if j < 0:
        return blob
    trimmed = blob[: j + 2]
    if len(trimmed) >= MIN_IMAGE_BYTES and _jpeg_slice_decodes_fully(trimmed):
        return trimmed
    return blob


def _jpeg_nearby_soi_starts(
    data: bytes, anchor: int, until: int, *, back: int = 12, forward: int = 4
) -> list[int]:
    """JPEG SOI indices within ``[anchor-back, anchor+forward]`` clipped to ``[0, until)``."""
    lo = max(0, anchor - back)
    hi = min(until - 3, anchor + forward, len(data) - 3)
    if hi < lo:
        return []
    out: list[int] = []
    for s in range(lo, hi + 1):
        if data[s : s + 3] == JPEG_SOI:
            out.append(s)
    return sorted(set(out))


def _best_jpeg_blob_in_range(data: bytes, start: int, until: int) -> bytes | None:
    """Pick best JPEG in ``[start, until)``: EOI-bound slices, dedupe, rank OLE-safe candidates."""
    ends = _jpeg_eoi_end_indices(data, start, until)
    if not ends:
        return None

    best_by_digest: dict[str, tuple[tuple[float, float, int, float, int], bytes]] = {}

    def _remember(cand: bytes) -> None:
        rk = _jpeg_ole_rank_tuple(cand)
        if rk is None:
            return
        key = hashlib.sha256(cand).hexdigest()
        prev = best_by_digest.get(key)
        if prev is None or rk < prev[0]:
            best_by_digest[key] = (rk, cand)

    for e in ends:
        slice_blob = data[start:e]
        if len(slice_blob) < MIN_IMAGE_BYTES:
            continue
        if is_xls_trademark_logo_blob_size(len(slice_blob)):
            continue
        trimmed = _trim_jpeg_after_last_eoi(slice_blob)
        cand = trimmed if len(trimmed) >= MIN_IMAGE_BYTES else slice_blob
        if len(cand) < MIN_IMAGE_BYTES or is_xls_trademark_logo_blob_size(len(cand)):
            continue
        _remember(cand)

    if not best_by_digest:
        return None
    return min(best_by_digest.values(), key=lambda t: t[0])[1]


def _best_jpeg_blob_in_soi_window(data: bytes, anchor: int, until: int) -> bytes | None:
    """Like ``_best_jpeg_blob_in_range`` but tries nearby SOIs (OLE padding before scan start)."""
    best_rk: tuple[float, float, int, float, int] | None = None
    best_blob: bytes | None = None
    for s in _jpeg_nearby_soi_starts(data, anchor, until):
        b = _best_jpeg_blob_in_range(data, s, until)
        if not b:
            continue
        rk = _jpeg_ole_rank_tuple(b)
        if rk is None:
            continue
        if best_rk is None or rk < best_rk:
            best_rk = rk
            best_blob = b
    return best_blob


def _pick_best_jpeg_from_candidates(candidates: list[bytes]) -> bytes | None:
    """Choose lowest glitch rank among non-corrupt blobs (dedupe by SHA-256)."""
    best_by_digest: dict[str, tuple[tuple[float, float, int, float, int], bytes]] = {}

    def _remember(cand: bytes) -> None:
        rk = _jpeg_ole_rank_tuple(cand)
        if rk is None:
            return
        key = hashlib.sha256(cand).hexdigest()
        prev = best_by_digest.get(key)
        if prev is None or rk < prev[0]:
            best_by_digest[key] = (rk, cand)

    for c in candidates:
        if len(c) < MIN_IMAGE_BYTES:
            continue
        _remember(c)

    if not best_by_digest:
        return None
    return min(best_by_digest.values(), key=lambda t: t[0])[1]


def _extract_jpegs_from_bytes(data: bytes) -> list[bytes]:
    """Return decoded JPEG blobs from a byte slice (``.xls`` fragment or OLE stream)."""
    blobs: list[bytes] = []
    sois = _all_jpeg_so_starts(data)
    for k, start in enumerate(sois):
        until = sois[k + 1] if k + 1 < len(sois) else len(data)
        segment = data[start:until]
        cands: list[bytes] = []

        if len(segment) >= MIN_IMAGE_BYTES and not is_xls_trademark_logo_blob_size(len(segment)):
            try:
                trimmed_seg = _trim_jpeg_after_last_eoi(segment)
                seg_blob = trimmed_seg if len(trimmed_seg) >= MIN_IMAGE_BYTES else segment
                if _jpeg_ole_rank_tuple(seg_blob):
                    cands.append(seg_blob)
            except Exception:
                pass

        eo = _best_jpeg_blob_in_soi_window(data, start, until)
        if eo:
            cands.append(eo)

        blob = _pick_best_jpeg_from_candidates(cands)
        if blob:
            blobs.append(blob)
    return blobs


def _extract_pngs_from_bytes(data: bytes) -> list[bytes]:
    blobs: list[bytes] = []
    pos = 0
    while True:
        start = data.find(PNG_START, pos)
        if start == -1:
            break
        end = data.find(PNG_END, start)
        if end == -1:
            break
        end += len(PNG_END)
        blob = data[start:end]
        if len(blob) >= MIN_IMAGE_BYTES and not is_xls_trademark_logo_blob_size(len(blob)):
            blobs.append(blob)
        pos = end
    return blobs


def _bmp_blob_decodes_well(blob: bytes) -> bool:
    if len(blob) < MIN_IMAGE_BYTES or is_xls_trademark_logo_blob_size(len(blob)):
        return False
    if Image is None:
        return True
    try:
        with Image.open(BytesIO(blob)) as im:
            im.load()
            return im.width >= 8 and im.height >= 8
    except Exception:
        return False


def _extract_bmps_from_bytes(data: bytes) -> list[bytes]:
    """Locate Windows BMP bitstreams (`BM` + bfSize) in ``data``."""
    blobs: list[bytes] = []
    pos = 0
    n = len(data)
    while pos <= n - 6:
        i = data.find(BMP_SIG, pos)
        if i < 0:
            break
        if i + 6 > n:
            break
        bf_size = int.from_bytes(data[i + 2 : i + 6], 'little')
        if bf_size < MIN_IMAGE_BYTES or bf_size > MAX_EMBEDDED_BMP_BYTES or i + bf_size > n:
            pos = i + 2
            continue
        blob = data[i : i + bf_size]
        if _bmp_blob_decodes_well(blob):
            blobs.append(blob)
            pos = i + bf_size
        else:
            pos = i + 2
    return blobs


def _ole_stream_chunks(src_path: Path) -> list[bytes]:
    """Read each OLE/CDF stream payload (compound document internals)."""
    if olefile is None or not olefile.isOleFile(src_path):
        return []
    out: list[bytes] = []
    try:
        with olefile.OleFileIO(src_path) as ole:
            for entry in ole.listdir():
                try:
                    raw = ole.openstream(entry).read()
                except (KeyError, OSError):
                    continue
                if len(raw) >= MIN_IMAGE_BYTES:
                    out.append(raw)
    except Exception as e:
        print(f"  Warning: could not traverse OLE streams in {src_path.name}: {e}")
    return out


def _candidate_buffers_legacy_xls(src_path: Path) -> list[bytes]:
    """Full disk image plus OLE stream bodies (images often isolated in streams)."""
    buffers = [src_path.read_bytes()]
    buffers.extend(_ole_stream_chunks(src_path))
    return buffers


MAX_ZLIB_SEEDS_PER_CHUNK = 96


def _try_zlib_inflate_truncated(blob_tail: bytes) -> bytes | None:
    """Best-eff zlib inflate on a truncated tail (Office sometimes stores deflate after ``\\x78\\x9c``)."""
    if len(blob_tail) < 64:
        return None
    for maxlen in (65_536, 262_144, 1_048_576, min(6 * 1024 * 1024, len(blob_tail))):
        try:
            probe = blob_tail[:maxlen]
            return zlib.decompress(probe)
        except zlib.error:
            continue
    return None


def _zlib_maybe_decompressed_blobs(blob: bytes) -> list[bytes]:
    """Return unique inflated payloads embedded as zlib streams inside ``blob``."""
    dedup_hashes: set[str] = set()
    out_list: list[bytes] = []
    pos = 0
    walks = 0
    while walks < MAX_ZLIB_SEEDS_PER_CHUNK:
        i = blob.find(b'\x78\x9c', pos)
        if i < 0:
            break
        walks += 1
        inflated = _try_zlib_inflate_truncated(blob[i:])
        pos = i + 2
        if not inflated or len(inflated) < MIN_IMAGE_BYTES:
            continue
        h_key = hashlib.sha256(inflated).hexdigest()
        if h_key in dedup_hashes:
            continue
        dedup_hashes.add(h_key)
        out_list.append(inflated)
    return out_list


def _dedupe_ordered_image_blobs(buffers: list[bytes]) -> list[tuple[bytes, str]]:
    """Unique images in stable order extension priority: JPG, PNG, BMP per buffer."""
    seen_hashes: set[str] = set()
    ordered: list[tuple[bytes, str]] = []
    extractors: tuple[tuple[Callable[[bytes], list[bytes]], str], ...] = (
        (_extract_jpegs_from_bytes, ".jpg"),
        (_extract_pngs_from_bytes, ".png"),
        (_extract_bmps_from_bytes, ".bmp"),
    )
    for chunk in buffers:
        work_chunks = [chunk, *_zlib_maybe_decompressed_blobs(chunk)]
        for sub in work_chunks:
            for extractor, ext in extractors:
                for piece in extractor(sub):
                    h = hashlib.sha256(piece).hexdigest()
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        ordered.append((piece, ext))
    return ordered


def _decoded_pixel_area_from_blob(blob: bytes) -> int:
    """Rough width*height decode for ranking embedded artefacts vs real photos."""
    if Image is None:
        return 0
    try:
        with Image.open(BytesIO(blob)) as im:
            im.load()
            return max(0, im.width * im.height)
    except Exception:
        return 0


def extract_from_xls_via_soffice_fallback(
    src_path: Path,
    out_dir: Path,
    log: Callable[[str], None],
) -> list[Path]:
    """Optional: convert ``.xls`` to ``.xlsx`` with LibreOffice CLI, then extract OOXML media."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        log("LibreOffice/soffice no está en PATH — no se puede convertir .xls.")
        return []

    tmp_conv = Path(tempfile.mkdtemp(prefix="xls_soffice_"))
    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "xlsx", "--outdir", str(tmp_conv), str(src_path)],
            capture_output=True,
            timeout=120,
            text=True,
        )
        if result.returncode != 0:
            log(
                f"soffice conversión fallida rc={result.returncode} stderr={result.stderr.strip()[:600]!s}"
            )
            return []
        xlsx_files = list(tmp_conv.glob("*.xlsx"))
        if not xlsx_files:
            log("soffice terminó pero no se ve .xlsx generado.")
            return []
        converted = xlsx_files[0]
        extracted = extract_from_xlsx(converted, out_dir)
        log(f"soffice fallback: {converted.name} → {len(extracted)} imagen(es) OOXML")
        return extracted
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        log(f"soffice error: {e}")
        return []
    finally:
        shutil.rmtree(tmp_conv, ignore_errors=True)


def _prioritize_extractions_legacy_xls(parts: list[tuple[bytes, str]]) -> list[tuple[bytes, str]]:
    """Put largest-decoding JPEG blobs first (.xls often embeds logos before pack shots)."""
    jpeg: list[tuple[bytes, str]] = []
    rest: list[tuple[bytes, str]] = []
    for blob, sfx in parts:
        if sfx == ".jpg":
            jpeg.append((blob, sfx))
        else:
            rest.append((blob, sfx))
    jpeg.sort(
        key=lambda it: (_decoded_pixel_area_from_blob(it[0]), len(it[0])),
        reverse=True,
    )
    return jpeg + rest


def extract_from_xls(
    src_path: Path,
    out_dir: Path,
    trace: Callable[[str], None] | None = None,
) -> list[Path]:
    """Extract images from a legacy ``.xls``.

    Combines flat-file JPEG/PNG/BMP scanning with per-OLE-stream scanning;
    blobs are SHA-256 deduplicated so the same JPEG is not emitted twice when
    it appears both in aggregate bytes and inside a stream.

    ``trace`` optional callback receives UTF-8 log lines for UI/consoles;
    prints also go to stdout with prefix ``[extract_images:xls]``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    def _t(line: str) -> None:
        print(f"[extract_images:xls] {line}", flush=True)
        if trace is not None:
            trace(line)

    try:
        nbytes = src_path.stat().st_size
    except OSError:
        nbytes = -1
    _t(f"entrada ruta_temp={src_path.name!s} tamaño_disk_B={nbytes} out_dir={out_dir}")

    buffers = _candidate_buffers_legacy_xls(src_path)
    n_ole_chunks = max(0, len(buffers) - 1)
    _t(f"buffers_total={len(buffers)} tamaño_primario_B={len(buffers[0]) if buffers else 0} chunks_OLE_extra={n_ole_chunks}")
    if len(buffers) > 1:
        ole_sizes = [len(b) for b in buffers[1:]]
        _t(f"OLE_chunk_sizes_B (hasta 12)={ole_sizes[:12]}")

    unique_parts = _dedupe_ordered_image_blobs(buffers)
    by_ext = Counter(sfx for _, sfx in unique_parts)
    _t(f"tras dedupe raster_unicos={len(unique_parts)} por_ext={dict(by_ext)}")
    unique_parts = _prioritize_extractions_legacy_xls(unique_parts)
    jpeg_order = [_decoded_pixel_area_from_blob(blob) for blob, sfx in unique_parts if sfx == ".jpg"]
    if jpeg_order:
        _t(f"JPEG priorizados (área_px desc, primeros 6)={jpeg_order[:6]}")

    extracted: list[Path] = []
    stem = src_path.stem
    for idx, (payload, sfx) in enumerate(unique_parts):
        out_path = out_dir / f"{stem}_{idx}{sfx}"
        out_path.write_bytes(payload)
        extracted.append(out_path)
        _t(f"escrito archivo={out_path.name} tam_B={len(payload)} sufijo={sfx}")
    _t(f"salida_paths={len(extracted)}")

    if not extracted and os.environ.get("LEGACY_XLS_SOFFICE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        _t("fallback: LEGACY_XLS_SOFFICE activo → LibreOffice headless (.xls→.xlsx) + extract zip")
        extracted = extract_from_xls_via_soffice_fallback(src_path, out_dir, _t)

    return extracted


def copy_loose_image(src_path: Path, out_dir: Path) -> Path | None:
    """Copy a standalone image file into out_dir, avoiding name collisions."""
    dest = out_dir / src_path.name
    if dest.exists():
        dest = out_dir / f"{src_path.parent.name}_{src_path.name}"
    if dest.exists():
        # Still collides — append incrementing counter
        stem = src_path.stem
        ext  = src_path.suffix
        idx  = 1
        while dest.exists():
            dest = out_dir / f"{src_path.parent.name}_{stem}_{idx}{ext}"
            idx += 1
    shutil.copy2(src_path, dest)
    return dest


def _unique_destination(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 1
    while True:
        c = directory / f"{stem}_{n}{suffix}"
        if not c.exists():
            return c
        n += 1


def save_normalized_image(src: Path, dest_dir: Path, stem_base: str) -> Path:
    """Decode ``src`` with Pillow and save a clean JPEG or PNG under ``dest_dir``.

    Used by the Streamlit import flow so blobs from OLE/ZIP are re-encoded
    deterministically (similar to manually re-saving from a Python console).

    ``stem_base`` must not contain a file extension.

    Raises:
        RuntimeError if Pillow is not available.
        OSError/PIL exceptions if the raster cannot be read.
    """
    if Image is None:
        raise RuntimeError("Pillow is required for save_normalized_image")

    dest_dir.mkdir(parents=True, exist_ok=True)
    clean_stem = re.sub(r"[^\w\-.]", "_", stem_base, flags=re.UNICODE).strip("._") or "image"
    clean_stem = clean_stem[:120]

    with Image.open(src) as im_raw:
        im_raw.load()

        wants_png = False
        if im_raw.mode in ("RGBA", "LA"):
            wants_png = True
        elif im_raw.mode == "P" and "transparency" in im_raw.info:
            wants_png = True

        if wants_png:
            im_out = im_raw.convert("RGBA")
            out_path = _unique_destination(dest_dir, clean_stem, ".png")
            im_out.save(out_path, format="PNG", optimize=True)
            return out_path

        rgb = im_raw.convert("RGB")
        out_path = _unique_destination(dest_dir, clean_stem, ".jpg")
        rgb.save(out_path, format="JPEG", quality=91, optimize=True)
        return out_path


def main(media_dir: Path, out_dir: Path) -> int:
    """Walk media_dir, extract all images into out_dir. Returns total count."""
    out_dir.mkdir(exist_ok=True)
    total = 0

    for path in sorted(media_dir.rglob('*')):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        extracted = []

        if ext == '.docx':
            extracted = extract_from_zip(path, out_dir, 'word/media/')
        elif ext == '.xlsx':
            extracted = extract_from_zip(path, out_dir, 'xl/media/')
        elif ext == '.xls':
            extracted = extract_from_xls(path, out_dir)
        elif ext in IMAGE_EXTS:
            result = copy_loose_image(path, out_dir)
            if result:
                extracted = [result]

        if extracted:
            print(f"  {path.name}: {len(extracted)} image(s)")
            total += len(extracted)

    print(f"\nTotal: {total} image(s) extracted to {out_dir}/")
    return total


if __name__ == '__main__':
    import sys
    media = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('MEDIA-20260415T015452Z-3-001/MEDIA/fotos pagina web')
    out   = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('extracted_images')
    main(media, out)
