"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from web.auth import NotAuthenticated
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from web.config import ROOT_DIR, UPLOADS_DIR
from web.database import init_db
from web.routes import auth, catalog, products


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT_DIR / "data").mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="360 Import — Catálogo", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)

static_dir = ROOT_DIR / "web" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(catalog.router)


@app.get("/")
def root():
    return RedirectResponse("/products", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(NotAuthenticated)
async def redirect_login(request: Request, exc: NotAuthenticated):
    return RedirectResponse("/login", status_code=303)
