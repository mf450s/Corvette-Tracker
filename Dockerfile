# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /dist

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    CORVETTE_TRACKER_HOST=0.0.0.0 \
    CORVETTE_TRACKER_PORT=8096 \
    CORVETTE_TRACKER_OUTPUT_DIR=/app/runtime \
    CORVETTE_TRACKER_DATABASE=/app/runtime/data/corvette_tracker.sqlite \
    CORVETTE_TRACKER_CONFIG=/app/config.yaml \
    CORVETTE_TRACKER_CRON_INTERVAL=6h \
    CORVETTE_TRACKER_RUN_ON_START=true
WORKDIR /app
RUN addgroup --system corvette && adduser --system --ingroup corvette corvette \
    && mkdir -p /app/runtime /app/runtime/data /app/runtime/feed /app/runtime/site \
    && chown -R corvette:corvette /app
COPY --from=builder /dist/*.whl /tmp/
RUN python -m pip install /tmp/*.whl \
    && rm /tmp/*.whl
COPY config.example.yaml /app/config.yaml
RUN chown corvette:corvette /app/config.yaml
USER corvette
EXPOSE 8096
VOLUME ["/app/runtime"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os, urllib.request; port=os.getenv('PORT', os.getenv('CORVETTE_TRACKER_PORT', '8096')); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=3).read()" || exit 1
CMD ["python", "-m", "corvette_tracker.web"]
