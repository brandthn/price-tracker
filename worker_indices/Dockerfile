FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared /app/shared
COPY worker_indices/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY worker_indices /app/worker_indices
CMD ["python", "worker_indices/main.py"]
