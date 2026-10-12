from fastapi import APIRouter, FastAPI

from app.api import health
from app.errors import install_error_handlers

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)

app = FastAPI(title="Aptitude Test Integrity Layer")
install_error_handlers(app)
app.include_router(api_router)
