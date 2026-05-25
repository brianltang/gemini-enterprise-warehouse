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

## 🛠️ Project Setup

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

## 🚀 Running the Application

### 1. Environment Variables
Ensure your Google Cloud project is set so the BigQuery client can authenticate:

```bash
export GOOGLE_CLOUD_PROJECT_ID="blt-test-project-2"
```

### 2. Boot up the Agent
Run the FastAPI server. The Agent will automatically spawn the MCP Tool Server as a subprocess, discover the `check_robot_sensors` tool, and bind it to Gemini.

```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service
uv run uvicorn main:app --host 0.0.0.0 --port 8080
```

---

## 📋 Technical Components

| Component | Responsibility |
| :--- | :--- |
| **Agent Service** | FastAPI + ADK. Handles Gemini reasoning and A2A protocol. |
| **MCP Tool Server** | FastMCP + BigQuery. Executes SQL queries on behalf of the agent. |
| **SafetyAssessment** | A Pydantic model enforcing structured output (Risk Level, Internal Thinking). |
| **CRAWL/WALK/RUN** | The core instructional logic used by the agent to categorize sensor risks. |

---

## ⚠️ Debugging MCP Handshaking
If you see a `CRITICAL: Handshake failed` error, the Tool Server script likely crashed on boot. You can debug the tool server independently by running:
```bash
cd ~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server
uv run python main.py
```
