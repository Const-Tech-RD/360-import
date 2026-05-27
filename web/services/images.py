"""Product image upload and removal."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from PIL import Image
from sqlalchemy.orm import Session

from web.config import ROOT_DIR, UPLOADS_DIR
from web.models import Product


def _normalize_upload(data: bytes, suffix: str) -> bytes:
    from io import BytesIO

    img = Image.open(BytesIO(data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    max_side = 1200
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = BytesIO()
    fmt = "JPEG" if suffix.lower() in {".jpg", ".jpeg"} else "PNG"
    img.save(buf, format=fmt, quality=88, optimize=True)
    return buf.getvalue()


def save_product_image(db: Session, product: Product, filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    out_name = f"{uuid.uuid4().hex}{suffix}"
    rel = f"products/{out_name}"
    dest = UPLOADS_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_upload(data, suffix)
    dest.write_bytes(normalized)

    old = product.imagen_path
    product.imagen_path = rel
    db.commit()
    db.refresh(product)

    if old:
        old_path = UPLOADS_DIR / old
        if old_path.exists() and old_path.is_file():
            try:
                old_path.unlink()
            except OSError:
                pass
    return rel


def remove_product_image(db: Session, product: Product) -> None:
    if not product.imagen_path:
        return
    path = UPLOADS_DIR / product.imagen_path
    product.imagen_path = None
    db.commit()
    if path.exists() and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def image_url(imagen_path: Optional[str]) -> Optional[str]:
    if not imagen_path:
        return None
    return f"/uploads/{imagen_path}"
