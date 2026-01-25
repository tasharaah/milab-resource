# Dockerfile for deploying MI Lab Resource Manager on Google Cloud Run
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source
COPY . .

ENV PORT=8080
ENV DJANGO_SETTINGS_MODULE=mi_lab.settings

CMD ["gunicorn", "mi_lab.wsgi:application", "--bind", "0.0.0.0:${PORT}", "--workers", "3"]