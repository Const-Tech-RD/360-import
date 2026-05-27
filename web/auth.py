"""Session-based admin authentication."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from web.config import ADMIN_PASSWORD, SECRET_KEY, SESSION_COOKIE, SESSION_MAX_AGE

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="catalog-admin")


def create_session_token() -> str:
    return _serializer.dumps({"role": "admin"})


def verify_session_token(token: str) -> bool:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("role") == "admin"
    except BadSignature:
        return False


def check_password(password: str) -> bool:
    return secrets.compare_digest(password, ADMIN_PASSWORD)


class NotAuthenticated(Exception):
    pass


def get_current_user(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not verify_session_token(token):
        raise NotAuthenticated()
    return "admin"


AuthUser = Annotated[str, Depends(get_current_user)]
