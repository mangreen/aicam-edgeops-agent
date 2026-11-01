FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd -r -u 10001 app
COPY app.py .
USER app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
