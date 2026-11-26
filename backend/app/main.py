import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.adjustments import router as adjustments_router
from app.api.agent import router as agent_router
from app.api.ai import router as ai_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.exceptions import router as exceptions_router
from app.api.extract import router as extract_router
from app.api.imports import router as imports_router
from app.api.insights import router as insights_router
from app.api.matching import router as matching_router
from app.api.summary import router as summary_router
from app.api.users import router as users_router
from app.auth import decode_access_token, get_current_user
from app.config import get_settings
from app.database import Base, engine
from app.services.request_context import reset_audit_actor, set_audit_actor


def _cors_origins() -> list[str]:
    origins = [origin.strip() for origin in get_settings().cors_origins.split(",") if origin.strip()]
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must not contain '*' when credentials are enabled")
    return origins


app = FastAPI(title="Reconcilr API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    public_paths = {"/login", "/register", "/health"}
    if os.getenv("APP_ENV", "production").casefold() == "development":
        public_paths.update({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
    token = None
    if request.url.path not in public_paths and request.method != "OPTIONS":
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            return _security_headers(JSONResponse(status_code=401, content={"detail": "Bearer token required"}))
        try:
            claims = decode_access_token(token)
        except HTTPException as exc:
            return _security_headers(JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}))
        request.state.auth_claims = claims
        actor_token = set_audit_actor(f"{claims['username']} ({claims['role']})")
    else:
        actor_token = None
    try:
        response = await call_next(request)
    finally:
        if actor_token is not None:
            reset_audit_actor(actor_token)
    return _security_headers(response)


app.include_router(auth_router)
protected_dependencies = [Depends(get_current_user)]
app.include_router(imports_router, dependencies=protected_dependencies)
app.include_router(extract_router, dependencies=protected_dependencies)
app.include_router(documents_router, dependencies=protected_dependencies)
app.include_router(matching_router, dependencies=protected_dependencies)
app.include_router(exceptions_router, dependencies=protected_dependencies)
app.include_router(adjustments_router, dependencies=protected_dependencies)
app.include_router(ai_router, dependencies=protected_dependencies)
app.include_router(agent_router, dependencies=protected_dependencies)
app.include_router(audit_router, dependencies=protected_dependencies)
app.include_router(summary_router, dependencies=protected_dependencies)
app.include_router(insights_router, dependencies=protected_dependencies)
app.include_router(users_router, dependencies=protected_dependencies)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
