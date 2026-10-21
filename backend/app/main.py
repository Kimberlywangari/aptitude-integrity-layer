from fastapi import APIRouter, FastAPI

from app.api import admin, chunks, complaints, events, health, precheck, review, session
from app.errors import install_error_handlers

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(session.router)
api_router.include_router(precheck.router)
api_router.include_router(events.router)
api_router.include_router(chunks.router)
api_router.include_router(complaints.router)
api_router.include_router(review.router)
api_router.include_router(admin.router)

app = FastAPI(title="Aptitude Test Integrity Layer")
install_error_handlers(app)
app.include_router(api_router)
