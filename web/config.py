"""App configuration from environment."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

_storage = os.getenv("STORAGE_DIR", "").strip()
if _storage:
    _storage_dir = Path(_storage)
    DATA_DIR = _storage_dir / "data"
    UPLOADS_DIR = _storage_dir / "uploads"
else:
    DATA_DIR = ROOT_DIR / "data"
    UPLOADS_DIR = ROOT_DIR / "uploads"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'catalog.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SESSION_COOKIE = "catalog_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
PDF_OUTPUT = ROOT_DIR / "catalogo_360import.pdf"
TEMPLATE_PATH = ROOT_DIR / "catalog_template.html"
CSV_FINAL = ROOT_DIR / "productos_final.csv"

PAGE_SIZE = int(os.getenv("PAGE_SIZE", "25"))
