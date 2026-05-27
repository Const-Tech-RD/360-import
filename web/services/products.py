"""Product CRUD service."""
from __future__ import annotations  # noqa: I001

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from web.models import Product
from web.schemas import ProductForm


def list_products(
    db: Session,
    *,
    q: str = "",
    categoria: str = "",
    con_imagen: str = "",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Product], int]:
    stmt = select(Product)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Product.producto.ilike(like),
                Product.producto_base.ilike(like),
                Product.proveedor.ilike(like),
            )
        )
    if categoria:
        stmt = stmt.where(Product.categoria == categoria)
    if con_imagen == "si":
        stmt = stmt.where(Product.imagen_path.isnot(None), Product.imagen_path != "")
    elif con_imagen == "no":
        stmt = stmt.where(or_(Product.imagen_path.is_(None), Product.imagen_path == ""))

    count_stmt = select(func.count()).select_from(Product)
    if q:
        like = f"%{q}%"
        count_stmt = count_stmt.where(
            or_(
                Product.producto.ilike(like),
                Product.producto_base.ilike(like),
                Product.proveedor.ilike(like),
            )
        )
    if categoria:
        count_stmt = count_stmt.where(Product.categoria == categoria)
    if con_imagen == "si":
        count_stmt = count_stmt.where(Product.imagen_path.isnot(None), Product.imagen_path != "")
    elif con_imagen == "no":
        count_stmt = count_stmt.where(or_(Product.imagen_path.is_(None), Product.imagen_path == ""))
    total = db.scalar(count_stmt) or 0

    stmt = stmt.order_by(Product.categoria, Product.producto)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt)), total


def get_product(db: Session, product_id: int) -> Product | None:
    return db.get(Product, product_id)


def get_categories(db: Session) -> list[str]:
    rows = db.scalars(
        select(Product.categoria)
        .where(Product.categoria != "")
        .distinct()
        .order_by(Product.categoria)
    )
    return list(rows)


def create_product(db: Session, form: ProductForm) -> Product:
    p = Product(
        producto=form.producto.strip(),
        producto_base=form.producto_base.strip(),
        presentacion=form.presentacion.strip(),
        unidades_por_caja=form.unidades_por_caja.strip(),
        descripcion=form.descripcion.strip(),
        proveedor=form.proveedor.strip(),
        categoria=form.categoria.strip(),
        ficha_tecnica_url=form.ficha_tecnica_url.strip(),
        excluido=form.excluido,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def update_product(db: Session, product: Product, form: ProductForm) -> Product:
    product.producto = form.producto.strip()
    product.producto_base = form.producto_base.strip()
    product.presentacion = form.presentacion.strip()
    product.unidades_por_caja = form.unidades_por_caja.strip()
    product.descripcion = form.descripcion.strip()
    product.proveedor = form.proveedor.strip()
    product.categoria = form.categoria.strip()
    product.ficha_tecnica_url = form.ficha_tecnica_url.strip()
    product.excluido = form.excluido
    db.commit()
    db.refresh(product)
    return product


def delete_product(db: Session, product: Product) -> None:
    db.delete(product)
    db.commit()
