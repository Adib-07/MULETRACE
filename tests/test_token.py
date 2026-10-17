"""Token handling: server-side parsing and the env file written by scripts/demo_start.sh."""
import os, re, stat, subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("raw,want", [("abc", "abc"), (" abc\n", "abc"), ("\tabc  ", "abc"), ("", ""), (None, "")])
def test_load_token_strips_whitespace(app_module, raw, want):
    assert app_module.load_token(raw) == want


@pytest.fixture(scope="module")
def app_module(api_env):
    import importlib, sys
    return sys.modules.get("api.main") or importlib.import_module("api.main")


def run_env_only(env_file, *args):
    env = dict(os.environ, MULETRACE_ENV_FILE=str(env_file))
    return subprocess.run(["bash", os.path.join(ROOT, "scripts", "demo_start.sh"), "--env-only", *args],
                          env=env, capture_output=True, text=True, check=True)


def test_demo_start_env_file_format_and_rotation(tmp_path):
    f = tmp_path / "muletrace.env"
    out = run_env_only(f)                                   # creates the file when missing
    text = f.read_text()
    assert re.fullmatch(r"MULETRACE_TOKEN=[A-Za-z0-9_-]{32}\n", text), "plain KEY=value, no quotes/export, one line"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    token = text.strip().split("=", 1)[1]
    assert token not in out.stdout + out.stderr and "cut -d= -f2" in out.stdout   # prints the command, never the token
    run_env_only(f)
    assert f.read_text() == text                            # no rotation unless asked
    run_env_only(f, "--rotate-token")
    assert f.read_text() != text and re.fullmatch(r"MULETRACE_TOKEN=[A-Za-z0-9_-]{32}\n", f.read_text())
