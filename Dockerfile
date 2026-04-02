FROM python:3.12-slim
RUN pip install --no-cache-dir nanobanana-mcp-server
COPY entrypoint.py /app/entrypoint.py
ENTRYPOINT ["python", "/app/entrypoint.py"]
