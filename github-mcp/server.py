"""
GitHub MCP Server — exposes GitHub API as kagent tools.

Tools:
  gh_get_pr_info      — get PR metadata (title, body, branch, author)
  gh_get_pr_files     — list files changed in a PR with their status
  gh_post_pr_comment  — post a new comment on a PR
  gh_update_pr_comment — update an existing comment by ID
  gh_find_pr_comment  — find an existing bot comment by prefix
"""
import os
import json
import httpx
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Mount, Route
import uvicorn

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

server = Server("github-mcp")


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="gh_get_pr_info",
            description="Get pull request metadata: title, body, author, base branch, head branch, number.",
            inputSchema={
                "type": "object",
                "required": ["owner", "repo", "pr_number"],
                "properties": {
                    "owner": {"type": "string", "description": "GitHub org or user"},
                    "repo":  {"type": "string", "description": "Repository name"},
                    "pr_number": {"type": "integer", "description": "Pull request number"},
                },
            },
        ),
        Tool(
            name="gh_get_pr_files",
            description=(
                "List all files changed in a pull request. "
                "Returns filename, status (added/modified/removed), additions, deletions, and patch excerpt."
            ),
            inputSchema={
                "type": "object",
                "required": ["owner", "repo", "pr_number"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo":  {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
            },
        ),
        Tool(
            name="gh_post_pr_comment",
            description="Post a new Markdown comment on a pull request.",
            inputSchema={
                "type": "object",
                "required": ["owner", "repo", "pr_number", "body"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo":  {"type": "string"},
                    "pr_number": {"type": "integer"},
                    "body": {"type": "string", "description": "Markdown content of the comment"},
                },
            },
        ),
        Tool(
            name="gh_update_pr_comment",
            description="Update an existing PR comment by its comment ID.",
            inputSchema={
                "type": "object",
                "required": ["owner", "repo", "comment_id", "body"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo":  {"type": "string"},
                    "comment_id": {"type": "integer", "description": "Comment ID to update"},
                    "body": {"type": "string", "description": "New Markdown content"},
                },
            },
        ),
        Tool(
            name="gh_find_pr_comment",
            description=(
                "Find an existing bot comment on a PR that starts with a given prefix. "
                "Returns the comment ID if found, or null. Use before posting to avoid duplicates."
            ),
            inputSchema={
                "type": "object",
                "required": ["owner", "repo", "pr_number", "prefix"],
                "properties": {
                    "owner": {"type": "string"},
                    "repo":  {"type": "string"},
                    "pr_number": {"type": "integer"},
                    "prefix": {"type": "string", "description": "Comment body prefix to search for"},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    async with httpx.AsyncClient(timeout=15.0, headers=_headers()) as client:
        try:
            if name == "gh_get_pr_info":
                owner, repo, pr = arguments["owner"], arguments["repo"], arguments["pr_number"]
                resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr}")
                resp.raise_for_status()
                d = resp.json()
                info = {
                    "number":       d["number"],
                    "title":        d["title"],
                    "author":       d["user"]["login"],
                    "base_branch":  d["base"]["ref"],
                    "head_branch":  d["head"]["ref"],
                    "head_sha":     d["head"]["sha"],
                    "body":         (d.get("body") or "")[:500],
                    "state":        d["state"],
                    "created_at":   d["created_at"],
                }
                return [TextContent(type="text", text=json.dumps(info, indent=2))]

            elif name == "gh_get_pr_files":
                owner, repo, pr = arguments["owner"], arguments["repo"], arguments["pr_number"]
                files = []
                page = 1
                while True:
                    resp = await client.get(
                        f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr}/files",
                        params={"per_page": 100, "page": page},
                    )
                    resp.raise_for_status()
                    batch = resp.json()
                    if not batch:
                        break
                    files.extend(batch)
                    page += 1

                result = [
                    {
                        "filename":  f["filename"],
                        "status":    f["status"],
                        "additions": f["additions"],
                        "deletions": f["deletions"],
                        "patch":     (f.get("patch") or "")[:300],
                    }
                    for f in files
                ]
                return [TextContent(type="text", text=json.dumps(result, indent=2))]

            elif name == "gh_post_pr_comment":
                owner, repo, pr = arguments["owner"], arguments["repo"], arguments["pr_number"]
                resp = await client.post(
                    f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr}/comments",
                    json={"body": arguments["body"]},
                )
                resp.raise_for_status()
                data = resp.json()
                return [TextContent(type="text", text=json.dumps({"comment_id": data["id"], "url": data["html_url"]}))]

            elif name == "gh_update_pr_comment":
                owner, repo = arguments["owner"], arguments["repo"]
                resp = await client.patch(
                    f"{GITHUB_API}/repos/{owner}/{repo}/issues/comments/{arguments['comment_id']}",
                    json={"body": arguments["body"]},
                )
                resp.raise_for_status()
                data = resp.json()
                return [TextContent(type="text", text=json.dumps({"comment_id": data["id"], "url": data["html_url"]}))]

            elif name == "gh_find_pr_comment":
                owner, repo, pr = arguments["owner"], arguments["repo"], arguments["pr_number"]
                prefix = arguments["prefix"]
                page = 1
                while True:
                    resp = await client.get(
                        f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr}/comments",
                        params={"per_page": 100, "page": page},
                    )
                    resp.raise_for_status()
                    comments = resp.json()
                    if not comments:
                        break
                    for c in comments:
                        if c["body"].startswith(prefix):
                            return [TextContent(type="text", text=json.dumps({"comment_id": c["id"], "found": True}))]
                    page += 1
                return [TextContent(type="text", text=json.dumps({"comment_id": None, "found": False}))]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except httpx.HTTPStatusError as e:
            return [TextContent(type="text", text=f"GitHub API error {e.response.status_code}: {e.response.text}")]
        except httpx.HTTPError as e:
            return [TextContent(type="text", text=f"HTTP error: {e}")]


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
    uvicorn.run(create_app(), host="0.0.0.0", port=8812)
