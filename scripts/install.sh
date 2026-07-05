#!/usr/bin/env bash
# install.sh — one interactive command to install the llm-d-bench MCP server and register it
# with Claude Code (the CLI).
#
# It does everything end-to-end:
#   1. fetches this repo + the llm-d-benchmarking-agent repo (the engine, at latest main)
#   2. clones the read-only sibling repos (llm-d / llm-d-benchmark / llm-d-skills)
#   3. builds a .venv and installs the engine + this server (`pip install -e` both → the
#      `llm-d-bench-mcp` command)
#   4. configures the claude-agent-sdk provider (no API key — uses your local `claude` login) + writes .env
#   5. registers the server with Claude Code (or just prints the config for you to paste)
#
# Scope (for now): the only verified path is the claude-agent-sdk provider + the Claude Code CLI
# client. Other providers (anthropic, openai) and clients (Claude Desktop, Cursor, VS Code, Codex
# CLI) are planned for a future release — see README.md.
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/TalBenAmii/llm-d-bench-mcp/main/scripts/install.sh)
#   ./scripts/install.sh            # same script, run from inside a checkout
#   ./scripts/install.sh -h
#
# Env overrides:
#   INSTALL_DIR=/path   where to clone the agent monorepo (default: ~/llm-d-benchmarking-agent)
#   REPOS_DIR=/path     where the sibling repos live (default: the agent project's parent dir)
#   SKIP_PULL=1         don't fast-forward an existing agent checkout to latest main
#
# Transport is stdio / local single-user (the server runs on YOUR machine against YOUR kubeconfig);
# there is no network/remote mode. See README.md for the security model and manual config.
set -euo pipefail

log()  { printf '\033[35m▸\033[0m %s\n' "$*"; }            # llm-d purple bullet
step() { printf '\n\033[1;35m━━ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[install] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m[install] ERROR: %s\033[0m\n' "$*" >&2; exit 1; }
trap 'rc=$?; [[ $rc -ne 0 ]] && printf "\n\033[1;31m[install] aborted (exit %s).\033[0m Fix the issue above and re-run — the script is idempotent.\n" "$rc" >&2' EXIT

case "${1:-}" in -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; trap - EXIT; exit 0 ;; esac

INSTALL_DIR="${INSTALL_DIR:-$HOME/llm-d-benchmarking-agent}"

find_mcp_root() {  # locate a checkout of THIS repo, from the CWD or the script's own path
  local d="$PWD"
  while [[ "$d" != "/" && -n "$d" ]]; do
    [[ -f "$d/llm_d_bench_mcp/__main__.py" ]] && { printf '%s' "$d"; return 0; }
    [[ -f "$d/llm-d-bench-mcp/llm_d_bench_mcp/__main__.py" ]] && { printf '%s' "$d/llm-d-bench-mcp"; return 0; }
    d="$(dirname "$d")"
  done
  local sd; sd="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")/.." 2>/dev/null && pwd || true)"   # script lives in scripts/
  [[ -n "$sd" && -f "$sd/llm_d_bench_mcp/__main__.py" ]] && { printf '%s' "$sd"; return 0; }
  return 1
}

MCP_DIR="$(find_mcp_root || true)"
if [[ -z "$MCP_DIR" ]]; then
  [[ "${_MCP_BOOTSTRAPPED:-0}" == 1 ]] && die "could not locate the MCP repo after cloning (bootstrap loop)."
  command -v git >/dev/null 2>&1 || die "git is required to fetch the repos — install git and re-run."
  # Clone the agent monorepo FIRST (git refuses to clone into a non-empty dir, so it must land
  # before this repo does), then this repo as a sibling inside it.
  if [[ ! -d "$INSTALL_DIR/.git" ]]; then
    step "Fetching the agent repo (the engine) → $INSTALL_DIR"
    git clone "https://github.com/TalBenAmii/llm-d-benchmarking-agent" "$INSTALL_DIR"
  fi
  MCP_DIR="$INSTALL_DIR/llm-d-bench-mcp"   # live as a sibling of the agent project
  if [[ -d "$MCP_DIR/.git" ]]; then
    log "MCP repo already cloned at $MCP_DIR — reusing it."
  else
    step "Fetching llm-d-bench-mcp → $MCP_DIR"
    git clone "https://github.com/TalBenAmii/llm-d-bench-mcp" "$MCP_DIR"
  fi
  [[ -f "$MCP_DIR/scripts/install.sh" ]] || die "cloned repo is missing $MCP_DIR/scripts/install.sh"
  export _MCP_BOOTSTRAPPED=1
  exec bash "$MCP_DIR/scripts/install.sh" "$@"   # re-run on-disk so paths resolve normally
fi
log "MCP repo: $MCP_DIR"

# --- the engine: the llm-d-benchmarking-agent repo, at latest main -------------------------------
# Prefer the sibling layout (this repo checked out inside the agent monorepo); else INSTALL_DIR.
if [[ -f "$(dirname "$MCP_DIR")/llm-d-benchmarking-agent-project/pyproject.toml" ]]; then
  MONOREPO="$(dirname "$MCP_DIR")"
else
  MONOREPO="$INSTALL_DIR"
  if [[ ! -d "$MONOREPO/.git" ]]; then
    step "Fetching the agent repo (the engine) → $MONOREPO"
    command -v git >/dev/null 2>&1 || die "git is required to fetch the agent repo — install git and re-run."
    git clone "https://github.com/TalBenAmii/llm-d-benchmarking-agent" "$MONOREPO"
  fi
fi
PROJECT_DIR="$MONOREPO/llm-d-benchmarking-agent-project"
[[ -f "$PROJECT_DIR/pyproject.toml" ]] || die "agent project not found at $PROJECT_DIR"

# Track latest main (the supported combination is this adapter + the engine's main tip). Best-effort:
# a dirty/diverged dev checkout is left alone with a warning.
if [[ "${SKIP_PULL:-0}" != 1 && -d "$MONOREPO/.git" ]]; then
  branch="$(git -C "$MONOREPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  if [[ "$branch" == "main" ]]; then
    git -C "$MONOREPO" pull --ff-only >/dev/null 2>&1 && log "Agent repo fast-forwarded to latest main." \
      || warn "could not fast-forward the agent repo (dirty or diverged) — continuing with what's checked out."
  else
    warn "agent repo is on branch '$branch', not main — continuing with what's checked out (SKIP_PULL=1 silences this)."
  fi
fi

cd "$PROJECT_DIR"
REPOS_DIR="${REPOS_DIR:-$(dirname "$PROJECT_DIR")}"   # sibling repos live next to the project
VENV="$PROJECT_DIR/.venv"
log "Engine: $PROJECT_DIR"

SUDO=""; if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

step "Prerequisites"
ensure_tool() {  # $1 = command name
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing $1…"; $SUDO apt-get update -y >/dev/null 2>&1 || true
    $SUDO apt-get install -y "$1" ca-certificates >/dev/null 2>&1 || true
  fi
  command -v "$1" >/dev/null 2>&1 || die "$1 is required but could not be installed automatically — install it and re-run."
}
ensure_tool git
ensure_tool curl

# Find a Python >=3.11 interpreter.
PYBIN=""
for c in python3.13 python3.12 python3.11 python3; do
  command -v "$c" >/dev/null 2>&1 || continue
  v="$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo 0.0)"
  if [[ "${v%%.*}" -eq 3 && "${v##*.}" -ge 11 ]]; then PYBIN="$c"; break; fi
done
[[ -n "$PYBIN" ]] || die "Python >=3.11 is required and none was found. Install python3.11+ (e.g. 'apt install python3.11 python3.11-venv') and re-run."
log "Python: $PYBIN ($("$PYBIN" -V 2>&1))"

# Pick a venv backend: prefer uv; else a python3 that can build a venv; else bootstrap uv.
if command -v uv >/dev/null 2>&1; then
  USE_UV=1
elif "$PYBIN" -c 'import ensurepip' >/dev/null 2>&1; then
  USE_UV=0
else
  warn "python cannot create virtualenvs here (python3-venv/ensurepip missing) — bootstrapping uv."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || die "uv bootstrap failed — install python3-venv and re-run."
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv bootstrapped but not on PATH — add ~/.local/bin to PATH and re-run."
  USE_UV=1
fi
log "venv backend: $([[ "$USE_UV" == 1 ]] && echo uv || echo 'python3 -m venv')"

# shellcheck source-path=SCRIPTDIR/..
# shellcheck source=/dev/null
source "$PROJECT_DIR/scripts/_env.sh"   # provides ensure_env + clone_if_missing + set_env_var
step "Sibling repos (read-only, under $REPOS_DIR)"
# llm-d + llm-d-benchmark live under the llm-d org; the skills library is in llm-d-incubation.
clone_if_missing llm-d           "$REPOS_DIR/llm-d"
clone_if_missing llm-d-benchmark "$REPOS_DIR/llm-d-benchmark"
clone_if_missing llm-d-skills    "$REPOS_DIR/llm-d-skills" llm-d-incubation

step "Install the engine + the MCP server (.venv + pip install -e both)"
if [[ ! -x "$VENV/bin/python" ]]; then
  if [[ "$USE_UV" == 1 ]]; then log "Creating venv with uv…"; uv venv --python "$PYBIN" "$VENV" >/dev/null
  else log "Creating venv with python3 -m venv…"; "$PYBIN" -m venv "$VENV"; fi
fi
PY="$VENV/bin/python"
if [[ "$USE_UV" == 1 ]]; then
  uv pip install --python "$PY" -e "$PROJECT_DIR" -e "$MCP_DIR" >/dev/null
else
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -e "$PROJECT_DIR" -e "$MCP_DIR" >/dev/null
fi
"$PY" -c "import llm_d_bench_mcp" >/dev/null 2>&1 || die "the MCP server failed to import after install."
log "Installed. The server imports OK."

ensure_env   # create .env from .env.example if missing

step "LLM provider"
set_env_var LLM_PROVIDER claude-agent-sdk
log "Using claude-agent-sdk — no API key (it authenticates through your local 'claude' login)."
# claude-agent-sdk can't run without the `claude` CLI: surface an already-installed copy (adds
# ~/.local/bin to PATH) or offer the official installer. Non-fatal (it warns for you) — you can
# install + log in later.
ensure_claude_cli || true

# HF_TOKEN (for GATED HF model deploys, e.g. Llama/Gemma) isn't prompted — set it in the project's
# .env, or pass `-e HF_TOKEN=hf_…` to your client, only if you'll actually deploy a gated model.

if [[ -x "$VENV/bin/llm-d-bench-mcp" ]]; then
  CMD_DISPLAY="$VENV/bin/llm-d-bench-mcp"
else
  CMD_DISPLAY="$PY -m llm_d_bench_mcp"
fi

step "Register with Claude Code"
if [[ "$(menu_select 'Register the MCP server with Claude Code?' 0 \
         'Claude Code (CLI) — register it for you' \
         "Skip — I'll wire it up myself")" == 0 ]]; then
  register_mcp_server "$CMD_DISPLAY" "" 1 || true   # INTERACTIVE=1: the helper prompts for scope and, if the CLI is missing, warns with a manual snippet (never fatal)
else
  log "Skipping registration — re-run this installer or see $MCP_DIR/README.md to register it later."
fi

step "Done"
log "Launch command : $CMD_DISPLAY"
log "Smoke-test it  : npx @modelcontextprotocol/inspector $CMD_DISPLAY   (lists 35 tools, 5 prompts, knowledge resources)"
log "Provider/config: $PROJECT_DIR/.env"
log "Web UI (optional): the browser app is installed too — start it with:  cd $PROJECT_DIR && ./scripts/run.sh --open   → http://127.0.0.1:8000"
log "The server is stdio/local — it runs on this machine against your kubeconfig. Advisory tools work"
log "with no cluster; deploy/run tools need a reachable cluster. Mutations are approved in YOUR client's"
log "own tool-permission prompt. Full details: $MCP_DIR/README.md"
trap - EXIT
