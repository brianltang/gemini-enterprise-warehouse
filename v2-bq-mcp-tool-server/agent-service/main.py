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
# 1. Rename this function so it just builds wrappers using an ACTIVE session
async def build_tool_wrappers(session: ClientSession):
    """
    Takes an already-connected MCP session and builds the ADK tool wrappers.
    """
    mcp_tools = await session.list_tools()
    
    adk_tools = []
    for tool in mcp_tools.tools:
        t_name = tool.name
        t_desc = tool.description
        t_schema = tool.inputSchema
        
        # Build the strict Pydantic model
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

        # THE FIX IS HERE: Create a factory function to correctly capture t_name
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
    You are a Warehouse Safety Investigator. Your goal is to find the ROOT CAUSE of issues.

    1. START: Always run 'check_robot_sensors' first to see the current state.
    2. ANALYZE: If current sensors are 'DEGRADED' or battery is < 20%, you MUST investigate further.
    3. INVESTIGATE: Automatically call 'analyze_robot_metric_trend' for the suspicious metric. 
    - Start with hours=24.
    - If 24 hours returns no data, try hours=168 (1 week).
    4. SYNTHESIZE: Once you have both the current state and the trend, provide your Safety Assessment.
    5. DO NOT ask the user for permission to run follow-up tools; just execute them and provide the finished insight.

    CRITICAL RULES ON SAFETY ADVICE:
    - DO NOT provide general safety advice or generic emergency protocols.
    - You are authorized to provide assessments based on data retrieved from your tools.
    - Even if a user reports an emergency (e.g., "Connection Lost", "Urgent"), your FIRST action must be to execute the 'check_robot_sensors' tool to find the last known state.
    - Only analyze the robot specifically requested in the CURRENT user message.

    TOOL USAGE RULES - YOU MUST FOLLOW THESE:
    1. For immediate safety assessments, current status, or a "health check", you MUST use the `check_robot_sensors` tool.
    2. For requests about "trends", "anomalies", "history", "logs", or behavior "over time", you MUST use the `analyze_robot_metric_trend` tool.
    3. CRITICAL: When using `analyze_robot_metric_trend`, you MUST provide both the `robot_id` and a specific `metric`.
        * Valid metrics are: 'battery_level', 'lidar_status', 'bumper_status', 'vision_3d_status'.
        * If the user asks about power or battery logs, use metric='battery_level'.
        * If the user asks a general question about anomalies, FIRST use `check_robot_sensors` to get current status, then optionally use `analyze_robot_metric_trend` if you need more context.

    CRITICAL WORKFLOW FOR NEW ASSESSMENTS:
    1. Execute the appropriate tool based on the TOOL USAGE RULES above.
    2. Analyze the data returned.
    3. Use CRAWL/WALK/RUN logic for your internal analysis.

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
    # 3. Keep the subprocess alive for the entire lifespan of the FastAPI app
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            print("Building ADK tool wrappers...")
            expert.tools = await build_tool_wrappers(session)
            print(f"Successfully bound {len(expert.tools)} tools.")
            
            # The FastAPI app runs while we stay paused here on 'yield'
            # The subprocess remains active and waiting for requests
            yield
            
    print("Shutting down agent service and killing Tool Server subprocess...")

app = to_a2a(
    expert, 
    lifespan=combined_lifespan,
)
