# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Set the working directory
WORKDIR /app

# 1. Copy project definitions first (for better layer caching)
COPY agent-service/pyproject.toml ./agent-service/
COPY bq-mcp-server/pyproject.toml ./bq-mcp-server/

# 2. Install dependencies using uv sync
# We install the SDKs explicitly here as well.
# We use --no-install-project to install only dependencies first.
RUN uv pip install --system --no-cache \
    "google-adk[a2a]" \
    "a2a-sdk[http-server]" \
    mcp \
    fastapi \
    uvicorn \
    google-cloud-bigquery \
    python-dotenv

# 3. Copy the actual application code
COPY bq-mcp-server /app/bq-mcp-server
COPY agent-service /app/agent-service

# 4. Set environment variables
ENV TOOL_SERVER_PATH=/app/bq-mcp-server/main.py
ENV GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 5. Expose the port
EXPOSE 8080

# 6. Start the server using 'uv run'
# This ensures the python environment is perfectly mapped.
CMD ["uv", "run", "uvicorn", "agent-service.main:app", "--host", "0.0.0.0", "--port", "8080"]
