"""Model Context Protocol integration boundaries."""

from deepresearch_agent.mcp.server import (
    MCP_PROTOCOL_VERSION,
    MCPResearchService,
    MCPServer,
    build_mcp_capability_registry,
)

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "MCPResearchService",
    "MCPServer",
    "build_mcp_capability_registry",
]
