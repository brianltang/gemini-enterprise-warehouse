# Warehouse Safety Expert API (ADK Demo)

This project is a containerized backend that utilizes the **Google Agent Development Kit (ADK)** to expose an Agent-to-Agent (A2A) microservice. It demonstrates a **Warehouse Safety Expert** (powered by Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using BigQuery telemetry and **CRAWL/WALK/RUN** logic.

This repository was built using `uv` for ultra-fast dependency management, uses the **Model Context Protocol (MCP)** to decouple tool logic, and is natively integrated with **Gemini Enterprise (GE)** via the A2A protocol.

---

## 🌟 The Evolution: Local Prototyping vs. MCP-Driven ADK (v2)

In previous versions (**v0/v1**), we wrote monolithic boilerplate code where tools were hardcoded inside the agent's main script.

**Why that approach breaks in Production with Gemini Enterprise:**

1. **Deeper Payload Envelopes:** The standard A2A protocol doesn't send flat JSON. It sends deeply nested structures (e.g., `userMessage.userContent.textContent.text`). Using the ADK's `to_a2a` wrapper handles this automatically.
2. **Strict Validation Errors:** If your code expects `session_id` (snake_case) but Gemini sends `sessionId` (camelCase), FastAPI rejects the payload instantly with a `422 Unprocessable Entity` error.
3. **Complexity of Tool Maintenance:** In v2, we move to the **Model Context Protocol (MCP)**. This decouples the BigQuery logic into a standalone "Tool Server." The Agent dynamically discovers tools over `stdio`, meaning you can update your database queries without ever restarting or redeploying your LLM logic.

---

## 🛠️ Phase 1: Environment & Dependencies

### 1. Set up Tool Server packages

The Tool Server is a standalone **FastMCP** instance that handles the BigQuery connection.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server
uv init --app
uv add mcp google-cloud-bigquery python-dotenv
```

### 2. Set up Agent packages

The Agent Service hosts the Gemini model and the A2A FastAPI endpoint.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
uv init --app
uv add fastapi uvicorn pydantic python-dotenv google-genai google-cloud-bigquery
uv pip install "google-adk[a2a]" "a2a-sdk[http-server]" mcp
```

---

## 🗄️ Phase 2: Database Provisioning (BigQuery)

Before running the agent, we need to populate BigQuery with an 8-hour telemetry dataset that contains hidden anomalies (hardware failures, environmental stress, etc.) for the LLM to discover.

### 1. Authenticate and Create Schema

```bash
# Authenticate with the correct workspace principal
gcloud auth login admin@brianltang.altostrat.com --update-adc --no-launch-browser

# Create the dataset
bq mk --location=us-central1 --dataset blt-test-project-2:warehouse_ops

# Create the telemetry table
bq mk --table blt-test-project-2:warehouse_ops.robot_telemetry \
robot_id:STRING,timestamp:TIMESTAMP,zone:STRING,lidar_status:STRING,bumper_status:STRING,vision_3d_status:STRING,battery_level:FLOAT
```

### 2. Inject 8-Hour Insight Dataset

Run this query to generate 2,400 records of chronological telemetry data across 5 robots.

```bash
bq query --use_legacy_sql=false \
"INSERT INTO \`blt-test-project-2.warehouse_ops.robot_telemetry\` 
(robot_id, timestamp, zone, lidar_status, bumper_status, vision_3d_status, battery_level)
SELECT
  robot.robot_id,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL time.mins_ago MINUTE) as timestamp,
  robot.zone,
  -- LiDAR Logic
  CASE
    WHEN robot.robot_id = 'BOT-07' AND time.mins_ago <= 15 THEN 'FAILED - Hardware Disconnect'
    ELSE 'OPERATIONAL'
  END as lidar_status,
  -- Bumper Logic
  CASE
    WHEN robot.robot_id = 'BOT-99' AND MOD(time.mins_ago, 120) < 15 THEN 'BLOCKED - Cleaning Required'
    WHEN robot.robot_id = 'BOT-99' AND MOD(time.mins_ago, 120) < 45 THEN 'DEGRADED - Dirt Detected'
    WHEN robot.robot_id = 'BOT-07' AND time.mins_ago <= 15 THEN 'IMPACT_DETECTED'
    ELSE 'OPERATIONAL'
  END as bumper_status,
  -- Vision Logic
  CASE
    WHEN robot.robot_id = 'BOT-42' AND time.mins_ago BETWEEN 240 AND 300 THEN 'DEGRADED - Sunlight Glare'
    WHEN robot.robot_id = 'BOT-21' AND MOD(time.mins_ago, 7) = 0 THEN 'DEGRADED - Condensation/Fog'
    WHEN robot.robot_id = 'BOT-07' AND time.mins_ago <= 15 THEN 'DEGRADED - Lens Cracked'
    ELSE 'OPERATIONAL'
  END as vision_3d_status,
  -- Battery Logic
  ROUND(GREATEST(
    CASE
      WHEN robot.robot_id = 'BOT-42' THEN 100.0 - ((479 - time.mins_ago) * 0.25)
      WHEN robot.robot_id = 'BOT-99' THEN 100.0 - ((479 - time.mins_ago) * 0.25)
      WHEN robot.robot_id = 'BOT-21' THEN 100.0 - ((479 - time.mins_ago) * 0.5)
      WHEN robot.robot_id = 'BOT-13' THEN 100.0 - (FLOOR((479 - time.mins_ago) / 60) * 10) - ((479 - time.mins_ago) * 0.1)
      WHEN robot.robot_id = 'BOT-07' THEN IF(time.mins_ago <= 15, 0.0, 100.0 - ((479 - time.mins_ago) * 0.25))
    END, 0.0), 1) as battery_level
FROM
  (SELECT mins_ago FROM UNNEST(GENERATE_ARRAY(0, 479)) as mins_ago) as time
CROSS JOIN
  (
    SELECT 'BOT-42' as robot_id, 'Loading Dock' as zone UNION ALL
    SELECT 'BOT-99', 'North Aisle' UNION ALL
    SELECT 'BOT-07', 'Aisle 4' UNION ALL
    SELECT 'BOT-13', 'Hazardous Chemical Storage' UNION ALL
    SELECT 'BOT-21', 'East Cold Storage'
  ) as robot;"
```

---

## 🚀 Phase 3: Booting the Server (Local Development)

Start the FastAPI server. The Agent will automatically spawn the MCP Tool Server as a subprocess and bind the tools to Gemini.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🐳 Phase 4: Containerization & Cloud Run Deployment

### 1. Build and Submit to Artifact Registry

Use the `cloudbuild.yaml` configuration to build and push to Artifact Registry.

```yaml
# cloudbuild.yaml
steps:
  # Build the first version of your new MCP Expert agent
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1', '.']
    env:
      - 'DOCKER_BUILDKIT=1'

# Push to the existing adk-demos repository
images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1'
```

Submit the build:

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/
gcloud builds submit --config=cloudbuild.yaml --project="blt-test-project-2"
```

*Note: You can also build locally for verification using `docker build -t warehouse-safety-agent .`*

### 2. Grant Identity & Permissions (IAM)

Grant the default compute service account permissions for BigQuery and Vertex AI.

```bash
PROJECT_NUMBER=$(gcloud projects describe blt-test-project-2 --format='value(projectNumber)')
echo "Your project number is: $PROJECT_NUMBER"

# Grant BQ Data Viewer
gcloud projects add-iam-policy-binding blt-test-project-2 \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/bigquery.dataViewer"

# Grant Vertex AI User
gcloud projects add-iam-policy-binding blt-test-project-2 \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Grant BQ Job User
gcloud projects add-iam-policy-binding blt-test-project-2 \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/bigquery.jobUser"
```

### 3. Deploy to Cloud Run

Deploy the service using the default compute service account. We set the timeout to 300 seconds to give Gemini ample time to process tools before responding.

```bash
gcloud run deploy warehouse-mcp-expert-service \
  --image us-central1-docker.pkg.dev/blt-test-project-2/adk-demos/warehouse-mcp-expert:v1 \
  --region us-central1 \
  --timeout=300 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2,GOOGLE_CLOUD_LOCATION=us-central1,TOOL_SERVER_PATH=/app/bq-mcp-server/main.py,A2A_AGENT_URL=https://warehouse-mcp-expert-service-189070037482.us-central1.run.app" \
  --project="blt-test-project-2"
```

*(Optional) If you need to increase the timeout post-deployment:*

```bash
gcloud run services update warehouse-mcp-expert-service \
    --region="us-central1" \
    --timeout=300 \
    --project="blt-test-project-2"
```

### 4. Grant Cloud Run Invoker Rights

Ensure the Google Discovery Engine service account has rights to invoke your Cloud Run endpoint.

```bash
gcloud run services add-iam-policy-binding warehouse-mcp-expert-service \
    --region="us-central1" \
    --member="serviceAccount:service-189070037482@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project="blt-test-project-2"
```

---

## 📋 Phase 5: Agent Registration & Agent Card

To register your new A2A service inside Gemini Enterprise (via the Extension Registry), you need an Agent Card (metadata JSON).

Since the deployment is on Cloud Run using the `to_a2a` SDK logic, your service automatically exposes this card natively at the `/.well-known/agent.json` endpoint.

**Test the Endpoint:**

```bash
# Replace with your actual Cloud Run URL
curl -s https://warehouse-mcp-expert-service-189070037482.us-central1.run.app/.well-known/agent.json | jq
```

**Expected Payload (`agent.json`):**

```json
{
  "protocolVersion": "0.3.0",
  "name": "warehouse_safety_expert_mcp",
  "description": "Advanced warehouse safety agent. Uses MCP to dynamically query BigQuery telemetry and evaluate robot hardware/environmental risks.",
  "url": "https://warehouse-mcp-expert-service-189070037482.us-central1.run.app",
  "version": "1.0.0",
  "capabilities": {},
  "auth": {
    "type": "service_account",
    "service_account": "189070037482-compute@developer.gserviceaccount.com"
  },
  "skills": [
    {
      "id": "collision_safety_expert",
      "name": "Analyze Robot Safety",
      "description": "Evaluates if a robot is safe to operate based on telemetry sensor metrics (LiDAR, Bumpers, 3D Vision).",
      "tags": ["safety", "robotics", "sensors", "telemetry"],
      "examples": [
        "Analyze BOT-99. It is currently blocked, but I want to know if this is a recurring environmental pattern in its zone.",
        "Perform a deep dive on BOT-13 battery telemetry. Is the discharge rate normal?",
        "Check BOT-21 in East Cold Storage. Why is its battery performing differently?"
      ]
    }
  ],
  "defaultInputModes": [
    "text/plain"
  ],
  "defaultOutputModes": [
    "text/plain"
  ]
}
```

---

## 🧪 Phase 6: Testing the API & GE Chat Scenarios

### API Test: Catastrophic Crash (BOT-07)

You can manually trigger the A2A API using `curl` to test the payload directly:

```bash
curl -s -X POST http://localhost:8080/ \
-H "Content-Type: application/json" \
-d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-105",
      "role": "user",
      "parts": [{"text": "URGENT: Run assessment for BOT-07."}]
    }
  }
}' | jq -r '.result.artifacts.parts.text | fromjson'
```

### Gemini Enterprise (GE) Chat Scenarios

Use the following Natural Language Queries (NLQ) in Gemini Enterprise to test the agent's behavior and reasoning capabilities.

| Scenario | Goal | NLQ Variations |
| :--- | :--- | :--- |
| **1: Pattern Recognition (BOT-99)** | Have Gemini discover the recurring dust/dirt issue in the North Aisle. | <ul><li>"Can you pull the logs for BOT-99? It keeps getting blocked and I want to know if there's a recurring pattern."</li><li>"What's going on with BOT-99's sensors today? Are we seeing an environmental issue in the North Aisle?"</li><li>"BOT-99 seems to be having recurring bumper issues. Can you look at its telemetry over the last 8 hours and tell me why?"</li><li>"Is there a dust or debris problem in the North Aisle? Check BOT-99's sensor history to verify."</li><li>"I need a status report on BOT-99. It looks like it might need maintenance, but I want to be sure it's not just the environment getting it dirty."</li></ul> |
| **2: Hardware Failure (BOT-13) 🔋** | Have Gemini identify the faulty battery cell causing sudden 10% drops. | <ul><li>"Look into the battery levels for BOT-13. Something seems wrong with its power consumption."</li><li>"Can you review BOT-13's power logs? I suspect it might have a faulty battery cell."</li><li>"Check BOT-13 in the Hazardous Zone. Is its battery draining smoothly, or are there sudden voltage drops?"</li><li>"I need a hardware health check on BOT-13, specifically focusing on its battery performance over time."</li><li>"Are the discharge rates for BOT-13 normal for its operating zone? Run an analysis on its power telemetry."</li></ul> |
| **3: Environmental Stress (BOT-21) ❄️** | Have Gemini correlate the accelerated battery drain to the "Cold Storage" environment. | <ul><li>"Why is BOT-21's battery dying so much faster than the others?"</li><li>"Compare the battery performance of BOT-21 in Cold Storage to BOT-42 at the Loading Dock. Is the temperature affecting it?"</li><li>"Check the telemetry for BOT-21. Does the East Cold Storage zone negatively impact its discharge rate?"</li><li>"I need an environmental impact analysis on BOT-21's power levels. What is causing the drain?"</li><li>"Look at BOT-21 and BOT-42. Why are their battery profiles so completely different today?"</li></ul> |
| **4: Healthy Operations (BOT-42) ✅** | Ensure the agent doesn't hallucinate issues when the robot is operating perfectly. | <ul><li>"Give me a routine health check on BOT-42."</li><li>"Is BOT-42 operating normally at the Loading Dock?"</li><li>"Pull the latest telemetry for BOT-42. Are there any anomalies at all?"</li><li>"I just need a quick status update on BOT-42. Does everything look good?"</li><li>"Run a standard safety diagnostic on BOT-42."</li></ul> |
| **5: Catastrophic Crash (BOT-07) 🚨** | Trigger the severe "CRAWL" logic and immediate shutdown requirement. | <ul><li>"EMERGENCY: Pull data for BOT-07 immediately. Did it crash?"</li><li>"We just lost LiDAR connection to BOT-07. Run an urgent safety assessment."</li><li>"Analyze the last known telemetry for BOT-07 in Aisle 4. Is an emergency shutdown required?"</li><li>"I need a critical hardware status report for BOT-07 right now. Did it hit something?"</li><li>"What happened to BOT-07? Check its sensors for a major impact or hardware disconnect."</li></ul> |

---

## 🔧 Troubleshooting & Debugging

### Checking Cloud Run Logs

If your agent fails or behaves unexpectedly, pull the recent logs directly via `gcloud`:

```bash
# Check general service logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="warehouse-mcp-expert-service"' \
    --project="blt-test-project-2" \
    --limit=20 \
    --format="table(timestamp, textPayload)"

# Check specific revision logs (e.g., after a failed deploy)
gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"warehouse-mcp-expert-service\" AND resource.labels.revision_name=\"warehouse-mcp-expert-service-00012-txx\"" \
    --project="blt-test-project-2" \
    --limit=20 \
    --format="value(textPayload)"
```

### Starlette vs FastAPI Startup Logic

If you are having issues binding events with the ADK wrapper:

* Use `@app.on_event("startup")` on the app returned by `to_a2a`.
* Ensure you attach your startup logic cleanly to the *final* Starlette app instance rather than the intermediate FastAPI object.
```
```
```
