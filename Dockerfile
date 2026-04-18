FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY initials/ /app/initials/

RUN mkdir -p /app/data

ENV DATA_DIR=/app/data

EXPOSE 5050

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5050", "app:app"]

