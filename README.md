# llm-d-bench-mcp: the llm-d benchmarking MCP server

Give Claude Code the ability to benchmark `llm-d` from plain English. Point it at this
server and it can probe a cluster, propose a benchmark plan you approve, deploy an `llm-d`
stack, run the benchmark, and explain the results, inside the same security sandbox and
approval gates as the [llm-d-benchmarking-agent](https://github.com/TalBenAmii/llm-d-benchmarking-agent)
app.

> Supported now: the `claude-agent-sdk` provider (no API key) wired into Claude Code
> (the CLI), the only path the installer sets up and verifies. The server speaks standard
> MCP, so other providers (`anthropic`, `openai`) and clients (Claude Desktop, Cursor, VS
> Code, OpenAI Codex CLI) are planned for a future release.

It is the agent's toolset re-exposed over the Model Context Protocol: 35 tools, 5 workflow
prompts, and the agent's entire knowledge base (60+ playbooks and heuristics) as readable
resources, so a generic agent behaves like a benchmarking expert rather than a blank slate.

## How it fits together

This repo is the thin MCP adapter (~500 lines: transport + approval/event adapters + the
knowledge-exposure surface). The engine (the 35 tools, the command policy, and the
`knowledge/` playbooks) lives in the
[llm-d-benchmarking-agent](https://github.com/TalBenAmii/llm-d-benchmarking-agent) repo, which
the installer clones at its latest `main` and installs into the same virtualenv. The engine
must run from a real checkout (it reads `knowledge/`, the command policy, and the read-only sibling
repos from disk at runtime), which is why it is not a pip dependency.

## Install (one command)

The installer fetches the engine + sibling repos, builds one venv with both packages,
configures the `claude-agent-sdk` provider, and registers the server with Claude Code (or
prints the config to paste yourself):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/TalBenAmii/llm-d-bench-mcp/main/scripts/install.sh)
```

Prefer to clone first? The same script runs from inside a checkout:

```bash
git clone https://github.com/TalBenAmii/llm-d-bench-mcp.git
cd llm-d-bench-mcp
./scripts/install.sh
```

It is idempotent (safe to re-run); the only prerequisite is being logged in to the `claude`
CLI (no API key — see Requirements; the installer offers to install the CLI if it's missing).
Because the engine app lands in the same venv you also get its web UI for free — the
installer's final message prints the launch line (`./scripts/run.sh --open` → http://127.0.0.1:8000).

## What your agent gets

### Tools (35)

| Group | What your agent can do | Examples |
|---|---|---|
| Sense & ground *(read-only, auto-run)* | Inspect the environment, GPUs, catalog, docs, knowledge | `probe_environment`, `advise_accelerators`, `list_catalog`, `discover_stack`, `search_knowledge`, `read_knowledge`, `fetch_key_docs`, `read_repo_doc` |
| Plan before you spend | Map a use case to a validated plan; check it fits | `propose_session_plan`, `check_capacity`, `estimate_run_duration`, `write_and_validate_config`, `generate_doe_experiment` |
| Deploy & run *(approval-gated)* | Set up repos, run the CLI, orchestrate Jobs & sweeps | `ensure_repos`, `run_setup`, `execute_llmdbenchmark`, `orchestrate_benchmark_run`, `orchestrate_sweep`, `provision_hf_secret` |
| Make sense of results *(read-only)* | Parse reports, compare runs/harnesses, track trends | `locate_and_parse_report`, `analyze_results`, `compare_reports`, `compare_harness_runs`, `aggregate_runs`, `result_history` |
| Observe & manage | Readiness checks, live cluster metrics, run management | `check_endpoint_readiness`, `observe_run_metrics`, `manage_orchestrated_runs`, `cancel_run` |
| Trust & reproduce | Provenance bundles, reproduce a run | `export_run_bundle`, `reproduce_run` |

Numbers are only ever reported from a validated Benchmark Report v0.2, never scraped from
logs or invented.

### Workflow prompts (5)

Entry points that drop your agent into the right playbook:

| Prompt | Arguments | What it sets up |
|---|---|---|
| `benchmark_this_model` | `model?`, `goal?`, `slo?` | The full interview → preconditions → plan → run → explain workflow |
| `pick_deploy_path` | `model?`, `accelerator?` | Choosing a deploy path + accelerator guidance |
| `interpret_this_report` | `report_path?` | Parsing and explaining a benchmark report |
| `design_a_sweep` | `objective?` | Designing a design-of-experiments sweep |
| `goal_seek_to_slo` | `slo` | Iterative sweep rounds toward an SLO at best goodput |

### Resources & instructions

Every knowledge file is exposed as a `doc://knowledge/<name>` resource, so your agent can read
the same playbooks the standalone agent reasons over. The server also advertises a
role/workflow preamble in its MCP `instructions` ("probe first, ground in docs, propose a
plan, run only with approval") that capable clients fold into their system prompt.

## Manual config (Claude Code)

The installer does this for you. By hand, register the console entry point by its absolute
path in the agent project's venv (the installer builds everything into that one venv):

```bash
claude mcp add llm-d-bench -s user -- /ABS/PATH/llm-d-benchmarking-agent-project/.venv/bin/llm-d-bench-mcp
# verify:  claude mcp list   (or /mcp inside a session)
```

A gated-model `HF_TOKEN` is optional; add it with `-e HF_TOKEN=hf_xxx`. The agent project's
`.env` already carries the LLM provider config and is loaded regardless of how the server is
launched. The module form (`.../.venv/bin/python -m llm_d_bench_mcp`) works too once both
packages are installed in the venv. Smoke-test it without a client using the official
inspector: `npx @modelcontextprotocol/inspector /ABS/PATH/.venv/bin/llm-d-bench-mcp`.

## Requirements & scope

- Python ≥ 3.11 and `git` (the installer handles the venv via `uv`, or `python3 -m venv`).
- LLM provider: `claude-agent-sdk`. No API key; authenticated via your `claude` CLI login.
- Client: Claude Code (the CLI).
- No cluster needed for the advisory tools and knowledge resources. The
  deploy/run/orchestrate tools need a reachable Kubernetes cluster + `kubeconfig` (and
  `HF_TOKEN` for gated models).
- The engine repo and its read-only siblings (`llm-d`, `llm-d-benchmark`, `llm-d-skills`) —
  the installer clones them all automatically.

## Security & scope

- stdio / local single-user only. The server has no network listener and no per-caller
  auth; it acts with your own kubeconfig. This is acceptable only for local use.
  HTTP/remote/shared transport is deliberately deferred, and "who may connect, whose
  credentials, what blast radius" become blocking questions before any such mode.
- Approval is re-homed to your client. Every tool call is gated by your MCP client's own
  tool-permission prompt; the richer `SessionPlan` approval uses MCP elicitation where the
  client supports it (with a graceful fallback otherwise). Nothing mutating runs without your
  say-so; never a silent auto-approve.

Design of record and rationale: [`DESIGN.md`](DESIGN.md). The engine / full agent:
[llm-d-benchmarking-agent](https://github.com/TalBenAmii/llm-d-benchmarking-agent).
