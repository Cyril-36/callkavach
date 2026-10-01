# CallKavach relay and listener app. Keys come from the host's secret settings, never from the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn>=0.30" "websockets>=13" "httpx>=0.27"

WORKDIR /app
COPY backend/spike/*.py backend/spike/
COPY backend/spike/samples backend/spike/samples
COPY frontend frontend
COPY assets assets

RUN useradd --create-home kavach
USER kavach

# One process: session limits and the hourly cap are held in memory, so run a single instance.
# --proxy-headers lets the TLS proxy's forwarded scheme reach the app.
CMD ["sh", "-c", "uvicorn --app-dir backend/spike audio_ws:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
