import base64
from pathlib import Path
import pytest


# ── get_initials ─────────────────────────────────────────────────────────────

def test_get_initials_three_words():
    from generate_pdf import get_initials
    assert get_initials("Scotti Riso Arborio") == "SRA"


def test_get_initials_two_words():
    from generate_pdf import get_initials
    assert get_initials("Di Biase") == "DB"


def test_get_initials_one_word():
    from generate_pdf import get_initials
    assert get_initials("Bonomi") == "B"


def test_get_initials_caps_at_three():
    from generate_pdf import get_initials
    assert get_initials("Scotti Riso Arborio Extra") == "SRA"


def test_get_initials_skips_non_alpha_starts():
    from generate_pdf import get_initials
    # "100%" starts with digit — skip it
    assert get_initials("100% Arborio") == "A"


# ── encode_image ─────────────────────────────────────────────────────────────

def test_encode_image_returns_none_for_false():
    from generate_pdf import encode_image
    assert encode_image('FALSE') is None


def test_encode_image_returns_none_for_empty_string():
    from generate_pdf import encode_image
    assert encode_image('') is None


def test_encode_image_returns_none_for_missing_file():
    from generate_pdf import encode_image
    assert encode_image('/no/such/file.jpg') is None


def test_encode_image_returns_jpeg_data_uri(tmp_path):
    from generate_pdf import encode_image
    img = tmp_path / "test.jpg"
    img.write_bytes(b'\xff\xd8\xff' + b'\x00' * 20 + b'\xff\xd9')
    result = encode_image(str(img))
    assert result is not None
    assert result.startswith('data:image/jpeg;base64,')


def test_encode_image_returns_png_data_uri(tmp_path):
    from generate_pdf import encode_image
    img = tmp_path / "test.png"
    img.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20)
    result = encode_image(str(img))
    assert result is not None
    assert result.startswith('data:image/png;base64,')


# ── build_pages ───────────────────────────────────────────────────────────────

def make_product(name: str, cat: str) -> dict:
    return {'Producto': name, 'Producto_Base': name, 'Presentacion': '',
            'Unidades_por_Caja': '', 'Descripción': '', 'Proveedor': 'X',
            'Categoria': cat, 'Imagenes': 'FALSE'}


def test_build_pages_groups_into_threes():
    from generate_pdf import build_pages
    products = [make_product(f"P{i}", "A") for i in range(7)]
    pages = build_pages(products, page_size=3)
    assert len(pages) == 3
    assert len(pages[0]) == 3
    assert len(pages[1]) == 3
    assert len(pages[2]) == 1


def test_build_pages_sorts_by_category_then_name():
    from generate_pdf import build_pages
    products = [
        make_product("Zebra", "Arroces"),
        make_product("Alpha", "Galletas"),
        make_product("Beta",  "Arroces"),
    ]
    pages = build_pages(products, page_size=3)
    flat = pages[0]
    assert flat[0]['Producto_Base'] == "Beta"
    assert flat[1]['Producto_Base'] == "Zebra"
    assert flat[2]['Producto_Base'] == "Alpha"


def test_build_pages_marks_first_product_in_category_with_banner():
    from generate_pdf import build_pages
    products = [
        make_product("A1", "Arroces"),
        make_product("A2", "Arroces"),
        make_product("B1", "Galletas"),
    ]
    pages = build_pages(products, page_size=3)
    flat = pages[0]
    assert flat[0]['show_banner'] is True   # first category
    assert flat[1]['show_banner'] is False  # same category
    assert flat[2]['show_banner'] is True   # new category


# ── render_html ───────────────────────────────────────────────────────────────

def test_render_html_contains_product_name(tmp_path):
    from generate_pdf import build_pages, render_html
    products = [make_product("Scotti Riso Arborio", "Arroces")]
    pages = build_pages(products)
    html = render_html(pages, Path("catalog_template.html"))
    assert "Scotti Riso Arborio" in html
    assert "360 IMPORT" in html
    assert "Página 1 / 1" in html
