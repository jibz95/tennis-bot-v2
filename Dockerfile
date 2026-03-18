FROM selenium/standalone-chrome:latest

USER root

RUN pip3 install flask==3.0.3 selenium==4.18.1 gunicorn==22.0.0 --break-system-packages

WORKDIR /app
COPY app.py .

ENV PORT=8080

EXPOSE 8080

CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
