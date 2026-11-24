"""Validated, time-bounded MCP client. Subprocess environment carries trusted identity."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .tools import MUTATIONS, SCHEMAS


async def call_tool(workspace, tool, args, *, approval_id=None, scopes=None):
    if tool not in SCHEMAS:
        raise PermissionError("Tool not allowlisted")
    parsed = SCHEMAS[tool].model_validate(args).model_dump(mode="json")
    if tool in MUTATIONS:
        if not approval_id:
            raise PermissionError("Approval required")
        parsed["approval_id"] = approval_id
    env = {
        **{
            key: os.environ[key]
            for key in (
                "PATH",
                "HOME",
                "SYSTEMROOT",
                "DATABASE_URL",
                "EMBEDDING_BACKEND",
                "EMBEDDING_MODEL",
                "EMBEDDING_REVISION",
                "RERANK_MODEL",
                "RERANK_REVISION",
                "HASH_DIMENSION",
                "HF_HOME",
                "HF_HUB_OFFLINE",
                "MCP_PERMISSIONS",
                "OMP_NUM_THREADS",
                "RETRIEVAL_METHOD",
                # Network settings (not credentials) so a child behind a corporate proxy
                # or TLS inspection can still validate its model cache.
                "HTTPS_PROXY",
                "https_proxy",
                "NO_PROXY",
                "no_proxy",
                "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE",
                "CURL_CA_BUNDLE",
                "HF_ENDPOINT",
                "HF_HUB_CACHE",
                "SENTENCE_TRANSFORMERS_HOME",
            )
            if key in os.environ
        },
        "MCP_WORKSPACE": workspace,
        "MCP_SCOPES": ",".join((["data:read"] if scopes is None else scopes)),
    }

    async def execute():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "agentos.mcp_server"], env=env
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, parsed)
                if result.isError:
                    raise ValueError("MCP tool execution rejected")
                value = result.structuredContent or json.loads(result.content[0].text)
                if not isinstance(value, dict) or len(json.dumps(value)) > 200000:
                    raise ValueError("Malformed or oversized tool output")
                expected = (
                    "sources"
                    if tool == "document_search"
                    else "datasets"
                    if tool == "dataset_schema"
                    else "receipt"
                    if tool in MUTATIONS
                    else "metric"
                    if tool == "business_metrics"
                    else "rows"
                )
                if expected not in value:
                    raise ValueError("Tool output schema mismatch")
                return value

    return await asyncio.wait_for(execute(), float(os.getenv("MCP_TIMEOUT_SECONDS", "40")))
