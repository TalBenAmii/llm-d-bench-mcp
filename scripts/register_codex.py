"""Register the existing stdio server in Codex without changing other settings."""
from __future__ import annotations

import json
import os
import tempfile
import tomllib
from pathlib import Path


def register(config: Path, command: list[str]) -> bool:
    """Append a new server section, or preserve an existing matching registration."""
    if not command:
        raise ValueError("an MCP server launch command is required")
    original = config.read_text() if config.exists() else ""
    parsed = tomllib.loads(original)
    existing = parsed.get("mcp_servers", {}).get("llm-d-bench")
    if existing is not None:
        if existing.get("command") != command[0] or existing.get("args", []) != command[1:]:
            raise ValueError(
                "llm-d-bench already uses a different command; registration was not changed. "
                "Inspect it with 'codex mcp get llm-d-bench' before updating it."
            )
        return False

    # JSON strings and arrays have compatible TOML syntax for these values. Validate
    # the whole document before writing, including configs that use inline tables.
    updated = original.rstrip("\n") + "\n\n[mcp_servers.llm-d-bench]\n"
    updated += f"command = {json.dumps(command[0], ensure_ascii=False)}\n"
    updated += f"args = {json.dumps(command[1:], ensure_ascii=False)}\n"
    updated += 'startup_timeout_sec = 30\ntool_timeout_sec = 3600\n'
    updated += 'default_tools_approval_mode = "prompt"\n'
    tomllib.loads(updated)

    config.parent.mkdir(parents=True, exist_ok=True)
    mode = config.stat().st_mode & 0o777 if config.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=".codex-mcp-", dir=config.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(updated)
        temporary.chmod(mode)
        temporary.replace(config)
    finally:
        temporary.unlink(missing_ok=True)
    return True


if __name__ == "__main__":
    import sys

    config = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    try:
        changed = register(config, sys.argv[1:])
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Codex registration failed: {exc}") from exc
    print(f"Registered llm-d-bench in {config}" if changed else
          "llm-d-bench is already registered; existing settings were preserved.")
