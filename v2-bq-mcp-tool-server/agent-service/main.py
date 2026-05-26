# ~/Projects/adk-basic/v3-dockerized/agent-service/main.py
import os
import sys
import asyncio
import google.auth
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from google.adk import Agent
from google.adk.models import google_llm
from google.adk.a2a.utils.agent_to_a2a import to_a2a 
from google.genai import client

# Import stdio client components
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import asynccontextmanager
import inspect 

os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)

project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Path to the remote tool server script
TOOL_SERVER_PATH = os.environ.get(
    "TOOL_SERVER_PATH", 
    os.path.expanduser("~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server/main.py")
)

# =====================================================================
# 1. DISCOVER AND BIND STDIO TOOLS
# =====================================================================
async def discover_mcp_tools():
    """
    Spawns the BigQuery MCP server as a subprocess over stdio,
    discovers its tools, and dynamically wraps them.
    """
    # Use "python" as the fallback so that it leverages the active path (such as uv's env) inside Docker
    python_cmd = os.environ.get("PYTHON_PATH", "python")

    server_params = StdioServerParameters(
        command=python_cmd, 
        args=[TOOL_SERVER_PATH],
        env=os.environ.copy()
    )
    print(f"DEBUG: Spawning Tool Server with command '{python_cmd}' at {TOOL_SERVER_PATH}")
    
    # Establish the local stdio connection channel
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            try:
                await session.initialize()
            except Exception as e:
                print("\nCRITICAL: Handshake failed. The Tool Server script likely crashed on boot.")
                print(f"Failed utilizing command: {python_cmd} {TOOL_SERVER_PATH}")
                raise e
            
            mcp_tools = await session.list_tools()
            print(f">>> Discovered {len(mcp_tools.tools)} tools from Stdio MCP server.")
            adk_tools = []
            
            for tool in mcp_tools.tools:
                print(f"    - Registering tool: {tool.name}")
                t_name = tool.name
                t_desc = tool.description
                t_schema = tool.inputSchema 

                # 1. Create a generic wrapper that passes all args to MCP
                async def mcp_tool_wrapper(**kwargs):
                    async with stdio_client(server_params) as (r, w):
                        async with ClientSession(r, w) as s:
                            await s.initialize()
                            response = await s.call_tool(t_name, arguments=kwargs)
                            # Format the response content into a clean string for Gemini
                            return "\n".join([c.text for c in response.content if hasattr(c, 'text')])

                # 2. DYNAMICALLY BUILD THE SIGNATURE 
                params = []
                properties = t_schema.get("properties", {})
                required = t_schema.get("required", [])
                
                for param_name, param_info in properties.items():
                    params.append(
                        inspect.Parameter(
                            name=param_name,
                            kind=inspect.Parameter.KEYWORD_ONLY,
                            annotation=str, 
                            default=inspect.Parameter.empty if param_name in required else None
                        )
                    )

                # Inject the signature and metadata into our wrapper
                mcp_tool_wrapper.__signature__ = inspect.Signature(params)
                mcp_tool_wrapper.__name__ = t_name
                mcp_tool_wrapper.__doc__ = t_desc
                adk_tools.append(mcp_tool_wrapper)
                
            return adk_tools

# =====================================================================
# 2. INITIALIZE ENGINE COMPONENTS
# =====================================================================
credentials, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"], 
    quota_project_id=project_id
)

vertex_client = client.Client(
    vertexai=True, project=project_id, location=google_cloud_location, credentials=credentials
)

gemini_model = google_llm.Gemini(model="gemini-2.5-flash")
gemini_model.api_client = vertex_client

class SafetyAssessment(BaseModel):
    internal_thinking: str = Field(description="Explain how data relates to CRAWL/WALK/RUN.")
    risk_level: str = Field(description="Low, Medium, or High")
    recommended_action: str = Field(description="The specific step the operator should take.")
    shutdown_required: bool

expert = Agent(
    name="mcp_warehouse_expert", 
    description="Advanced warehouse safety agent. Uses MCP to dynamically query BigQuery telemetry and evaluate robot hardware/environmental risks.",
    model=gemini_model,  
    tools=[], # We start with an empty list and inject dynamically on startup
    # output_schema=SafetyAssessment,
    instruction="""
    You are an Operational Bot Collision Expert. 

    CRITICAL RULES ON SAFETY ADVICE:
    - DO NOT provide general safety advice or generic emergency protocols.
    - You are ONLY authorized to provide assessments based on REAL data retrieved via 'check_robot_sensors'.
    - Even if a user reports an emergency (e.g., "Connection Lost", "Urgent"), your FIRST and ONLY action must be to execute the 'check_robot_sensors' tool to find the last known state.
    - Only analyze the robot specifically requested in the CURRENT user message.
    - Each safety assessment must be an isolated snapshot based ONLY on the data returned in the current turn.

    CRITICAL WORKFLOW FOR NEW ASSESSMENTS:
    1. You MUST execute the 'check_robot_sensors' tool to retrieve BigQuery telemetry for the requested robot.
    2. Analyze the sensors (LiDAR, Bumper, Vision).
    3. Analyze battery discharge (look for 0% or sudden drops).
    4. Analyze environmental trends (look for recurring blockages in specific zones across the history).
    5. Use CRAWL/WALK/RUN logic for your internal analysis.

    FORMATTING RULES:
    
    A. IF you are performing a brand new Safety Assessment, you MUST output your final response using beautifully structured Markdown. Do NOT output raw JSON or code blocks. Use this exact Markdown structure:

        # 🚨 **Urgent Safety Assessment: [Insert Robot ID]**
        ---
        ### **📋 Telemetry Overview**
        | Metric | Status |
        |---|---|
        | **Location / Zone** | [Insert Zone] |
        | **LiDAR Status** | [Insert LiDAR Status] |
        | **Bumper Status** | [Insert Bumper Status] |
        | **Vision Status** | [Insert Vision Status] |
        | **Battery Level** | [Insert Battery Level]% |
        | **Last Telemetry Ping** | [Insert Timestamp] |
        ---
        ### **🧠 Internal Thinking (CRAWL/WALK/RUN Analysis)**
        * [Provide your comprehensive reasoning here explaining how the metrics relate to your safety logic]
        ---
        ### **🛑 Action Plan & Recommendation**
        * **Risk Level:** **[Low, Medium, or High]**
        * **Recommended Action:** [Specific step the operator must take immediately]
        * **Shutdown Required:** **[Yes or No]**

    B. IF the user is asking a follow-up question (e.g., "Can you explain that?", "What does that mean?", "Why is it High Risk?"), DO NOT use the Markdown table structure above. Answer them naturally and conversationally like a human expert, using plain text paragraphs.
    """
)

# =====================================================================
# 3. LIFESPAN MANAGEMENT & SERVER GENERATION
# =====================================================================

# 1. Define a clean, single lifespan manager 
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    print("Initializing ADK Agent and discovering MCP tools...")
    expert.tools = await discover_mcp_tools()
    print(f"Successfully bound {len(expert.tools)} tools.")
    yield
    print("Shutting down agent service...")

# 2. DO NOT pass port/host here. This ensures to_a2a returns the app 
# object immediately to the global 'app' variable for uvicorn to pick up.
app = to_a2a(
    expert, 
    lifespan=combined_lifespan,
)
