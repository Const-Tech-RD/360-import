"""Tests for save_normalized_image (Streamlit-import re-encode path)."""

from io import BytesIO
from pathlib import Path

from PIL import Image


def test_save_normalized_jpeg_to_jpg(tmp_path: Path):
    from extract_images import save_normalized_image

    buf = BytesIO()
    im = Image.new("RGB", (16, 12), color=(100, 50, 25))
    im.save(buf, format="JPEG", quality=92)
    src = tmp_path / "src.jpg"
    src.write_bytes(buf.getvalue())

    out = tmp_path / "out_dir"
    result = save_normalized_image(src, out, "test_jpeg_norm")
    assert result.suffix == ".jpg"
    assert result.exists()
    with Image.open(result) as im2:
        assert im2.mode == "RGB"


def test_save_normalized_png_opaque_becomes_jpg(tmp_path: Path):
    from extract_images import save_normalized_image

    buf = BytesIO()
    im = Image.new("RGB", (10, 10), color=(0, 200, 0))
    im.save(buf, format="PNG")
    src = tmp_path / "s.png"
    src.write_bytes(buf.getvalue())

    result = save_normalized_image(src, tmp_path / "d", "png_rgb")
    assert result.suffix == ".jpg"


def test_save_normalized_png_with_alpha_keeps_png(tmp_path: Path):
    from extract_images import save_normalized_image

    rgba = Image.new("RGBA", (8, 8), color=(255, 0, 0, 128))
    buf = BytesIO()
    rgba.save(buf, format="PNG")
    src = tmp_path / "rgba.png"
    src.write_bytes(buf.getvalue())

    result = save_normalized_image(src, tmp_path / "d2", "alpha")
    assert result.suffix == ".png"
    with Image.open(result) as im:
        assert im.mode == "RGBA"


def test_save_normalized_unique_collision(tmp_path: Path):
    from extract_images import save_normalized_image

    buf = BytesIO()
    Image.new("RGB", (6, 6), color=(1, 2, 3)).save(buf, format="JPEG")
    src = tmp_path / "a.jpg"
    src.write_bytes(buf.getvalue())

    dest = tmp_path / "collision"
    dest.mkdir()
    (dest / "stem.jpg").touch()
    result = save_normalized_image(src, dest, "stem")
    assert result.name.startswith("stem_")
    assert result.suffix == ".jpg"
