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
async def list_available_robots() -> str:
    """
    Lists all unique robot IDs and their primary operating zones currently present 
    in the warehouse database. Use this tool when the user asks "what bots are available",
    "list the robots", or is unsure which robot ID to check.
    """
    # This query extracts the most recent zone for each unique robot_id in the system
    query = """
        WITH RankedTelemetry AS (
            SELECT 
                robot_id, 
                zone,
                ROW_NUMBER() OVER (PARTITION BY robot_id ORDER BY timestamp DESC) as rn
            FROM `warehouse_ops.robot_telemetry`
        )
        SELECT robot_id, zone
        FROM RankedTelemetry
        WHERE rn = 1
        ORDER BY robot_id ASC
    """
    
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(
            None, 
            lambda: bq_client.query(query)
        )
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return "No active robots found in the database telemetry."
            
        report = "Available Robots in the Warehouse:\n"
        for row in results:
            report += f"  - {row.robot_id} (Operating Zone: {row.zone})\n"
            
        return report.strip()
    except Exception as e:
        return f"Error querying available robots from BigQuery: {str(e)}"

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
    # Validate metric to prevent SQL injection and ensure it's a valid column
    valid_metrics = ['battery_level', 'lidar_status', 'bumper_status', 'vision_3d_status']
    if metric not in valid_metrics:
        return f"Invalid metric '{metric}'. Valid metrics are: {', '.join(valid_metrics)}"

    # Determine if the metric is numeric or categorical for different analysis
    is_numeric_metric = metric == 'battery_level'

    if is_numeric_metric:
        query = f"""
            SELECT
                AVG({metric}) as avg_value,
                MIN({metric}) as min_value,
                MAX({metric}) as max_value,
                COUNT(*) as data_points
            FROM `warehouse_ops.robot_telemetry`
            WHERE robot_id = @robot_id AND timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        """
    else: # Categorical metric
        query = f"""
            SELECT
                {metric} as status,
                COUNT(*) as count
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
        query_job = await loop.run_in_executor(
            None, lambda: bq_client.query(query, job_config=job_config)
        )
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))

        if not results:
             return f"No telemetry data found for robot {robot_id} for metric '{metric}' in the last {hours} hours."
        if is_numeric_metric and results[0].data_points == 0:
             return f"No telemetry data found for robot {robot_id} for metric '{metric}' in the last {hours} hours."

        report = f"Trend analysis for Robot '{robot_id}' metric '{metric}' over the last {hours} hours:\\n"
        
        if is_numeric_metric:
            row = results[0]
            report += (
                f"  - Average: {row.avg_value:.2f}\\n"
                f"  - Minimum: {row.min_value}\\n"
                f"  - Maximum: {row.max_value}\\n"
                f"  - Data Points: {row.data_points}"
            )
        else:
            for row in results:
                report += f"  - Status '{row.status}': {row.count} occurrences\\n"

        return report.strip()

    except Exception as e:
        return f"Error querying BigQuery for trends: {str(e)}"
        
if __name__ == "__main__":
    # FastMCP manages its own stdio runner directly on start
    server.run()