from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.adjustments import router as adjustments_router
from app.api.audit import router as audit_router
from app.api.exceptions import router as exceptions_router
from app.api.imports import router as imports_router
from app.api.matching import router as matching_router
from app.api.summary import router as summary_router
from app.database import Base, engine

app = FastAPI(title="Reconcilr API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(imports_router)
app.include_router(matching_router)
app.include_router(exceptions_router)
app.include_router(adjustments_router)
app.include_router(audit_router)
app.include_router(summary_router)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
