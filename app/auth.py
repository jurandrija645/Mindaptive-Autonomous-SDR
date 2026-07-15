from fastapi import Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings


def install_session_middleware(app):
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)


def is_authed(request: Request) -> bool:
    return bool(request.session.get("authed"))


def require_auth(request: Request):
    if not is_authed(request):
        return RedirectResponse(url="/login", status_code=303)
    return None
