# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Set the working directory to the ROOT of the app
WORKDIR /app

# 1. Copy both project folders into the container
COPY bq-mcp-server /app/bq-mcp-server
COPY agent-service /app/agent-service

# 2. Install dependencies for BOTH projects AND explicitly install google-adk
RUN cd /app/bq-mcp-server && uv pip install --system --no-cache -r pyproject.toml
RUN cd /app/agent-service && uv pip install --system --no-cache -r pyproject.toml

# EXPLICITLY install the SDK packages that weren't inside pyproject.toml
RUN uv pip install --system --no-cache "google-adk[a2a]" "a2a-sdk[http-server]" mcp

# 3. Set environment variables
ENV TOOL_SERVER_PATH=/app/bq-mcp-server/main.py
ENV GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2
ENV PYTHONUNBUFFERED=1

# 4. Expose the A2A port
EXPOSE 8080

# 5. Start the Agent Service from the ROOT WORKDIR
CMD ["uvicorn", "agent-service.main:app", "--host", "0.0.0.0", "--port", "8080"]
