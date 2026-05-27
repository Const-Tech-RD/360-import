"""ORM models."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from web.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    producto: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    producto_base: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    presentacion: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    unidades_por_caja: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, default="", nullable=False)
    proveedor: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    categoria: Mapped[str] = mapped_column(String(256), default="", index=True, nullable=False)
    imagen_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    ficha_tecnica_url: Mapped[str] = mapped_column(String(1024), default="", nullable=False)
    excluido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_catalog_dict(self) -> dict:
        """Row shape expected by generate_pdf / catalog_exclude."""
        return {
            "Producto": self.producto,
            "Producto_Base": self.producto_base,
            "Presentacion": self.presentacion,
            "Unidades_por_Caja": self.unidades_por_caja,
            "Descripción": self.descripcion,
            "Proveedor": self.proveedor,
            "Categoria": self.categoria,
            "Imagenes": self.imagen_path if self.imagen_path else "FALSE",
            "Ficha_Tecnica_URL": self.ficha_tecnica_url,
            "_excluido": self.excluido,
        }
