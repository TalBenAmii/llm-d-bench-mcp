# llm-d-bench-mcp — standalone MCP server (stdio) for the llm-d-benchmarking-agent

> The **thin MCP adapter** split out of the agent repo: it re-exposes the agent's tools +
> knowledge + workflow to *other people's* MCP clients (Claude Desktop, Claude Code, Cursor).
> Pure mechanism: it imports the engine (`app.*`) from the
> [llm-d-benchmarking-agent](https://github.com/TalBenAmii/llm-d-benchmarking-agent) checkout —
> the judgment ships as MCP resources/prompts/server-`instructions` sourced from the agent's
> `knowledge/` (data, never duplicated here). Full design of record → **`DESIGN.md`**.
> Run it with `python -m llm_d_bench_mcp` (or the `llm-d-bench-mcp` console script).

## Repo structure
```
llm-d-bench-mcp/
├─ llm_d_bench_mcp/
│  ├─ __init__.py       exports build_server, main
│  ├─ __main__.py       python -m llm_d_bench_mcp → main()
│  ├─ server.py         low-level Server: list_tools/call_tool (run_tool) + stdio loop + wires resources/prompts
│  ├─ adapters.py       per-connection adapters: build_connection_context (one ToolContext per stdio connection) + ApproveFn (client-gated commands + elicit_form/sentinel for SessionPlan) + EmitFn (→ MCP log notification, best-effort, + structured log)
│  └─ content.py        knowledge-exposure surface: knowledge/ → doc://knowledge/<stem> resources (+ traversal guard) + 5 workflow prompts (embed the relevant knowledge/ playbooks) + INSTRUCTIONS (server-level role/workflow nudge)
├─ tests/               pytest suite (hermetic; needs the agent repo importable — see below)
├─ scripts/install.sh   the one-command installer (curl-able); clones the agent repo at latest main
├─ README.md            user-facing docs (install, tools, prompts, security)
└─ DESIGN.md            the implementation spec / design of record
```

## Non-negotiables
1. **Thin code, thick agent** — adapters + transport only, no decision logic. All judgment lives
   in the agent repo's `knowledge/` and is exposed, never duplicated.
2. **Reuse, don't fork** — `list_tools` mirrors the agent's `tool_definitions()`; `call_tool` →
   `run_tool` → the shared `dispatch()`. Don't re-implement validation or handlers here.
3. **The approval gate is re-homed, not removed** (`adapters.py`) — `kind="command"` returns True
   (the client already prompted for the tool call); `kind="session_plan"` uses MCP `elicit_form`
   with a sentinel pass-through fallback. Never a silent auto-approve of a mutation.
4. **Security deferred to local/stdio single-user** (`DESIGN.md` §11) — acceptable only over
   stdio; revisit before any HTTP/shared transport.
5. **SDK pin:** `mcp>=1.28,<2`, low-level `mcp.server.lowlevel.Server` (not `FastMCP`, not the v2
   on the SDK's `main` branch). camelCase `inputSchema`/`mimeType` on the `types.*` models.
6. **The engine is a checkout, not a pip dep** — `app.*` must import from a real
   llm-d-benchmarking-agent checkout (its `knowledge/`, allowlist, and sibling repos are read
   from disk at runtime). The installer clones the agent repo at **latest `main`** and
   `pip install -e`s it into the same venv as this package. Never vendor engine code here.

## Dev setup & tests
- Dev layout: this repo sits as a **sibling of `llm-d-benchmarking-agent-project/`** inside the
  agent monorepo checkout; the shared venv is the agent project's `.venv` with BOTH packages
  editable-installed (`pip install -e <agent-project> -e .`).
- The import surface this adapter uses from `app.*` is guarded by an import-surface smoke test in
  the agent repo (its merge gate breaks on a rename before it can break new installs here).
- Tests: `tests/test_mcp_server.py` (hermetic: tool mirror/dispatch, approval re-homing,
  resources, prompts, instructions wiring). Don't run the suite by hand — the merge gate
  (`.git/hooks/pre-commit`, main-only) runs ruff + pytest, using the agent project's venv.
