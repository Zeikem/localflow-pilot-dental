from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.whatsapp import router as whatsapp_router
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.auto_create_schema:
        init_db()
    yield


app = FastAPI(
    title="LocalFlow Core",
    version="0.3.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(whatsapp_router)
