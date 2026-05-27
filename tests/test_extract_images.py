import random
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
import pytest

from PIL import Image


# ── helpers ────────────────────────────────────────────────────────────────

TINY_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'\x00' * 200 + bytes([0xFF, 0xD9])
TINY_PNG  = b'\x89PNG\r\n\x1a\n' + b'\x00' * 200 + b'IEND\xaeB`\x82'


def minimal_valid_jpeg_bytes() -> bytes:
    """Real JPEG bitstream so Pillow can validate extraction from .xls."""
    im = Image.new('RGB', (8, 8), color=(200, 10, 10))
    buf = BytesIO()
    im.save(buf, format='JPEG', quality=85)
    return buf.getvalue()


def make_zip(path: Path, files: dict[str, bytes]):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "extracted"
    d.mkdir()
    return d


# ── extract_from_zip ────────────────────────────────────────────────────────

def test_extract_from_docx_returns_jpeg(tmp_path, out_dir):
    from extract_images import extract_from_zip
    docx = tmp_path / "product.docx"
    make_zip(docx, {"word/media/image1.jpg": TINY_JPEG, "word/document.xml": b"<x/>"})
    result = extract_from_zip(docx, out_dir, "word/media/")
    assert len(result) == 1
    assert result[0].suffix == ".jpg"
    assert result[0].read_bytes() == TINY_JPEG


def test_extract_from_xlsx_returns_png(tmp_path, out_dir):
    from extract_images import extract_from_zip
    xlsx = tmp_path / "sheet.xlsx"
    make_zip(xlsx, {"xl/media/image1.png": TINY_PNG, "[Content_Types].xml": b""})
    result = extract_from_zip(xlsx, out_dir, "xl/media/")
    assert len(result) == 1
    assert result[0].suffix == ".png"


def test_extract_from_zip_skips_trademark_logo_blob(tmp_path, out_dir):
    """xlsx/docx embed the same ~33.4KB Riso Scotti media as legacy .xls."""
    from extract_images import extract_from_zip

    PNG_END = b'IEND\xaeB`\x82'
    PNG_START = b'\x89PNG\r\n\x1a\n'
    target = 33_390
    logo_png = PNG_START + (b'\x00' * (target - len(PNG_START) - len(PNG_END))) + PNG_END
    assert len(logo_png) == target

    xlsx = tmp_path / "Risotto con trufas.xlsx"
    make_zip(xlsx, {"xl/media/image1.png": logo_png, "[Content_Types].xml": b""})
    result = extract_from_zip(xlsx, out_dir, "xl/media/")
    assert result == []


def test_extract_from_zip_keeps_next_image_after_skipping_logo(tmp_path, out_dir):
    from extract_images import extract_from_zip

    PNG_END = b'IEND\xaeB`\x82'
    PNG_START = b'\x89PNG\r\n\x1a\n'
    logo = PNG_START + (b'\x00' * (33_400 - len(PNG_START) - len(PNG_END))) + PNG_END
    good = PNG_START + (b'\x42' * 2000) + PNG_END

    xlsx = tmp_path / "Jasmine rice 500g.xlsx"
    make_zip(xlsx, {
        "xl/media/a.png": logo,
        "xl/media/b.png": good,
        "[Content_Types].xml": b"",
    })
    result = extract_from_zip(xlsx, out_dir, "xl/media/")
    assert len(result) == 1
    assert result[0].read_bytes() == good


def test_extract_from_zip_skips_non_image(tmp_path, out_dir):
    from extract_images import extract_from_zip
    docx = tmp_path / "doc.docx"
    make_zip(docx, {"word/media/embed.xml": b"<xml/>", "word/document.xml": b"<x/>"})
    result = extract_from_zip(docx, out_dir, "word/media/")
    assert result == []


def test_extract_from_zip_skips_subdirs(tmp_path, out_dir):
    from extract_images import extract_from_zip
    docx = tmp_path / "doc.docx"
    make_zip(docx, {"word/media/sub/image1.jpg": TINY_JPEG})
    result = extract_from_zip(docx, out_dir, "word/media/")
    assert result == []


def test_extract_from_zip_corrupt_file_returns_empty(tmp_path, out_dir):
    from extract_images import extract_from_zip
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"not a zip")
    result = extract_from_zip(bad, out_dir, "word/media/")
    assert result == []


def test_extract_from_zip_multiple_images(tmp_path, out_dir):
    from extract_images import extract_from_zip
    docx = tmp_path / "multi.docx"
    make_zip(docx, {
        "word/media/image1.jpg": TINY_JPEG,
        "word/media/image2.png": TINY_PNG,
    })
    result = extract_from_zip(docx, out_dir, "word/media/")
    assert len(result) == 2


# ── extract_from_xls ────────────────────────────────────────────────────────

def make_xls_with_jpeg(path: Path):
    """Write a fake binary file containing a JPEG blob preceded by junk."""
    jpeg = minimal_valid_jpeg_bytes()
    path.write_bytes(b'\x00' * 512 + jpeg + b'\x00' * 128)


def make_xls_with_png(path: Path):
    png = b'\x89PNG\r\n\x1a\n' + b'\x42' * 2000 + b'IEND\xaeB`\x82'
    path.write_bytes(b'\x00' * 512 + png + b'\x00' * 128)


def test_extract_from_xls_finds_jpeg(tmp_path, out_dir):
    from extract_images import extract_from_xls
    xls = tmp_path / "product.xls"
    make_xls_with_jpeg(xls)
    result = extract_from_xls(xls, out_dir)
    assert len(result) == 1
    assert result[0].suffix == ".jpg"


def test_extract_from_xls_finds_png(tmp_path, out_dir):
    from extract_images import extract_from_xls
    xls = tmp_path / "product.xls"
    make_xls_with_png(xls)
    result = extract_from_xls(xls, out_dir)
    assert len(result) == 1
    assert result[0].suffix == ".png"


def test_extract_from_xls_empty_returns_empty(tmp_path, out_dir):
    from extract_images import extract_from_xls
    xls = tmp_path / "empty.xls"
    xls.write_bytes(b'\x00' * 512)
    result = extract_from_xls(xls, out_dir)
    assert result == []


def test_extract_from_xls_skips_tiny_blobs(tmp_path, out_dir):
    from extract_images import extract_from_xls
    xls = tmp_path / "tiny.xls"
    # JPEG that's only 10 bytes — below the 500-byte threshold
    xls.write_bytes(bytes([0xFF, 0xD8, 0xFF]) + b'\x00' * 5 + bytes([0xFF, 0xD9]))
    result = extract_from_xls(xls, out_dir)
    assert result == []


def test_extract_from_xls_skips_trademark_logo_png_size(tmp_path, out_dir):
    """Riso Scotti–sized PNG blobs from legacy .xls must not be written (~33.0–33.5KB)."""
    from extract_images import extract_from_xls

    PNG_END = b'IEND\xaeB`\x82'
    PNG_START = b'\x89PNG\r\n\x1a\n'
    target = 33_406
    body_len = target - len(PNG_START) - len(PNG_END)
    logo_png = PNG_START + (b'\x00' * body_len) + PNG_END
    assert len(logo_png) == target

    xls = tmp_path / "Basmati rice 500g.xls"
    xls.write_bytes(b'\x00' * 512 + logo_png + b'\x00' * 128)
    result = extract_from_xls(xls, out_dir)
    assert result == []


def test_extract_from_xls_skips_trademark_logo_jpeg_size(tmp_path, out_dir):
    """Same trademark blobs often appear as JPEG from .xls byte scans."""
    from extract_images import extract_from_xls

    target = 33_390
    bad_jpg = b'\xff\xd8\xff' + (b'\x00' * (target - 5)) + b'\xff\xd9'
    assert len(bad_jpg) == target

    xls = tmp_path / "Risotto con trufas.xls"
    xls.write_bytes(b'\x00' * 512 + bad_jpg + b'\x00' * 128)
    result = extract_from_xls(xls, out_dir)
    assert result == []


def test_extract_from_xls_keeps_png_after_skipping_logo_blob(tmp_path, out_dir):
    from extract_images import extract_from_xls

    PNG_END = b'IEND\xaeB`\x82'
    PNG_START = b'\x89PNG\r\n\x1a\n'
    logo_len = 33_400
    logo_png = PNG_START + (b'\x00' * (logo_len - len(PNG_START) - len(PNG_END))) + PNG_END
    good_png = PNG_START + (b'\x42' * 2000) + PNG_END

    xls = tmp_path / "rice.xls"
    xls.write_bytes(b'\x00' * 100 + logo_png + b'PAD' + good_png + b'\x00' * 100)
    result = extract_from_xls(xls, out_dir)
    assert len(result) == 1
    assert result[0].suffix == ".png"
    assert result[0].stat().st_size == len(good_png)


def test_extract_from_xls_keeps_jpeg_after_skipping_logo_blob(tmp_path, out_dir):
    from extract_images import extract_from_xls

    bad_len = 33_406
    bad_jpg = b'\xff\xd8\xff' + (b'\x00' * (bad_len - 5)) + b'\xff\xd9'
    good_jpg = minimal_valid_jpeg_bytes()

    xls = tmp_path / "Jasmine rice 500g.xls"
    xls.write_bytes(b'\x00' * 100 + bad_jpg + b'XX' + good_jpg + b'\x00' * 100)
    result = extract_from_xls(xls, out_dir)
    assert len(result) == 1
    assert result[0].suffix == ".jpg"
    assert result[0].stat().st_size == len(good_jpg)


def test_extract_bmps_from_bytes_finds_nested_bmp():
    from extract_images import _extract_bmps_from_bytes

    buf = BytesIO()
    img = Image.new("RGB", (18, 12), color=(10, 200, 30))
    img.save(buf, format="BMP")
    bmp = buf.getvalue()
    assert bmp[:2] == b"BM"
    frag = b"PREFIX" * 120 + bmp + b"TAIL"
    found = _extract_bmps_from_bytes(frag)
    assert len(found) == 1
    assert found[0] == bmp


def test_dedupe_ordered_image_blobs_removes_duplicate_jpeg():
    from extract_images import _dedupe_ordered_image_blobs

    j = minimal_valid_jpeg_bytes()
    parts = _dedupe_ordered_image_blobs([j, j])
    assert len(parts) == 1


def test_extract_from_xls_uses_additional_buffer(monkeypatch, tmp_path, out_dir):
    import extract_images as ei

    xls = tmp_path / "noread.xls"
    xls.write_bytes(b"PLAIN_NO_EMBEDDED_MARKER")
    jpeg = minimal_valid_jpeg_bytes()
    monkeypatch.setattr(
        ei,
        "_candidate_buffers_legacy_xls",
        lambda _path: [b"", jpeg],
    )
    extracted = ei.extract_from_xls(xls, out_dir)
    assert len(extracted) == 1
    assert extracted[0].suffix.lower() == ".jpg"



def test_prioritize_extractions_legacy_xls_prefers_large_jpeg():
    from extract_images import _prioritize_extractions_legacy_xls

    bio_s = BytesIO()
    Image.new("RGB", (30, 20), color=(1, 2, 3)).save(bio_s, format="JPEG")
    blob_s = bio_s.getvalue()

    bio_l = BytesIO()
    Image.new("RGB", (300, 200), color=(9, 8, 7)).save(bio_l, format="JPEG")
    blob_l = bio_l.getvalue()

    inp = [(blob_s, ".jpg"), (blob_l, ".jpg")]
    out = _prioritize_extractions_legacy_xls(inp)
    assert out[0][0] == blob_l


# ── jpeg OLE-glitch heuristic (large .xls embeds) ─────────────────────────────

def _jpeg_bytes_glitch_green_bottom_large() -> bytes:
    """Large JPEG with uniform neon-ish green lower half — decoder glitch profile."""
    from PIL import ImageDraw

    rng = random.Random(2026)
    w, h = 1204, 910
    im = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(im)
    bottom_y = int(h * 0.57)
    draw.rectangle([(0, bottom_y), (w - 1, h - 1)], fill=(26, 247, 52))
    step_x, step_y = 10, 8
    for y in range(0, bottom_y, step_y):
        for x in range(0, w, step_x):
            rc = rng.randint(0, 219)
            bc = rng.randint(0, 239)
            im.putpixel((x, min(y + step_y - 1, bottom_y - 1)), (rc, rng.randint(55, 200), bc))
            im.putpixel((min(x + 6, w - 1), y), (rc, rng.randint(50, 195), bc))
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _jpeg_bytes_large_smooth_gradient_catlike() -> bytes:
    """High-res varied colour field (no flat decoder fill); should stay non-corrupt."""
    w, h = 1040, 960
    im = Image.new("RGB", (w, h))
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            r = (x * 194 + y * 3) % 256
            g = (255 - abs(x - y)) % 256
            b = (x ^ y) % 256
            for dy in range(8):
                for dx in range(8):
                    if x + dx < w and y + dy < h:
                        im.putpixel((x + dx, y + dy), (r, g, b))
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=91)
    return buf.getvalue()


def test_jpeg_likely_decode_corrupt_large_green_bottom_matches_ole_glitch():
    from extract_images import _jpeg_likely_decode_corrupt

    glitch = _jpeg_bytes_glitch_green_bottom_large()
    assert len(glitch) >= 65_536
    assert _jpeg_likely_decode_corrupt(glitch) is True


def test_user_upload_bypasses_trademark_logo_size_filter(tmp_path):
    from extract_images import (
        XLS_TRADEMARK_LOGO_MAX,
        XLS_TRADEMARK_LOGO_MIN,
        should_ignore_extracted_png,
        should_ignore_xls_trademark_logo_file,
    )

    band_bytes = b"A" * ((XLS_TRADEMARK_LOGO_MIN + XLS_TRADEMARK_LOGO_MAX) // 2)
    outside = tmp_path / "extracted_elsewhere" / "logoish.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(band_bytes)

    inside = tmp_path / "catalog" / "user_upload" / "logoish.jpg"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(band_bytes)

    assert should_ignore_xls_trademark_logo_file(outside) is True
    assert should_ignore_xls_trademark_logo_file(inside) is False
    assert should_ignore_extracted_png(inside) is False


def test_user_upload_bypasses_truncated_xls_jpeg_heuristic(tmp_path):
    from extract_images import should_skip_truncated_xls_jpeg

    glitch = _jpeg_bytes_glitch_green_bottom_large()

    outside = tmp_path / "xls_extract" / "glitch.jpg"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(glitch)

    inside = tmp_path / "imgs" / "user_upload" / "glitch.jpg"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(glitch)

    assert should_skip_truncated_xls_jpeg(outside) is True
    assert should_skip_truncated_xls_jpeg(inside) is False


def test_jpeg_likely_decode_corrupt_large_gradient_stays_clean():
    from extract_images import _jpeg_likely_decode_corrupt

    blob = _jpeg_bytes_large_smooth_gradient_catlike()
    assert len(blob) >= 65_536
    assert _jpeg_likely_decode_corrupt(blob) is False


def test_pick_best_jpeg_from_candidates_prefers_clean_over_green_glitch():
    from extract_images import _pick_best_jpeg_from_candidates

    glitch = _jpeg_bytes_glitch_green_bottom_large()
    clean = _jpeg_bytes_large_smooth_gradient_catlike()

    worst_first = _pick_best_jpeg_from_candidates([glitch, clean])
    best_first = _pick_best_jpeg_from_candidates([clean, glitch])

    assert worst_first == clean
    assert best_first == clean


def _jpeg_bytes_bottom_electric_green_blue_bands_large() -> bytes:
    """Simulates MCU-style green/blue horizontal slabs (OLE decode preview artefacts)."""
    w, h = 1643, 2174
    im = Image.new("RGB", (w, h), (252, 252, 252))
    for y in range(h // 2, h):
        for x in range(w):
            c = (18, 238, 42) if (y // 10) % 2 == 0 else (28, 52, 238)
            im.putpixel((x, y), c)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=92)
    blob = buf.getvalue()
    assert len(blob) >= 65_536
    return blob


def test_jpeg_likely_decode_corrupt_electric_green_blue_bands():
    """Wide bottom glitch detector flags neon green/electric-blue horizontal decode garbage."""
    from extract_images import _jpeg_bottom_wide_glitch_pixel_fraction, _jpeg_likely_decode_corrupt

    blob = _jpeg_bytes_bottom_electric_green_blue_bands_large()
    with Image.open(BytesIO(blob)) as im_rgb:
        im_rgb = im_rgb.convert("RGB")
        im_rgb.load()
        ww, hh = im_rgb.size
        wide_frac = _jpeg_bottom_wide_glitch_pixel_fraction(im_rgb, ww, hh)

    assert wide_frac >= 0.30
    assert _jpeg_likely_decode_corrupt(blob) is True


def _jpeg_bytes_horizontal_striped_packshot_large() -> bytes:
    """Synthetic ~packaging sleeve: saturated horizontal bands → high ole band-score; warm bottom avoids neon glitch."""
    w, h = 1643, 2174
    im = Image.new("RGB", (w, h))
    colors_top = [
        (220, 40, 35),
        (245, 165, 28),
        (238, 228, 96),
        (210, 105, 180),
        (180, 30, 140),
        (240, 248, 230),
    ]
    y_floor = int(h * 0.62)
    for y in range(h):
        if y >= y_floor:
            shade = int(90 + ((y % 140) / 139) * 45)
            c = (max(55, shade + 12), shade, max(40, shade - 25))
            for x in range(w):
                im.putpixel((x, y), c)
            continue
        band = (y // 9) % len(colors_top)
        c = colors_top[band]
        for x in range(w):
            im.putpixel((x, y), c)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=90)
    blob = buf.getvalue()
    assert len(blob) >= 65_536
    return blob


def test_jpeg_likely_decode_corrupt_scotti_pack_pattern_stays_clean():
    """Regression: large labelled pack shots must not flip corrupt on stripe band-score alone."""
    from extract_images import (
        _jpeg_bottom_neon_fill_fraction,
        _jpeg_likely_decode_corrupt,
        _jpeg_row_uniform_band_score,
        _jpeg_sample_high_sat_and_extreme,
    )

    blob = _jpeg_bytes_horizontal_striped_packshot_large()
    with Image.open(BytesIO(blob)) as im_rgb:
        im_rgb = im_rgb.convert("RGB")
        im_rgb.load()
        ww, hh = im_rgb.size
        bands = _jpeg_row_uniform_band_score(im_rgb, ww, hh)
        hs_pct, _ = _jpeg_sample_high_sat_and_extreme(im_rgb, ww, hh)
        neon = _jpeg_bottom_neon_fill_fraction(im_rgb, ww, hh)

    assert bands > 60
    assert hs_pct > 18.0
    assert neon < 0.10
    assert _jpeg_likely_decode_corrupt(blob) is False


def _jpeg_bytes_luma_busy_top_flat_bottom_sheet() -> bytes:
    """Large JPEG resembling a glossy label (noisy crop top + flat packaging base)."""
    w, h = 1643, 2174
    rng = random.Random(11)
    im = Image.new("RGB", (w, h))
    y_top = int(h * 0.12)
    y_mid = int(h * 0.50)
    for y in range(h):
        if y < y_top:
            for x in range(0, w, 3):
                im.putpixel(
                    (x, y),
                    (rng.randint(70, 235), rng.randint(30, 215), rng.randint(20, 200)),
                )
        elif y < y_mid:
            row_tone = min(229, max(186, 208 + ((y % 9) ^ 3)))
            for x in range(w):
                px = row_tone - 8 if x % 113 == 0 else row_tone
                im.putpixel((x, y), (px, px, px))
        else:
            base = (236, 231, 226)
            for x in range(w):
                rr = base[0] - 1 if x % 239 == 0 else base[0]
                im.putpixel((x, y), (rr, base[1], base[2]))
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=93)
    blob = buf.getvalue()
    assert len(blob) >= 65_536
    return blob


def test_jpeg_corrupt_busy_top_flat_bottom_not_flagged_when_bottom_neon_clean():
    from extract_images import _jpeg_likely_decode_corrupt

    blob = _jpeg_bytes_luma_busy_top_flat_bottom_sheet()
    assert _jpeg_likely_decode_corrupt(blob) is False


def test_extract_from_xls_finds_jpeg_after_zlib_wrap(tmp_path, out_dir):
    """zlib-compressed JPEG inside monolithic buffer (Office-style deflate seed)."""
    from extract_images import extract_from_xls

    inner = zlib.compress(minimal_valid_jpeg_bytes())
    assert inner[:2] == b"\x78\x9c"
    xls = tmp_path / "zlib_pack.xls"
    xls.write_bytes(b"PREFIX_\x78\x01" + inner + b"_SUFFIX_TAIL")
    result = extract_from_xls(xls, out_dir)
    assert len(result) == 1
    assert result[0].suffix == ".jpg"


@pytest.mark.integration
def test_integration_scotti_xls_when_download_present(tmp_path, out_dir):
    from extract_images import extract_from_xls, should_skip_truncated_xls_jpeg

    cand = Path.home() / "Downloads" / "Scotti Riso Arborio 1 kg x 10.xls"
    if not cand.is_file():
        pytest.skip("Local Scotti .xls not in ~/Downloads")

    extracted = extract_from_xls(cand, out_dir)
    assert extracted, "Expected at least one raster from workbook JPEG layout"
    for p in extracted:
        if p.suffix.lower() in (".jpg", ".jpeg"):
            assert not should_skip_truncated_xls_jpeg(p)


# ── copy_loose_image ────────────────────────────────────────────────────────

def test_copy_loose_image_copies_file(tmp_path, out_dir):
    from extract_images import copy_loose_image
    img = tmp_path / "salov foto.png"
    img.write_bytes(TINY_PNG)
    result = copy_loose_image(img, out_dir)
    assert result is not None
    assert result.exists()
    assert result.read_bytes() == TINY_PNG


def test_copy_loose_image_avoids_overwrite(tmp_path, out_dir):
    from extract_images import copy_loose_image
    img = tmp_path / "photo.jpg"
    img.write_bytes(TINY_JPEG)
    (out_dir / "photo.jpg").write_bytes(b"existing")
    result = copy_loose_image(img, out_dir)
    assert result is not None
    assert (out_dir / "photo.jpg").read_bytes() == b"existing"  # original untouched
    assert result.read_bytes() == TINY_JPEG  # written under alternate name


# ── main orchestrator ───────────────────────────────────────────────────────

def test_main_extracts_from_nested_dirs(tmp_path, out_dir):
    from extract_images import main as extract_main
    media = tmp_path / "media"
    sub = media / "sub"
    sub.mkdir(parents=True)

    docx = sub / "product.docx"
    make_zip(docx, {"word/media/image1.jpg": TINY_JPEG})

    loose = media / "photo.png"
    loose.write_bytes(TINY_PNG)

    total = extract_main(media, out_dir)
    assert total == 2
    assert len(list(out_dir.iterdir())) == 2


def test_main_dispatches_xls(tmp_path, out_dir):
    from extract_images import main as extract_main
    media = tmp_path / "media"
    media.mkdir()

    xls = media / "product.xls"
    jpeg = minimal_valid_jpeg_bytes()
    xls.write_bytes(b'\x00' * 512 + jpeg + b'\x00' * 128)

    total = extract_main(media, out_dir)
    assert total == 1
    extracted = list(out_dir.iterdir())
    assert len(extracted) == 1
    assert extracted[0].suffix == ".jpg"
