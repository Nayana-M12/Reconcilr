from fastapi import FastAPI

from app.api.imports import router as imports_router
from app.database import Base, engine

app = FastAPI(title="Reconcilr API", version="1.0.0")
app.include_router(imports_router)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
