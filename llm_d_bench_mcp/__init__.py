"""Standalone MCP server (stdio) re-exposing the llm-d-benchmarking-agent's tools, knowledge,
and workflow to external MCP clients (Claude Desktop, Claude Code, Cursor, ...).

Pure mechanism: it reuses the agent's ``app/tools`` (registry / dispatch / ToolContext) and ships
the judgment as MCP resources + prompts + server ``instructions`` sourced from the agent's
``knowledge/`` — never duplicated here. The engine lives in the llm-d-benchmarking-agent repo,
which the installer clones and installs next to this one. See ``DESIGN.md`` for the full design.
"""
from __future__ import annotations

from llm_d_bench_mcp.server import build_server, main

__all__ = ["build_server", "main"]
