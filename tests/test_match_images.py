import csv
from pathlib import Path
import pytest


# ── find_best_match ─────────────────────────────────────────────────────────

def test_find_best_match_exact():
    from match_images import find_best_match
    names = ["Scotti Riso Arborio", "Bonomi Amaretti", "Di Biase Hongos"]
    assert find_best_match("Scotti Riso Arborio", names, threshold=60) == "Scotti Riso Arborio"


def test_find_best_match_partial():
    from match_images import find_best_match
    names = ["Arborio rice 1kg", "Basmati rice 500g"]
    # "Scotti Riso Arborio" should match "Arborio rice 1kg" better than "Basmati"
    result = find_best_match("Scotti Riso Arborio", names, threshold=30)
    assert result == "Arborio rice 1kg"


def test_find_best_match_below_threshold_returns_none():
    from match_images import find_best_match
    names = ["completely unrelated text"]
    assert find_best_match("Scotti Riso Arborio", names, threshold=60) is None


def test_find_best_match_empty_candidates_returns_none():
    from match_images import find_best_match
    assert find_best_match("Anything", [], threshold=60) is None


# ── build_image_index ───────────────────────────────────────────────────────

def test_build_image_index_maps_stem_to_path(tmp_path):
    from match_images import build_image_index
    (tmp_path / "Arborio rice 1kg.jpg").write_bytes(b"")
    (tmp_path / "Basmati rice 500g.png").write_bytes(b"")
    index = build_image_index(tmp_path)
    assert "Arborio rice 1kg" in index
    assert index["Arborio rice 1kg"].suffix == ".jpg"


def test_build_image_index_empty_dir_returns_empty(tmp_path):
    from match_images import build_image_index
    assert build_image_index(tmp_path) == {}


# ── match_products (integration) ──────────────────────────────────────────────

def make_csv(path: Path, rows: list[dict]):
    fieldnames = list(rows[0].keys())
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def test_match_updates_imagenes_when_matched(tmp_path):
    from match_images import match_products
    csv_in  = tmp_path / "products.csv"
    csv_out = tmp_path / "matched.csv"
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "Arborio rice 1kg.jpg").write_bytes(b"")

    make_csv(csv_in, [
        {'Producto': 'Scotti Riso Arborio 1kg x10', 'Producto_Base': 'Scotti Riso Arborio',
         'Presentacion': '1 kg', 'Unidades_por_Caja': '10',
         'Descripción': '', 'Proveedor': 'RISO SCOTTI', 'Categoria': 'arroces', 'Imagenes': 'FALSE'},
    ])

    matched, unmatched = match_products(csv_in, img_dir, csv_out, threshold=30)
    rows = read_csv(csv_out)
    assert matched == 1
    assert unmatched == 0
    assert rows[0]['Imagenes'] != 'FALSE'
    assert 'Arborio' in rows[0]['Imagenes']


def test_match_leaves_false_when_no_match(tmp_path):
    from match_images import match_products
    csv_in  = tmp_path / "products.csv"
    csv_out = tmp_path / "matched.csv"
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    (img_dir / "unrelated_photo.jpg").write_bytes(b"")

    make_csv(csv_in, [
        {'Producto': 'Scotti Riso Arborio 1kg', 'Producto_Base': 'Scotti Riso Arborio',
         'Presentacion': '1 kg', 'Unidades_por_Caja': '10',
         'Descripción': '', 'Proveedor': 'RISO SCOTTI', 'Categoria': 'arroces', 'Imagenes': 'FALSE'},
    ])

    matched, unmatched = match_products(csv_in, img_dir, csv_out, threshold=60)
    rows = read_csv(csv_out)
    assert matched == 0
    assert unmatched == 1
    assert rows[0]['Imagenes'] == 'FALSE'
