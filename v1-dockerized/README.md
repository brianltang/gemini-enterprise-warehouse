# Warehouse Safety Expert API (ADK Demo)

This project is a containerized FastAPI backend that utilizes the **Google Agent Development Kit (ADK)**. It demonstrates a Warehouse Safety Agent (using Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using CRAWL/WALK/RUN logic.

This repository was built using `uv` for ultra-fast dependency management and is fully Dockerized for secure deployment to Google Cloud Run.

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
*(If you are installing behind a corporate proxy/Airlock, use: `uv pip install google-adk --index-url https://pypi.org/simple`)*

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

## 4. The Google Cloud Container Contract

When deploying containers to Google Cloud Run, the application must adhere to a strict container contract to avoid failing health checks, triggering security blocks, or crashing.

| Rule | Description | Implementation in this Project |
| :--- | :--- | :--- |
| **Dynamic Port Binding** | The web server must listen on the port defined by the `$PORT` environment variable (injected dynamically by Cloud Run's load balancer). Hardcoding a port like `8000` causes immediate termination. | Handled in the `Dockerfile` via: `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]` |
| **Workload Identity** | Never bake `.env` files or JSON keys into the Docker image. Use the attached Service Account to authenticate. | The python script uses `google.auth.default()`, which is smart enough to switch from looking at files on your Cloudtop to automatically talking to the hidden metadata server in GCP. |
| **Statelessness** | You cannot trust local disk or memory to persist across requests or scale-to-zero events. | Currently uses `InMemorySessionService` for demo purposes. For production, swap to `VertexAiSessionService` or Firestore so state lives outside the container. |
| **Structured Logging** | Do not write to `.log` files. Print to `stdout`/`stderr`. | FastAPI and Uvicorn log to `stdout` natively, which Google Cloud Logging automatically ingests and indexes. |
| **Non-Root Execution** | Containers should ideally run as a non-root user to trap hackers so they cannot install malware or alter the container's OS. | *(Recommended for future production hardening via `groupadd` and `useradd` in the Dockerfile).* |

---

## 5. Dockerization & Deployment Architecture

Because this project is built in a corporate environment (with Airlock and internal registries), running `uv sync` directly inside a Cloud Build container fails due to missing credentials. 

**The Workaround Strategy:**
1. Export dependencies locally to a portable format: `uv export --format requirements-txt > requirements.txt`
2. Remove the internal `google-adk` package from the `requirements.txt` to bypass strict cryptographic hash checks.
3. In the `Dockerfile`, use the **full `python:3.11` image** (not `slim`) to ensure build tools like `gcc` are present for compiling complex dependencies (like `pydantic-core`).
4. Install public packages via `pip`, then install `google-adk` directly from the public index in a separate step.

### Step-by-Step Cloud Deployment

**Step 1: Auth & Project Configuration**
```bash
gcloud auth login --update-adc --no-launch-browser
gcloud config set project blt-test-project-1
gcloud config set account admin@brianltang.altostrat.com
```

**Step 2: Artifact Registry Creation**
```bash
gcloud artifacts repositories create adk-demos \
    --repository-format=docker \
    --location=us-central1 \
    --description="Docker repository for ADK demos"
```

**Step 3: Configure IAM Permissions**
If we don't do this, Cloud Run will use the default Compute Engine Service Account which will crash since it doesn’t have Vertex AI access by default.
```bash
# Allow Cloud Build to execute and read source files
gcloud projects add-iam-policy-binding blt-test-project-1 \
    --member="serviceAccount:640836206760-compute@developer.gserviceaccount.com" \
    --role="roles/cloudbuild.builds.builder"
gcloud projects add-iam-policy-binding blt-test-project-1 \
    --member="serviceAccount:640836206760-compute@developer.gserviceaccount.com" \
    --role="roles/storage.admin"

# Allow Cloud Run to call Gemini/Vertex AI models
gcloud projects add-iam-policy-binding blt-test-project-1 \
    --member="serviceAccount:640836206760-compute@developer.gserviceaccount.com" \
    --role="roles/aiplatform.user"
```

**Step 4: Build the Container**
Create a `cloudbuild.yaml` file in your root folder defining the Docker BuildKit steps, then submit the build.
```bash
gcloud builds submit --config cloudbuild.yaml .
```

**Step 5: Secure Cloud Run Deployment**
Deploy the service securely. The GCP project has org security policies that prevent exposing endpoints to `allUsers` (the internet), so we deploy it as an authenticated, internal-only service.
```bash
gcloud run deploy warehouse-safety-expert \
    --image us-central1-docker.pkg.dev/blt-test-project-1/adk-demos/warehouse-safety-agent:v1 \
    --region us-central1 \
    --platform managed \
    --no-allow-unauthenticated \
    --set-env-vars GOOGLE_CLOUD_PROJECT_ID=blt-test-project-1,GOOGLE_CLOUD_LOCATION=us-central1
```

**Step 6: Testing the Live API**
You cannot query the endpoint publicly. To test from your terminal, you must pass an authorization bearer token (your own identity credentials) in the header. Make sure to append `/analyze-safety` to the URL.
```bash
curl -X POST "https://warehouse-safety-expert-640836206760.us-central1.run.app/analyze-safety" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{
           "query": "Check robot_id_456 and tell me if it is safe to operate.", 
           "session_id": "test-session-1"
         }'
```
