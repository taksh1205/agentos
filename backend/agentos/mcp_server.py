"""Host-bound stdio MCP server. Tools cannot select their own workspace identity."""

import os

from mcp.server.fastmcp import FastMCP

from .rag import Retrieval
from .store import Store
from .tools import ToolService

mcp = FastMCP("AgentOS scoped business tools")
store = Store()
service = ToolService(store, None)


def invoke(name, args, approval_id=None):
    w = os.getenv("MCP_WORKSPACE")
    if not w:
        raise PermissionError("Missing host workspace binding")
    scopes = os.getenv("MCP_SCOPES", "data:read").split(",")
    # Legacy MCP_PERMISSIONS remains a second, narrower host allowlist.
    legacy = os.getenv("MCP_PERMISSIONS")
    if legacy:
        required = "search" if name == "document_search" else "analytics"
        if required not in legacy.split(","):
            raise PermissionError("Host tool permission denied")
    if name == "document_search" and service.rag is None:
        service.rag = Retrieval(store)
    return service.invoke(w, name, args, scopes=scopes, approval_id=approval_id)


@mcp.tool()
def document_search(query: str, k: int = 5, source: str | None = None) -> dict:
    return invoke("document_search", dict(query=query, k=k, source=source))


@mcp.tool()
def business_metrics(
    metric: str = "revenue", start: str | None = None, end: str | None = None
) -> dict:
    return invoke("business_metrics", dict(metric=metric, start=start, end=end))


@mcp.tool()
def dataset_schema() -> dict:
    return invoke("dataset_schema", {})


@mcp.tool()
def inventory_retrieval() -> dict:
    return invoke("inventory_retrieval", {})


@mcp.tool()
def invoice_analysis(as_of: str | None = None) -> dict:
    return invoke("invoice_analysis", {"as_of": as_of})


@mcp.tool()
def create_report(title: str, body: str, approval_id: str) -> dict:
    return invoke("create_report", dict(title=title, body=body), approval_id)


@mcp.tool()
def export_csv(dataset: str, approval_id: str) -> dict:
    return invoke("export_csv", dict(dataset=dataset), approval_id)


@mcp.tool()
def create_followup(title: str, description: str, approval_id: str) -> dict:
    return invoke("create_followup", dict(title=title, description=description), approval_id)


@mcp.tool()
def draft_email(to: str, subject: str, body: str, approval_id: str) -> dict:
    return invoke("draft_email", dict(to=to, subject=subject, body=body), approval_id)


@mcp.tool()
def update_inventory(sku: str, quantity: int, approval_id: str) -> dict:
    return invoke("update_inventory", dict(sku=sku, quantity=quantity), approval_id)


@mcp.tool()
def create_notification(message: str, approval_id: str) -> dict:
    return invoke("create_notification", dict(message=message), approval_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
