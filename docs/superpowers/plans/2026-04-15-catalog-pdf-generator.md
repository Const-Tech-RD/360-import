# Catalog PDF Generator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-stage Python pipeline that extracts product images from Office documents, fuzzy-matches them to products in a CSV, and renders a branded A4 PDF catalog via Playwright.

**Architecture:** Three independent scripts run in sequence: `extract_images.py` walks the media folder and pulls embedded images out of `.docx`/`.xlsx`/`.xls` files into a flat folder; `match_images.py` fuzzy-matches those filenames against product names and writes an updated CSV; `generate_pdf.py` renders a Jinja2 HTML template and prints it to PDF with Playwright headless Chromium.

**Tech Stack:** Python 3.11+, `python-docx`, `openpyxl`, `rapidfuzz`, `jinja2`, `playwright` (Python), `pytest`

---

## File Structure

```
360-import/
├── extract_images.py          # Stage 1: extract images from Office docs
├── match_images.py            # Stage 2: fuzzy-match images → products
├── catalog_template.html      # Jinja2 HTML template for the catalog
├── generate_pdf.py            # Stage 3: render HTML → PDF via Playwright
├── requirements.txt           # Python dependencies
├── extracted_images/          # Created by extract_images.py (gitignored)
├── productos_normalizado.csv  # Already exists (from brainstorming)
├── productos_con_imagenes.csv # Created by match_images.py
├── catalogo_360import.pdf     # Created by generate_pdf.py
└── tests/
    ├── test_extract_images.py
    ├── test_match_images.py
    └── test_generate_pdf.py
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `tests/` directory

- [ ] **Step 1: Create requirements.txt**

```
python-docx>=1.1.2
openpyxl>=3.1.2
rapidfuzz>=3.6.1
jinja2>=3.1.3
playwright>=1.43.0
pytest>=8.1.1
```

- [ ] **Step 2: Install dependencies and Playwright browser**

```bash
pip install -r requirements.txt
playwright install chromium
```

Expected output ends with: `chromium ... downloaded`

- [ ] **Step 3: Verify Playwright works**

```bash
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.set_content('<h1>OK</h1>')
    b.close()
print('Playwright OK')
"
```

Expected: `Playwright OK`

- [ ] **Step 4: Create tests directory**

```bash
mkdir tests
touch tests/__init__.py
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/__init__.py
git commit -m "chore: add requirements and test directory"
```

---

## Task 2: Image Extraction — ZIP-based Formats (.docx, .xlsx)

Both `.docx` and `.xlsx` are ZIP archives. Images live at `word/media/` and `xl/media/` respectively.

**Files:**
- Create: `extract_images.py`
- Create: `tests/test_extract_images.py`

- [ ] **Step 1: Write failing tests for `extract_from_zip`**

Create `tests/test_extract_images.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_extract_images.py -v -k "zip"
```

Expected: `ModuleNotFoundError: No module named 'extract_images'`

- [ ] **Step 3: Implement `extract_from_zip` in `extract_images.py`**

Create `extract_images.py`:

```python
import shutil
import zipfile
from pathlib import Path

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}


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
                idx = len(extracted)
                out_name = f"{src_path.stem}_{idx}{ext}"
                out_path = out_dir / out_name
                out_path.write_bytes(z.read(name))
                extracted.append(out_path)
    except Exception as e:
        print(f"  Warning: could not read {src_path.name}: {e}")
    return extracted
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_extract_images.py -v -k "zip"
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add extract_images.py tests/test_extract_images.py
git commit -m "feat: extract images from zip-based office formats (docx, xlsx)"
```

---

## Task 3: Image Extraction — Legacy .xls (Binary Scanning)

Legacy `.xls` files are OLE2 binaries. We extract images by scanning raw bytes for JPEG and PNG magic bytes — no external library needed.

**Files:**
- Modify: `extract_images.py`
- Modify: `tests/test_extract_images.py`

- [ ] **Step 1: Write failing tests for `extract_from_xls`**

Append to `tests/test_extract_images.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_extract_images.py -v -k "xls"
```

Expected: `ImportError` or `AttributeError: module 'extract_images' has no attribute 'extract_from_xls'`

- [ ] **Step 3: Implement `extract_from_xls` in `extract_images.py`**

Append to `extract_images.py` (after `extract_from_zip`):

```python
MIN_IMAGE_BYTES = 500  # skip tiny blobs that are likely thumbnails or artifacts


def extract_from_xls(src_path: Path, out_dir: Path) -> list[Path]:
    """Extract images from a legacy .xls by scanning raw bytes for image magic."""
    data = src_path.read_bytes()
    extracted = []
    idx = 0

    # ── JPEG: FF D8 FF … FF D9 ──────────────────────────────────────────────
    JPEG_START = b'\xff\xd8\xff'
    JPEG_END   = b'\xff\xd9'
    pos = 0
    while True:
        start = data.find(JPEG_START, pos)
        if start == -1:
            break
        end = data.find(JPEG_END, start + 3)
        if end == -1:
            break
        end += 2
        blob = data[start:end]
        if len(blob) >= MIN_IMAGE_BYTES:
            out_path = out_dir / f"{src_path.stem}_{idx}.jpg"
            out_path.write_bytes(blob)
            extracted.append(out_path)
            idx += 1
        pos = end

    # ── PNG: 89 50 4E 47 … 49 45 4E 44 AE 42 60 82 ─────────────────────────
    PNG_START = b'\x89PNG\r\n\x1a\n'
    PNG_END   = b'IEND\xaeB`\x82'
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
        if len(blob) >= MIN_IMAGE_BYTES:
            out_path = out_dir / f"{src_path.stem}_{idx}.png"
            out_path.write_bytes(blob)
            extracted.append(out_path)
            idx += 1
        pos = end

    return extracted
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_extract_images.py -v -k "xls"
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add extract_images.py tests/test_extract_images.py
git commit -m "feat: extract images from legacy .xls via binary scanning"
```

---

## Task 4: Extraction Orchestrator

Walk the media folder tree, dispatch to the right extractor per file type, and copy loose images.

**Files:**
- Modify: `extract_images.py`
- Modify: `tests/test_extract_images.py`

- [ ] **Step 1: Write failing tests for `copy_loose_image` and `main`**

Append to `tests/test_extract_images.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_extract_images.py -v -k "copy or orchestrator or main"
```

Expected: `ImportError` for `copy_loose_image` and `main`

- [ ] **Step 3: Implement `copy_loose_image` and `main` in `extract_images.py`**

Append to `extract_images.py`:

```python
def copy_loose_image(src_path: Path, out_dir: Path) -> Path | None:
    """Copy a standalone image file into out_dir, avoiding name collisions."""
    dest = out_dir / src_path.name
    if dest.exists():
        dest = out_dir / f"{src_path.parent.name}_{src_path.name}"
    shutil.copy2(src_path, dest)
    return dest


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
        elif ext in ('.jpg', '.jpeg', '.png'):
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
```

- [ ] **Step 4: Run all extraction tests**

```bash
pytest tests/test_extract_images.py -v
```

Expected: all tests pass

- [ ] **Step 5: Run extraction against the real media folder**

```bash
python extract_images.py
```

Expected: output listing extracted images per file, ending with `Total: N image(s) extracted to extracted_images/`

- [ ] **Step 6: Add `extracted_images/` to .gitignore**

```bash
echo "extracted_images/" >> .gitignore
echo "catalogo_360import.pdf" >> .gitignore
echo "productos_con_imagenes.csv" >> .gitignore
```

- [ ] **Step 7: Commit**

```bash
git add extract_images.py tests/test_extract_images.py .gitignore
git commit -m "feat: extraction orchestrator — walks media tree, dispatches by file type"
```

---

## Task 5: Image–Product Fuzzy Matching

Fuzzy-match image filenames against `Producto_Base` in the CSV and write `productos_con_imagenes.csv`.

**Files:**
- Create: `match_images.py`
- Create: `tests/test_match_images.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_match_images.py`:

```python
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


# ── match_images (integration) ──────────────────────────────────────────────

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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_match_images.py -v
```

Expected: `ModuleNotFoundError: No module named 'match_images'`

- [ ] **Step 3: Implement `match_images.py`**

Create `match_images.py`:

```python
import csv
import sys
from pathlib import Path

from rapidfuzz import fuzz, process

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}


def build_image_index(images_dir: Path) -> dict[str, Path]:
    """Return {stem: path} for all image files in images_dir."""
    return {
        p.stem: p
        for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    }


def find_best_match(product_name: str, candidate_names: list[str], threshold: int) -> str | None:
    """Return the best-matching candidate name, or None if below threshold."""
    if not candidate_names:
        return None
    result = process.extractOne(product_name, candidate_names, scorer=fuzz.token_sort_ratio)
    if result and result[1] >= threshold:
        return result[0]
    return None


def load_csv(path: Path) -> list[dict]:
    with open(path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def match_products(
    csv_in: Path,
    images_dir: Path,
    csv_out: Path,
    threshold: int = 60,
) -> tuple[int, int]:
    """
    Match products in csv_in to images in images_dir.
    Writes csv_out with Imagenes column updated.
    Returns (matched_count, unmatched_count).
    """
    index = build_image_index(images_dir)
    candidate_names = list(index.keys())
    rows = load_csv(csv_in)
    matched = unmatched = 0

    for row in rows:
        base = row.get('Producto_Base', row.get('Producto', ''))
        best = find_best_match(base, candidate_names, threshold)
        if best:
            row['Imagenes'] = str(index[best])
            matched += 1
        else:
            row['Imagenes'] = 'FALSE'
            unmatched += 1

    write_csv(rows, csv_out)
    return matched, unmatched


if __name__ == '__main__':
    csv_in    = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('productos_normalizado.csv')
    images_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('extracted_images')
    csv_out   = Path(sys.argv[3]) if len(sys.argv) > 3 else Path('productos_con_imagenes.csv')

    matched, unmatched = match_products(csv_in, images_dir, csv_out)
    total = matched + unmatched
    print(f"Matched:   {matched}/{total}")
    print(f"Unmatched: {unmatched}/{total}")
    print(f"Output:    {csv_out}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_match_images.py -v
```

Expected: all tests pass

- [ ] **Step 5: Run matching against real data**

```bash
python match_images.py
```

Expected: `Matched: N/170`, `Unmatched: M/170`, `Output: productos_con_imagenes.csv`

- [ ] **Step 6: Commit**

```bash
git add match_images.py tests/test_match_images.py
git commit -m "feat: fuzzy image-product matching with rapidfuzz"
```

---

## Task 6: HTML Catalog Template

The Jinja2 template that produces the full A4 catalog HTML. Each `.page` div becomes one PDF page.

**Files:**
- Create: `catalog_template.html`

- [ ] **Step 1: Create the Jinja2 template**

Create `catalog_template.html`:

```html
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@700;900&family=Raleway:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    /* ── Reset & base ───────────────────────────────────────────────────── */
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Raleway', sans-serif; background: #f9f7f4; }

    /* ── Page ───────────────────────────────────────────────────────────── */
    .page {
      width: 182mm;          /* A4 210mm – 14mm × 2 margins */
      min-height: 273mm;     /* A4 297mm – 12mm × 2 margins */
      display: flex;
      flex-direction: column;
      page-break-after: always;
      background: #f9f7f4;
    }

    /* ── Page header ────────────────────────────────────────────────────── */
    .page-header {
      background: #f0ece4;
      padding: 10px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 2px solid #c99229;
      flex-shrink: 0;
    }
    .brand { font-family: 'Cinzel', serif; color: #32523a; font-size: 16px; font-weight: 900; letter-spacing: 2px; }
    .tagline { color: #897670; font-size: 8px; margin-top: 1px; }
    .catalog-label { font-family: 'Cinzel', serif; color: #c99229; font-size: 9px; font-weight: 700; letter-spacing: 1px; text-align: right; }
    .catalog-sub { color: #897670; font-size: 7px; text-align: right; margin-top: 2px; }

    /* ── Category banner ────────────────────────────────────────────────── */
    .cat-banner {
      background: #ede8de;
      padding: 6px 16px;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid #ddd5c5;
      border-top: 1px solid #ddd5c5;
      flex-shrink: 0;
    }
    .cat-bar { width: 3px; height: 14px; background: #c99229; border-radius: 2px; flex-shrink: 0; }
    .cat-name { font-family: 'Cinzel', serif; font-size: 8.5px; font-weight: 700; color: #32523a; text-transform: uppercase; letter-spacing: 1.5px; }
    .cat-divider { flex: 1; height: 1px; background: #c5b9af; margin-left: 4px; }
    .cat-supplier { font-size: 7px; color: #897670; }

    /* ── Product row ────────────────────────────────────────────────────── */
    .product-row {
      display: flex;
      border-bottom: 1px solid #e8e2d8;
      background: #f9f7f4;
      flex: 1;
    }
    .product-row.alt { background: #f3efe8; }

    .product-img {
      width: 110px;
      background: #ede8de;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      border-right: 2px solid #e8dfc8;
      flex-direction: column;
      gap: 4px;
      padding: 8px 0;
    }
    .product-img img {
      max-width: 90px;
      max-height: 80px;
      object-fit: contain;
    }
    .placeholder {
      width: 48px; height: 48px;
      border-radius: 50%;
      background: #f0ece4;
      border: 2px solid #c99229;
      display: flex; align-items: center; justify-content: center;
      font-family: 'Cinzel', serif;
      font-size: 13px;
      font-weight: 700;
      color: #c99229;
    }
    .img-label { font-size: 6px; color: #b5a898; }

    .product-info { flex: 1; padding: 8px 14px; display: flex; flex-direction: column; justify-content: center; }
    .product-name {
      font-family: 'Cinzel', serif;
      font-size: 9px;
      font-weight: 700;
      color: #261c17;
      border-bottom: 1px solid #e2d8c5;
      padding-bottom: 4px;
      margin-bottom: 6px;
    }
    .product-body { display: flex; gap: 12px; }
    .product-desc { flex: 1.4; }
    .product-desc p { color: #6b5a52; font-size: 7px; line-height: 1.6; }
    .product-tags { display: flex; gap: 4px; margin-top: 5px; flex-wrap: wrap; }
    .tag-supplier {
      background: #32523a; color: #f5f3ef;
      font-size: 6px; padding: 1px 5px; border-radius: 2px; font-weight: 500;
    }
    .tag-cat {
      background: transparent; color: #32523a;
      font-size: 6px; padding: 1px 5px; border-radius: 2px;
      border: 1px solid #32523a;
    }
    .product-specs { flex: 1; }
    .specs-table { width: 100%; border-collapse: collapse; font-size: 7px; }
    .specs-table thead tr { background: #32523a; }
    .specs-table thead th { padding: 3px 5px; color: #f5f3ef; text-align: left; font-weight: 500; }
    .specs-table tbody tr { background: #edeae2; }
    .specs-table tbody td { padding: 3px 5px; color: #261c17; }

    /* ── Page footer ────────────────────────────────────────────────────── */
    .page-footer {
      background: #f0ece4;
      border-top: 1px solid #ddd5c5;
      padding: 4px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-shrink: 0;
    }
    .footer-text { color: #b5a898; font-size: 6px; }
    .page-num { color: #c99229; font-size: 7px; font-family: 'Cinzel', serif; }
  </style>
</head>
<body>

{% for page_items in pages %}
<div class="page">

  <!-- Header -->
  <div class="page-header">
    <div>
      <div class="brand">360 IMPORT</div>
      <div class="tagline">Importadora de Productos Gourmet Italianos</div>
    </div>
    <div>
      <div class="catalog-label">CATÁLOGO 2026</div>
      <div class="catalog-sub">República Dominicana</div>
    </div>
  </div>

  <!-- Products -->
  {% for item in page_items %}

    {% if item.show_banner %}
    <div class="cat-banner">
      <div class="cat-bar"></div>
      <span class="cat-name">{{ item.Categoria }}</span>
      <div class="cat-divider"></div>
      <span class="cat-supplier">{{ item.Proveedor }}</span>
    </div>
    {% endif %}

    <div class="product-row {% if loop.index is even %}alt{% endif %}">
      <div class="product-img">
        {% if item.image_data %}
          <img src="{{ item.image_data }}" alt="{{ item.Producto_Base }}">
        {% else %}
          <div class="placeholder">{{ item.initials }}</div>
          <div class="img-label">Sin imagen</div>
        {% endif %}
      </div>
      <div class="product-info">
        <div class="product-name">{{ item.Producto }}</div>
        <div class="product-body">
          <div class="product-desc">
            {% if item.Descripción %}
            <p>{{ item.Descripción }}</p>
            {% else %}
            <p style="color:#c5b9af;font-style:italic;">Sin descripción</p>
            {% endif %}
            <div class="product-tags">
              <span class="tag-supplier">{{ item.Proveedor }}</span>
              <span class="tag-cat">{{ item.Categoria }}</span>
            </div>
          </div>
          <div class="product-specs">
            <table class="specs-table">
              <thead><tr><th>Presentación</th><th>Caja</th></tr></thead>
              <tbody>
                <tr>
                  <td>{{ item.Presentacion if item.Presentacion else '—' }}</td>
                  <td>{{ item.Unidades_por_Caja ~ ' un' if item.Unidades_por_Caja else '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

  {% endfor %}

  <!-- Footer -->
  <div class="page-footer">
    <span class="footer-text">360 Import · info@360import.com</span>
    <span class="page-num">Página {{ loop.index }} / {{ total_pages }}</span>
  </div>

</div>
{% endfor %}

</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add catalog_template.html
git commit -m "feat: add Jinja2 catalog HTML template"
```

---

## Task 7: PDF Generation Script

Load the matched CSV, build page data, render HTML, and print to PDF via Playwright.

**Files:**
- Create: `generate_pdf.py`
- Create: `tests/test_generate_pdf.py`

- [ ] **Step 1: Write failing tests for pure functions**

Create `tests/test_generate_pdf.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_generate_pdf.py -v
```

Expected: `ModuleNotFoundError: No module named 'generate_pdf'`

- [ ] **Step 3: Implement `generate_pdf.py`**

Create `generate_pdf.py`:

```python
import asyncio
import base64
import csv
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.async_api import async_playwright


# ── Pure helpers ─────────────────────────────────────────────────────────────

def get_initials(name: str) -> str:
    """Return up to 3 uppercase initials from words that start with a letter."""
    words = name.split()
    initials = [w[0].upper() for w in words if w and w[0].isalpha()]
    return ''.join(initials[:3])


def encode_image(image_path: str) -> str | None:
    """Return a base64 data URI for the image, or None if missing/FALSE."""
    if not image_path or image_path == 'FALSE':
        return None
    p = Path(image_path)
    if not p.exists():
        return None
    suffix = p.suffix.lower().lstrip('.')
    if suffix == 'jpg':
        suffix = 'jpeg'
    data = base64.b64encode(p.read_bytes()).decode()
    return f"data:image/{suffix};base64,{data}"


def build_pages(products: list[dict], page_size: int = 3) -> list[list[dict]]:
    """
    Sort products by (Categoria, Producto_Base), annotate each with
    show_banner=True on category change, then chunk into pages of page_size.
    """
    sorted_prods = sorted(
        products,
        key=lambda p: (p.get('Categoria', '').lower(), p.get('Producto_Base', '').lower())
    )
    last_cat = None
    annotated = []
    for p in sorted_prods:
        item = dict(p)
        cat = item.get('Categoria', '')
        item['show_banner'] = (cat != last_cat)
        item['image_data']  = encode_image(item.get('Imagenes', 'FALSE'))
        item['initials']    = get_initials(item.get('Producto_Base', item.get('Producto', '')))
        last_cat = cat
        annotated.append(item)

    return [annotated[i:i + page_size] for i in range(0, len(annotated), page_size)]


def render_html(pages: list[list[dict]], template_path: Path) -> str:
    """Render the Jinja2 template with page data."""
    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    return template.render(pages=pages, total_pages=len(pages))


# ── Playwright PDF ────────────────────────────────────────────────────────────

async def html_to_pdf(html: str, output_path: Path) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page    = await browser.new_page()
        await page.set_content(html)
        await page.wait_for_load_state('networkidle')
        await page.pdf(
            path=str(output_path),
            format='A4',
            print_background=True,
            margin={'top': '12mm', 'bottom': '12mm', 'left': '14mm', 'right': '14mm'},
        )
        await browser.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def load_products(csv_path: Path) -> list[dict]:
    with open(csv_path, encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main(
    csv_path: Path         = Path('productos_con_imagenes.csv'),
    template_path: Path    = Path('catalog_template.html'),
    output_path: Path      = Path('catalogo_360import.pdf'),
) -> None:
    products = load_products(csv_path)
    print(f"Loaded {len(products)} products")

    pages = build_pages(products)
    print(f"Built {len(pages)} page(s)")

    html = render_html(pages, template_path)
    print(f"HTML rendered ({len(html):,} chars)")

    asyncio.run(html_to_pdf(html, output_path))
    print(f"PDF saved → {output_path}")


if __name__ == '__main__':
    main(
        csv_path      = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('productos_con_imagenes.csv'),
        template_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('catalog_template.html'),
        output_path   = Path(sys.argv[3]) if len(sys.argv) > 3 else Path('catalogo_360import.pdf'),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_generate_pdf.py -v
```

Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add generate_pdf.py tests/test_generate_pdf.py
git commit -m "feat: PDF generation — build_pages, render_html, Playwright pdf export"
```

---

## Task 8: End-to-End Smoke Test

Run the full pipeline and verify the output PDF is produced and non-empty.

**Files:** none new

- [ ] **Step 1: Run all unit tests**

```bash
pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 2: Run Stage 1 — image extraction**

```bash
python extract_images.py
```

Expected: `Total: N image(s) extracted to extracted_images/`
Verify: `ls extracted_images/ | wc -l` shows N > 0

- [ ] **Step 3: Run Stage 2 — image matching**

```bash
python match_images.py
```

Expected output like:
```
Matched:   42/170
Unmatched: 128/170
Output:    productos_con_imagenes.csv
```

- [ ] **Step 4: Run Stage 3 — PDF generation**

```bash
python generate_pdf.py
```

Expected:
```
Loaded 170 products
Built 57 page(s)
HTML rendered (N chars)
PDF saved → catalogo_360import.pdf
```

- [ ] **Step 5: Verify the PDF**

```bash
python -c "
from pathlib import Path
size = Path('catalogo_360import.pdf').stat().st_size
assert size > 10_000, f'PDF too small: {size} bytes'
print(f'PDF OK — {size:,} bytes')
"
```

Expected: `PDF OK — N bytes` (should be several hundred KB at minimum)

- [ ] **Step 6: Open and review the PDF**

```bash
start catalogo_360import.pdf
```

Check: category banners appear, placeholder circles show for unmatched products, matched products show their images, fonts render correctly.

- [ ] **Step 7: Final commit**

```bash
git add .
git commit -m "feat: complete 3-stage catalog PDF pipeline"
```

---

## Running the Full Pipeline

```bash
pip install -r requirements.txt
playwright install chromium

python extract_images.py
python match_images.py
python generate_pdf.py
```

Output: `catalogo_360import.pdf`
