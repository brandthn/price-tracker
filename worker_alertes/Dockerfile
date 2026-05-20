FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY shared /app/shared
COPY worker_alertes/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY worker_alertes /app/worker_alertes
CMD ["python", "worker_alertes/main.py"]
