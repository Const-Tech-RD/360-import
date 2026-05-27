"""
360 Import — Catalog Review App
Streamlit app for manually reviewing and correcting image-product matches.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image
import streamlit as st

from extract_images import (
    extract_from_docx,
    extract_from_xls,
    extract_from_xlsx,
    save_normalized_image,
    should_ignore_extracted_png,
    should_skip_truncated_xls_jpeg,
)
from generate_pdf import normalize_catalog_image_path
from catalog_exclude import is_product_excluded_from_catalog
from catalog_descriptions import apply_descriptions
from catalog_ficha_tecnica import apply_ficha_tecnica, load_ficha_map

# Trust local catalog assets; avoid PIL DecompressionBombWarning on very large PNGs.
Image.MAX_IMAGE_PIXELS = 300_000_000

# ── Config ────────────────────────────────────────────────────────────────────

CSV_SOURCE   = Path("productos_con_imagenes.csv")
CSV_EXPORT   = Path("productos_final.csv")
IMAGES_DIR   = Path("extracted_images")
THUMB_CACHE_DIR = Path("assets/.gallery_thumbs")  # persistent gallery grid thumbnails (gitignored)
USER_UPLOAD_REL = Path("user_upload")  # under IMAGES_DIR
STATE_FILE   = Path("review_state.json")
PDF_OUTPUT   = Path("catalogo_360import.pdf")
TEMPLATE     = Path("catalog_template.html")
IMAGE_EXTS   = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
DESC_EXPAND_THRESHOLD = 200  # longer descriptions collapse into expander on product card
LOGO_PATH    = Path("assets/images/LOGO 360 IMPORT.PNG")

st.set_page_config(
    page_title="360 Import — Catálogo",
    page_icon="🇮🇹",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Responsive layout tweaks (narrow viewports stack columns; softer image sizing).
REVIEW_CSS_MARKDOWN = """<style>
@media (max-width: 768px) {
    .block-container { padding-left: 1rem !important; padding-right: 1rem !important; max-width: 100% !important; }
    section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] {
        flex-direction: column !important;
        gap: 0.75rem !important;
        flex-wrap: nowrap !important;
    }
    section[data-testid="stMain"] div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        width: 100% !important;
        min-width: unset !important;
        flex: 1 1 auto !important;
    }
    aside[data-testid="stSidebar"] div[data-horizontal="true"] div[role="radiogroup"] {
        flex-direction: column !important;
        align-items: flex-start !important;
        gap: 0.35rem !important;
    }
}
section[data-testid="stMain"] img.catalog-thumb {
    height: auto !important;
    max-height: min(140px, 32vh);
    width: 100%;
    max-width: 100%;
}
section[data-testid="stMain"] img.catalog-large {
    height: auto !important;
    max-height: min(320px, 45vh);
    width: 100%;
    max-width: 100%;
}
.product-nav-meta {
    font-size: 0.88rem;
    color: #555;
    margin: 0 0 0.35rem 0;
    line-height: 1.35;
}
</style>
"""
st.markdown(REVIEW_CSS_MARKDOWN, unsafe_allow_html=True)

_OFFICE_IMPORT_TRACE_MAX_LINES = 120


def _office_import_trace_append(msg: str) -> None:
    """Print to stderr (terminal) and accumulate for the sidebar log panel."""
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"{ts} {msg}"
    print(f"[office-import] {line}", flush=True, file=sys.stderr)
    bucket = st.session_state.setdefault("_office_import_trace", [])
    bucket.append(line)
    overflow = len(bucket) - _OFFICE_IMPORT_TRACE_MAX_LINES
    if overflow > 0:
        del bucket[:overflow]


def _office_import_trace_reset() -> None:
    st.session_state["_office_import_trace"] = []


def _office_import_banner_set(title: str, body: str, variant: str = "info") -> None:
    st.session_state["_office_import_banner"] = {
        "title": title,
        "body": body,
        "variant": variant,
    }


def _office_import_banner_clear() -> None:
    st.session_state.pop("_office_import_banner", None)


def render_office_import_banner_sidebar() -> None:
    banner = st.session_state.get("_office_import_banner")
    if banner is None:
        return

    vt = banner.get("variant", "info")
    icon = {"info": "ℹ️", "success": "✅", "warning": "⚠️"}.get(vt, "ℹ️")
    banner_title = banner.get("title") or "Extracción Office"

    with st.expander(f"{icon} {banner_title} — último resultado", expanded=True):
        st.markdown(banner.get("body", ""))
        trace_lines = st.session_state.get("_office_import_trace") or []
        if trace_lines:
            with st.expander("Log técnico (mirror de la consola stderr)", expanded=True):
                st.code("\n".join(trace_lines), language="text")

        if st.button("Ocultar panel", key="office_import_banner_dismiss", help="Sólo oculta este panel lateral"):
            _office_import_banner_clear()
            st.rerun()


def _office_preview_instruction_markdown(n_paths: int) -> str:
    """Texto reproducido en vista previa (diálogo) y en el panel lateral."""
    img_dir = IMAGES_DIR.as_posix()
    return (
        f"Hay **{n_paths} imagen(es)** lista(s) para revisión.\n\n"
        "**Confirmá** para guardarlas saneadas (**JPEG**, o **PNG** si llevan transparencia) "
        f"en la carpeta **`{img_dir}`** dentro del proyecto.\n\n"
        "**Cancelá** para borrar solo el temporal de staging sin modificar ese directorio.\n\n"
        "**Tip:** cuando cierres el diálogo, este texto también queda disponible como "
        "**«último resultado»** en la barra lateral (contraíble), junto con el log técnico."
    )


# ── Data helpers ──────────────────────────────────────────────────────────────

@st.cache_data
def load_products() -> list[dict]:
    with open(CSV_SOURCE, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@st.cache_data(show_spinner=False)
def get_all_images(images_cache_generation: int) -> list[Path]:
    _ = images_cache_generation  # bumps cache version when uploads/extract runs
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    paths = sorted(
        [
            p for p in IMAGES_DIR.rglob("*")
            if p.is_file()
            and p.suffix.lower() in IMAGE_EXTS
            and not should_ignore_extracted_png(p)
            and not should_skip_truncated_xls_jpeg(p)
        ],
        key=lambda p: str(p).lower(),
    )
    return paths


def _session_gallery_paths(gen: int) -> list[Path]:
    """One rglob per session per gallery index generation; avoids calling get_all_images every modal rerun."""
    g = int(gen)
    ss = st.session_state
    if int(ss.get("_gallery_snap_gen", -1)) == g:
        raw = ss.get("_gallery_snap_paths")
        if isinstance(raw, list):
            return [Path(p) for p in raw]
    paths = get_all_images(g)
    ss["_gallery_snap_paths"] = [str(p.resolve()) for p in paths]
    ss["_gallery_snap_gen"] = g
    return list(paths)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


@st.cache_data(show_spinner=False)
def img_b64(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "jpg":
        suffix = "jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/{suffix};base64,{data}"


def img_html(
    path: Path,
    width: str = "100%",
    height: str = "220px",
    css_class: str = "",
) -> str:
    classes = ["catalog-img-root"]
    if css_class:
        classes.append(css_class.strip())
    cls_attr = " ".join(classes)
    style = (
        f"width:{width};max-width:100%;height:{height};"
        "object-fit:contain;border-radius:6px;"
    )
    return f'<img class="{cls_attr}" src="{img_b64(path)}" style="{style}" />'


def _build_thumbnail_raster(path: Path, max_px: int, quality: int) -> tuple[bytes, str]:
    """Resize image to fit max_px square; return (jpeg or png bytes, mime subtype)."""
    im = Image.open(path)
    im.load()
    if im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
    elif im.mode == "P":
        im = im.convert("RGB")
    elif im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGB")

    thumb = im.copy()
    try:
        resample = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover
        resample = Image.LANCZOS  # type: ignore[attr-defined]
    thumb.thumbnail((max_px, max_px), resample)

    buf = BytesIO()
    if thumb.mode == "RGBA":
        thumb.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "png"
    thumb.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), "jpeg"


def _thumb_cache_key_hex(path_resolved: str, mtime_ns: int, size_b: int, max_px: int, quality: int) -> str:
    basis = f"{path_resolved}\0{mtime_ns}\0{size_b}\0{max_px}\0{quality}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _clear_gallery_thumb_disk_cache() -> None:
    """Remove persisted grid thumbnails (e.g. after corruption); directory is recreated on demand."""
    if not THUMB_CACHE_DIR.exists():
        return
    for child in THUMB_CACHE_DIR.iterdir():
        try:
            if child.is_file():
                child.unlink()
        except OSError:
            pass


@st.cache_data(show_spinner=False)
def _gallery_thumb_data_uri_cached(
    path_str: str,
    mtime_ns: int,
    size_b: int,
    max_px: int,
    quality: int,
    thumb_cache_buster: int,
) -> str:
    """Disk-backed thumbnail with Streamlit process cache; buster invalidates after «clear» action."""
    _ = thumb_cache_buster
    key = _thumb_cache_key_hex(path_str, mtime_ns, size_b, max_px, quality)
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    jpg_p = THUMB_CACHE_DIR / f"{key}.jpg"
    png_p = THUMB_CACHE_DIR / f"{key}.png"

    if jpg_p.is_file():
        raw = jpg_p.read_bytes()
        return f"data:image/jpeg;base64,{base64.b64encode(raw).decode()}"
    if png_p.is_file():
        raw = png_p.read_bytes()
        return f"data:image/png;base64,{base64.b64encode(raw).decode()}"

    path = Path(path_str)
    raw_bytes, subtype = _build_thumbnail_raster(path, max_px, quality)
    out = jpg_p if subtype == "jpeg" else png_p
    try:
        out.write_bytes(raw_bytes)
    except OSError:
        pass
    return f"data:image/{subtype};base64,{base64.b64encode(raw_bytes).decode()}"


def gallery_thumb_html(path: Path, height: str = "120px", css_class: str = "catalog-thumb") -> str:
    """HTML img for picker grid using a small cached raster (not full-file base64)."""
    try:
        stt = path.stat()
    except OSError:
        return img_html(path, height=height, css_class=css_class)

    buster = int(st.session_state.get("thumb_cache_buster", 0))
    uri = _gallery_thumb_data_uri_cached(
        str(path.resolve()),
        stt.st_mtime_ns,
        stt.st_size,
        220,
        82,
        buster,
    )
    classes = ["catalog-img-root"]
    if css_class:
        classes.append(css_class.strip())
    cls_attr = " ".join(classes)
    style = (
        f"width:100%;max-width:100%;height:{height};"
        "object-fit:contain;border-radius:6px;"
    )
    return f'<img class="{cls_attr}" src="{uri}" style="{style}" />'


def _gallery_pick_button_id(img_path: Path) -> str:
    """Stable widget key fragment from a path (avoids collisions on duplicate filenames)."""
    try:
        rel = img_path.resolve().relative_to(Path.cwd().resolve())
        basis = rel.as_posix()
    except ValueError:
        basis = str(img_path.resolve())
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def bump_images_generation() -> None:
    st.session_state.pop("_gallery_snap_paths", None)
    st.session_state.pop("_gallery_snap_gen", None)
    st.session_state.images_cache_generation = int(
        st.session_state.get("images_cache_generation", 0)
    ) + 1


def _sanitize_upload_stem(name: str) -> str:
    stem = Path(name).stem
    cleaned = re.sub(r"[^\w\s\-.]", "_", stem, flags=re.UNICODE)
    cleaned = cleaned.strip().replace(" ", "_") or "upload"
    return cleaned[:120]


def _unique_path_in_dir(directory: Path, stem: str, suffix: str) -> Path:
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    n = 1
    while True:
        c = directory / f"{stem}_{n}{suffix}"
        if not c.exists():
            return c
        n += 1


def persist_uploaded_image(filename: str, data: bytes) -> Path | None:
    suf = Path(filename).suffix.lower()
    if suf not in IMAGE_EXTS:
        return None
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dest_dir = IMAGES_DIR / USER_UPLOAD_REL
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_upload_stem(filename)
    out = _unique_path_in_dir(dest_dir, stem, suf)
    out.write_bytes(data)
    return out


def _pil_office_preview_thumbnail(path: Path, max_px: int = 960) -> Image.Image:
    """Decode in Pillow + down-scale so Chromium/Streamlit does not glitch on huge OLE JPEG."""
    pim = Image.open(path)
    pim.load()
    thumb = pim.copy()
    try:
        resample = Image.Resampling.LANCZOS  # Pillow >= 10
    except AttributeError:  # pragma: no cover
        resample = Image.LANCZOS  # type: ignore[attr-defined]
    try:
        thumb.thumbnail((max_px, max_px), resample)
    except Exception:
        thumb.thumbnail((max_px, max_px))

    if thumb.mode == "RGBA":
        return thumb
    if thumb.mode == "P" and "transparency" in thumb.info:
        return thumb.convert("RGBA")
    if thumb.mode == "RGB":
        return thumb
    if thumb.mode in ("CMYK", "LAB", "P"):
        return thumb.convert("RGB")
    return thumb.convert("RGB")


def _dispose_office_import_preview() -> None:
    prev = st.session_state.pop("_office_import_preview", None)
    if prev and prev.get("staging_dir"):
        shutil.rmtree(prev["staging_dir"], ignore_errors=True)


def _extract_docx_into_staging_dir(data: bytes, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp.write(data)
        tp = Path(tmp.name)
    try:
        _office_import_trace_append("docx: leyendo word/media desde ZIP OOXML")
        result = extract_from_docx(tp, out_dir)
        _office_import_trace_append(f"docx: blobs extraídos del ZIP antes de filtrar = {len(result)}")
        for p in result:
            try:
                nb = p.stat().st_size
            except OSError:
                nb = -1
            _office_import_trace_append(f"  · {p.name} ({nb} B)")
        return result
    finally:
        tp.unlink(missing_ok=True)


def _extract_excel_into_staging_dir(data: bytes, filename: str, out_dir: Path) -> list[Path]:
    suf = Path(filename).suffix.lower()
    if suf not in (".xlsx", ".xls"):
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=suf, delete=False) as tmp:
        tmp.write(data)
        tp = Path(tmp.name)
    try:
        try:
            nb = tp.stat().st_size
        except OSError:
            nb = -1
        _office_import_trace_append(f"Excel temp listo sufijo={suf} tamaño_temp_B={nb} archivo_origen={filename!r}")

        if suf == ".xlsx":
            paths = extract_from_xlsx(tp, out_dir)
            _office_import_trace_append(f"xlsx OOXML: elementos escritos en staging = {len(paths)}")
            for p in paths:
                try:
                    sz = p.stat().st_size
                except OSError:
                    sz = -1
                _office_import_trace_append(f"  · {p.name} ({sz} B)")
            return paths

        _office_import_trace_append("legacy .xls: escaneando compuesto OLE / binario…")
        return extract_from_xls(tp, out_dir, trace=_office_import_trace_append)
    finally:
        tp.unlink(missing_ok=True)


def _office_import_usable_paths(paths: list[Path]) -> list[Path]:
    """JPEGs flagged as OLE-glitch artefacts are dropped; other formats unchanged."""
    out: list[Path] = []
    _office_import_trace_append(f"filtro glitch: entrada {len(paths)} path(s)")
    for p in paths:
        suf = p.suffix.lower()
        try:
            fsz = p.stat().st_size
        except OSError:
            fsz = -1
        if suf not in ('.jpg', '.jpeg'):
            _office_import_trace_append(f"✓ Mantengo (sin filtro JPEG-OLE): `{p.name}` ({fsz} B)")
            out.append(p)
            continue
        if should_skip_truncated_xls_jpeg(p):
            _office_import_trace_append(
                f"✗ JPEG descartado `_jpeg_likely_decode_corrupt`: `{p.name}` ({fsz} B)"
            )
            continue
        _office_import_trace_append(f"✓ JPEG aceptado: `{p.name}` ({fsz} B)")
        out.append(p)
    _office_import_trace_append(f"filtro glitch: salida {len(out)} archivo(s)")
    return out


def _commit_office_import_preview() -> int:
    """Normalize and persist preview images to ``IMAGES_DIR``. Returns count saved or ``-1`` on failure."""
    prev = st.session_state.get("_office_import_preview")
    if not prev:
        return -1
    staging_dir = prev.get("staging_dir")
    stem_safe = _sanitize_upload_stem(prev["source_filename"])
    usable = [Path(pstr) for pstr in prev["paths"]]
    _office_import_trace_append(f"confirmar clic: saneando {len(usable)} ruta(s) desde `{stem_safe}`")
    if not usable:
        _office_import_trace_append("confirmar cancelado: lista de vistas previas vacía")
        _office_import_banner_set(
            title="No se puede importar",
            body=(
                "No hay imágenes JPEG válidas después del filtro anti-corruptos OLE "
                "(o no quedaron rutas seleccionadas). Revisá el **log técnico** junto."
            ),
            variant="warning",
        )
        st.warning("No hay imágenes válidas para importar.")
        return -1

    try:
        _office_import_trace_append(f"guardando saneadas bajo `{stem_safe}_office*` → {IMAGES_DIR.as_posix()}/")
        for i, p in enumerate(usable):
            dest = save_normalized_image(p, IMAGES_DIR, f"{stem_safe}_office{i}")
            _office_import_trace_append(f"  guardado `{dest.name}`")
    except Exception as e:
        _office_import_trace_append(f"ERROR save_normalized_image: {e}")
        _office_import_banner_set(
            title="Error al guardar",
            body=f"No se pudieron saneizar/guardar: `{e}`. Mirá stderr y el log técnico.",
            variant="warning",
        )
        st.error(f"No se pudieron guardar las imágenes saneadas: {e}")
        return -1

    if staging_dir:
        shutil.rmtree(staging_dir, ignore_errors=True)
    st.session_state.pop("_office_import_preview", None)

    if prev["kind"] == "excel":
        st.session_state["_last_sidebar_excel_sig"] = prev["source_sig"]
    else:
        st.session_state["_last_sidebar_docx_sig"] = prev["source_sig"]

    bump_images_generation()
    n_saved = len(usable)
    _office_import_banner_set(
        title="Importación completada",
        body=(
            f"Se guardaron **{n_saved}** imagen(es) saneadas en **`{IMAGES_DIR.as_posix()}`** "
            "(relativo al proyecto). Podés cerrar esta nota cuando quieras."
        ),
        variant="success",
    )
    return n_saved


@st.dialog("Vista previa — importación")
def office_import_preview_dialog() -> None:
    prev = st.session_state.get("_office_import_preview")
    if not prev:
        return

    paths = [Path(p) for p in prev["paths"]]
    is_excel = prev["kind"] == "excel"
    st.markdown("**Extracción desde Excel (.xlsx / .xls)**" if is_excel else "**Extracción desde Word (.docx)**")
    st.caption(prev.get("source_filename", ""))

    instruction_md = prev.get("instruction_md") or _office_preview_instruction_markdown(len(paths))
    st.info(instruction_md, icon="ℹ️")

    cols_n = min(3, len(paths))
    if cols_n >= 1:
        for row_start in range(0, len(paths), cols_n):
            cols = st.columns(cols_n)
            for j, img_path in enumerate(paths[row_start : row_start + cols_n]):
                with cols[j]:
                    try:
                        pv = _pil_office_preview_thumbnail(img_path)
                        st.image(pv, caption=img_path.name, use_container_width=True)
                    except Exception as e:
                        st.caption(img_path.name)
                        st.warning(f"Vista previa no disponible: {e}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "Confirmar importación",
            type="primary",
            use_container_width=True,
            key="office_preview_confirm_key",
        ):
            n_imp = _commit_office_import_preview()
            if n_imp >= 1:
                st.success(f"Importadas {n_imp} imagen(es).")
                st.rerun()

    with c2:
        if st.button(
            "Cancelar",
            use_container_width=True,
            key="office_preview_cancel_key",
        ):
            _dispose_office_import_preview()
            st.rerun()


def image_path_for_state(path: Path) -> str:
    """Store paths relative to cwd when inside the repo (helps PDF/export)."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path.resolve())


def export_final_csv(products: list[dict], state: dict) -> None:
    rows = []
    for i, row in enumerate(products):
        if is_product_excluded_from_catalog(row):
            continue
        r = dict(row)
        entry = state.get(str(i), {})
        if "image" in entry:
            r["Imagenes"] = entry["image"]
        im = r.get("Imagenes", "FALSE")
        if im and im != "FALSE":
            r["Imagenes"] = normalize_catalog_image_path(im)
        rows.append(r)
    rows, _ = apply_descriptions(rows)
    rows, _ = apply_ficha_tecnica(rows)
    if rows:
        fieldnames = list(rows[0].keys())
        with open(CSV_EXPORT, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(rows)


def get_product_image(idx: int, products: list[dict], state: dict) -> str | None:
    """Return the current image path for a product (state overrides CSV)."""
    entry = state.get(str(idx), {})
    if "image" in entry:
        return entry["image"]
    return products[idx].get("Imagenes", "FALSE")


def status_of(idx: int, state: dict) -> str:
    """'approved' | 'no_image' | 'pending'"""
    return state.get(str(idx), {}).get("status", "pending")


def product_has_valid_catalog_image(idx: int, products: list[dict], state: dict) -> bool:
    """Same validity as ``render_product_card`` (path exists + not excluded by XLS/heuristics)."""
    img_path_str = get_product_image(idx, products, state)
    img_path = Path(img_path_str) if img_path_str and img_path_str != "FALSE" else None
    return bool(
        img_path
        and img_path.exists()
        and not should_ignore_extracted_png(img_path)
        and not should_skip_truncated_xls_jpeg(img_path)
    )


def normalize_pending_without_valid_image(products: list[dict], state: dict) -> bool:
    """Set ``no_image`` + ``FALSE`` for pending rows that have no assignable catalog image.

    Leaves **approved** and **no_image** entries unchanged ("already decided").
    """
    changed = False
    for i in range(len(products)):
        st_v = status_of(i, state)
        if st_v == "approved" or st_v == "no_image":
            continue
        if product_has_valid_catalog_image(i, products, state):
            continue
        entry = state.setdefault(str(i), {})
        entry["status"] = "no_image"
        entry["image"] = "FALSE"
        changed = True
    return changed


def _navigate_current_product(idx: int) -> None:
    """Set active catalog row and dismiss image picker dialog (scoped to prior product)."""
    st.session_state.current_idx = idx
    st.session_state.gallery_open = False


def _clear_gallery_on_product_context_change() -> None:
    """Close picker when staying on index but navigation/review invalidated dialog context."""
    st.session_state.gallery_open = False


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar(products: list[dict], state: dict) -> tuple[list[int], str]:
    with st.sidebar:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), width=160)
        st.title("360 Import")
        st.caption("Revisión de Catálogo")
        st.divider()

        # Progress
        total = len(products)
        approved  = sum(1 for i in range(total) if status_of(i, state) == "approved")
        no_img    = sum(1 for i in range(total) if status_of(i, state) == "no_image")
        pending   = total - approved - no_img
        matched   = sum(1 for p in products if p.get("Imagenes", "FALSE") not in ("FALSE", ""))

        st.markdown(f"**Progreso:** {approved + no_img}/{total} revisados")
        st.progress((approved + no_img) / total if total else 0)
        col1, col2, col3 = st.columns(3)
        col1.metric("✅ Aprobados", approved)
        col2.metric("❌ Sin imagen", no_img)
        col3.metric("⏳ Pendientes", pending)
        st.caption(f"Fuzzy match inicial: {matched}/{total}")
        st.divider()

        # Filters
        st.subheader("Filtros")
        categories = sorted({p.get("Categoria", "") for p in products if p.get("Categoria")})
        cat_filter = st.selectbox("Categoría", ["Todas"] + categories)

        status_filter = st.radio(
            "Estado",
            ["Todos", "Pendientes", "Aprobados", "Sin imagen"],
            horizontal=True,
        )
        search = st.text_input("Buscar producto", placeholder="nombre, proveedor…")
        st.divider()

        # Actions
        st.subheader("Acciones")
        if st.button("📥 Exportar CSV final", use_container_width=True):
            export_final_csv(products, state)
            st.success(f"Exportado: {CSV_EXPORT}")

        if st.button("📄 Generar PDF", use_container_width=True, type="primary"):
            export_final_csv(products, state)
            with st.spinner("Generando PDF…"):
                result = subprocess.run(
                    [sys.executable, "generate_pdf.py", str(CSV_EXPORT), str(TEMPLATE), str(PDF_OUTPUT)],
                    capture_output=True, text=True,
                )
            if result.returncode == 0:
                st.success(f"PDF generado: {PDF_OUTPUT}")
            else:
                st.error(f"Error: {result.stderr[-500:]}")

        st.divider()
        st.markdown("###### Galería de imágenes")
        st.caption(
            "La lista de miniaturas viene de la carpeta **`extracted_images`** (y sincronización tipo Drive). "
            "**Actualizar lista** si agregaste archivos sin usar el import de la app."
        )
        g1, g2 = st.columns(2)
        with g1:
            if st.button(
                "🔁 Actualizar lista",
                use_container_width=True,
                key="sidebar_gallery_refresh_index",
                help="Vuelve a escanear la carpeta por archivos nuevos o renombrados",
            ):
                bump_images_generation()
                st.success("Lista de galería actualizada.")
                st.rerun()
        with g2:
            if st.button(
                "🗑️ Limpiar caché miniaturas",
                use_container_width=True,
                key="sidebar_gallery_clear_thumbs",
                help="Borra miniaturas en disco y en memoria (regenera al abrir el modal)",
            ):
                _clear_gallery_thumb_disk_cache()
                st.session_state.thumb_cache_buster = int(
                    st.session_state.get("thumb_cache_buster", 0)
                ) + 1
                clr = getattr(_gallery_thumb_data_uri_cached, "clear", None)
                if callable(clr):
                    clr()
                st.success("Caché de miniaturas vaciada.")
                st.rerun()

        st.divider()
        st.markdown("###### Importar imágenes")
        st.caption(
            "Seleccioná el **producto activo** en la lista principal (resaltado); subí foto(s) y "
            "la **primera** se asigna a ese producto en estado **pendiente** (podés **Aprobar** después). "
            "Las demás sólo se guardan en la carpeta para asignar desde la galería."
        )
        st.caption("Seleccioná archivo(s) y confirmá según cada tipo de archivo abajo.")

        new_imgs = st.file_uploader(
            "Imágenes locales",
            type=["jpg", "jpeg", "png", "gif", "bmp", "tiff", "webp"],
            accept_multiple_files=True,
            label_visibility="collapsed",
            key="sidebar_import_local_images",
        )
        btn_loc = st.button("Importar imágenes locales", use_container_width=True, key="btn_sidebar_import_local")
        if btn_loc and new_imgs:
            tag = tuple(sorted((f.name, f.size, len(f.getvalue())) for f in new_imgs))
            if st.session_state.get("_last_sidebar_local_import_sig") != tag:
                dests: list[Path] = []
                for uf in new_imgs:
                    d = persist_uploaded_image(uf.name, uf.getvalue())
                    if d is not None:
                        dests.append(d)

                if dests:
                    st.session_state._last_sidebar_local_import_sig = tag
                    bump_images_generation()
                    idx = int(st.session_state.get("current_idx", 0))
                    entry = state.setdefault(str(idx), {})
                    entry["image"] = image_path_for_state(dests[0])
                    entry["status"] = "pending"
                    save_state(state)

                    prod_label = "—"
                    if 0 <= idx < len(products):
                        prod_label = (
                            products[idx].get("Producto")
                            or products[idx].get("Producto_Base")
                            or f"#{idx}"
                        )
                    extra = ""
                    if len(dests) > 1:
                        extra = f" Otras **{len(dests) - 1}** archivo(s): sólo en carpeta (asignalas desde **Cambiar imagen**)."

                    subdir = USER_UPLOAD_REL.as_posix().strip("/").replace("\\", "/")
                    st.success(
                        f"**{dests[0].name}** → producto **{prod_label}** (pendiente de aprobar).{extra} "
                        f"Carpeta: `{IMAGES_DIR.as_posix()}/{subdir}/`."
                    )
                else:
                    st.warning("No hay imágenes válidas.")
                st.rerun()
            else:
                st.info("Ese mismo lote ya fue importado. Cambiá la selección.")

        with st.expander("Importar desde Office (.docx / Excel)", expanded=False):
            docx_f = st.file_uploader(
                "Word (.docx)",
                type=["docx"],
                accept_multiple_files=False,
                label_visibility="visible",
                key="sidebar_import_docx",
            )
            btn_doc = st.button(
                "Extraer del .docx",
                use_container_width=True,
                disabled=docx_f is None,
                key="btn_sidebar_docx_extract",
            )
            if btn_doc and docx_f is not None:
                sig_doc = (docx_f.name, docx_f.size, len(docx_f.getvalue()))
                if st.session_state.get("_last_sidebar_docx_sig") == sig_doc:
                    st.info("Este archivo ya fue procesado.")
                else:
                    _dispose_office_import_preview()
                    _office_import_trace_reset()
                    _office_import_banner_clear()
                    _office_import_trace_append(
                        f"docx: inicio archivo={docx_f.name} bytes_en_uploader={docx_f.size}"
                    )
                    staging_root = tempfile.mkdtemp(prefix="st_office_docx_")
                    staging_out = Path(staging_root) / "extracted"
                    ex_paths = _extract_docx_into_staging_dir(docx_f.getvalue(), staging_out)
                    usable = _office_import_usable_paths(ex_paths)
                    src_name_esc = Path(docx_f.name).name
                    if not ex_paths:
                        shutil.rmtree(staging_root, ignore_errors=True)
                        _office_import_banner_set(
                            title="Word — sin imágenes embebidas",
                            body=(
                                f"No aparecieron blobs en **`word/media/`** para **`{src_name_esc}`** "
                                "o el .docx no se pudo leer como ZIP (documento ilegible)."
                            ),
                            variant="warning",
                        )
                    elif not usable:
                        shutil.rmtree(staging_root, ignore_errors=True)
                        _office_import_banner_set(
                            title="Word — sólo JPEG glitch",
                            body=(
                                f"Se extrajeron **{len(ex_paths)}** archivo(s) de media, pero **todos** los JPEG "
                                "fueron descartados por la heurística anti-corruptos OLE.\n\n"
                                "Probá exportar de otra forma o subí la foto con **Importar imágenes locales**."
                            ),
                            variant="warning",
                        )
                    else:
                        md = _office_preview_instruction_markdown(len(usable))
                        _office_import_banner_set(title="Word — vista previa", body=md, variant="info")
                        st.session_state["_office_import_preview"] = {
                            "kind": "word",
                            "staging_dir": staging_root,
                            "paths": [str(p) for p in usable],
                            "source_sig": sig_doc,
                            "source_filename": docx_f.name,
                            "instruction_md": md,
                        }
                        _office_import_trace_append(
                            f"docx: staging OK ({len(usable)} imagen(es)) → abrir diálogo de vista previa"
                        )
                    st.rerun()

            xlsx_f = st.file_uploader(
                "Excel (.xlsx, .xls)",
                type=["xlsx", "xls"],
                accept_multiple_files=False,
                label_visibility="visible",
                key="sidebar_import_excel",
            )
            btn_xls = st.button(
                "Extraer del Excel",
                use_container_width=True,
                disabled=xlsx_f is None,
                key="btn_sidebar_excel_extract",
            )
            if btn_xls and xlsx_f is not None:
                sig_xls = (xlsx_f.name, xlsx_f.size, len(xlsx_f.getvalue()))
                if st.session_state.get("_last_sidebar_excel_sig") == sig_xls:
                    st.info("Este archivo ya fue procesado.")
                else:
                    _dispose_office_import_preview()
                    _office_import_trace_reset()
                    _office_import_banner_clear()
                    _office_import_trace_append(
                        f"excel: inicio archivo={xlsx_f.name} bytes_en_uploader={xlsx_f.size}"
                    )
                    staging_root = tempfile.mkdtemp(prefix="st_office_xlsx_")
                    staging_out = Path(staging_root) / "extracted"
                    ex_paths = _extract_excel_into_staging_dir(
                        xlsx_f.getvalue(), xlsx_f.name, staging_out
                    )
                    ext = Path(xlsx_f.name).suffix.lower()
                    src_name_esc = Path(xlsx_f.name).name
                    xls_hint = (
                        "Algunos .xls sólo exponen vectores/metafile (WMF/EMF), BLIPzlib u otros OLE: "
                        "no hay JPEG/PNG “planos” hasta convertir o rasterizar.\n\n"
                        "Guardá como **.xlsx** en Excel/LibreOffice y repetí la extracción; "
                        "o iniciá la app con **`LEGACY_XLS_SOFFICE=1`** si `soffice`/`libreoffice` está en PATH "
                        "(conversión headless a `.xlsx` y extracción OOXML).\n\n"
                        "También podés usar **Importar imágenes locales**."
                    )
                    usable = _office_import_usable_paths(ex_paths)

                    if not ex_paths:
                        shutil.rmtree(staging_root, ignore_errors=True)
                        body = f"No aparecieron imágenes rastreadas en **`{src_name_esc}`**."
                        if ext == ".xls":
                            body += f"\n\n{xls_hint}"
                        _office_import_banner_set(title="Excel — sin imágenes", body=body, variant="warning")
                    elif not usable:
                        shutil.rmtree(staging_root, ignore_errors=True)
                        if ext == ".xls":
                            discard_body = (
                                f"Para **`{src_name_esc}`** se escribieron **{len(ex_paths)}** archivo(s), "
                                "pero **ningún JPEG** pasó el filtro anti-glitch OLE "
                                "(JPEG que decodifican pero muestran bandas verdes/azules o otros artefactos típicos de OLE).\n\n"
                                f"{xls_hint}"
                            )
                        else:
                            discard_body = (
                                f"Se extrajeron **{len(ex_paths)}** JPEG desde **`{src_name_esc}`**, pero **todos** "
                                "fueron descartados por corrupción visible al decodificar."
                            )
                        _office_import_banner_set(
                            title="Excel — sólo JPEG descartados",
                            body=discard_body,
                            variant="warning",
                        )
                    else:
                        md = _office_preview_instruction_markdown(len(usable))
                        _office_import_banner_set(title="Excel — vista previa", body=md, variant="info")
                        st.session_state["_office_import_preview"] = {
                            "kind": "excel",
                            "staging_dir": staging_root,
                            "paths": [str(p) for p in usable],
                            "source_sig": sig_xls,
                            "source_filename": xlsx_f.name,
                            "instruction_md": md,
                        }
                        _office_import_trace_append(
                            f"excel: staging OK ({len(usable)} imagen(es)) → abrir diálogo de vista previa"
                        )
                    st.rerun()

        render_office_import_banner_sidebar()

    # Build filtered index list
    filtered: list[int] = []
    for i, p in enumerate(products):
        if cat_filter != "Todas" and p.get("Categoria", "") != cat_filter:
            continue
        st_val = status_of(i, state)
        if status_filter == "Pendientes" and st_val != "pending":
            continue
        if status_filter == "Aprobados" and st_val != "approved":
            continue
        if status_filter == "Sin imagen" and st_val != "no_image":
            continue
        if search:
            term = search.lower()
            haystack = " ".join([
                p.get("Producto", ""), p.get("Producto_Base", ""),
                p.get("Proveedor", ""), p.get("Categoria", ""),
            ]).lower()
            if term not in haystack:
                continue
        filtered.append(i)

    return filtered, cat_filter


# ── Image picker ──────────────────────────────────────────────────────────────

def render_image_picker(product_idx: int, state: dict) -> None:
    gen = int(st.session_state.get("images_cache_generation", 0))
    all_images = _session_gallery_paths(gen)
    page_step = 32
    st.markdown("#### Seleccionar imagen")

    col_search, col_toggle = st.columns([3, 1])
    with col_search:
        search = st.text_input(
            "Buscar imagen",
            key="gallery_img_search_global",
            placeholder="nombre de archivo…",
        )
    with col_toggle:
        hide_matched = st.checkbox(
            "Ocultar asignadas",
            value=True,
            key="gallery_hide_assigned_global",
        )

    filt_sig = (search.lower().strip(), hide_matched, gen)
    if st.session_state.get("_gallery_filter_sig") != filt_sig:
        st.session_state._gallery_filter_sig = filt_sig
        st.session_state.gallery_visible_limit = page_step

    already_used = {
        entry["image"]
        for i, entry in state.items()
        if entry.get("status") == "approved" and "image" in entry and i != str(product_idx)
    }

    filtered = [
        p
        for p in all_images
        if (not search or search.lower() in p.name.lower())
        and (not hide_matched or str(p) not in already_used)
    ]

    if not filtered:
        st.info("Sin resultados.")
        return

    limit = int(st.session_state.get("gallery_visible_limit", page_step))
    visible = filtered[:limit]
    st.caption(f"Mostrando **{len(visible)}** de **{len(filtered)}** imagen(es).")

    cols_per_row = 4
    for row_start in range(0, len(visible), cols_per_row):
        cols = st.columns(cols_per_row)
        for col_idx, img_path in enumerate(visible[row_start : row_start + cols_per_row]):
            with cols[col_idx]:
                st.markdown(
                    gallery_thumb_html(img_path, height="120px", css_class="catalog-thumb"),
                    unsafe_allow_html=True,
                )
                st.caption(img_path.name[:28])
                with st.popover("🔍", use_container_width=True):
                    st.image(str(img_path), caption=img_path.name, use_container_width=True)
                pid = _gallery_pick_button_id(img_path)
                if st.button("Seleccionar", key=f"gallery_pick_{pid}"):
                    entry = state.setdefault(str(product_idx), {})
                    entry["image"] = image_path_for_state(img_path)
                    entry["status"] = "approved"
                    save_state(state)
                    st.session_state.gallery_open = False
                    st.rerun()

    if len(visible) < len(filtered):
        if st.button("Cargar más (+32)", key="gallery_load_more_btn"):
            st.session_state.gallery_visible_limit = min(len(filtered), limit + page_step)
            st.rerun()


@st.dialog("Elegir imagen")
def image_picker_dialog(product_idx: int, products: list[dict], state: dict) -> None:
    p = products[product_idx]
    title = (p.get("Producto") or p.get("Producto_Base") or f"#{product_idx}").strip()
    st.markdown(f"**{title}**")
    st.caption("Elegí una imagen de la galería del proyecto (también podés usar **Cerrar** y volver después).")

    close_col, _ = st.columns([1, 3])
    with close_col:
        if st.button("Cerrar", key="gallery_dialog_close", use_container_width=True):
            st.session_state.gallery_open = False
            st.rerun()

    render_image_picker(product_idx, state)


# ── Product card ──────────────────────────────────────────────────────────────

def render_product_card(
    product_idx: int,
    products: list[dict],
    state: dict,
    filtered_indices: list[int],
) -> None:
    p = products[product_idx]
    st_val = status_of(product_idx, state)
    img_path_str = get_product_image(product_idx, products, state)
    img_path = Path(img_path_str) if img_path_str and img_path_str != "FALSE" else None
    img_valid = product_has_valid_catalog_image(product_idx, products, state)

    # Navigation
    pos = filtered_indices.index(product_idx) if product_idx in filtered_indices else 0
    nav_left, nav_info, nav_right = st.columns([1, 4, 1])
    with nav_left:
        if st.button("← Anterior", disabled=pos == 0, use_container_width=True):
            _navigate_current_product(filtered_indices[pos - 1])
            st.rerun()
    with nav_info:
        st.markdown(
            f"<div style='text-align:center;padding-top:6px'>"
            f"Producto <b>{pos + 1}</b> de <b>{len(filtered_indices)}</b></div>",
            unsafe_allow_html=True,
        )
    with nav_right:
        if st.button("Siguiente →", disabled=pos >= len(filtered_indices) - 1, use_container_width=True):
            _navigate_current_product(filtered_indices[pos + 1])
            st.rerun()

    st.divider()

    # Product info + image
    info_col, img_col = st.columns([3, 2])

    with info_col:
        STATUS_BADGE = {
            "approved": "🟢 Aprobado",
            "no_image": "🔴 Sin imagen",
            "pending":  "🟡 Pendiente",
        }
        st.markdown(f"**Estado:** {STATUS_BADGE[st_val]}")
        st.markdown(f"## {p.get('Producto', '')}")
        st.markdown(f"**Base:** {p.get('Producto_Base', '—')}")
        st.markdown(f"**Presentación:** {p.get('Presentacion', '—')}  |  **Unidades/Caja:** {p.get('Unidades_por_Caja', '—')}")
        st.markdown(f"**Categoría:** `{p.get('Categoria', '—')}`")
        st.markdown(f"**Proveedor:** {p.get('Proveedor', '—')}")

        desc = p.get("Descripción", "")
        if desc:
            if len(desc) > DESC_EXPAND_THRESHOLD:
                with st.expander("Descripción", expanded=False):
                    st.markdown(desc)
            else:
                st.markdown(f"**Descripción:** {desc}")

        ficha_url = (p.get("Ficha_Tecnica_URL") or "").strip() or load_ficha_map().get(
            (p.get("Producto") or "").strip().casefold(), ""
        )
        if ficha_url:
            st.markdown(
                f'<a href="{ficha_url}" target="_blank" rel="noopener noreferrer" '
                'style="display:inline-block;margin-top:8px;padding:6px 14px;background:#c99229;'
                'color:#fff;text-decoration:none;font-size:14px;font-weight:600;border-radius:4px;">'
                "Ver Ficha Técnica</a>",
                unsafe_allow_html=True,
            )

        st.divider()

        # Action buttons
        btn_col1, btn_col2, btn_col3 = st.columns(3)
        with btn_col1:
            if st.button("✅ Aprobar", use_container_width=True, type="primary", key=f"approve_{product_idx}"):
                entry = state.setdefault(str(product_idx), {})
                entry["status"] = "approved"
                if "image" not in entry:
                    entry["image"] = (
                        image_path_for_state(img_path) if img_valid else "FALSE"
                    )
                save_state(state)
                # Auto-advance to next
                if pos < len(filtered_indices) - 1:
                    _navigate_current_product(filtered_indices[pos + 1])
                else:
                    _clear_gallery_on_product_context_change()
                st.rerun()
        with btn_col2:
            toggle_label = "🔽 Cerrar galería" if st.session_state.get("gallery_open") else "🔄 Cambiar imagen"
            if st.button(toggle_label, use_container_width=True, key=f"change_{product_idx}"):
                st.session_state.gallery_open = not st.session_state.get("gallery_open", False)
                st.rerun()
        with btn_col3:
            if st.button("❌ Sin imagen", use_container_width=True, key=f"noimag_{product_idx}"):
                entry = state.setdefault(str(product_idx), {})
                entry["image"] = "FALSE"
                entry["status"] = "no_image"
                save_state(state)
                if pos < len(filtered_indices) - 1:
                    _navigate_current_product(filtered_indices[pos + 1])
                else:
                    _clear_gallery_on_product_context_change()
                st.rerun()

        if img_path and img_path.exists():
            st.caption(f"📁 `{img_path.name}`")
        if img_path and img_path.exists() and not img_valid:
            st.caption(
                "Imagen excluida (logo ~33 KB o JPEG .xls truncado); elige otra en la galería."
            )

    with img_col:
        st.markdown("**Imagen actual**")
        if img_valid:
            st.markdown(
                img_html(img_path, height="320px", css_class="catalog-large"),
                unsafe_allow_html=True,
            )
            with st.popover("🔍 Vista previa", use_container_width=True):
                st.image(str(img_path), caption=img_path.name, use_container_width=True)
        else:
            st.markdown(
                "<div style='height:320px;display:flex;align-items:center;justify-content:center;"
                "background:#f5f5f5;border-radius:8px;border:2px dashed #ccc;'>"
                "<span style='color:#999;font-size:48px;'>📷</span></div>",
                unsafe_allow_html=True,
            )
            st.caption("Sin imagen asignada")


# ── Product list panel ────────────────────────────────────────────────────────

def render_product_list(filtered_indices: list[int], products: list[dict], state: dict) -> None:
    STATUS_ICON = {"approved": "🟢", "no_image": "🔴", "pending": "🟡"}
    current = st.session_state.get("current_idx", filtered_indices[0] if filtered_indices else 0)

    sig = tuple(filtered_indices)
    if st.session_state.get("_product_list_filter_sig") != sig:
        st.session_state._product_list_filter_sig = sig
        page_size_init = int(st.session_state.get("product_list_page_size", 24))
        if page_size_init not in (12, 24, 48):
            page_size_init = 24
        if current in filtered_indices:
            pos = filtered_indices.index(current)
            st.session_state.product_list_page = pos // page_size_init
        else:
            st.session_state.product_list_page = 0

    st.markdown(
        f'<p class="product-nav-meta"><b>{len(filtered_indices)}</b> producto(s) en esta vista</p>',
        unsafe_allow_html=True,
    )

    def _fmt_jump_row(i: int) -> str:
        pr = products[i]
        ic = STATUS_ICON[status_of(i, state)]
        name = pr.get("Producto_Base") or pr.get("Producto") or "—"
        short = name[:42] + ("…" if len(name) > 42 else "")
        return f"{ic} {short} (#{i})"

    jump_ix = filtered_indices.index(current) if current in filtered_indices else 0
    chosen = st.selectbox(
        "Ir al producto",
        options=filtered_indices,
        format_func=_fmt_jump_row,
        index=jump_ix,
    )
    if chosen != current:
        _navigate_current_product(chosen)
        page_size = int(st.session_state.get("product_list_page_size", 24))
        if page_size not in (12, 24, 48):
            page_size = 24
        pos = filtered_indices.index(chosen)
        st.session_state.product_list_page = pos // page_size
        st.rerun()

    page_size = st.selectbox("Por página", [12, 24, 48], key="product_list_page_size")

    n = len(filtered_indices)
    page = int(st.session_state.get("product_list_page", 0))
    max_page = max(0, (n - 1) // page_size) if n else 0
    if page > max_page:
        page = max_page
        st.session_state.product_list_page = page

    start = page * page_size
    end = min(start + page_size, n)
    slice_indices = filtered_indices[start:end]

    nav_prev, nav_mid, nav_next = st.columns([1, 3, 1])
    with nav_prev:
        if st.button(
            "◀",
            disabled=page <= 0,
            key="product_list_prev_page",
            help="Página anterior",
            use_container_width=True,
        ):
            st.session_state.product_list_page = page - 1
            st.rerun()
    with nav_mid:
        st.caption(f"{start + 1}–{end} de {n} · pág. {page + 1}/{max_page + 1}")
    with nav_next:
        if st.button(
            "▶",
            disabled=page >= max_page,
            key="product_list_next_page",
            help="Página siguiente",
            use_container_width=True,
        ):
            st.session_state.product_list_page = page + 1
            st.rerun()

    for row_start in range(0, len(slice_indices), 2):
        pair = slice_indices[row_start : row_start + 2]
        cols = st.columns(2)
        for col_idx, i in enumerate(pair):
            with cols[col_idx]:
                pr = products[i]
                st_val = status_of(i, state)
                icon = STATUS_ICON[st_val]
                nm = pr.get("Producto_Base") or pr.get("Producto") or "—"
                label = f"{icon} {nm[:22]}"
                is_active = i == current
                btn_type = "primary" if is_active else "secondary"
                if st.button(label, key=f"nav_{i}", use_container_width=True, type=btn_type):
                    _navigate_current_product(i)
                    st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    products = load_products()
    state = load_state()

    if normalize_pending_without_valid_image(products, state):
        save_state(state)

    if "current_idx" not in st.session_state:
        st.session_state.current_idx = 0
    if "images_cache_generation" not in st.session_state:
        st.session_state.images_cache_generation = 0
    if "gallery_open" not in st.session_state:
        if "picking" in st.session_state:
            st.session_state.gallery_open = st.session_state.pop("picking")
        else:
            st.session_state.gallery_open = False
    if "product_list_page" not in st.session_state:
        st.session_state.product_list_page = 0
    if "thumb_cache_buster" not in st.session_state:
        st.session_state.thumb_cache_buster = 0

    filtered_indices, _ = render_sidebar(products, state)

    if st.session_state.get("_office_import_preview"):
        office_import_preview_dialog()

    if not filtered_indices:
        st.info("No hay productos que coincidan con los filtros seleccionados.")
        return

    # Clamp current index to filtered list
    if st.session_state.current_idx not in filtered_indices:
        _navigate_current_product(filtered_indices[0])

    if st.session_state.get("gallery_open"):
        image_picker_dialog(st.session_state.current_idx, products, state)

    list_col, card_col = st.columns([1, 3])

    with list_col:
        render_product_list(filtered_indices, products, state)

    with card_col:
        render_product_card(st.session_state.current_idx, products, state, filtered_indices)


if __name__ == "__main__":
    main()
