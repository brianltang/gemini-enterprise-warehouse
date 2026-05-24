# Warehouse Safety Expert API (ADK Demo)

This project is a containerized backend that utilizes the **Google Agent Development Kit (ADK)** to expose an Agent-to-Agent (A2A) microservice. It demonstrates a Warehouse Safety Agent (powered by Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using CRAWL/WALK/RUN logic.

This repository was built using `uv` for ultra-fast dependency management, is fully Dockerized for secure deployment to Google Cloud Run, and is natively integrated with **Gemini Enterprise (GE)** via the A2A protocol.

---

## 🌟 The Evolution: Local Prototyping (v0) vs. Gemini A2A (v1)

In **v0**, we wrote a massive chunk of custom boilerplate code:
* Manually created `InMemoryRunner` instances and managed `active_sessions` maps.
* Intercepted and parsed async event streams looking for `event.output` or nested `function_call.args`.
* Built strict `UserQuery` Pydantic models to capture simple incoming payloads.

**Why v0 breaks in Production with Gemini Enterprise:**
1. **Deeper Payload Envelopes:** The standard A2A protocol doesn't send flat JSON. It sends deeply nested structures (e.g., `userMessage.userContent.textContent.text` and `sessionId` in camelCase). 
2. **Strict Validation Errors:** If code expects `session_id` (snake_case) but Gemini sends `sessionId` (camelCase), FastAPI rejects the payload instantly with an HTTP `422 Unprocessable Entity` error before logic runs.
3. **Complexity of Protocol Maintenance:** Implementing gRPC, JSON-RPC envelopes, streaming protocols, and session context manually is error-prone and hard to upgrade.

### 💡 The ADK Solution: `to_a2a()`
The Google ADK provides the **`to_a2a()`** utility to handle this entire lifecycle cleanly. By passing your `expert` Agent to `to_a2a(expert)`, the ADK dynamically generates a complete FastAPI/Starlette application in-memory:
* **No Manual Input Mapping:** It auto-opens the Gemini A2A envelope, extracts the user's text, feeds it directly to the agent, and manages session history automatically.
* **Automatic Output Translation:** It maps your structured Pydantic output (`SafetyAssessment`) back into the required A2A format seamlessly.
* **Metadata Exposing:** It configures the `POST /` endpoint and auto-generates the `GET /.well-known/agent-card.json` metadata card for Gemini Enterprise discovery.

---

## 🛠️ 1. Local Setup & Initialization

This project requires `uv` to manage the virtual environment and dependencies seamlessly.

**Step 1: Create the directory and initialize `uv`**
```bash
mkdir v1-dockerized
cd v1-dockerized
uv init --app
```
*(Note: `uv init` creates a `pyproject.toml` and a default `hello.py`. Ensure your code is saved in `main.py`.)*

**Step 2: Install Web Dependencies**
Add the core web and GCP packages:
```bash
uv add fastapi uvicorn pydantic python-dotenv google-genai
```

**Step 3: Install the Google ADK and A2A Components (The Fix)**
To resolve `ModuleNotFoundError` for ADK and `JSONRPCApplication` startup errors, install these specific ADK packages:
```bash
uv pip install "google-adk[a2a]"
uv pip install "a2a-sdk[http-server]"
```
*(If behind a corporate proxy/Airlock: append `--index-url https://pypi.org/simple`)*

---

## ⚙️ 2. Environment Configuration & The Production Code

Create a `.env` file in your root directory. `uv` will automatically detect and load these variables:
```ini
GOOGLE_API_USE_CLIENT_CERTIFICATE=false
GOOGLE_CLOUD_PROJECT_ID="your-gcp-project-id"
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_LOCATION="us-central1"
```

### The Code (`main.py`)
Because the ADK abstracts routing, the code is incredibly lean. The ADK `to_a2a` wrapper takes 100% control of the `app` object.

```python
import os
import google.auth
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google.adk import Agent
from google.adk.models import google_llm
from google.adk.a2a.utils.agent_to_a2a import to_a2a 
from google.genai import client

# 1. ENVIRONMENT SETUP
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION")
if project_id: 
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

# 2. SCHEMAS & TOOLS
class SafetyAssessment(BaseModel):
    internal_thinking: str = Field(description="Explain how data relates to CRAWL/WALK/RUN.")
    risk_level: str = Field(description="Low, Medium, or High")
    recommended_action: str = Field(description="The specific step the operator should take.")
    shutdown_required: bool

def check_robot_sensors(robot_id: str):
    """Checks the real-time status of LiDAR, Bumpers, and 3D Vision for a robot."""
    return {
        "robot_id": robot_id, 
        "lidar": "OPERATIONAL", 
        "bumpers": "DEGRADED - Cleaning Required", 
        "vision_3d": "OPERATIONAL", 
        "safety_status": "CAUTION"
    }

# 3. INITIALIZE ENGINE COMPONENTS
credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"], quota_project_id=project_id)
vertex_client = client.Client(vertexai=True, project=project_id, location=google_cloud_location, credentials=credentials)
gemini_model = google_llm.Gemini(model="gemini-2.5-flash")
gemini_model.api_client = vertex_client

expert = Agent(
    name="collision_safety_expert", 
    model=gemini_model,  
    tools=[check_robot_sensors],
    output_schema=SafetyAssessment,  # Magic of output parsing happens here
    instruction="""
    You are an Operational Bot Collision Expert. 
    ALWAYS check sensor data using your tools before providing an assessment.
    Use CRAWL/WALK/RUN logic.
    """
)

# 4. EXPOSE AGENT AS A2A WEB APP
port = int(os.environ.get("PORT", 8080))
app = to_a2a(expert, port=port)
```

### Test Locally
Start the server:
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```
In a separate terminal, test the ADK auto-generated Agent Card:
```bash
curl http://localhost:8080/.well-known/agent-card.json
```

---

## 🐳 3. Dockerization & The Google Cloud Contract

When deploying containers to Google Cloud Run, the application must adhere to a strict container contract:

| Rule | Implementation |
| :--- | :--- |
| **Dynamic Port Binding** | Cloud Run dynamically injects `$PORT`. Handled in Dockerfile via `CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]` |
| **Workload Identity** | Never bake `.env` keys. `google.auth.default()` natively talks to the hidden GCP metadata server. |
| **Statelessness** | Do not trust local disk/memory. (Note: swap `InMemorySessionService` for `VertexAiSessionService` for production state persistence). |
| **Structured Logging** | Print to `stdout`/`stderr` only. Cloud Logging automatically ingests it. |
| **Non-Root Execution** | Run as a non-root user (`groupadd`/`useradd`) to prevent privilege escalation. |

### Export Requirements & Build Dockerfile
Since corporate builds (e.g., Airlock) can fail `uv sync` during cloud builds, export a flat `requirements.txt` first:
```bash
uv export --format requirements-txt > requirements.txt
```

**`Dockerfile`**
```dockerfile
# 1. Use the full python image (not slim) to get build tools out of the box
FROM python:3.11

# Create non-root user group and user for security posture
RUN groupadd -r appgroup && useradd -r -g appgroup -m appuser

WORKDIR /app
COPY requirements.txt .

# 3. Install standard requirements
RUN pip install --no-cache-dir -r requirements.txt --index-url https://pypi.org/simple

# 4. Install A2A dependencies
RUN pip install --no-cache-dir "google-adk[a2a]" "a2a-sdk[http-server]" --index-url https://pypi.org/simple

COPY . .

# Set permissions for non-root user
RUN chown -R appuser:appgroup /app
USER appuser

# 6. Expose the standard Cloud Run port
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

---

## ☁️ 4. Cloud Deployment Architecture

**Step 1: Auth & Project Config**
```bash
gcloud auth login --update-adc --no-launch-browser
gcloud config set project [YOUR_PROJECT_ID]
gcloud config set account [YOUR_ACCOUNT]
```

**Step 2: Artifact Registry Creation**
```bash
gcloud artifacts repositories create adk-demos \
    --repository-format=docker \
    --location=us-central1 \
    --description="Docker repository for ADK demos"
```

**Step 3: Configure IAM Permissions**
Cloud Build requires permissions to read/write, and Cloud Run needs permissions to call Vertex AI:
```bash
# Define service account variables
PROJECT_NUM=$(gcloud projects describe [YOUR_PROJECT_ID] --format="value(projectNumber)")
BUILD_SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] --member="serviceAccount:${BUILD_SA}" --role="roles/cloudbuild.builds.builder"
gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] --member="serviceAccount:${BUILD_SA}" --role="roles/storage.admin"
gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] --member="serviceAccount:${BUILD_SA}" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] --member="serviceAccount:${BUILD_SA}" --role="roles/logging.logWriter"
gcloud projects add-iam-policy-binding [YOUR_PROJECT_ID] --member="serviceAccount:${BUILD_SA}" --role="roles/aiplatform.user"
```

**Step 4: Build the Container**
Create a `cloudbuild.yaml` file:
```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-safety-agent:v1', '.']
    env:
      - 'DOCKER_BUILDKIT=1'
images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-safety-agent:v1'
```
Run the build:
```bash
gcloud builds submit --config cloudbuild.yaml .
```

**Step 5: Secure Cloud Run Deployment**
Deploying securely avoids organizational policy blocks on `allUsers`:
```bash
gcloud run deploy warehouse-safety-expert \
    --image us-central1-docker.pkg.dev/[YOUR_PROJECT_ID]/adk-demos/warehouse-safety-agent:v1 \
    --region us-central1 \
    --platform managed \
    --no-allow-unauthenticated \
    --set-env-vars GOOGLE_CLOUD_PROJECT_ID=[YOUR_PROJECT_ID],GOOGLE_CLOUD_LOCATION=us-central1
```

---

## 🤝 5. Gemini Enterprise (GE) Integration

**Step 1: Allow GE to Wake Up Cloud Run**
Gemini Enterprise runs in a Google-managed service account. Grant the Discovery Engine Service Agent explicit permission to invoke Cloud Run:
```bash
gcloud run services add-iam-policy-binding warehouse-safety-expert \
    --region=us-central1 \
    --member="serviceAccount:service-[YOUR_PROJECT_NUMBER]@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
    --role="roles/run.invoker"
```

**Step 2: Register the A2A Agent Card in GE**
1. Open the **Gemini Enterprise / Vertex AI Search and Conversation** console.
2. Under **Agents > Add Agents**, select **Custom agent via A2A** and click **Add**.
3. Paste the following JSON (ensure the `url` targets your base domain directly, as `to_a2a` hosts everything dynamically at `/`):

```json
{
  "protocolVersion": "0.3.0",
  "name": "warehouse_safety_expert",
  "description": "An Operational Bot Collision Expert that evaluates real-time sensor data (LiDAR, Bumpers, 3D Vision) using CRAWL/WALK/RUN logic.",
  "url": "https://warehouse-safety-expert-xxxx.us-central1.run.app",
  "version": "1.0.0",
  "capabilities": {},
  "skills": [
    {
      "id": "analyze-safety",
      "name": "Analyze Robot Safety",
      "description": "Evaluates if a robot is safe to operate based on current sensor status.",
      "tags": ["safety", "robotics", "sensors"],
      "examples": [
        "Check robot_id_456 and tell me if it is safe to operate.",
        "Check sensors on robot 456"
      ]
    }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"]
}
```

### Try it out!
Open the Gemini Enterprise web interface and prompt your agent:
> *"Hey, can you ask the Warehouse Safety Expert to check sensors on robot 456?"*
