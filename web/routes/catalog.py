"""Catalog PDF generation and download."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from web.auth import AuthUser
from web.config import PDF_OUTPUT, ROOT_DIR
from web.database import get_db
from web.services.catalog_export import generate_catalog_pdf

router = APIRouter(prefix="/catalog", tags=["catalog"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "web" / "templates"))


@router.post("/generate", response_class=HTMLResponse)
def catalog_generate(
    request: Request,
    user: AuthUser,
    db: Session = Depends(get_db),
):
    try:
        generate_catalog_pdf(db)
        msg = "Catálogo PDF generado correctamente."
        ok = True
    except Exception as e:
        msg = f"Error al generar PDF: {e}"
        ok = False
    return templates.TemplateResponse(
        request,
        "catalog/_status.html",
        {"message": msg, "ok": ok, "pdf_exists": PDF_OUTPUT.exists()},
    )


@router.get("/download")
def catalog_download(user: AuthUser):
    if not PDF_OUTPUT.exists():
        return HTMLResponse("PDF no generado aún", status_code=404)
    return FileResponse(
        PDF_OUTPUT,
        media_type="application/pdf",
        filename="catalogo_360import.pdf",
    )
