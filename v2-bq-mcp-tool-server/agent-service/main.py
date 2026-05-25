# ~/Projects/adk-basic/v2-bq-mcp-tool-server/agent-service/main.py
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

os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION")

# Path to the remote tool server script
TOOL_SERVER_PATH = os.path.expanduser("~/Projects/adk-basic/v2-bq-mcp-tool-server/bq-mcp-server/main.py")

# =====================================================================
# 1. DISCOVER AND BIND STDIO TOOLS
# =====================================================================
async def discover_mcp_tools():
    """
    Spawns the BigQuery MCP server as a subprocess over stdio,
    discovers its tools, and dynamically wraps them.
    """
    # Define parameters using the current python, but set the correct CWD
    # and map stderr to the terminal so we can see why it crashes!
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
                
                def make_mcp_call_wrapper(t_name=tool.name):
                    async def mcp_tool_callable(*args, **kwargs):
                        # On invocation, spawn the subprocess again to execute the call
                        async with stdio_client(server_params) as (r, w):
                            async with ClientSession(r, w) as s:
                                await s.initialize()
                                response = await s.call_tool(t_name, arguments=kwargs)
                                return response.content
                    
                    mcp_tool_callable.__name__ = t_name
                    mcp_tool_callable.__doc__ = tool.description
                    return mcp_tool_callable
                
                adk_tools.append(make_mcp_call_wrapper())
                
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

# Discover the tools synchronously on startup
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

discovered_tools = loop.run_until_complete(discover_mcp_tools())

class SafetyAssessment(BaseModel):
    internal_thinking: str = Field(description="Explain how data relates to CRAWL/WALK/RUN.")
    risk_level: str = Field(description="Low, Medium, or High")
    recommended_action: str = Field(description="The specific step the operator should take.")
    shutdown_required: bool

expert = Agent(
    name="collision_safety_expert", 
    model=gemini_model,  
    tools=discovered_tools, # Bound directly!
    output_schema=SafetyAssessment,
    instruction="""
    You are an Operational Bot Collision Expert. 
    ALWAYS check sensor data using your tools before providing an assessment.
    Use CRAWL/WALK/RUN logic.
    """
)

port = int(os.environ.get("PORT", 8080))
app = to_a2a(expert, port=port)
