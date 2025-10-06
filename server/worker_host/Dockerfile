FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps if you later need (left minimal for now)
RUN pip install --no-cache-dir --upgrade pip

# Copy worker_host package
COPY server/worker_host/pyproject.toml server/worker_host/ /app/server/worker_host/
RUN cd /app/server/worker_host && pip install --no-cache-dir .

# App entry
COPY server/worker_host/worker_host /app/worker_host

# We DO NOT copy props; we bind-mount repository at runtime so we can import from /app/props
ENV PYTHONPATH=/app

CMD ["python", "-m", "worker_host.main"]
