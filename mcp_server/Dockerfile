FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8090

ENV MCP_SSE_HOST=0.0.0.0
ENV MCP_SSE_PORT=8090

CMD ["python", "server.py"]
