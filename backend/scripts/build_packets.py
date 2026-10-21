"""Build the evidence packet for every flagged candidate in a sitting.

    python -m scripts.jobs build_packets --sitting <id or name>

Run after compute_flags (and detect_silence, so the microphone stretches the server found are in).
Safe to repeat: packets are rebuilt from the flags as they stand.
"""

import argparse

from app.clock import SystemClock
from app.services.packets import build_sitting_packets
from scripts.common import add_sitting_argument, resolve_sitting


def main(argv: list[str] | None = None) -> None:
    from app.db import SessionLocal

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_sitting_argument(parser)
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        sitting = resolve_sitting(db, args.sitting)
        built = build_sitting_packets(db, SystemClock(), sitting.id)
        db.commit()
    print(f"sitting {sitting.id} ({sitting.name}): {built} packets built")


if __name__ == "__main__":
    main()
