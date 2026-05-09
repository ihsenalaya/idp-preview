"""
Jaeger MCP Server — exposes Jaeger traces as kagent tools.

Tools:
  jaeger_get_services     — list all services that have traces
  jaeger_get_traces       — get recent traces for a service
  jaeger_get_trace        — get a single trace by ID with all spans
"""
import os
import json
import httpx
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, CallToolResult
from starlette.applications import Starlette
from starlette.routing import Mount, Route
import uvicorn

JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger.observability:16686")

server = Server("jaeger-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="jaeger_get_services",
            description="List all services that have traces in Jaeger.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="jaeger_get_traces",
            description=(
                "Get recent traces for a service from Jaeger. "
                "Use this to find failing or slow requests. "
                "Returns a list of traces with span count, duration, and start time."
            ),
            inputSchema={
                "type": "object",
                "required": ["service"],
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name (e.g. idp-preview-pr-42)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of traces to return (default 10)",
                        "default": 10,
                    },
                    "lookback": {
                        "type": "string",
                        "description": "Time window e.g. '1h', '30m', '6h' (default '1h')",
                        "default": "1h",
                    },
                    "tags": {
                        "type": "string",
                        "description": "Filter by tags in Jaeger query format e.g. 'error=true'",
                    },
                },
            },
        ),
        Tool(
            name="jaeger_get_trace",
            description=(
                "Get a single trace by its trace ID from Jaeger. "
                "Returns all spans with operation names, durations, tags, and logs. "
                "Use this to drill into a specific failing request."
            ),
            inputSchema={
                "type": "object",
                "required": ["trace_id"],
                "properties": {
                    "trace_id": {
                        "type": "string",
                        "description": "Trace ID (hex string, 16 or 32 chars)",
                    }
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            if name == "jaeger_get_services":
                resp = await client.get(f"{JAEGER_URL}/api/services")
                resp.raise_for_status()
                services = resp.json().get("data", [])
                return [TextContent(type="text", text="\n".join(services) or "No services found.")]

            elif name == "jaeger_get_traces":
                service = arguments["service"]
                limit = arguments.get("limit", 10)
                lookback = arguments.get("lookback", "1h")
                params = {"service": service, "limit": limit, "lookback": lookback}
                if "tags" in arguments:
                    params["tags"] = arguments["tags"]

                resp = await client.get(f"{JAEGER_URL}/api/traces", params=params)
                resp.raise_for_status()
                traces = resp.json().get("data", [])

                if not traces:
                    return [TextContent(type="text", text=f"No traces found for service '{service}'.")]

                lines = [f"Found {len(traces)} trace(s) for '{service}':\n"]
                for t in traces:
                    trace_id = t.get("traceID", "?")
                    spans = t.get("spans", [])
                    duration_us = t.get("spans", [{}])[0].get("duration", 0) if spans else 0
                    start_us = spans[0].get("startTime", 0) if spans else 0
                    has_error = any(
                        tag.get("key") == "error" and tag.get("value")
                        for span in spans
                        for tag in span.get("tags", [])
                    )
                    lines.append(
                        f"  traceID={trace_id}  spans={len(spans)}"
                        f"  duration={duration_us/1000:.1f}ms"
                        f"{'  ERROR' if has_error else ''}"
                    )
                return [TextContent(type="text", text="\n".join(lines))]

            elif name == "jaeger_get_trace":
                trace_id = arguments["trace_id"]
                resp = await client.get(f"{JAEGER_URL}/api/traces/{trace_id}")
                resp.raise_for_status()
                data = resp.json().get("data", [])

                if not data:
                    return [TextContent(type="text", text=f"Trace '{trace_id}' not found.")]

                spans = data[0].get("spans", [])
                processes = data[0].get("processes", {})

                lines = [f"Trace {trace_id} — {len(spans)} span(s):\n"]
                for span in spans:
                    proc = processes.get(span.get("processID", ""), {})
                    svc = proc.get("serviceName", "?")
                    op = span.get("operationName", "?")
                    dur = span.get("duration", 0) / 1000
                    tags = {t["key"]: t["value"] for t in span.get("tags", [])}
                    logs = span.get("logs", [])
                    line = f"  [{svc}] {op}  {dur:.1f}ms"
                    if tags.get("error"):
                        line += "  ERROR"
                    if tags.get("http.status_code"):
                        line += f"  HTTP {tags['http.status_code']}"
                    lines.append(line)
                    for log in logs:
                        for field in log.get("fields", []):
                            if field["key"] in ("message", "error", "event"):
                                lines.append(f"      log: {field['value']}")

                return [TextContent(type="text", text="\n".join(lines))]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"Jaeger API error: {e}")]


def create_app():
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    return Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )


if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=8811)
