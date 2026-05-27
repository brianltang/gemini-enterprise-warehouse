FROM python:3.13-bookworm

# 1. Install uv binary directly (enables super-fast system pip installs)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 2. Security: Set up Non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser
WORKDIR /app

# 3. Copy only the dependency configuration from agent-service first (improves caching)
COPY agent-service/pyproject.toml /app/agent-service/

# 4. Install dependencies directly into the system python using PyPI
# This compiles your pyproject.toml and adds the specific A2A and MCP modules
RUN cd /app/agent-service && \
    uv pip install --system . --index-url https://pypi.org/simple && \
    uv pip install --system "google-adk[a2a]" "a2a-sdk[http-server]" mcp --index-url https://pypi.org/simple

# 5. Copy the application source code
COPY agent-service/ /app/agent-service/
COPY bq-mcp-server/ /app/bq-mcp-server/

# 6. Change file ownership to your non-root user
RUN chown -R appuser:appgroup /app
USER appuser

# 7. Set Environment Variables
ENV TOOL_SERVER_PATH="/app/bq-mcp-server/main.py"
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
EXPOSE 8080

# 8. Start the FastAPI app from the global system path
# We use python -m uvicorn which is best practice to guarantee the correct Python interpreter runs it
CMD ["sh", "-c", "python -m uvicorn agent-service.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
