"""Product CRUD routes (HTML + HTMX)."""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from web.auth import AuthUser
from web.config import PAGE_SIZE, ROOT_DIR
from web.database import get_db
from web.models import Product
from web.schemas import ProductForm
from web.services import images as image_svc
from web.services import products as product_svc

router = APIRouter(prefix="/products", tags=["products"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "web" / "templates"))


def _form_from_request(
    producto: str = Form(""),
    producto_base: str = Form(""),
    presentacion: str = Form(""),
    unidades_por_caja: str = Form(""),
    descripcion: str = Form(""),
    proveedor: str = Form(""),
    categoria: str = Form(""),
    ficha_tecnica_url: str = Form(""),
    excluido: str = Form(""),
) -> ProductForm:
    return ProductForm(
        producto=producto,
        producto_base=producto_base,
        presentacion=presentacion,
        unidades_por_caja=unidades_por_caja,
        descripcion=descripcion,
        proveedor=proveedor,
        categoria=categoria,
        ficha_tecnica_url=ficha_tecnica_url,
        excluido=excluido == "on",
    )


@router.get("", response_class=HTMLResponse)
def product_list(
    request: Request,
    user: AuthUser,
    db: Session = Depends(get_db),
    q: str = "",
    categoria: str = "",
    con_imagen: str = "",
    page: int = 1,
):
    items, total = product_svc.list_products(
        db, q=q, categoria=categoria, con_imagen=con_imagen, page=page, page_size=PAGE_SIZE,
    )
    pages = max(1, math.ceil(total / PAGE_SIZE))
    return templates.TemplateResponse(
        request,
        "products/list.html",
        {
            "products": items,
            "q": q,
            "categoria": categoria,
            "con_imagen": con_imagen,
            "page": page,
            "pages": pages,
            "total": total,
            "categories": product_svc.get_categories(db),
            "image_url": image_svc.image_url,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def product_new(request: Request, user: AuthUser, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "products/form.html",
        {
            "product": None,
            "form": None,
            "categories": product_svc.get_categories(db),
            "image_url": image_svc.image_url,
            "error": "",
            "saved": False,
        },
    )


@router.post("/new")
def product_create(
    request: Request,
    user: AuthUser,
    db: Session = Depends(get_db),
    form: ProductForm = Depends(_form_from_request),
):
    dup = db.scalar(select(Product).where(Product.producto == form.producto.strip()))
    if dup:
        return templates.TemplateResponse(
            request,
            "products/form.html",
            {
                "product": None,
                "form": form,
                "categories": product_svc.get_categories(db),
                "image_url": image_svc.image_url,
                "error": "Ya existe un producto con ese nombre",
                "saved": False,
            },
            status_code=400,
        )
    p = product_svc.create_product(db, form)
    return RedirectResponse(f"/products/{p.id}/edit", status_code=303)


@router.get("/{product_id}/edit", response_class=HTMLResponse)
def product_edit(
    request: Request,
    product_id: int,
    user: AuthUser,
    db: Session = Depends(get_db),
    saved: int = 0,
):
    p = product_svc.get_product(db, product_id)
    if not p:
        return RedirectResponse("/products", status_code=303)
    return templates.TemplateResponse(
        request,
        "products/form.html",
        {
            "product": p,
            "form": None,
            "categories": product_svc.get_categories(db),
            "image_url": image_svc.image_url,
            "error": "",
            "saved": bool(saved),
        },
    )


@router.post("/{product_id}/edit")
def product_update(
    product_id: int,
    user: AuthUser,
    db: Session = Depends(get_db),
    form: ProductForm = Depends(_form_from_request),
):
    p = product_svc.get_product(db, product_id)
    if not p:
        return RedirectResponse("/products", status_code=303)
    product_svc.update_product(db, p, form)
    return RedirectResponse(f"/products/{product_id}/edit?saved=1", status_code=303)


@router.post("/{product_id}/image", response_class=HTMLResponse)
async def product_upload_image(
    request: Request,
    product_id: int,
    user: AuthUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
):
    p = product_svc.get_product(db, product_id)
    if not p:
        return HTMLResponse("Producto no encontrado", status_code=404)
    data = await file.read()
    if not data:
        return HTMLResponse("Archivo vacío", status_code=400)
    image_svc.save_product_image(db, p, file.filename or "upload.jpg", data)
    db.refresh(p)
    return templates.TemplateResponse(
        request,
        "products/_image_preview.html",
        {"product": p, "image_url": image_svc.image_url},
    )


@router.delete("/{product_id}/image", response_class=HTMLResponse)
def product_remove_image(
    request: Request,
    product_id: int,
    user: AuthUser,
    db: Session = Depends(get_db),
):
    p = product_svc.get_product(db, product_id)
    if not p:
        return HTMLResponse("", status_code=404)
    image_svc.remove_product_image(db, p)
    db.refresh(p)
    return templates.TemplateResponse(
        request,
        "products/_image_preview.html",
        {"product": p, "image_url": image_svc.image_url},
    )


@router.delete("/{product_id}")
def product_delete(
    product_id: int,
    user: AuthUser,
    db: Session = Depends(get_db),
):
    p = product_svc.get_product(db, product_id)
    if p:
        path = p.imagen_path
        product_svc.delete_product(db, p)
        if path:
            from pathlib import Path
            from web.config import UPLOADS_DIR
            fp = UPLOADS_DIR / path
            if fp.exists():
                fp.unlink(missing_ok=True)
    return HTMLResponse("")
