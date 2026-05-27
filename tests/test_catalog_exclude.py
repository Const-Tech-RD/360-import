from catalog_exclude import is_product_excluded_from_catalog, filter_catalog_rows_for_export

EXCLUDED = "GR RIGATONI TRAFILADO AL BRONZO 500 GR X 24"
EXCLUDED_PECORINO = "LATTERIA SORESINA QUESO PECORINO ROMANO 250 GR X 15"


def test_rigatoni_24_excluded():
    assert is_product_excluded_from_catalog({"Producto": EXCLUDED})


def test_pecorino_excluded():
    assert is_product_excluded_from_catalog({"Producto": EXCLUDED_PECORINO})


def test_strips_whitespace_for_match():
    assert is_product_excluded_from_catalog({"Producto": f"  {EXCLUDED}  "})
    assert not is_product_excluded_from_catalog({"Producto": EXCLUDED + "X"})


def test_filter_keeps_other_rows():
    rows = [
        {"Producto": EXCLUDED},
        {"Producto": "Other"},
    ]
    assert filter_catalog_rows_for_export(rows) == [{"Producto": "Other"}]
