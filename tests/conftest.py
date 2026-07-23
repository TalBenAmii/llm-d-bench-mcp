"""Shared pytest fixtures.

The agent (the engine this adapter re-exposes) must be importable as ``app`` — the installer and
the dev setup both `pip install -e` the agent repo into the same venv as this package. Paths
(knowledge/, the command policy) resolve through the agent's own settings, so the suite works wherever
that checkout lives.
"""
from __future__ import annotations

import os

import pytest

from app.config import get_settings

# Hermetic baseline: neutralize the developer's .env SIMULATE toggle before the first settings
# read. A dev .env with SIMULATE=1 otherwise makes approval-dependent tests deadlock — simulate
# mode skips the per-command approval those tests wait for. Env vars take precedence over the
# .env file in pydantic-settings; clearing the lru_cache covers any earlier read.
os.environ["SIMULATE"] = "0"
get_settings.cache_clear()


@pytest.fixture()
def tool_ctx(tmp_path):
    """A ToolContext wired to the real repos but an isolated temp workspace."""
    from app.security.policy import CommandPolicy
    from app.security.runner import CommandRunner
    from app.tools.context import ToolContext

    s = get_settings()
    policy = CommandPolicy.from_file(s.command_policy_path)
    runner = CommandRunner(s.repo_paths)
    return ToolContext(settings=s, policy=policy, runner=runner, workspace=tmp_path / "ws")
