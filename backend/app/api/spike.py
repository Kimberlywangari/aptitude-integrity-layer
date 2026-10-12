"""TEMPORARY D2 spike routes. Delete this file before the pilot (D14 checklist).

They exist to answer, with evidence from real SEB: which headers does SEB send on fetch(),
which key type (Config Key or Browser Exam Key) reproduces them, and does the URL the server
rebuilds match the one SEB hashed. They are not mounted when ENV=production.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.seb import (
    CONFIG_KEY_HEADER,
    REQUEST_HASH_HEADER,
    public_request_url,
    request_hash,
)

router = APIRouter(prefix="/spike", tags=["spike"])

SPIKE_LOG = Path(__file__).resolve().parents[3] / "data" / "spike-log.jsonl"


@router.get("/echo")
def echo(
    request: Request,
    settings: Settings = Depends(get_settings),
    key: list[str] = Query(default_factory=list, description="keys to test (spike only)"),
) -> dict:
    """Return what the server received and whether any given key reproduces the SEB hashes."""
    url = public_request_url(request, settings)
    headers = {name: value for name, value in request.headers.items()}
    received = {
        "request_hash (Browser Exam Key)": headers.get(REQUEST_HASH_HEADER),
        "config_key_hash (Config Key)": headers.get(CONFIG_KEY_HEADER),
    }
    got_request_hash = (headers.get(REQUEST_HASH_HEADER) or "").lower()
    got_config_hash = (headers.get(CONFIG_KEY_HEADER) or "").lower()
    results = []
    for candidate in [*settings.seb_keys, *key]:
        expected = request_hash(url, candidate)
        results.append(
            {
                "key_preview": candidate[:6] + "...",
                "expected_hash": expected,
                "matches_request_hash": expected == got_request_hash,
                "matches_config_key_hash": expected == got_config_hash,
            }
        )
    user_agent = headers.get("user-agent", "")
    return {
        "user_agent": user_agent,
        "seb_in_user_agent": "SEB" in user_agent,
        "url_the_server_rebuilt": url,
        "received": received,
        "key_results": results,
        "all_headers": headers,
    }


class SpikeLog(BaseModel):
    lines: list[dict]


@router.post("/log")
def save_log(body: SpikeLog) -> dict:
    """Keep the page's log on disk, so evidence survives when SEB blocks copy and screenshots."""
    SPIKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat()
    with SPIKE_LOG.open("a", encoding="utf-8") as fh:
        for line in body.lines:
            fh.write(json.dumps({"received_at": stamp, **line}) + "\n")
    return {"saved": len(body.lines), "file": str(SPIKE_LOG)}
