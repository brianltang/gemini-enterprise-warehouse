# Use the official, highly optimized uv image for building
FROM ghcr.io/astral-sh/uv:python3.11-alpine AS builder

# Set the working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy only the files needed to install dependencies (leveraging Docker caching)
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# --- RUNTIME STAGE ---
# Use a lightweight, clean python image for the final runtime
FROM python:3.11-alpine

WORKDIR /app

# Copy the virtual environment and application code from the builder stage
COPY --from=builder /app/.venv /app/.venv
COPY . .

# Ensure the app uses the virtual environment's python/packages
ENV PATH="/app/.venv/bin:$PATH"
ENV PORT=8000

EXPOSE 8000

# Run the app directly using uvicorn inside the virtual environment
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
