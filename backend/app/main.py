from fastapi import APIRouter, FastAPI

from app.api import admin, health, review, session, spike
from app.config import get_settings
from app.errors import install_error_handlers

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(session.router)
api_router.include_router(review.router)
api_router.include_router(admin.router)
if get_settings().env != "production":
    api_router.include_router(spike.router)  # temporary D2 spike; delete before the pilot

app = FastAPI(title="Aptitude Test Integrity Layer")
install_error_handlers(app)
app.include_router(api_router)
