FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/comics /app/data/covers /app/data/pages /app/data/nfo /app/data/staging /comics /nfo

EXPOSE 8724

CMD ["gunicorn", "--bind", "0.0.0.0:8724", "--workers", "4", "--worker-class", "gevent", "--worker-connections", "1000", "--timeout", "0", "--graceful-timeout", "600", "run:app"]
