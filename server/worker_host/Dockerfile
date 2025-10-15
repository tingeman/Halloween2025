# server/worker_host/Dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# upgrade pip then install
RUN python -m pip install --upgrade pip 

# Copy package source into the image so the package can be executed as a module
# placing it at /app/worker_host makes `python -m worker_host.main` work when
# /app is on PYTHONPATH.
COPY server/worker_host /app/worker_host
# Built-in workers shipped with the image
COPY server/worker_host/builtin_workers /opt/builtin_workers

# copy props into the image so the collector can read per-prop requirements
COPY props /app/props

# Ensure the script knows where the repo root is
ENV REPO_ROOT=/app

# run collector and install combined requirements
RUN python /app/worker_host/collect_requirements.py /tmp/combined-requirements.txt \
    && pip install --no-cache-dir -r /tmp/combined-requirements.txt

# # Install runtime requirements (dashboard-style)
# COPY server/worker_host/requirements.txt ./requirements.txt
# RUN pip install --no-cache-dir -r requirements.txt


# We bind-mount repository props at runtime; ensure PYTHONPATH includes:
# - /app (parent of /app/worker_host)
# - /opt/libs/py (read-only shared libs)
# - /opt/builtin_workers (built-in backends)
ENV PYTHONPATH=/app:/opt/libs/py:/opt/builtin_workers

# Run worker host module so relative imports inside the package work
CMD ["python", "-m", "worker_host.main"]