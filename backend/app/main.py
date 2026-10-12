from fastapi import APIRouter, FastAPI

from app.api import health

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)

app = FastAPI(title="Aptitude Test Integrity Layer")
app.include_router(api_router)
