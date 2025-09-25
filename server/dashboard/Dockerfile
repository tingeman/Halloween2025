# server/dashboard/Dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY server/dashboard/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/dashboard/app.py ./app.py
COPY server/dashboard/mqtt_service.py ./mqtt_service.py
COPY server/dashboard/plugin_loader.py ./plugin_loader.py
# Built-in plugins shipped with the image
COPY server/dashboard/builtin_plugins ./builtin_plugins

EXPOSE 8050
CMD ["python", "app.py"]
