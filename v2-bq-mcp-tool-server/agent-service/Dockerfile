FROM python:3.13-bookworm

# Copy uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# set up non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser
WORKDIR /app

# Install standard dependencies
COPY pyproject.toml
RUN uv pip install --system . --index-url https://pypi.org/simple
RUN uv pip install --system "google-adk[a2a]" "a2a-sdk[http-server]" mcp httpx --index-url https://pypi.org/simple

COPY . .
RUN chown -R appuser:appgroup /app
USER appuser

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]