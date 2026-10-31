FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV WEB_HOST=0.0.0.0 \
    WEB_PORT=8000 \
    ENV_FILE=/app/.env \
    GARMINTOKENS=/data/garmin-tokens \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "-m", "web"]
