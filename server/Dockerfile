FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
RUN useradd --create-home app && mkdir /data && chown app:app /data
USER app
EXPOSE 8000
# In-memory sessions/jobs require ONE API process. Worker threads handle downloads.
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
