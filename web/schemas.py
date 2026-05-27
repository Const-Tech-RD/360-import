"""Pydantic schemas for forms and API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProductForm(BaseModel):
    producto: str = Field(min_length=1, max_length=512)
    producto_base: str = ""
    presentacion: str = ""
    unidades_por_caja: str = ""
    descripcion: str = ""
    proveedor: str = ""
    categoria: str = ""
    ficha_tecnica_url: str = ""
    excluido: bool = False
