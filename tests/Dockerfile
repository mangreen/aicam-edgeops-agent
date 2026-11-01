# 測試專用映像：Host 不需要 Python。首次 build 後可離線重跑。
FROM python:3.11-slim
WORKDIR /w
COPY agent/requirements.txt req.txt
COPY requirements-dev.txt req-dev.txt
RUN pip install --no-cache-dir -r req.txt -r req-dev.txt
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
