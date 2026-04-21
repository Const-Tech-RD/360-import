# 360 Import — Product Catalog PDF Generator

**Date:** 2026-04-15  
**Status:** Approved

---

## Overview

A Python pipeline that reads a normalized product CSV, extracts embedded images from Office documents, matches images to products by name, and generates a branded A4 PDF catalog using Playwright.

---

## Input Data

- **`productos_normalizado.csv`** — already generated. Columns: `Producto`, `Producto_Base`, `Presentacion`, `Unidades_por_Caja`, `Descripción`, `Proveedor`, `Categoria`, `Imagenes`
- **`MEDIA-20260415T015452Z-3-001/MEDIA/fotos pagina web/`** — nested folder tree containing:
  - `.xls` / `.xlsx` files with embedded product images
  - `.docx` files with embedded product images
  - A few loose `.jpg` / `.png` files

---

## Pipeline — 3 Stages

### Stage 1: Image Extraction (`extract_images.py`)

- Walk the entire media folder tree recursively
- For each `.docx`: use `python-docx` to extract all embedded images from `document.inline_shapes` and `document.part.rels`
- For each `.xls` / `.xlsx`: use `openpyxl` (for `.xlsx`) and `xlrd` + raw OLE extraction (for `.xls`) to pull embedded images from sheet drawing parts
- For loose `.jpg` / `.png`: copy as-is
- Save all extracted images to a flat `extracted_images/` folder at the project root
- Filename convention: `<source_doc_stem>_<index>.<ext>` (e.g. `Arborio rice 1kg_0.jpg`)
- Log a summary: how many images extracted per file, any failures

### Stage 2: Image Matching (`match_images.py`)

- Load `productos_normalizado.csv`
- Build a list of all files in `extracted_images/`
- For each product (by `Producto_Base`), use `rapidfuzz.process.extractOne` to find the best-matching image filename (token sort ratio, threshold ≥ 60)
- If a match is found: set `Imagenes` to the relative path of the matched image
- If no match: leave `Imagenes` as `FALSE`
- Write result to `productos_con_imagenes.csv`
- Print a match report: matched count, unmatched count, top ambiguous matches for review

### Stage 3: PDF Generation (`generate_pdf.py`)

- Load `productos_con_imagenes.csv`
- Sort products by `Categoria`, then by `Producto_Base`
- Group into pages of 3 products each; inject a category banner whenever the category changes
- For each product, encode the matched image as a base64 data URI (embedded inline in HTML); if `Imagenes` is `FALSE`, render the placeholder
- Render a single HTML string from a Jinja2 template (`catalog_template.html`)
- Use Playwright (Python `playwright` package, async API) to print the HTML to PDF:
  - Format: A4
  - `print_background: True`
  - Margins: 12mm top/bottom, 14mm left/right
- Output: `catalogo_360import.pdf`

---

## PDF Visual Design

### Color Palette (from bella-catalogo-web.lovable.app)

| Token | Hex | Usage |
|---|---|---|
| Cream | `#f9f7f4` | Page background |
| Cream-alt | `#f3efe8` | Alternating product row |
| Tan | `#ede8de` | Image area, category banner bg |
| Border | `#e8e2d8` | Row dividers |
| Olive | `#32523a` | Supplier tags, table header, brand text |
| Gold | `#c99229` | Accent bar, placeholder ring, underline, page number |
| Dark brown | `#261c17` | Product names, body text |
| Muted | `#897670` | Tagline, supplier label in banner |
| Light muted | `#b5a898` | "Sin imagen" label, footer text |

### Typography

- **Cinzel** (Google Fonts) — brand name, product names, category names, page number
- **Raleway** (Google Fonts) — all other text (description, tags, table, footer)
- Fonts embedded via Google Fonts `@import` in the HTML `<head>`

### Page Structure (top to bottom)

1. **Page header** — light cream (`#f0ece4`), gold bottom border  
   - Left: "360 IMPORT" in Cinzel olive, tagline in Raleway muted  
   - Right: "CATÁLOGO 2026" in Cinzel gold, sub-label in Raleway muted  

2. **Category banner** (injected on category change) — tan bg (`#ede8de`), thin border top/bottom  
   - Gold left-accent bar | Category name in Cinzel olive | divider line | Supplier in Raleway muted  

3. **Product rows** (3 per page, alternating cream/cream-alt)  
   - **Image area** (130px wide, gold right border):  
     - If image: `<img>` scaled to fit  
     - If no image: circle with gold border, Cinzel initials from `Producto_Base` (first letter of each word, max 3)  
     - "Sin imagen" label below placeholder in Raleway light muted  
   - **Info area** (flex: 1, 10px 16px padding):  
     - Product name in Cinzel dark brown, gold bottom border  
     - Below: two columns — description (flex 1.4) + specs table (flex 1)  
     - Description: Raleway 8px, line-height 1.65, muted brown  
     - Tags: olive filled (supplier) + olive outlined (category)  
     - Specs table: olive header row, tan body row; columns: Presentación, Caja  

4. **Page footer** — cream bg, tan top border  
   - Left: contact text in Raleway light muted  
   - Right: "Página N" in Cinzel gold  

---

## Output Files

| File | Description |
|---|---|
| `extracted_images/` | All images pulled from Office docs + loose files |
| `productos_con_imagenes.csv` | Normalized CSV with `Imagenes` column filled in |
| `catalog_template.html` | Jinja2 HTML template for the catalog |
| `catalogo_360import.pdf` | Final A4 PDF catalog |

---

## Tech Stack

| Package | Purpose |
|---|---|
| `python-docx` | Extract images from `.docx` files |
| `openpyxl` | Extract images from `.xlsx` files |
| `xlrd` + `olefile` | Extract images from legacy `.xls` files |
| `rapidfuzz` | Fuzzy name matching |
| `jinja2` | HTML template rendering |
| `playwright` (Python) | HTML → PDF via headless Chromium |

---

## Error Handling

- Extraction failures (corrupt files, unsupported formats) are logged and skipped — they don't abort the pipeline
- Match threshold of 60 is conservative; unmatched products get a placeholder, never a wrong image
- If Playwright is not installed, the script prints install instructions and exits cleanly

---

## Running the Pipeline

```bash
pip install python-docx openpyxl xlrd olefile rapidfuzz jinja2 playwright
playwright install chromium

python extract_images.py
python match_images.py
python generate_pdf.py
```
