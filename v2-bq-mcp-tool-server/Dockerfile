FROM python:3.13-slim
WORKDIR /app

# 1. Copy the internal, pre-downloaded Google packages directly from your laptop's .venv
# into the global Python environment of the container. 
# This bypasses Cloud Build's inability to authenticate to Corp Airlock!
COPY agent-service/.venv/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

# 2. Copy your code
COPY agent-service/ /app/agent-service/
COPY bq-mcp-server/ /app/bq-mcp-server/

# 3. Environment Variables
ENV TOOL_SERVER_PATH="/app/bq-mcp-server/main.py"
ENV PYTHONUNBUFFERED=1

# 4. Start the server using `python -m uvicorn` instead of the uvicorn binary.
# This completely bypasses all broken symlinks and hardcoded laptop paths!
CMD exec python -m uvicorn agent-service.main:app --host 0.0.0.0 --port ${PORT:-8080}
