"""Login routes."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web.auth import check_password, create_session_token, verify_session_token
from web.config import ROOT_DIR, SESSION_COOKIE, SESSION_MAX_AGE

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=str(ROOT_DIR / "web" / "templates"))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    token = request.cookies.get(SESSION_COOKIE)
    if token and verify_session_token(token):
        return RedirectResponse("/products", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"error": error},
    )


@router.post("/login")
def login_submit(
    request: Request,
    password: str = Form(...),
):
    if not check_password(password):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Contraseña incorrecta"},
            status_code=401,
        )
    response = RedirectResponse("/products", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(),
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
