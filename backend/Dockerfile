# The API and the worker run from this one image (the worker just starts a different command).
# ffmpeg is here for the two things the server does with video: joining chunks into a file that
# seeks, and scanning the audio for muted stretches.
# Base images are pinned by digest so a rebuild uses the image that was tested; Dependabot proposes
# newer ones (.github/dependabot.yml) and CI runs on each proposal.
FROM python:3.13-slim@sha256:d98cc29d3266e535dd9da1099688d9cb3ca4753813571e071763d17725460962

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so a code change does not reinstall them. constraints.txt holds the exact
# versions the tests ran against, so a rebuild next month installs the same ones.
COPY pyproject.toml constraints.txt ./
RUN pip install -c constraints.txt ".[claude]"

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 appuser && mkdir -p /data/video && chown appuser /data/video
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"

# Migrations first, so a fresh database comes up ready; --proxy-headers because nginx sits in front.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
