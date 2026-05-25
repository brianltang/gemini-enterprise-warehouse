import os
import google.auth
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from google.adk import Agent
from google.adk.models import google_llm
from google.adk.a2a.utils.agent_to_a2a import to_a2a 
from google.genai import client

# =====================================================================
# 1. ENVIRONMENT & AUTH SETUP
# =====================================================================
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION")

if project_id:
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

# =====================================================================
# 2. SCHEMAS & TOOLS
# =====================================================================
class SafetyAssessment(BaseModel):
    internal_thinking: str = Field(description="Explain how data relates to CRAWL/WALK/RUN.")
    risk_level: str = Field(description="Low, Medium, or High")
    recommended_action: str = Field(description="The specific step the operator should take.")
    shutdown_required: bool

def check_robot_sensors(robot_id: str):
    """Checks the real-time status of LiDAR, Bumpers, and 3D Vision for a robot."""
    return {
        "robot_id": robot_id,
        "lidar": "OPERATIONAL",
        "bumpers": "DEGRADED - Cleaning Required",
        "vision_3d": "OPERATIONAL",
        "safety_status": "CAUTION"
    }

# =====================================================================
# 3. INITIALIZE ENGINE COMPONENTS
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

expert = Agent(
    name="collision_safety_expert", 
    model=gemini_model,  
    tools=[check_robot_sensors],
    output_schema=SafetyAssessment, # <-- where magic of output parsing happens, we give this object to agent, ADK does rest
    instruction="""
    You are an Operational Bot Collision Expert. 
    ALWAYS check sensor data using your tools before providing an assessment.
    Use CRAWL/WALK/RUN logic.
    """
)

# =====================================================================
# 4. EXPOSE AGENT AS A2A WEB APP
# =====================================================================
# to_a2a() returns a fully working ASGI app.
# We assign it directly to 'app'.
port = int(os.environ.get("PORT", 8080))
app = to_a2a(expert, port=port)
