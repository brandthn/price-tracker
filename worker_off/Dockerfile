FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared /app/shared
COPY worker_off/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY worker_off /app/worker_off
CMD ["python", "worker_off/main.py"]
