from pathlib import Path

from catalog_descriptions import (
    DEFAULT_DESCRIPTIONS_PATH,
    apply_descriptions,
    load_description_map,
)


def test_load_description_map_has_entries():
    m = load_description_map(DEFAULT_DESCRIPTIONS_PATH)
    assert len(m) >= 20
    assert "el arroz integral italiano" in m[_normalize_key("Scotti ARROZ VENERE NEGRO 1KG X 10")].lower()


def _normalize_key(name: str) -> str:
    return name.strip().casefold()


def test_apply_descriptions_exact_match():
    rows = [
        {
            "Producto": "Scotti ARROZ VENERE NEGRO 1KG X 10",
            "Descripción": "",
        }
    ]
    desc_map = {_normalize_key("Scotti ARROZ VENERE NEGRO 1KG X 10"): "Texto de prueba."}
    out, report = apply_descriptions(rows, desc_map)
    assert out[0]["Descripción"] == "Texto de prueba."
    assert report.applied == 1


def test_apply_descriptions_alias_gemignani():
    rows = [{"Producto": "Gemignani aceite de trufas 250 gr x 6", "Descripción": ""}]
    m = load_description_map(DEFAULT_DESCRIPTIONS_PATH)
    out, report = apply_descriptions(rows, m)
    assert "trufa blanca" in out[0]["Descripción"].lower()
    assert report.applied == 1


def test_apply_descriptions_alias_torrente():
    rows = [{"Producto": "TOMATES PELADO LA TORRENTE", "Descripción": ""}]
    m = load_description_map(DEFAULT_DESCRIPTIONS_PATH)
    out, report = apply_descriptions(rows, m)
    assert "La Torrente" in out[0]["Descripción"]
    assert report.applied == 1


def test_empty_sidecar_does_not_overwrite_existing():
    rows = [{"Producto": "Foo", "Descripción": "Existing text"}]
    out, report = apply_descriptions(rows, {})
    assert out[0]["Descripción"] == "Existing text"
    assert report.applied == 0


def test_unmatched_key_in_report(tmp_path: Path):
    tsv = tmp_path / "desc.tsv"
    tsv.write_text(
        "Producto\tDescripción\n"
        "Producto Inexistente XYZ\tSolo en sidecar.\n",
        encoding="utf-8",
    )
    rows = [{"Producto": "Otro Producto", "Descripción": ""}]
    m = load_description_map(tsv)
    _, report = apply_descriptions(rows, m)
    assert report.applied == 0
    assert len(report.unmatched_keys) == 1
