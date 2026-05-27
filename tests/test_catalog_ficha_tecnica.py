from pathlib import Path

from catalog_ficha_tecnica import (
    DEFAULT_FICHA_PATH,
    apply_ficha_tecnica,
    load_ficha_map,
)


def test_load_ficha_map_has_seven_entries():
    m = load_ficha_map(DEFAULT_FICHA_PATH)
    assert len(m) == 7


def test_apply_ficha_tecnica_exact_match_fb_chef():
    rows = [{"Producto": "FB Aceite Extra Virgen chef 5 lit x 2"}]
    m = load_ficha_map(DEFAULT_FICHA_PATH)
    out, report = apply_ficha_tecnica(rows, m)
    assert report.applied == 1
    assert "drive.google.com" in out[0]["Ficha_Tecnica_URL"]
    assert "1vw-E9PifRx39whGSc_7huy47WM2Vb6Gl" in out[0]["Ficha_Tecnica_URL"]


def test_apply_ficha_no_match_leaves_row_unchanged():
    rows = [{"Producto": "Producto Sin Ficha"}]
    out, report = apply_ficha_tecnica(rows, load_ficha_map(DEFAULT_FICHA_PATH))
    assert report.applied == 0
    assert "Ficha_Tecnica_URL" not in out[0]


def test_render_html_includes_ficha_button():
    from generate_pdf import build_pages, render_html

    product = {
        "Producto": "FB Aceite Extra Virgen chef 5 lit x 2",
        "Producto_Base": "FB Aceite Extra Virgen chef",
        "Presentacion": "",
        "Unidades_por_Caja": "2",
        "Descripción": "",
        "Proveedor": "SALOV",
        "Categoria": "aceites",
        "Imagenes": "FALSE",
    }
    rows, _ = apply_ficha_tecnica([product], load_ficha_map(DEFAULT_FICHA_PATH))
    pages = build_pages(rows)
    html = render_html(pages, Path("catalog_template.html"))
    assert "Ver Ficha Técnica" in html
    assert "drive.google.com" in html
