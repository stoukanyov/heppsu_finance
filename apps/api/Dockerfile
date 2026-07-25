FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Unicode шрифт с кирилица за PDF генериране.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Приложението НЕ се върти като root. UID 1001 съвпада с потребителя `deploy` на
# хоста, за да може да пише в монтираната /app/storage.
RUN groupadd -g 1001 app \
    && useradd -u 1001 -g 1001 -m -s /usr/sbin/nologin app \
    && mkdir -p /app/storage \
    && chown -R app:app /app/storage
USER app

EXPOSE 8000

# Production: без reload. Броят работници се задава от compose според ядрата.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
