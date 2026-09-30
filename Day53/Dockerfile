FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# application code and the (read-only) reference data; no secrets, no tests, no local databases (see .dockerignore)
COPY . .

# run as an unprivileged user; the only writable place is the volume for the audit and job databases
RUN useradd --system --uid 10001 agent && mkdir -p /var/lib/agent && chown agent /var/lib/agent
USER agent
ENV AUDIT_DB_PATH=/var/lib/agent/audit.db JOBS_DB_PATH=/var/lib/agent/jobs.db
VOLUME ["/var/lib/agent"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready', timeout=4).status == 200 else 1)"

# ONE worker on purpose: the job queue is in-process memory; scale with more replicas only after the queue moves out of process
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
