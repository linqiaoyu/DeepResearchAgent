"""Model Context Protocol integration boundaries."""

from deepresearch_agent.mcp.client import (
    MCP_DISCOVERY_NODE_CONTRACT,
    DiscoveredMCPTool,
    ExternalMCPTool,
    MCPStdioClient,
)
from deepresearch_agent.mcp.server import (
    MCP_PROTOCOL_VERSION,
    MCPResearchService,
    MCPServer,
    build_mcp_capability_registry,
)

__all__ = [
    "MCP_DISCOVERY_NODE_CONTRACT",
    "MCP_PROTOCOL_VERSION",
    "DiscoveredMCPTool",
    "ExternalMCPTool",
    "MCPResearchService",
    "MCPServer",
    "MCPStdioClient",
    "build_mcp_capability_registry",
]
