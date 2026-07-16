# syntax=docker/dockerfile:1

# ---- builder: install deps into an isolated venv ----
FROM python:3.14-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime ----
FROM python:3.14-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . .
RUN chmod +x entrypoint.sh
RUN useradd --uid 10001 --no-create-home appuser
USER appuser
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
