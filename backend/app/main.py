import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import settings
from app.db.session import Base, engine
from app.models import catalog  # noqa: F401

logging.basicConfig(level=logging.INFO)
Base.metadata.create_all(bind=engine)

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title=settings.app_name,
    root_path=settings.normalized_base_path,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")
