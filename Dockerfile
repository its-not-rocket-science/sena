FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VENV_PATH=/opt/venv

WORKDIR /app

RUN python -m venv "$VENV_PATH"
ENV PATH="$VENV_PATH/bin:$PATH"

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --upgrade pip && pip install .[api]

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    SENA_API_HOST=0.0.0.0 \
    SENA_API_PORT=8000

WORKDIR /app

RUN addgroup --system sena && adduser --system --ingroup sena sena

COPY --from=builder /opt/venv /opt/venv
COPY --chown=sena:sena src /app/src
COPY --chown=sena:sena pyproject.toml README.md /app/

USER sena

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request;host=os.getenv('SENA_API_HOST','127.0.0.1');port=os.getenv('SENA_API_PORT','8000');urllib.request.urlopen(f'http://{host}:{port}/v1/health',timeout=3).read()"

CMD ["python", "-m", "uvicorn", "sena.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
