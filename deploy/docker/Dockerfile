FROM python:3.13-slim-bookworm
ARG APP_VERSION=development
LABEL org.opencontainers.image.version=$APP_VERSION
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Shanghai
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home app \
    && mkdir -p /var/lib/autolycus && chown app:app /var/lib/autolycus
USER app
CMD ["python", "-m", "autolycus.daemon", "--config", "/etc/autolycus/config.toml"]
