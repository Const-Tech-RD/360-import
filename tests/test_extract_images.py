import zipfile
from pathlib import Path
import pytest


# ── helpers ────────────────────────────────────────────────────────────────

TINY_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'\x00' * 200 + bytes([0xFF, 0xD9])
TINY_PNG  = b'\x89PNG\r\n\x1a\n' + b'\x00' * 200 + b'IEND\xaeB`\x82'


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
    jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'\x42' * 2000 + bytes([0xFF, 0xD9])
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
    # Write a fake .xls with an embedded JPEG large enough to pass MIN_IMAGE_BYTES
    jpeg = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b'\x42' * 2000 + bytes([0xFF, 0xD9])
    xls.write_bytes(b'\x00' * 512 + jpeg + b'\x00' * 128)

    total = extract_main(media, out_dir)
    assert total == 1
    extracted = list(out_dir.iterdir())
    assert len(extracted) == 1
    assert extracted[0].suffix == ".jpg"
