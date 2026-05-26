# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# Set the working directory
WORKDIR /app

# 1. Copy both project folders into the container
COPY bq-mcp-server /app/bq-mcp-server
COPY agent-service /app/agent-service

# 2. Install dependencies for BOTH projects into the system environment
# We use --system so we don't have to manage two different .venv folders inside Docker
RUN cd /app/bq-mcp-server && uv pip install --system -r pyproject.toml
RUN cd /app/agent-service && uv pip install --system -r pyproject.toml

# 3. Set environment variables
# This tells the Agent where the Tool Server lives inside the container
ENV TOOL_SERVER_PATH=/app/bq-mcp-server/main.py
ENV GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2
ENV PYTHONUNBUFFERED=1

# 4. Expose the A2A port
EXPOSE 8080

# 5. Start the Agent Service
# The Agent will automatically spawn the Tool Server subprocess internally
WORKDIR /app/agent-service
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
