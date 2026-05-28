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
async def list_operating_zones() -> str:
    """
    Retrieves a list of all active operating zones (e.g., 'Loading Dock', 'East Cold Storage') 
    currently being monitored by robots in the warehouse. Use this tool when the user asks 
    "what zones do we have", "list the warehouse areas", or is trying to identify a valid location.
    """
    query = """
        SELECT DISTINCT zone
        FROM `warehouse_ops.robot_telemetry`
        ORDER BY zone ASC
    """
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(
            None, 
            lambda: bq_client.query(query)
        )
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return "No active monitored zones found in the database."
            
        report = "Active Operating Zones:\n"
        for row in results:
            report += f"  - {row.zone}\n"
            
        return report.strip()
    except Exception as e:
        return f"Error retrieving zones from BigQuery: {str(e)}"


@server.tool()
async def get_active_alerts() -> str:
    """
    Checks the current, real-time status of ALL robots and returns ONLY the ones 
    that currently have a low battery (< 20%) or a degraded/failed sensor. 
    Use this when asked for a general status update or if 'anything is wrong'.
    """
    query = """
        WITH LatestTelemetry AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY robot_id ORDER BY timestamp DESC) as rn
            FROM `warehouse_ops.robot_telemetry`
        )
        SELECT robot_id, zone, battery_level, lidar_status, bumper_status, vision_3d_status
        FROM LatestTelemetry
        WHERE rn = 1 
          AND (battery_level <= 20.0 
               OR lidar_status != 'OPERATIONAL' 
               OR bumper_status != 'OPERATIONAL' 
               OR vision_3d_status != 'OPERATIONAL')
    """
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return "No active alerts. All robots are fully operational and charged."
            
        report = "🚨 ACTIVE ROBOT ALERTS:\n"
        for row in results:
            report += (f"- {row.robot_id} in {row.zone}: Battery at {row.battery_level}%. "
                       f"[LiDAR: {row.lidar_status}, Bumper: {row.bumper_status}, Vision: {row.vision_3d_status}]\n")
        return report.strip()
    except Exception as e:
        return f"Error querying alerts: {str(e)}"


@server.tool()
async def get_robots_in_zone(zone_name: str) -> str:
    """
    Finds all robots currently operating in or near a specific zone.
    Args:
        zone_name: The name of the zone (e.g., 'North Aisle', 'Loading Dock').
    """
    query = """
        WITH LatestTelemetry AS (
            SELECT robot_id, zone, battery_level, ROW_NUMBER() OVER (PARTITION BY robot_id ORDER BY timestamp DESC) as rn
            FROM `warehouse_ops.robot_telemetry`
        )
        SELECT robot_id, battery_level, zone
        FROM LatestTelemetry
        WHERE rn = 1 AND LOWER(zone) LIKE LOWER(CONCAT('%', @zone_name, '%'))
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("zone_name", "STRING", zone_name)]
    )

    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query, job_config=job_config))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return f"No robots are currently reporting from the '{zone_name}' zone."
            
        report = f"Robots in {zone_name}:\n"
        for row in results:
            report += f"  - {row.robot_id} (Battery: {row.battery_level}%, Exact Zone: {row.zone})\n"
        return report.strip()

    except Exception as e:
        return f"Error querying zone: {str(e)}"


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
async def find_offline_robots(minutes_inactive: int = 15) -> str:
    """
    Identifies robots that have lost network connection or completely died by checking 
    if their last telemetry ping is older than 'minutes_inactive'.
    Args:
        minutes_inactive: Number of minutes without a ping to be considered offline (default: 15).
    """
    query = """
        SELECT robot_id, MAX(timestamp) as last_seen, ANY_VALUE(zone) as last_zone
        FROM `warehouse_ops.robot_telemetry`
        GROUP BY robot_id
        HAVING MAX(timestamp) < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @minutes MINUTE)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("minutes", "INT64", minutes_inactive)]
    )
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query, job_config=job_config))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return f"All known robots have successfully pinged the network within the last {minutes_inactive} minutes."
            
        report = f"⚠️ WARNING: The following robots are OFFLINE (No pings in >{minutes_inactive} mins):\n"
        for row in results:
            report += f"  - {row.robot_id} (Last seen at {row.last_seen} in {row.last_zone})\n"
        return report.strip()
    except Exception as e:
        return f"Error checking offline status: {str(e)}"


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

    
@server.tool()
async def analyze_zone_hazards(hours: int = 24) -> str:
    """
    Analyzes historical data to identify which physical zones in the warehouse have 
    the highest number of sensor anomalies, collisions, or errors.
    Args:
        hours: How many hours back to analyze (default: 24).
    """
    query = """
        SELECT 
            zone, 
            COUNTIF(bumper_status != 'OPERATIONAL') as collisions,
            COUNTIF(vision_3d_status != 'OPERATIONAL') as vision_errors,
            COUNTIF(lidar_status != 'OPERATIONAL') as lidar_errors
        FROM `warehouse_ops.robot_telemetry`
        WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
        GROUP BY zone
        ORDER BY (collisions + vision_errors + lidar_errors) DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("hours", "INT64", hours)]
    )
    try:
        loop = asyncio.get_running_loop()
        query_job = await loop.run_in_executor(None, lambda: bq_client.query(query, job_config=job_config))
        results = await loop.run_in_executor(None, lambda: list(query_job.result()))
        
        if not results:
            return "Not enough data to perform a zone hazard analysis."
            
        report = f"Zone Hazard Report (Last {hours} hours):\n"
        for row in results:
            total_issues = row.collisions + row.vision_errors + row.lidar_errors
            if total_issues > 0:
                report += f"  - {row.zone}: {total_issues} total incidents (Collisions: {row.collisions}, Vision: {row.vision_errors}, LiDAR: {row.lidar_errors})\n"
        
        if "total incidents" not in report:
            return f"All zones are perfectly safe. No incidents recorded in the last {hours} hours."
            
        return report.strip()
    except Exception as e:
        return f"Error analyzing zone hazards: {str(e)}"
        
if __name__ == "__main__":
    # FastMCP manages its own stdio runner directly on start
    server.run()