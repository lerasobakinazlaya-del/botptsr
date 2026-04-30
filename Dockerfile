FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system app \
    && adduser --system --ingroup app --home /app --shell /usr/sbin/nologin app

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .
RUN mkdir -p /app/logs && chown -R app:app /app

USER app

CMD ["python", "main.py"]
