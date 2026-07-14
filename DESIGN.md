# DESIGN: `llm-d-bench-mcp`, a standalone MCP server exposing the agent's tools, knowledge, and workflow

> **Status: IMPLEMENTED, split into its own repo.** Built 2026-06-30 as `app/mcp/` inside the agent
> repo; moved here 2026-07-05 as `llm_d_bench_mcp/` (fresh history, same code, re-homed imports).
> Import-checked + unit-tested (`tests/test_mcp_server.py`, 17 tests); the merge gate (ruff + pytest)
> is the authoritative green check. This doc is the design of record — code-level detail lives in the
> source files it points at, with one noted deviation in §4. It follows the locked decisions in the
> agent repo's `docs/history/proposals/05-mcp-server.md` §9 (that doc now lives only in the agent
> repo's git history — `docs/history/` was removed 2026-07-10). The engine is NOT vendored (see the
> README's "How it fits together"); the `app.*` import surface this adapter uses is guarded by an
> import-surface smoke test in the agent repo's suite, and `app/...` references below point into the
> engine checkout. Manual smoke over stdio (MCP Inspector / Claude Code) is still recommended before
> relying on it against a real client — the README has the command.

Decisions this implements (from proposal 05 §9): full operator (all functional tools, incl. mutating),
judgment shipped as MCP resources + prompts + server `instructions`, stdio transport, one `Session`
per stdio connection, approval re-homed to the connecting client, security hardening deferred to
local/stdio single-user.

## 0. Confirmation of invariants

The agent repo's `CLAUDE.md` rules 3–7 all hold: the package is pure mechanism (judgment ships as
data — resources, prompts, `instructions`); tool args stay schema-validated through `dispatch()` and
the SessionPlan gate is unchanged; the allowlist + mutating classifier run on every command; secrets
stay in the server process (subprocess env scrubbing untouched); resources and the catalog read
`knowledge/` + the upstream repos live, nothing vendored. The only changes: the human approval gate
is re-homed to the connecting client (§5), and security hardening is consciously deferred to
local/stdio single-user (§11).

## 1. Goal and what ships

A standalone process, launched by an MCP client (Claude Desktop, Claude Code, Cursor) over stdio,
exposing three MCP surfaces backed by the existing app: **tools** (the functional tools from
`REGISTRY` — probe, plan, deploy, run, orchestrate, analyze, tear down), **resources** (every
`knowledge/*.md|*.yaml` file, 50 files — the same playbooks our agent reads), and **prompts**
(workflow entry points that inject the relevant playbook + the workflow shape). Plus the
server-level `instructions` string (role + workflow), advertised at `initialize`, so even a client
that never fetches a resource inherits the basic "how this agent behaves" shape.

The product goal, in one line: let a generic agent behave like our benchmark agent. The tools are
its hands; the resources/prompts/instructions are the nudge toward our judgment.

## 2. Package layout (`llm_d_bench_mcp/`)

Per-file responsibilities live in this repo's `CLAUDE.md` (the scoped map). In one line each:
`server.py` builds the low-level `Server`, registers all six handlers, and runs the stdio loop;
`adapters.py` holds the per-connection context (§4) + approval (§5) + emit (§6) adapters;
`content.py` is the knowledge-exposure surface (§7–§9); `__main__.py` makes
`python -m llm_d_bench_mcp` work. All judgment-bearing text lives in `knowledge/` (data) and is
referenced, not duplicated, by `content.py`.

## 3. Tool surface (`server.py`)

**`list_tools` mirrors `tool_definitions()`** — one mapping detail: our dicts use snake_case
`input_schema`, MCP `types.Tool` wants camelCase `inputSchema`; translated per tool.

**`call_tool` routes through `dispatch()` and mirrors `loop._invoke`'s error handling.** `dispatch()`
already returns `{"error": ...}` dicts for unknown-tool / invalid-args instead of raising, and lets a
handler raise `ApprovalRejected`; we catch exactly that one exception, as the web loop does, and
return `{"rejected": True, "reason": ...}`. Results return as JSON `TextContent` — the floor every
client understands — optionally alongside the structured-dict form for clients that support it.

**Meta-tool adaptation.** Two of the 36 registry tools are web-loop-only. `load_tools` exists only
for lazy tool-group reveal protecting the web agent's cached prompt prefix; an MCP client manages its
own tool list, so it is dropped (if a future client chokes on 35 tools, revisit via
`tools/list_changed`; out of scope for v1). `suggest_next_steps` is kept unchanged: its dict output
is plain structured suggestions the connecting agent renders however it likes (no UI buttons). So
`_EXPOSED` = all of `REGISTRY` minus `load_tools` (35 tools). Documented in `CLAUDE.md`.

## 4. Per-connection context (`adapters.py`)

A stdio server process serves exactly one client connection, so "one `Session` per connection"
(decision 05 §9.5) collapses to one `ToolContext` + `Session` per process, built lazily on first use
and reused for the process lifetime (`build_connection_context`). This gives the operator flow
(propose plan → run → analyze) a shared `workspace/` + run registry across calls, for free. It builds
the same `ToolContext` the web path builds, wiring our approval (§5) and emit (§6) adapters in place
of the loop's, and pre-warms the live catalog.

**Decision taken (deviation from the original plan).** Rather than refactor `app/main.py`'s startup
to share a `build_context(...)` helper (which would touch the web path with no local way to run the
suite and verify it), `build_connection_context` constructs the deps directly, mirroring
`app/main.py` with a pointer comment. The drift surface is ~5 lines and a later refactor can still
extract the shared helper. The benefit: the change stayed purely additive — no existing runtime code
was modified, so the web path is untouched and the merge gate only had the new package + tests to
validate.

The `Session` object is optional for v1: most fields are web-UI bookkeeping and we need only the
`ctx`. Hold a singleton `ToolContext`; attach a minimal `Session` only if an exposed tool reads it
(today that is sidebar namespace inference only, so likely unneeded).

## 5. Approval adapter (`adapters.py`)

`ToolContext.request_approval` (`ApproveFn`) is called with `kind ∈ {"command", "session_plan"}`.

**`kind == "command"` → return `True` (client already gated the call).** Every `tools/call` is
independently prompted by the connecting client's permission system before the handler runs, so by
the time a handler reaches `ctx.run_command()`, the user has already allowed this tool invocation.
This is the "works freely like a normal local agent" decision, not a silent auto-approve: the human
checkpoint is the client's per-call prompt, and a single tool call maps to a single user permission
(a tool that internally runs several commands still corresponds to one user-approved invocation,
which is the right granularity).

**`kind == "session_plan"` → elicitation, sentinel fallback.** The plan is inert (it mutates
nothing), so the safety here is confirmation quality, not gating a mutation. Where the client
advertises the `elicitation` capability (captured at `initialize`), ask explicitly via `elicit_form`
with a single boolean `approve` field; otherwise pass through — the plan is returned in the tool
result and every downstream mutating tool call is still independently client-gated. On any
elicitation error, degrade to the sentinel path (treat as unsupported) so an older client never
hard-fails a plan proposal. (SDK mechanics — `elicit_form` over the deprecated `elicit`, flat
primitive-only schema, `ElicitResult` actions — verified against `mcp` 1.28.1; see `adapters.py`.)

The allowlist + classifier still execute on every command regardless of `kind` handling; the adapter
only decides the human-gate question, never whether a command is allowed.

## 6. Event adapter (`adapters.py`)

`EmitFn` feeds the web UI's live event stream; MCP has no equivalent rich surface. Map best-effort:
forward to the client as an MCP logging notification (when a logging level is set) so a curious
client can watch progress, and always write to the existing structured logger
(`app/observability/`) so the server has its own trail. `emit` must never raise into a handler;
wrap and swallow (a dropped progress line is not a tool failure).

## 7. Resources (`content.py`)

Publish every knowledge file as an MCP resource under `doc://knowledge/<stem>`. Source of truth is
the same glob the prompt builder uses (`_knowledge_sections` in `app/agent/prompt.py`):
`knowledge/*.md|*.yaml|*.yml` minus `EXCLUDED_KNOWLEDGE_FILES` (`CLAUDE.md`, `README.md`) — 50 files
today. Descriptions reuse the prompt builder's one-line purpose extractor; mime type by suffix.
`_resolve_knowledge_uri` must reject any URI resolving outside `knowledge/` (path-traversal guard;
read-only, but still). Declaring `@list_resources()` is what advertises the `resources` capability.

Later (out of v1 scope): also expose the upstream repo docs catalogued in `knowledge/key_docs.yaml`
under a `repo://` scheme. Noted, not built.

## 8. Prompts (`content.py`)

Workflow prompts — the user-invokable "slash commands" a client surfaces — each returning messages
that embed the relevant playbook content from `knowledge/` plus a short workflow directive:

| Prompt name | Arguments | Returns (message content) |
|---|---|---|
| `benchmark_this_model` | `model`, `goal?`, `slo?` | the interview→preconditions→plan→run→explain workflow + `quickstart_playbook.md` + `welllit_path_advisor.yaml` |
| `pick_deploy_path` | `model?`, `accelerator?` | `deploy_path_playbook.md` + `welllit_path_advisor.yaml` |
| `interpret_this_report` | `report_path?` | `results_interpretation.md` + `analysis.md`, directing use of `analyze_results`/`locate_and_parse_report` |
| `design_a_sweep` | `objective?` | `sweep_playbook.md`, directing `generate_doe_experiment`/`orchestrate_sweep` |
| `goal_seek_to_slo` | `slo` | `sweep_playbook.md` (its goal-seeking section), directing iterative sweep rounds + `analyze_results` |

`list_prompts` returns the same static table as `types.Prompt` entries. The directive text is the
only new prose; the substance is loaded from `knowledge/` so it cannot drift.

## 9. Server instructions (`content.py`)

Advertised once at `initialize` (constructor arg: `Server("llm-d-bench", instructions=...)`;
`create_initialization_options()` folds it in); many clients merge it into their system prompt.
Assembled from the existing `ROLE` constant in `app/agent/prompt.py` (reuse, don't duplicate),
stripped of web-UI specifics (approval cards, sidebar, WebSocket), plus a short MCP workflow
preamble: interview → probe and check preconditions → propose a SessionPlan and get it approved →
run → explain from the validated Benchmark Report, never from logs; read `doc://knowledge/*` for
judgment; mutations are gated by the client. Exact text in `content.py`.

## 10. Entrypoint and packaging (`__main__.py`, `pyproject.toml`)

`server.build_server(settings)` registers the six handlers bound to the per-process `ToolContext`;
`main()` runs the stdio loop; `__main__.py` makes `python -m llm_d_bench_mcp` work;
`[project.scripts]` adds the `llm-d-bench-mcp` console command. Dependency: `mcp>=1.28,<2` — pinned
away from the in-development v2 on `main`, which has an incompatible constructor-callback API.
Python ≥3.10 (already the project floor) is what `mcp` requires.

Client registration (Claude Desktop `claude_desktop_config.json` / Claude Code `.mcp.json`),
identical stdio block:

```json
{ "mcpServers": { "llm-d-bench": {
    "command": "python", "args": ["-m", "llm_d_bench_mcp"],
    "env": { "HF_TOKEN": "${HF_TOKEN}" }
} } }
```

Secrets go in `env` (expanded at launch), never in `args`.

## 11. Security posture (deferred, on the record)

Per decision 05 §9.6 / §8, v1 targets local single-user / stdio:
- The server acts with the user's own kubeconfig; it is trusted like any local agent the user runs.
- No connection authn/authz, no per-caller credential scoping, no network listener (stdio only).
- Still enforced (free, pure): the allowlist + mutating classifier on every command; subprocess env
  scrubbing; the read-only path for read-only tools.
- The human gate is the connecting client's per-tool-call permission prompt (§5).

**This is acceptable ONLY for local/stdio use. Before any HTTP / shared / remote transport, "who may
connect, whose credentials, what is the blast radius" become blocking, not deferred.** Flagged loudly
so the deferral stays a choice.

## 12. Tests (`tests/test_mcp_server.py`)

17 hermetic tests (no live cluster, no LLM, no network) in one flat file, matching the house
`tests/test_*.py` convention. They cover: `list_tools` mirroring the registry (`load_tools` absent),
`call_tool` dispatch and invalid-args error surfacing, both approval kinds (command auto-true;
session-plan elicit accept/decline plus the sentinel fallback), resources matching the knowledge
glob with traversal rejection, prompt listing/embedding, and non-empty web-UI-free instructions.
Logic was validated by direct calls against the installed `mcp` 1.28.0; the merge gate runs them
under the full suite, inside the ~14s hermetic budget (`tests/CLAUDE.md`; `conftest` already forces
`SIMULATE=0`).

## 13. Out of scope for v1 (noted, not built)

1. HTTP / streamable transport and the authz it forces (§11).
2. Multi-connection / multi-tenant session mapping (stdio = one connection, §4).
3. Repo-doc resources under `repo://` (§7).
4. Group-based lazy tool reveal via `tools/list_changed` (§3 meta-tool note).
5. Rich event surface (cards, command-trail streaming): only best-effort MCP logging (§6).
