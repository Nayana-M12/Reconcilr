from __future__ import annotations

import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.adjustments import router as adjustments_router
from app.api.agent import router as agent_router
from app.api.ai import router as ai_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.exceptions import router as exceptions_router
from app.api.imports import router as imports_router
from app.api.matching import router as matching_router
from app.api.summary import router as summary_router
from app.auth.security import decode_access_token
from app.config import get_settings
from app.database import Base, engine

DOCS_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def _parse_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS") or get_settings().cors_origins
    origins = [item.strip() for item in raw.split(",") if item.strip() and item.strip() != "*"]
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


def create_app() -> FastAPI:
    application = FastAPI(title="Reconcilr API", version="1.0.0")

    @application.middleware("http")
    async def docs_auth_and_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in DOCS_PATHS:
            app_env = (os.getenv("APP_ENV") or get_settings().app_env or "production").strip().lower()
            if app_env != "development":
                auth_header = request.headers.get("authorization") or ""
                if not auth_header.lower().startswith("bearer "):
                    return JSONResponse(
                        {"detail": "Not authenticated"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                token = auth_header.split(" ", 1)[1].strip()
                try:
                    decode_access_token(token)
                except HTTPException as exc:
                    return JSONResponse(
                        {"detail": exc.detail},
                        status_code=exc.status_code,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=_parse_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    application.include_router(auth_router)
    application.include_router(imports_router)
    application.include_router(matching_router)
    application.include_router(exceptions_router)
    application.include_router(adjustments_router)
    application.include_router(ai_router)
    application.include_router(agent_router)
    application.include_router(audit_router)
    application.include_router(summary_router)

    @application.on_event("startup")
    def create_tables() -> None:
        Base.metadata.create_all(bind=engine)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
