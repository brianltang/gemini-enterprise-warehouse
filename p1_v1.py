import os
import uuid
import asyncio
import google.auth
import json # make outputs into pretty JSON objects instead of escaped strings
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from google.adk import Agent
from google.adk.models import google_llm
from google.adk.runners import Runner, InMemoryRunner
from google.adk.sessions import InMemorySessionService
from google.genai import client, types

# =====================================================================
# 1. ENVIRONMENT & AUTH SETUP
# =====================================================================
os.environ["GOOGLE_API_USE_CLIENT_CERTIFICATE"] = "false"
load_dotenv(override=True)
project_id = os.environ.get("GOOGLE_CLOUD_PROJECT_ID")
use_vertex_ai = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")
google_cloud_location = os.environ.get("GOOGLE_CLOUD_LOCATION")

# Some hidden logic going on - force the SDK to use your variables!
if project_id:
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

# =====================================================================
# 2. SCHEMAS & TOOLS
# =====================================================================
class UserQuery(BaseModel):
    query: str
    session_id: str = None 

# we are creating structure for output
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
    output_schema=SafetyAssessment,
    instruction="""
    You are an Operational Bot Collision Expert. 
    ALWAYS check sensor data using your tools before providing an assessment.
    Use CRAWL/WALK/RUN logic.
    """
)

# --- GLOBAL APP STATE ---
active_sessions = {}
APP_NAME = "warehouse-safety-expert-demo"

# =====================================================================
# 4. FASTAPI ENDPOINTS
# =====================================================================
app = FastAPI(title="Warehouse Safety Agent API")

@app.post("/analyze-safety")
async def analyze_safety(req: UserQuery):
    s_id = req.session_id or str(uuid.uuid4())
    u_id = "brian-tang-l7-demo"

    try:
        # 1. Provision or retrieve the Runner for this specific session
        if s_id not in active_sessions:
            print(f">>> Provisioning fresh Runner and internal Session: {s_id}")
            # --- THE FIX: InMemoryRunner manages its own service, so we remove the param ---
            runner = InMemoryRunner(agent=expert, app_name=APP_NAME)
            
            # Explicitly provision the session in the runner's internal service
            await runner.session_service.create_session(
                session_id=s_id, 
                user_id=u_id, 
                app_name=APP_NAME
            )
            active_sessions[s_id] = runner

        runner = active_sessions[s_id]

        # 2. Prepare the payload
        new_msg = types.Content(parts=[types.Part(text=req.query)], role="user")

        # 3. Call run_async to stay in the FastAPI event loop
        events = runner.run_async(
            user_id=u_id,
            session_id=s_id,
            new_message=new_msg
        )

        final_assessment = None
        # 4. Iterate through the stream to capture the FINAL output
        async for event in events:
            # Check for structured JSON output
            if hasattr(event, 'output') and event.output is not None:
                final_assessment = event.output
            
            # Fallback: Extraction from 'set_model_response' tool call
            elif hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if part.function_call and part.function_call.name == "set_model_response":
                        final_assessment = part.function_call.args
                    elif part.text and not final_assessment:
                        final_assessment = part.text

        # If final_assessment is a string (JSON), parse it back into a dict
        if isinstance(final_assessment, str):
            try:
                final_assessment = json.loads(final_assessment)
            except:
                pass # Keep as string if it's not valid JSON

        return {
            "session_id": s_id,
            "assessment": final_assessment
        }

    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
