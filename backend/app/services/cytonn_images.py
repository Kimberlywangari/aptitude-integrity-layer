"""Copying the pictures Cytonn's questions depend on onto our server.

42% of Cytonn's questions are a picture plus a line of text (a chart, a figure, a sequence), so a
bank without them would be unusable in most sections. The pictures are public files on Cytonn's own
site; they are fetched once, at load time, and kept in the database, so a candidate's test never
depends on Cytonn's website being up and the candidate's browser never talks to it.

Only the host the API itself lives on is ever contacted, over https, and only an actual picture is
kept: what comes back is recognised by its first bytes, not by what the server calls it (Cytonn's
server labels PNG files `image/jpeg`).
"""

import hashlib
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

MAX_BYTES = 2_000_000  # Cytonn's biggest picture is far smaller: this only stops an accident
WORKERS = 8
TIMEOUT_S = 30.0

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


@dataclass(frozen=True)
class ImageBlob:
    content_type: str
    data: bytes
    sha256: str


def sniff(data: bytes) -> str | None:
    """The picture type of these bytes, or None if they are not a picture we show."""
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def fetch_one(url: str, allowed_host: str, client: httpx.Client) -> ImageBlob:
    """One picture. Raises ValueError with a reason a person can read."""
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != allowed_host:
        raise ValueError(f"not an https address on {allowed_host}")
    safe = urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, ""))
    try:
        response = client.get(safe, follow_redirects=False)
    except httpx.HTTPError as problem:
        raise ValueError(f"could not be fetched ({type(problem).__name__})") from problem
    if response.status_code != 200:
        raise ValueError(f"answered {response.status_code}")
    data = response.content
    if len(data) > MAX_BYTES:
        raise ValueError(f"is {len(data)} bytes, over the {MAX_BYTES} limit")
    content_type = sniff(data)
    if content_type is None:
        raise ValueError("is not a picture")
    return ImageBlob(content_type, data, hashlib.sha256(data).hexdigest())


def fetch_images(
    urls: Iterable[str],
    allowed_host: str,
    *,
    client: httpx.Client | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, ImageBlob], dict[str, str]]:
    """(pictures by address, reasons by address for those that failed). Several at a time: there
    are about 770 and each is a small file."""
    wanted = sorted(set(urls))
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S)
    got: dict[str, ImageBlob] = {}
    failed: dict[str, str] = {}

    def work(url: str) -> tuple[str, ImageBlob | str]:
        try:
            return url, fetch_one(url, allowed_host, http)
        except ValueError as problem:
            return url, str(problem)

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for done, (url, outcome) in enumerate(pool.map(work, wanted), start=1):
                if isinstance(outcome, ImageBlob):
                    got[url] = outcome
                else:
                    failed[url] = outcome
                if progress:
                    progress(done, len(wanted))
    finally:
        if own:
            http.close()
    return got, failed
