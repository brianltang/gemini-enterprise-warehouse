# Warehouse Safety Expert API (V3 - Autonomous Investigator)

This project is a containerized backend that utilizes the **Google Agent Development Kit (ADK)** to expose an Agent-to-Agent (A2A) microservice. It demonstrates a **Warehouse Safety Expert** (powered by Gemini) that evaluates robot sensor data from BigQuery, uses **CRAWL/WALK/RUN** logic, and now features **autonomous, multi-turn diagnostic investigation** capabilities.

This repository uses `uv` for dependency management, the **Model Context Protocol (MCP)** to decouple tool logic from the agent, and is natively integrated with **Gemini Enterprise (GE)** via the A2A protocol.

---

## 🌟 The Evolution: From v1 Monolith to V3 Autonomous Agent

This project has evolved significantly to showcase a production-grade, resilient, and intelligent agent architecture.

1.  **V1 (Monolithic):** Tools were hardcoded inside the agent's main script. This was brittle and hard to maintain.
2.  **V2 (Decoupled MCP):** We moved the BigQuery logic into a standalone "Tool Server" using the Model Context Protocol (MCP). The agent dynamically discovered tools over `stdio`, allowing for independent updates. However, this introduced new challenges with performance and AI reasoning.
3.  **V3 (Optimized & Autonomous):** This version represents a production-ready architecture with critical improvements:
    *   **Persistent Connections:** We eliminated the massive performance bottleneck of spawning a new process for every tool call. The agent now maintains a single, persistent connection to the Tool Server for the entire application lifespan, resulting in near-instantaneous tool execution.
    *   **Ironclad Pydantic Schemas:** To solve "loosy-goosy" AI behavior, the agent now dynamically builds strict `Pydantic` models from the tool server's schemas. This forces the AI to adhere to correct data types (`int` vs. `str`) and required parameters, eliminating crashes and hallucinated tool calls.
    *   **Autonomous Investigator Prompting:** The agent's instructions have been upgraded to give it a "Reason and Act" (ReAct) protocol. It is now authorized to autonomously perform follow-up investigations (e.g., check historical trends after seeing a real-time anomaly) without asking the user for permission, delivering a complete root-cause analysis in a single turn.

---

## 🛠️ Phase 1: Environment & Dependencies

This phase sets up two isolated Python environments using `uv`, a high-speed package manager.

### 1. Set up Tool Server packages (`bq-mcp-server`)

This command initializes an environment for our "Tool Server," which will directly interact with BigQuery. We add `mcp` for the tool protocol, `google-cloud-bigquery` for database access, and `python-dotenv` for managing environment variables.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server
uv init --app
uv add mcp google-cloud-bigquery python-dotenv
```

### 2. Set up Agent packages (`agent-service`)

This initializes the environment for our "Agent Service," the AI's brain. It includes `fastapi` and `uvicorn` for the web server, `pydantic` for data validation, and the Google ADK/A2A/MCP SDKs to communicate with Gemini and the Tool Server.

```bash
cd ~/Projects/adk-basic/v3-dockerized/agent-service
uv init --app
uv add fastapi uvicorn pydantic python-dotenv google-genai google-cloud-bigquery
uv pip install "google-adk[a2a]" "a2a-sdk[http-server]" mcp
```

---

## 🗄️ Phase 2: Database Provisioning (BigQuery)

This phase prepares the backend database with a rich, realistic dataset for the agent to analyze.

### 1. Authenticate and Create Schema

These commands set up the necessary structure in BigQuery. First, we log into Google Cloud. Then, we use the `bq` command-line tool to create a `dataset` (like a database schema) called `warehouse_ops` and a `table` within it called `robot_telemetry` with specific columns and data types.

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

This powerful SQL query generates and inserts 2,400 realistic-looking telemetry records into our new table. It simulates 8 hours of data (`GENERATE_ARRAY(0, 479)`) for 5 different robots. Crucially, the `CASE` statements are used to intentionally "bake in" anomalies and specific failure patterns (like hardware disconnects, sensor blockages, and sudden battery drops) for the agent to later discover through its investigation.

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

## 💻 Phase 3: Architectural Deep Dive & Code Breakdown

Rather than deploying monolithic scripts, V3 uses a highly optimized, decoupled design patterns. Let’s break down the three most critical components of the codebase.

### 1. Dynamic Pydantic Schema Compilation (The Interface)
To bridge the gap between JSON-RPC (MCP) and Python type hints (ADK), we dynamically compile Pydantic schemas using the tool definitions discovered at startup.

```python
# Inside build_tool_wrappers()
InputModel = create_model(
    f"{t_name}_input",
    __base__=BaseModel,
    **{
        prop_name: (
            str if prop_info.get("type") == "string" else
            int if prop_info.get("type") == "integer" else
            float if prop_info.get("type") == "number" else
            bool if prop_info.get("type") == "boolean" else dict,
            Field(
                default=... if prop_name in t_schema.get("required", []) else prop_info.get("default", None),
                description=prop_info.get("description", "")
            )
        )
        for prop_name, prop_info in t_schema.get("properties", {}).items()
    }
)
```
* **Why this is critical:** Standard MCP servers declare dynamic JSON schemas. By feeding these into Pydantic at boot, we force Gemini to strictly respect variable constraints (like casting the lookback period `hours` strictly to a Python `int`). If Gemini tries to call a tool incorrectly, the A2A gateway intercepts and corrects it before it crashes the BigQuery driver.

### 2. Persistent Stream Multiplexing (The Lifespan)
Older systems spawned a new sub-process on every single tool execution. V3 mounts a persistent stdio session within FastAPI's lifespan configuration.

```python
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    # Spawns background process ONCE on FastAPI bootup
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            expert.tools = await build_tool_wrappers(session)
            yield # Keep connection open while server runs
```
* **Why this is critical:** Spawning a Python subprocess, authenticating with Google Cloud Application Default Credentials (ADC), and initializing the BigQuery driver on every turn takes 3–5 seconds. This lifecycle keeps the subprocess open in the background. Subsequent tool calls execute in milliseconds using standard JSON-RPC stream multiplexing.

### 3. Factory Closure Scoping (The Executor)
When dynamically generating async functions inside loops, standard Python closures can leak variable scopes. V3 uses a factory function to ensure clean tool isolation.

```python
def create_wrapper(tool_name):
    async def mcp_tool_wrapper(params: InputModel):
        arguments = params.model_dump()
        try: 
            response = await session.call_tool(tool_name, arguments=arguments)
            return "\n".join([c.text for c in response.content if hasattr(c, 'text')])
        except Exception as e:
            print(f"CRITICAL: Tool call to '{tool_name}' failed: {e}")
            return "ERROR: The telemetry system is temporarily offline."
    return mcp_tool_wrapper
```
* **Why this is critical:** Without the `create_wrapper` factory function, Python's lazy evaluation would cause every discovered tool wrapper to invoke whichever `t_name` was evaluated *last* in the dynamic registration loop. This factory explicitly locks the `tool_name` namespace per generated tool.

---

## 🚀 Phase 4: Local Development

These commands start the web server on your local machine. The `export` command sets your Google Cloud project, and the `uv run` command starts the `uvicorn` web server, pointing it to the `app` object in your `main.py` file.

```bash
cd ~/Projects/adk-basic/v3-dockerized/agent-service
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🐳 Phase 5: Containerization & Cloud Run Deployment

This phase packages the entire application into a Docker container and deploys it to a scalable, serverless environment on Google Cloud.

### 1. Unified Dockerfile

The `Dockerfile` is a blueprint for building our container.
*   `COPY`: It copies both the `agent-service` and `bq-mcp-server` directories into the container's filesystem.
*   `RUN uv pip install`: It installs all necessary Python libraries into the container.
*   `ENV`: It sets crucial environment variables. `TOOL_SERVER_PATH` tells the agent where to find the tool server *inside the container*, and `PYTHONPATH` ensures Python can find the `agent-service` module.
*   `CMD`: This is the command that runs when the container starts, launching our Uvicorn web server.

```dockerfile
# Use the official uv image with Python 3.13
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# 1. Copy both project folders into the container
COPY bq-mcp-server /app/bq-mcp-server
COPY agent-service /app/agent-service

# 2. Install all dependencies into the system's Python environment
RUN uv pip install --system --no-cache \
    "google-adk[a2a]" \
    "a2a-sdk[http-server]" \
    "mcp" \
    "fastapi" \
    "uvicorn" \
    "pydantic" \
    "google-cloud-bigquery" \
    "python-dotenv" \
    "google-genai"

# 3. Set environment variables for the container
ENV TOOL_SERVER_PATH=/app/bq-mcp-server/main.py
ENV GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

EXPOSE 8080

# 4. Start the Agent Service's Uvicorn server
CMD ["uvicorn", "agent-service.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 2. Build and Submit with Cloud Build

The `cloudbuild.yaml` file tells Google Cloud Build how to build the Docker image from our `Dockerfile`. The `gcloud builds submit` command initiates this process, which builds the container and pushes it to Google's Artifact Registry.

```yaml
# cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1', '.']
    env:
      - 'DOCKER_BUILDKIT=1'

images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/adk-demos/warehouse-mcp-expert:v1'
```

Submit the build:

```bash
cd ~/Projects/adk-basic/v3-dockerized/
gcloud builds submit --config=cloudbuild.yaml --project="blt-test-project-2"
```

### 3. Grant IAM Permissions

These commands give the Cloud Run service the necessary permissions to operate. We grant its service account the ability to run jobs and read data in BigQuery (`bigquery.jobUser`, `bigquery.dataViewer`) and the ability to call the Gemini AI model (`aiplatform.user`).

```bash
PROJECT_NUMBER=$(gcloud projects describe blt-test-project-2 --format='value(projectNumber)')
SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant BigQuery Reader & Workspace Privileges
gcloud projects add-iam-policy-binding blt-test-project-2 --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding blt-test-project-2 --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.jobUser"

# Grant Vertex AI User for LLM execution
gcloud projects add-iam-policy-binding blt-test-project-2 --member="serviceAccount:${SA_EMAIL}" --role="roles/aiplatform.user"
```

### 4. Deploy to Cloud Run

This command takes the container image we built and deploys it as a scalable microservice. `--allow-unauthenticated` makes it a public endpoint, and `--set-env-vars` passes necessary configuration to the running container.

```bash
gcloud run deploy warehouse-mcp-expert-service \
  --image us-central1-docker.pkg.dev/blt-test-project-2/adk-demos/warehouse-mcp-expert:v1 \
  --region us-central1 \
  --timeout=300 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT_ID=blt-test-project-2,GOOGLE_CLOUD_LOCATION=us-central1,TOOL_SERVER_PATH=/app/bq-mcp-server/main.py" \
  --project="blt-test-project-2"
```

### 5. Grant Cloud Run Invoker Rights

This final permission step allows other Google Cloud services (specifically, the Discovery Engine service account used by Gemini Enterprise extensions) to securely call our new Cloud Run endpoint.

```bash
gcloud run services add-iam-policy-binding warehouse-mcp-expert-service \
    --region="us-central1" \
    --member="serviceAccount:service-189070037482@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project="blt-test-project-2"
```

---

## 🧪 Phase 6: Verification & BigQuery Telemetry Tests

These SQL queries are for you to run manually in the BigQuery console. Their purpose is to prove that the insights provided by the AI agent are factually correct and directly derivable from the raw data, ensuring the agent is not "hallucinating."

### 1. Prove LiDAR Stability (BOT-13)

This query verifies the agent's claim that BOT-13's LiDAR was 100% operational over the past week. It should return only one row for the "OPERATIONAL" status with a count of 480.

```sql
SELECT
  lidar_status,
  COUNT(*) AS total_pings
FROM
  `blt-test-project-2.warehouse_ops.robot_telemetry`
WHERE
  robot_id = 'BOT-13'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
GROUP BY
  lidar_status;
```
*   **Expected Result:** A single row with status `OPERATIONAL` and a count of `480`.

### 2. Prove Power Log Degradation (BOT-13)

This query confirms the agent's diagnosis of a faulty battery by calculating the min, max, and average battery levels. The key finding should be a `min_battery` of 0.0%, which validates the warning.

```sql
SELECT
  robot_id,
  AVG(battery_level) AS avg_battery,
  MIN(battery_level) AS min_battery,
  MAX(battery_level) AS max_battery,
  COUNT(*) AS data_points
FROM
  `blt-test-project-2.warehouse_ops.robot_telemetry`
WHERE
  robot_id = 'BOT-13'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
GROUP BY
  robot_id;
```
*   **Expected Result:** `avg_battery` ≈ 42.96%, `min_battery` = 0.0%, `max_battery` = 100.0%.

### 3. Verify No Anomalies (BOT-42)

This query proves that BOT-42 is operating perfectly by grouping all its sensor statuses. A healthy robot should only have one combination of statuses: all `OPERATIONAL`.

```sql
SELECT
  lidar_status,
  bumper_status,
  vision_3d_status,
  COUNT(*) as occurrences
FROM
  `blt-test-project-2.warehouse_ops.robot_telemetry`
WHERE
  robot_id = 'BOT-42'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 168 HOUR)
GROUP BY 1, 2, 3;
```
*   **Expected Result:** A single row where all three status columns are `OPERATIONAL`.

---

## 🤖 Phase 7: Gemini Enterprise Chat Scenarios

Use these natural language queries in Gemini Enterprise to test the agent's autonomous reasoning and diagnostic capabilities across different failure modes.

| Scenario | Goal | NLQ Variations |
| :--- | :--- | :--- |
| **Pattern Recognition** | Have Gemini discover the recurring dust/dirt issue for BOT-99. | "Can you pull the logs for BOT-99? It keeps getting blocked and I want to know if there's a recurring pattern." <br/> "What's going on with BOT-99's sensors today? Are we seeing an environmental issue in the North Aisle?" |
| **Hardware Failure** | Have Gemini identify the faulty battery cell on BOT-13 causing sudden 10% drops. | "Look into the battery levels for BOT-13. Something seems wrong with its power consumption." <br/> "Can you review BOT-13's power logs? I suspect it might have a faulty battery cell." |
| **Environmental Stress** | Have Gemini correlate BOT-21's accelerated battery drain to the "Cold Storage" environment. | "Why is BOT-21's battery dying so much faster than the others?" <br/> "Compare the battery performance of BOT-21 in Cold Storage to BOT-42 at the Loading Dock." |
| **Healthy Operations** | Ensure the agent doesn't hallucinate issues for a perfectly healthy robot (BOT-42). | "Give me a routine health check on BOT-42." <br/> "Pull the latest telemetry for BOT-42. Are there any anomalies at all?" |
| **Catastrophic Crash** | Trigger the severe CRAWL logic and immediate shutdown requirement for BOT-07. | "EMERGENCY: Pull data for BOT-07 immediately. Did it crash?" <br/> "We just lost LiDAR connection to BOT-07. Run an urgent safety assessment." |

---