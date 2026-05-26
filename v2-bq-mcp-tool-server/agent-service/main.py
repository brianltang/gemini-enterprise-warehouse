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
    server_params = StdioServerParameters(
        command=sys.executable, # Uses the active virtualenv python
        args=[TOOL_SERVER_PATH],
        env=os.environ.copy() # Passes GCP/ADC environment variables
    )
    print(f"DEBUG: Spawning Tool Server at {TOOL_SERVER_PATH}")
    
    # Establish the local stdio connection channel
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            try:
                await session.initialize()
            except Exception as e:
                print("\nCRITICAL: Handshake failed. The Tool Server script likely crashed on boot.")
                print("Run 'uv run python ../bq-mcp-server/main.py' manually to see the error.\n")
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
    output_schema=SafetyAssessment,
    instruction="""
    You are an Operational Bot Collision Expert. 
    ALWAYS analyze the full history of the provided telemetry to find patterns.
    Look for environmental trends (recurring issues in specific zones) 
    and hardware anomalies (unsteady battery drain).
    Use CRAWL/WALK/RUN logic for the final risk level.
    CRITICAL FORMATTING RULE: 
    When outputting your SafetyAssessment fields, ensure the text in 'internal_thinking' 
    and 'recommended_action' is formatted using clean Markdown. Use bolding (**), 
    bullet points (-), or Markdown tables (|---|) where appropriate. 
    Gemini Enterprise will render this Markdown directly to the end-user.
    """
)

# =====================================================================
# 3. LIFESPAN MANAGEMENT & SERVER GENERATION
# =====================================================================

# 1. Define a clean, single lifespan manager 
@asynccontextmanager
async def combined_lifespan(app: FastAPI):
    # This runs ONCE when the server boots
    print("Initializing ADK Agent and discovering MCP tools...")
    expert.tools = await discover_mcp_tools()
    print(f"Successfully bound {len(expert.tools)} tools.")
    yield
    # This runs ONCE when the server shuts down
    print("Shutting down agent service...")

# 2. Define port first so it is in scope before calling to_a2a
port = int(os.environ.get("PORT", 8080))

# 3. Pass your lifespan context manager directly into the to_a2a function
app = to_a2a(
    expert, 
    port=port, 
    lifespan=combined_lifespan
)
