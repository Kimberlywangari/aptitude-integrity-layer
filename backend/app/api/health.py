from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("select 1"))
    except Exception:
        response.status_code = 503
        return {"status": "error", "db": False}
    return {"status": "ok", "db": True}
