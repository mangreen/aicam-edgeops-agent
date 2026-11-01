FROM python:3.11-slim
WORKDIR /app
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 AICAM_CONFIG=/app/config/agent.toml
COPY agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd -r -u 10001 app && mkdir /data && chown app /data
COPY agent/src src
COPY agent/runbooks runbooks
COPY agent/ui ui
COPY config config
USER app
CMD ["uvicorn", "aicam.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
