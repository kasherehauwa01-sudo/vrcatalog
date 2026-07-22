import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db.session import Base, engine
from app.models import catalog  # noqa: F401

logging.basicConfig(level=logging.INFO)
Base.metadata.create_all(bind=engine)
app = FastAPI(title="VR Catalog API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")
