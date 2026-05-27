"""App configuration from environment."""
from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT_DIR / 'data' / 'catalog.db'}")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SESSION_COOKIE = "catalog_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

UPLOADS_DIR = ROOT_DIR / "uploads"
PDF_OUTPUT = ROOT_DIR / "catalogo_360import.pdf"
TEMPLATE_PATH = ROOT_DIR / "catalog_template.html"
CSV_FINAL = ROOT_DIR / "productos_final.csv"

PAGE_SIZE = int(os.getenv("PAGE_SIZE", "25"))
