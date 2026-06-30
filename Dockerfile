FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first (cached layer). All deps ship manylinux wheels, so no apt needed.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Application
COPY gwa ./gwa
COPY run.py .

# Run as a non-root user. uid 10001 also owns /app/data so files written into the
# host-mounted volume are not root-owned; override with compose `user:` to match host.
RUN useradd -m -u 10001 app && mkdir -p /app/data && chown -R app:app /app
USER app

EXPOSE 8000

# 0.0.0.0 inside the container is required for the published port to be reachable;
# docker-compose publishes it to host loopback by default.
CMD ["uvicorn", "gwa.ui.app:app", "--host", "0.0.0.0", "--port", "8000"]
