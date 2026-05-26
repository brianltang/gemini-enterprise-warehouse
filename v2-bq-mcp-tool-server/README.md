# Warehouse Safety Expert API (ADK Demo)

This project is a containerized backend that utilizes the **Google Agent Development Kit (ADK)** to expose an Agent-to-Agent (A2A) microservice. It demonstrates a **Warehouse Safety Expert** (powered by Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using BigQuery telemetry and **CRAWL/WALK/RUN** logic.

This repository was built using `uv` for ultra-fast dependency management, uses the **Model Context Protocol (MCP)** to decouple tool logic, and is natively integrated with **Gemini Enterprise (GE)** via the A2A protocol.

---

## **🌟 The Evolution: Local Prototyping vs. MCP-Driven ADK (v2)**

In previous versions (**v0/v1**), we wrote monolithic boilerplate code where tools were hardcoded inside the agent's main script.

**Why that approach breaks in Production with Gemini Enterprise:**

1. **Deeper Payload Envelopes:** The standard A2A protocol doesn't send flat JSON. It sends deeply nested structures (e.g., `userMessage.userContent.textContent.text`). Using the ADK's `to_a2a` wrapper handles this automatically.

2. **Strict Validation Errors:** If your code expects `session_id` (snake_case) but Gemini sends `sessionId` (camelCase), FastAPI rejects the payload instantly with a `422 Unprocessable Entity` error.

3. **Complexity of Tool Maintenance:** In v2, we move to **Model Context Protocol (MCP)**. This decouples the BigQuery logic into a standalone "Tool Server." The Agent dynamically discovers tools over `stdio`, meaning you can update your database queries without ever restarting or redeploying your LLM logic.

---

## **🛠️ Phase 1: Environment & Dependencies**

### **1. Set up Tool Server packages**
The Tool Server is a standalone **FastMCP** instance that handles the BigQuery connection.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server
uv init --app
uv add mcp google-cloud-bigquery python-dotenv
```

### **2. Set up Agent packages**
The Agent Service hosts the Gemini model and the A2A FastAPI endpoint.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
uv init --app
uv add fastapi uvicorn pydantic python-dotenv google-genai google-cloud-bigquery
uv pip install "google-adk[a2a]" "a2a-sdk[http-server]" mcp
```

---

## **🗄️ Phase 2: Database Provisioning (BigQuery)**

Before running the agent, we need to populate BigQuery with an 8-hour telemetry dataset that contains hidden anomalies (hardware failures, environmental stress, etc.) for the LLM to discover.

### **1. Authenticate and Create Schema**

```bash
# Authenticate with the correct workspace principal
gcloud auth login admin@brianltang.altostrat.com --update-adc --no-launch-browser

# Create the dataset
bq mk --location=us-central1 --dataset blt-test-project-2:warehouse_ops

# Create the telemetry table
bq mk --table blt-test-project-2:warehouse_ops.robot_telemetry \
robot_id:STRING,timestamp:TIMESTAMP,zone:STRING,lidar_status:STRING,bumper_status:STRING,vision_3d_status:STRING,battery_level:FLOAT
```

### **2. Inject 8-Hour Insight Dataset**

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

## **🚀 Phase 3: Booting the Server (Local Development)**

Start the FastAPI server. The Agent will automatically spawn the MCP Tool Server as a subprocess and bind the tools to Gemini.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## **🐳 Phase 4: Containerization & Cloud Run Deployment**

### **1. Build Locally (Verification)**
```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/
docker build -t warehouse-safety-agent .
```

### **2. Cloud Build Deployment**
Use the `cloudbuild.yaml` configuration to build and push to Artifact Registry.

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1', '.']
    env: ['DOCKER_BUILDKIT=1']
images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1'
```

Submit the build:
```bash
gcloud builds submit --config=cloudbuild.yaml --project="blt-test-project-2"
```

### **3. Grant Identity & Permissions (IAM)**
Grant the default compute service account permissions for BigQuery and Vertex AI.

```bash
PROJECT_NUMBER=$(gcloud projects describe blt-test-project-2 --format='value(projectNumber)')

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

### **4. Deploy to Cloud Run**
```bash
gcloud run deploy warehouse-mcp-expert-service \
  --image us-central1-docker.pkg.dev/blt-test-project-2/adk-demos/warehouse-mcp-expert:v1 \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2,GOOGLE_CLOUD_LOCATION=us-central1,TOOL_SERVER_PATH=/app/bq-mcp-server/main.py" \
  --project="blt-test-project-2"
```

---

## **🧪 Phase 5: Testing the API**

### **Catastrophic Crash (BOT-07)**
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
