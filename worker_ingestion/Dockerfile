FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared /app/shared
COPY worker_ingestion/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY worker_ingestion /app/worker_ingestion
CMD ["python", "worker_ingestion/main.py"]
