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

# =====================================================================
# 1. DEFINE THE MCP TOOL (Standard Pythonic Registration)
# =====================================================================
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
        # Run synchronous BQ calls in executor to avoid blocking the async event loop
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(
            None, 
            lambda: bq_client.query(query, job_config=job_config)
        )
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

if __name__ == "__main__":
    # FastMCP manages its own stdio runner directly on start
    server.run()