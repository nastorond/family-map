# python:3.12-slim은 amd64/arm64 모두 제공되므로 NAS 아키텍처와 상관없이 빌드된다.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=wsgi.py \
    DATABASE_PATH=/data/family.db

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir /data \
    && chown app:app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY wsgi.py .

USER app

EXPOSE 8000

# SQLite는 쓰기가 한 프로세스에 몰리는 게 안전해서 워커 1개 + 스레드로 돌린다.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8000", "wsgi:app"]
