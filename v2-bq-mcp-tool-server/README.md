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

### 1. Set up Tool Server packages (`bq-mcp-server`)

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server
uv init --app
uv add mcp google-cloud-bigquery python-dotenv
```

### 2. Set up Agent packages (`agent-service`)

```bash
cd ~/Projects/adk-basic/v3-dockerized/agent-service
uv init --app
uv add fastapi uvicorn pydantic python-dotenv google-genai google-cloud-bigquery
uv pip install "google-adk[a2a]" "a2a-sdk[http-server]" mcp
```

---

## 🗄️ Phase 2: Database Provisioning (BigQuery)

Populate BigQuery with an 8-hour telemetry dataset containing hidden anomalies for the agent to discover.

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

## 💻 Phase 3: Core Codebase

### 1. The BigQuery MCP Tool Server (`bq-mcp-server/main.py`)

This script runs the dynamic BigQuery query execution layer. It exposes Python functions as tools over a standard I/O (stdio) JSON-RPC channel.

```python
# ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server/main.py
import os
import sys
import asyncio
from mcp.server.fastmcp import FastMCP
from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv(override=True)
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
bq_client = bigquery.Client(project=project_id)

# Initialize FastMCP instead of standard Server
server = FastMCP("bq-tool-server")

@server.tool()
async def check_robot_sensors(robot_id: str) -> str:
    """
    Fetches real-time sensor status for a robot from BigQuery. Use for safety assessments.

    Args:
        robot_id: The unique ID of the robot (e.g., BOT-99, JETSON-ORIN-01)
    """
    query = """
        SELECT zone, lidar_status, bumper_status, vision_3d_status, battery_level, timestamp
        FROM `warehouse_ops.robot_telemetry`
        WHERE robot_id = @robot_id
        ORDER BY timestamp DESC
        LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("robot_id", "STRING", robot_id)]
    )
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query, job_config=job_config))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return f"No telemetry found for {robot_id}."
            
        row = results[0]
        status_report = (
            f"Robot: {robot_id}\n"
            f"Zone: {row.zone}\n"
            f"Sensors: LiDAR={row.lidar_status}, Bumpers={row.bumper_status}, Vision={row.vision_3d_status}\n"
            f"Battery: {row.battery_level}%\n"
            f"Last Reported: {row.timestamp}"
        )
        return status_report
    except Exception as e:
        return f"Error querying BigQuery: {str(e)}"

@server.tool()
async def analyze_robot_metric_trend(robot_id: str, metric: str, hours: int = 24) -> str:
    """
    Analyzes the historical trend of a specific metric for a robot over a time period.
    Use this for requests about 'history', 'trends', 'logs', or 'anomalies'.

    Args:
        robot_id: The unique ID of the robot.
        metric: The metric to analyze (e.g., 'battery_level', 'lidar_status').
        hours: The number of hours to look back for the trend analysis (default: 24).
    """
    valid_metrics = ['battery_level', 'lidar_status', 'bumper_status', 'vision_3d_status']
    if metric not in valid_metrics:
        return f"Invalid metric '{metric}'. Valid metrics are: {', '.join(valid_metrics)}"

    is_numeric_metric = metric == 'battery_level'

    if is_numeric_metric:
        query = f"""
            SELECT AVG({metric}) as avg_value, MIN({metric}) as min_value, MAX({metric}) as max_value, COUNT(*) as data_points
            FROM `warehouse_ops.robot_telemetry`
            WHERE robot_id = @robot_id AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        """
    else: # Categorical metric
        query = f"""
            SELECT {metric} as status, COUNT(*) as count
            FROM `warehouse_ops.robot_telemetry`
            WHERE robot_id = @robot_id AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
            GROUP BY {metric}
            ORDER BY count DESC
        """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("robot_id", "STRING", robot_id),
            bigquery.ScalarQueryParameter("hours", "INT64", hours),
        ]
    )
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query, job_config=job_config))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))

        if not results or (is_numeric_metric and results[0].data_points == 0):
             return f"No telemetry data found for robot {robot_id} for metric '{metric}' in the last {hours} hours."

        report = f"Trend analysis for Robot '{robot_id}' metric '{metric}' over the last {hours} hours:\n"
        
        if is_numeric_metric:
            row = results[0]
            report += (
                f"  - Average: {row.avg_value:.2f}\n"
                f"  - Minimum: {row.min_value}\n"
                f"  - Maximum: {row.max_value}\n"
                f"  - Data Points: {row.data_points}"
            )
        else:
            for row in results:
                report += f"  - Status '{row.status}': {row.count} occurrences\n"

        return report.strip()
    except Exception as e:
        return f"Error querying BigQuery for trends: {str(e)}"
        
if __name__ == "__main__":
    server.run()
```

### 2. The Autonomous Agent Service (`agent-service/main.py`)

This is the central coordinating A2A service. It reads the local MCP tool server, compiles typing contracts using Pydantic, establishes a persistent process-wide lifecycle session, and injects instructions enabling sequential multi-turn loops.

```python
# ~/Projects/adk-basic/v3-dockerized/agent-service/main.py
import os
import sys
import asyncio
import google.auth
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field, create_model
from google.adk import Agent
from google.adk.models import google_llm
from google.adk.a2a.utils.agent_to_a2a import to_a2a 
from google.genai import client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import asynccontextmanager
import inspect 

os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)

project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

TOOL_SERVER_PATH = os.environ.get(
    "TOOL_SERVER_PATH", 
    os.path.expanduser("~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server/main.py")
)

async def build_tool_wrappers(session: ClientSession):
    mcp_tools = await session.list_tools()
    adk_tools = []
    for tool in mcp_tools.tools:
        t_name = tool.name
        t_desc = tool.description
        t_schema = tool.inputSchema

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

        def create_wrapper(tool_name):
            async def mcp_tool_wrapper(params: InputModel):
                arguments = params.model_dump()
                try: 
                    response = await session.call_tool(tool_name, arguments=arguments)
                    return "\n".join([c.text for c in response.content if hasattr(c, 'text')])
                except Exception as e:
                    print(f"CRITICAL: Tool call to '{tool_name}' failed, session might be dead: {e}")
                    return "ERROR: The telemetry system is temporarily offline. Please retry in 10 seconds."
            return mcp_tool_wrapper

        wrapper = create_wrapper(t_name)
        wrapper.__name__ = t_name
        wrapper.__doc__ = t_desc
        adk_tools.append(wrapper)
        
    return adk_tools

credentials, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"], 
    quota_project_id=project_id
)
vertex_client = client.Client(
    vertexai=True, project=project_id, location=google_cloud_location, credentials=credentials
)
gemini_model = google_llm.Gemini(model="gemini-1.5-flash-001")
gemini_model.api_client = vertex_client

expert = Agent(
    name="mcp_warehouse_expert", 
    description="Advanced warehouse safety agent. Uses MCP to dynamically query BigQuery telemetry and evaluate robot hardware/environmental risks.",
    model=gemini_model,  
    tools=[], 
    instruction="""
    You are a Warehouse Safety Investigator. Your goal is to find the ROOT CAUSE of issues.

    1. START: Always run 'check_robot_sensors' first to see the current state.
    2. ANALYZE: If current sensors are 'DEGRADED' or battery is < 20%, you MUST investigate further.
    3. INVESTIGATE: Automatically call 'analyze_robot_metric_trend' for the suspicious metric. 
       - Start with hours=24.
       - If 24 hours returns no data, try hours=168 (1 week).
    4. SYNTHESIZE: Once you have both the current state and the trend, provide your Safety Assessment.
    5. DO NOT ask the user for permission to run follow-up tools; just execute them and provide the finished insight.

    TOOL USAGE RULES - YOU MUST FOLLOW THESE:
    1. For immediate safety assessments, current status, or a "health check", you MUST use the `check_robot_sensors` tool.
    2. For requests about "trends", "anomalies", "history", "logs", or behavior "over time", you MUST use the `analyze_robot_metric_trend` tool.

    FORMATTING RULES:
    A. IF you are performing a brand new Safety Assessment, you MUST output your final response using beautifully structured Markdown.
    B. IF the user is asking a follow-up question, answer naturally in plain text paragraphs.
    """
)

@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    python_cmd = os.environ.get("PYTHON_PATH", "python")
    server_params = StdioServerParameters(
        command=python_cmd, 
        args=[TOOL_SERVER_PATH],
        env=os.environ.copy(),
        stderr=sys.stderr
    )
    
    print("Starting persistent Tool Server subprocess...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Building ADK tool wrappers...")
            expert.tools = await build_tool_wrappers(session)
            print(f"Successfully bound {len(expert.tools)} tools.")
            yield
    print("Shutting down agent service and killing Tool Server subprocess...")

app = to_a2a(
    expert, 
    lifespan=combined_lifespan,
)
```

---

## 🚀 Phase 4: Local Development

Start the FastAPI server. The Agent will automatically spawn the MCP Tool Server as a subprocess and bind the tools to Gemini.

```bash
cd ~/Projects/adk-basic/v3-dockerized/agent-service
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🐳 Phase 5: Containerization & Cloud Run Deployment

### 1. Unified Dockerfile

Create this `Dockerfile` in the root project directory (`v3-dockerized`). It packages both services into a single, high-performance container.

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

```bash
gcloud run services add-iam-policy-binding warehouse-mcp-expert-service \
    --region="us-central1" \
    --member="serviceAccount:service-189070037482@gcp-sa-discoveryengine.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --project="blt-test-project-2"
```

---

## 🧪 Phase 6: Verification & BigQuery Telemetry Tests

Run these queries in the BigQuery console to prove the agent's assessments are data-driven and not hallucinations.

### 1. Prove LiDAR Stability (BOT-13)
The agent claims **BOT-13's** LiDAR was 100% OPERATIONAL for 480 pings over 168 hours. Verify this:

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
The agent assesses a faulty battery due to wide fluctuations. Confirm this profile:

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
*   **Expected Result:** `avg_battery` ≈ 42.96%, `min_battery` = 0.0%, `max_battery` = 100.0%. The `min` value dropping to 0.0% validates the agent's warning.

### 3. Verify No Anomalies (BOT-42)
Prove BOT-42 is healthy by checking for any non-operational statuses.

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

Use these natural language queries in Gemini Enterprise to test the agent's autonomous reasoning.

| Scenario | Goal | NLQ Variations |
| :--- | :--- | :--- |
| **Pattern Recognition** | Have Gemini discover the recurring dust/dirt issue for BOT-99. | "Can you pull the logs for BOT-99? It keeps getting blocked and I want to know if there's a recurring pattern." <br/> "What's going on with BOT-99's sensors today? Are we seeing an environmental issue in the North Aisle?" |
| **Hardware Failure** | Have Gemini identify the faulty battery cell on BOT-13 causing sudden 10% drops. | "Look into the battery levels for BOT-13. Something seems wrong with its power consumption." <br/> "Can you review BOT-13's power logs? I suspect it might have a faulty battery cell." |
| **Environmental Stress** | Have Gemini correlate BOT-21's accelerated battery drain to the "Cold Storage" environment. | "Why is BOT-21's battery dying so much faster than the others?" <br/> "Compare the battery performance of BOT-21 in Cold Storage to BOT-42 at the Loading Dock." |
| **Healthy Operations** | Ensure the agent doesn't hallucinate issues for a perfectly healthy robot (BOT-42). | "Give me a routine health check on BOT-42." <br/> "Pull the latest telemetry for BOT-42. Are there any anomalies at all?" |
| **Catastrophic Crash** | Trigger the severe CRAWL logic and immediate shutdown requirement for BOT-07. | "EMERGENCY: Pull data for BOT-07 immediately. Did it crash?" <br/> "We just lost LiDAR connection to BOT-07. Run an urgent safety assessment." |
