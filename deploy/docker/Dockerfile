FROM golang:1.25-bookworm AS cron-builder
# Pinned source, Go verifies module checksums; embed IANA timezone data.
RUN CGO_ENABLED=0 go install -tags timetzdata github.com/aptible/supercronic@v0.2.33

FROM python:3.13-slim-bookworm
ARG APP_VERSION=development
LABEL org.opencontainers.image.version=$APP_VERSION
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai
WORKDIR /app
COPY --from=cron-builder /go/bin/supercronic /usr/local/bin/supercronic
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app \
    && mkdir -p /var/lib/autolycus && chown app:app /var/lib/autolycus
USER app
CMD ["python", "-m", "autolycus.cron", "--config", "/etc/autolycus/config.toml"]
