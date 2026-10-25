"""Load Cytonn's questions from their aptitude API into the question bank.

    python -m scripts.jobs fetch_cytonn_bank [--file PATH] [--save-raw PATH] [--dry-run] [--force]
                                             [--no-images]

Reads GET {APTITUDE_API_BASE_URL}/sections with the key in X-API-KEY (.env). One request per
run. The key goes in the X-API-KEY header only: it is never printed, logged or put in a message.
`--file` loads a response saved earlier instead of calling the API. `--save-raw` keeps the response
as received; put it under data/, which git ignores (it holds the answer key).

The questions arrive as HTML and become plain text. About 42% depend on a picture (almost all of
Numerical, Logical, Error Checking and Office Assistant); the pictures are public files on Cytonn's
site, fetched once and kept in our database so a candidate's test never depends on their website.
`--no-images` loads without them, which leaves out every question that needs one.

Questions Cytonn has not marked with a correct answer, or has marked with more than one, are
skipped and listed. The rules are in app/services/cytonn_bank.py and the reasoning in
docs/plan/cytonn-api-question-bank.md.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator, Mapping
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.models import QuestionImage
from app.services import cytonn_bank, cytonn_images
from app.services.cytonn_bank import BankInUse, LoadResult, ParsedBank
from app.services.cytonn_images import ImageBlob

TIMEOUT_S = 30.0


class FetchError(Exception):
    """The API could not be read. The message never contains the key."""


def fetch_endpoint(
    base_url: str,
    api_key: str,
    path: str,
    *,
    params: dict[str, int] | None = None,
    client: httpx.Client | None = None,
) -> bytes:
    """The raw body of GET {base_url}/{path}. The key goes in the header, never in the URL."""
    if not api_key:
        raise FetchError("X-API-KEY is empty. Add the key Cytonn gave you to .env.")
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        response = http.get(
            f"{base_url.rstrip('/')}/{path}",
            params=params,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
        )
    except httpx.HTTPError as problem:
        raise FetchError(f"could not reach Cytonn's API ({type(problem).__name__})") from problem
    finally:
        if own:
            http.close()

    if response.status_code == 401:
        raise FetchError(
            "Cytonn rejected the API key (401 Unauthorized). Check X-API-KEY in .env, and "
            "ask Cytonn whether the key has been replaced."
        )
    if response.status_code == 429:
        raise FetchError("Cytonn's API is rate limiting us (429). Wait a minute and run it again.")
    if response.status_code != 200:
        raise FetchError(f"Cytonn's API answered {response.status_code}, not 200")
    return response.content


def fetch_sections(base_url: str, api_key: str, *, client: httpx.Client | None = None) -> bytes:
    """The raw body of GET /sections."""
    return fetch_endpoint(base_url, api_key, "sections", client=client)


class _AssumeFetched(Mapping[str, ImageBlob]):
    """For a dry run: every picture is taken to be fetchable, so the report shows what a real run
    would load without making 770 requests."""

    def __getitem__(self, url: str) -> ImageBlob:
        return ImageBlob("image/png", b"", hashlib.sha256(url.encode()).hexdigest())

    def __contains__(self, url: object) -> bool:
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def _progress(done: int, total: int) -> None:
    if done == total or done % 100 == 0:
        print(f"  {done} of {total} pictures")


def _report(bank: ParsedBank, result: LoadResult, *, dry_run: bool, source: str) -> None:
    verb = "would be" if dry_run else "were"
    print(
        f"{result.created} questions created, {result.updated} updated, "
        f"{result.unchanged} unchanged ({verb} applied from {source}); "
        f"{result.images_stored} pictures {'to store' if dry_run else 'stored'}"
    )
    if result.no_image:
        shown = ", ".join(str(i) for i in result.no_image[: cytonn_bank.SAMPLE])
        print(
            f"{len(result.no_image)} questions left out because a picture was not available "
            f"(Cytonn ids {shown}{', ...' if len(result.no_image) > cytonn_bank.SAMPLE else ''})"
        )
    for section, count in sorted(result.by_section.items()):
        minutes = bank.minutes.get(section)
        pace = f", {minutes:g} min per question" if minutes else ""
        print(f"  {section:32} {count:4} questions{pace}")

    if bank.skipped:
        reasons: dict[str, list[int | None]] = defaultdict(list)
        for cytonn_id, reason in bank.skipped:
            reasons[reason].append(cytonn_id)
        print(f"{len(bank.skipped)} questions skipped (they cannot be scored as they are):")
        for reason, ids in sorted(reasons.items(), key=lambda item: -len(item[1])):
            shown = ", ".join(str(i) for i in ids[: cytonn_bank.SAMPLE])
            print(f"  {len(ids):4}  {reason} (Cytonn ids {shown}{', ...' if len(ids) > 5 else ''})")
    if result.kept_used:
        print(
            f"{len(result.kept_used)} questions differ from Cytonn's but a session has already "
            "drawn them, so they were left as they are (their answer key must not change after "
            f"candidates were scored): Cytonn ids {result.kept_used[: cytonn_bank.SAMPLE]}"
        )
    if result.missing_upstream:
        print(
            f"{len(result.missing_upstream)} questions we hold are no longer in Cytonn's list and "
            f"were kept: Cytonn ids {result.missing_upstream[: cytonn_bank.SAMPLE]}"
        )
    for warning in bank.warnings:
        print(f"warning: {warning}")


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, help="load a saved response, not the API")
    parser.add_argument("--save-raw", type=Path, help="write the response as received here")
    parser.add_argument("--dry-run", action="store_true", help="check and report, change nothing")
    parser.add_argument(
        "--force", action="store_true", help="load even while a session is in progress"
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="do not fetch pictures: questions that need one are left out",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        if args.file:
            raw, source = args.file.read_bytes(), args.file.name
        else:
            raw = fetch_sections(settings.aptitude_api_base_url, settings.aptitude_api_key)
            source = "Cytonn's API"
        if args.save_raw:
            args.save_raw.parent.mkdir(parents=True, exist_ok=True)
            args.save_raw.write_bytes(raw)
        bank = cytonn_bank.parse_sections(json.loads(raw))
    except (FetchError, OSError, ValueError) as problem:  # ValueError covers bad JSON too
        raise SystemExit(f"not loaded: {problem}") from problem

    host = urlsplit(settings.aptitude_api_base_url).hostname or ""
    with SessionLocal() as db:
        pictures: Mapping[str, ImageBlob] = {}
        failed: dict[str, str] = {}
        if args.dry_run:
            pictures = _AssumeFetched()
        elif not args.no_images:
            have = set(db.scalars(select(QuestionImage.source_url)))
            wanted = [url for url in bank.images_needed if url not in have]
            if wanted:
                print(f"fetching {len(wanted)} pictures from {host} ...")
                pictures, failed = cytonn_images.fetch_images(wanted, host, progress=_progress)
        try:
            result = cytonn_bank.load_bank(db, bank, force=args.force, images=pictures)
        except BankInUse as problem:
            db.rollback()
            raise SystemExit(f"not loaded: {problem}") from problem
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
    _report(bank, result, dry_run=args.dry_run, source=source)
    for url, why in list(failed.items())[: cytonn_bank.SAMPLE]:
        print(f"picture {url} {why}")
    if failed:
        print(f"{len(failed)} pictures could not be fetched in all")


if __name__ == "__main__":
    main()
