# Warehouse Safety Expert API (ADK Demo)

This project is a containerized backend that utilizes the **Google Agent Development Kit (ADK)** to expose an Agent-to-Agent (A2A) microservice. It demonstrates a **Warehouse Safety Expert** (powered by Gemini) that evaluates robot sensor data (LiDAR, Bumpers, 3D Vision) using BigQuery telemetry and **CRAWL/WALK/RUN** logic.

This repository was built using `uv` for ultra-fast dependency management, uses the **Model Context Protocol (MCP)** to decouple tool logic, and is natively integrated with **Gemini Enterprise (GE)** via the A2A protocol.

---

## 🌟 The Evolution: Local Prototyping vs. MCP-Driven ADK (v2)

In previous versions (**v0/v1**), we wrote monolithic boilerplate code where tools were hardcoded inside the agent's main script. 

**Why that approach breaks in Production with Gemini Enterprise:**

1. **Deeper Payload Envelopes:** The standard A2A protocol doesn't send flat JSON. It sends deeply nested structures (e.g., `userMessage.userContent.textContent.text`). Using the ADK's `to_a2a` wrapper handles this automatically.
2. **Strict Validation Errors:** If your code expects `session_id` (snake_case) but Gemini sends `sessionId` (camelCase), FastAPI rejects the payload instantly with a `422 Unprocessable Entity` error.
3. **Complexity of Tool Maintenance:** In v2, we move to **MCP (Model Context Protocol)**. This decouples the BigQuery logic into a standalone "Tool Server." The Agent dynamically discovers tools over `stdio`, meaning you can update your database queries without ever restarting or redeploying your LLM logic.

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
Run this massive query to generate 2,400 records of chronological telemetry data across 5 robots.

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
    -- BOT-99: The Recurring Dust Issue (gets dirty every 2 hours, cleans up, gets dirty again)
    WHEN robot.robot_id = 'BOT-99' AND MOD(time.mins_ago, 120) < 15 THEN 'BLOCKED - Cleaning Required'
    WHEN robot.robot_id = 'BOT-99' AND MOD(time.mins_ago, 120) < 45 THEN 'DEGRADED - Dirt Detected'
    -- BOT-07: The Crash
    WHEN robot.robot_id = 'BOT-07' AND time.mins_ago <= 15 THEN 'IMPACT_DETECTED'
    ELSE 'OPERATIONAL'
  END as bumper_status,
  
  -- Vision Logic
  CASE
    -- BOT-42: Sunlight Glare Anomaly (Only happens between 4-5 hours ago when sun hits the dock)
    WHEN robot.robot_id = 'BOT-42' AND time.mins_ago BETWEEN 240 AND 300 THEN 'DEGRADED - Sunlight Glare'
    -- BOT-21: Cold Storage Condensation (Flickers constantly)
    WHEN robot.robot_id = 'BOT-21' AND MOD(time.mins_ago, 7) = 0 THEN 'DEGRADED - Condensation/Fog'
    -- BOT-07: Post-crash
    WHEN robot.robot_id = 'BOT-07' AND time.mins_ago <= 15 THEN 'DEGRADED - Lens Cracked'
    ELSE 'OPERATIONAL'
  END as vision_3d_status,
  
  -- Battery Logic
  ROUND(GREATEST(
    CASE
      -- Standard drain (15% per hour)
      WHEN robot.robot_id = 'BOT-42' THEN 100.0 - ((479 - time.mins_ago) * 0.25)
      WHEN robot.robot_id = 'BOT-99' THEN 100.0 - ((479 - time.mins_ago) * 0.25)
      
      -- BOT-21: Cold Storage kills batteries 2x faster (30% per hour)
      WHEN robot.robot_id = 'BOT-21' THEN 100.0 - ((479 - time.mins_ago) * 0.5)
      
      -- BOT-13: Faulty Battery Cell (sudden 10% drops every hour instead of smooth drain)
      WHEN robot.robot_id = 'BOT-13' THEN 100.0 - (FLOOR((479 - time.mins_ago) / 60) * 10) - ((479 - time.mins_ago) * 0.1)
      
      -- BOT-07: Drops to 0 at crash
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

## 🚀 Phase 3: Booting the Server

Start the FastAPI server. The Agent will automatically spawn the MCP Tool Server as a subprocess, discover the `check_robot_sensors` tool, and bind it to Gemini.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 🧪 Phase 4: Running the Test Suite

Open a second terminal window to run these tests. We use `jq` to parse the complex JSON-RPC A2A payload into a clean, human-readable response. 

**Ensure `jq` is installed first:**
```bash
sudo apt-get update && sudo apt-get install -y jq
```

### Scenario 1: Pattern Recognition (BOT-99)
Tests if Gemini can see the recurring dust issue in the North Aisle across an 8-hour window.
```bash
curl -s -X POST http://localhost:8080/ \
-H "Content-Type: application/json" \
-d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-101",
      "role": "user",
      "parts": [{"text": "Analyze BOT-99. It is currently blocked, but I want to know if this is a recurring environmental pattern in its zone."}]
    }
  }
}' | jq -r '.result.artifacts.parts.text | fromjson'
```

### Scenario 2: Hardware Failure (BOT-13)
Tests if Gemini identifies the "Faulty Battery Cell" (sudden 10% drops) instead of smooth drain.
```bash
curl -s -X POST http://localhost:8080/ \
-H "Content-Type: application/json" \
-d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-102",
      "role": "user",
      "parts": [{"text": "Perform a deep dive on BOT-13 battery telemetry. Is the discharge rate normal for a Hazardous Zone operation?"}]
    }
  }
}' | jq -r '.result.artifacts.parts.text | fromjson'
```

### Scenario 3: Environmental Stress (BOT-21)
Tests if Gemini connects the "Cold Storage" zone to accelerated battery drain.
```bash
curl -s -X POST http://localhost:8080/ \
-H "Content-Type: application/json" \
-d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-103",
      "role": "user",
      "parts": [{"text": "Check BOT-21 in East Cold Storage. Why is its battery performing differently than BOT-42?"}]
    }
  }
}' | jq -r '.result.artifacts.parts.text | fromjson'
```

### Scenario 4: Healthy Operations (BOT-42)
Ensures the agent doesn't "hallucinate" problems when operations are normal.
```bash
curl -s -X POST http://localhost:8080/ \
-H "Content-Type: application/json" \
-d '{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "message/send",
  "params": {
    "message": {
      "messageId": "msg-104",
      "role": "user",
      "parts": [{"text": "Analyze BOT-42 at the Loading Dock."}]
    }
  }
}' | jq -r '.result.artifacts.parts.text | fromjson'
```

### Scenario 5: Catastrophic Crash (BOT-07)
Triggers the most severe "CRAWL" logic, hardware disconnects, and immediate shutdown requirement.
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
