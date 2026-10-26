from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.services import disk

router = APIRouter()


@router.get("/health")
def health(
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        db.execute(text("select 1"))
    except Exception:
        response.status_code = 503
        return {"status": "error", "db": False}
    # Still a 200: Docker's own health check reads the code, and a full disk is no reason to
    # restart the API. An uptime monitor that looks for "status":"ok" sees the change.
    return {"status": "low_disk" if disk.is_low(settings.video_root_path) else "ok", "db": True}
