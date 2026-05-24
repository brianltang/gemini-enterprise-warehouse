# 1. Use the FULL python image (not slim) to get build tools for free
FROM python:3.11

WORKDIR /app

# 2. Copy the requirements file (with google-adk REMOVED)
COPY requirements.txt .

# 3. Install the standard locked dependencies
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# 4. Install google-adk and the A2A HTTP server components
RUN pip install --no-cache-dir "google-adk[a2a]" "a2a-sdk[http-server]" --index-url https://pypi.org/simple

# 5. Copy the rest of your app
COPY . .

# 6. Ensure the port is set for Cloud Run
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
