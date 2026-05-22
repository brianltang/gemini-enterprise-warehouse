# Warehouse Safety Expert API (ADK Demo)

This project is a containerized FastAPI backend that utilizes the **Google Agent Development Kit (ADK)**. It demonstrates a Warehouse Safety Agent (using Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using CRAWL/WALK/RUN logic.

This repository was built using `uv` for ultra-fast dependency management and is fully Dockerized for deployment.

---

## 1. Local Directory Setup & `uv` Initialization

This project requires `uv` to manage the virtual environment and dependencies seamlessly.

**Step 1: Create the directory and initialize `uv`**
```bash
mkdir v1-dockerized
cd v1-dockerized
uv init --app
```
*Note: `uv init` creates a `pyproject.toml` and a default `hello.py`. Rename `hello.py` to `main.py` or ensure your code is saved in `main.py`.*

**Step 2: Install Web Dependencies**
Add the core web and GCP packages to your project:
```bash
uv add fastapi uvicorn pydantic python-dotenv google-genai
```

**Step 3: Install the Google ADK (The Fix)**
To resolve `ModuleNotFoundError: No module named 'google.adk'`, you must explicitly install the ADK into your `uv` environment.
```bash
uv add google-adk
```
*(If you are installing via a local wheel file in the corporate environment, use: `uv pip install google-adk --index-url https://pypi.org/simple`)*

---

## 2. Environment Configuration

Create a `.env` file in your root directory. `uv` will automatically detect and load these variables into your application during runtime.

```ini
GOOGLE_API_USE_CLIENT_CERTIFICATE=false
GOOGLE_CLOUD_PROJECT_ID="your-gcp-project-id"
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION="us-central1"
```

---

## 3. Running Locally (Live Reload)

To start the FastAPI server locally, you do not need to manually source a virtual environment. `uv` handles it automatically.

**Run the server:**
```bash
uv run uvicorn main:app --reload
```

* **`main:app`**: Tells Uvicorn to look inside the `main.py` file for the `app = FastAPI(...)` object.
* **`--reload`**: Enables hot-reloading. The server will restart automatically when you save changes to `main.py`.

Once running, access the interactive API documentation here: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 4. Dockerization

This project includes an optimized `Dockerfile` that leverages `uv` to build the container rapidly.

**Step 1: Build the Image**
```bash
docker build -t warehouse-safety-agent .
```

**Step 2: Run the Container**
Run the container locally, mapping port 8000 and injecting your `.env` file for Google Cloud authentication:
```bash
docker run -p 8000:8000 --env-file .env warehouse-safety-agent
```

*(Note for Cloud Deployment
