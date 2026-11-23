"""Installer routing and config preservation without downloads or real user config writes."""
from __future__ import annotations

import os
import runpy
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "scripts/register_codex.py"
register = runpy.run_path(str(REGISTER))["register"]


def test_registration_preserves_other_servers_and_handles_spaces(tmp_path):
    config = tmp_path / "config.toml"
    original = '# Keep this comment\nmodel = "example"\n[mcp_servers.other]\ncommand = "other"\n'
    config.write_text(original)
    config.chmod(0o640)
    command = ["/a path/python", "-m", "llm_d_bench_mcp"]
    assert register(config, command)
    result = tomllib.loads(config.read_text())
    server = result["mcp_servers"].pop("llm-d-bench")
    assert result == tomllib.loads(original)
    assert config.read_text().startswith(original)
    assert config.stat().st_mode & 0o777 == 0o640
    assert server == {
        "command": command[0], "args": command[1:], "startup_timeout_sec": 30,
        "tool_timeout_sec": 3600, "default_tools_approval_mode": "prompt",
    }


def test_registration_creates_private_config_and_is_idempotent(tmp_path):
    config = tmp_path / "new/config.toml"
    assert register(config, ["/server"])
    original = config.read_bytes()
    assert config.stat().st_mode & 0o777 == 0o600
    assert not register(config, ["/server"])
    assert config.read_bytes() == original


def test_matching_registration_keeps_custom_options(tmp_path):
    config = tmp_path / "config.toml"
    original = '[mcp_servers."llm-d-bench"]\ncommand = "/server"\ntool_timeout_sec = 900\nenabled = false\n'
    config.write_text(original)
    assert not register(config, ["/server"])
    assert config.read_text() == original


@pytest.mark.parametrize("original", [
    '[mcp_servers.llm-d-bench]\ncommand = "/different/server"\n',
    '[mcp_servers.llm-d-bench]\nurl = "https://example.invalid/mcp"\n',
    'model = [broken',
    'mcp_servers = {}\n',  # closed inline table cannot be extended by a section
])
def test_registration_failure_does_not_modify_config(tmp_path, original):
    config = tmp_path / "config.toml"
    config.write_text(original)
    with pytest.raises(ValueError):
        register(config, ["/server"])
    assert config.read_text() == original


def _executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


@pytest.fixture()
def installation(tmp_path):
    """Run the actual installer; fake only dependency installation and external CLIs."""
    from app.config import PROJECT_ROOT

    repo = tmp_path / "checkout"
    mcp = repo / "llm-d-bench-mcp"
    project = repo / "llm-d-benchmarking-agent-project"
    for directory in [mcp / "scripts", mcp / "llm_d_bench_mcp",
                      project / "scripts", project / ".venv/bin"]:
        directory.mkdir(parents=True)
    (mcp / "llm_d_bench_mcp/__main__.py").touch()
    (project / "pyproject.toml").touch()
    (project / ".env").write_text("LLM_PROVIDER=codex-sdk\nKEEP_ME=original\n")
    shutil.copy2(ROOT / "scripts/install.sh", mcp / "scripts/install.sh")
    shutil.copy2(PROJECT_ROOT / "scripts/_env.sh", project / "scripts/_env.sh")
    for name in ["llm-d", "llm-d-benchmark", "llm-d-skills"]:
        (repo / name).mkdir()
        (repo / name / "present").touch()
    _executable(project / ".venv/bin/python", f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n")
    _executable(project / ".venv/bin/llm-d-bench-mcp", "#!/bin/sh\nexit 0\n")
    # Redirect only the helper's target file, not HOME or CODEX_HOME. Execute its real function.
    (mcp / "scripts/register_codex.py").write_text(
        "import os, runpy, sys\nfrom pathlib import Path\n"
        f"runpy.run_path({str(REGISTER)!r})['register']"
        "(Path(os.environ['TEST_CODEX_CONFIG']), sys.argv[1:])\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ["uv", "claude", "codex"]:
        _executable(binaries / name,
                    f'#!/bin/sh\nprintf "%s\\n" "{name} $*" >> "$TEST_INSTALL_TRACE"\nexit 0\n')
    for name in ["git", "curl"]:
        _executable(binaries / name, "#!/bin/sh\nexit 99\n")
    config = tmp_path / "codex/config.toml"
    trace = tmp_path / "trace"
    env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "SKIP_PULL": "1",
           "TEST_CODEX_CONFIG": str(config), "TEST_INSTALL_TRACE": str(trace),
           "REPOS_DIR": str(repo)}

    def run(*args, script=None, cwd=None):
        return subprocess.run(
            ["bash", str(script or mcp / "scripts/install.sh"), *args],
            cwd=cwd or tmp_path, env=env, capture_output=True, text=True,
            start_new_session=True, timeout=20,
        )

    return run, project, config, trace, tmp_path


def test_codex_installer_preserves_provider_and_does_not_use_claude(installation):
    run, project, config, trace, _ = installation
    original = (project / ".env").read_bytes()
    for _ in range(2):
        result = run("--client", "codex")
        assert result.returncode == 0, result.stdout + result.stderr
    server = tomllib.loads(config.read_text())["mcp_servers"]["llm-d-bench"]
    assert server["command"] == str(project / ".venv/bin/llm-d-bench-mcp")
    assert server["default_tools_approval_mode"] == "prompt"
    assert (project / ".env").read_bytes() == original
    assert "claude " not in trace.read_text()


def test_codex_does_not_create_web_env_and_supports_module_fallback(installation):
    run, project, config, _, _ = installation
    (project / ".env").unlink()
    (project / ".venv/bin/llm-d-bench-mcp").unlink()
    result = run("--client", "codex")
    assert result.returncode == 0, result.stdout + result.stderr
    server = tomllib.loads(config.read_text())["mcp_servers"]["llm-d-bench"]
    assert server["command"] == str(project / ".venv/bin/python")
    assert server["args"] == ["-m", "llm_d_bench_mcp"]
    assert not (project / ".env").exists()


@pytest.mark.parametrize("args", [(), ("--client", "claude-code")])
def test_claude_installer_remains_the_default(installation, args):
    run, project, config, trace, _ = installation
    result = run(*args)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LLM_PROVIDER=claude-agent-sdk" in (project / ".env").read_text()
    assert "KEEP_ME=original" in (project / ".env").read_text()
    assert "claude mcp add llm-d-bench" in trace.read_text()
    assert not config.exists()


@pytest.mark.parametrize("args", [("--client",), ("--client", "invalid"), ("--invalid",)])
def test_bad_arguments_fail_before_installation(installation, args):
    run, _, config, trace, _ = installation
    result = run(*args)
    assert result.returncode != 0
    assert not config.exists() and not trace.exists()


def test_help_does_not_install(installation):
    run, _, config, trace, _ = installation
    result = run("--help")
    assert result.returncode == 0 and "--client claude-code|codex" in result.stdout
    assert not config.exists() and not trace.exists()


def test_missing_codex_fails_before_installation(installation):
    run, _, config, trace, temporary = installation
    launcher = temporary / "without-codex.sh"
    installer = temporary / "checkout/llm-d-bench-mcp/scripts/install.sh"
    launcher.write_text(
        '#!/bin/bash\ncommand() {\n'
        '  if [[ "$*" == "-v codex" ]]; then return 1; fi\n'
        '  builtin command "$@"\n}\nexport -f command\n'
        f'exec bash {shlex.quote(str(installer))} "$@"\n'
    )
    result = run("--client", "codex", script=launcher)
    assert result.returncode != 0 and "Codex CLI is required" in result.stderr
    assert not config.exists() and not trace.exists()


def test_bootstrap_preserves_client_option(installation):
    run, project, config, trace, temporary = installation
    bootstrap = temporary / "bootstrap.sh"
    shutil.copy2(ROOT / "scripts/install.sh", bootstrap)
    # A curl-launched script first finds the already-downloaded repo at INSTALL_DIR.
    project.parent.joinpath(".git").mkdir()
    project.parent.joinpath("llm-d-bench-mcp/.git").mkdir()
    # Pass INSTALL_DIR without changing the fixture's home or actual user settings.
    launcher = temporary / "launch.sh"
    launcher.write_text(
        f"#!/bin/bash\nexport INSTALL_DIR={shlex.quote(str(project.parent))}\n"
        f"exec bash {shlex.quote(str(bootstrap))} \"$@\"\n"
    )
    result = run("--client", "codex", script=launcher)
    assert result.returncode == 0, result.stdout + result.stderr
    assert config.exists()
    assert "claude " not in trace.read_text()
