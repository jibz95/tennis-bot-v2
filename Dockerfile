FROM mcr.microsoft.com/playwright/python:v1.41.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir

COPY app.py .

ENV PORT=8080
EXPOSE 8080
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
