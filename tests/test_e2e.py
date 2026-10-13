"""End-to-end tests: real temp git repos + canned sessions through the CLI."""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receipts import cli
from receipts.reporters import render_json, render_terminal
from receipts.verifiers import Report, Result, PASS, WARN, FAIL
from receipts.claims import Claim

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def make_repo():
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
    with open(os.path.join(tmp, "auth.py"), "w") as fh:
        fh.write("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp, check=True)
    # Unstaged modification -> shows in `git diff`.
    with open(os.path.join(tmp, "auth.py"), "a") as fh:
        fh.write("y = 2\n")
    return tmp


def run_cli(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(argv))
    return code, buf.getvalue()


# --- happy path ------------------------------------------------------------

def test_e2e_verified():
    repo = make_repo()
    summary = "Modified auth.py. Ran python -m pytest tests/ -q. 84 tests pass."
    code, out = run_cli("verify", summary, "--repo", repo,
                        "--session", os.path.join(FIX, "session_pass.jsonl"))
    assert code == 0
    assert "VERIFIED" in out


def test_e2e_json_output():
    repo = make_repo()
    summary = "Modified auth.py. 84 tests pass."
    code, out = run_cli("verify", summary, "--repo", repo,
                        "--session", os.path.join(FIX, "session_pass.jsonl"),
                        "--json")
    assert code == 0
    payload = json.loads(out)
    assert payload["verdict"] == "VERIFIED"
    assert payload["pass_rate"] == 1.0
    assert len(payload["claims"]) == 2


# --- failure paths ---------------------------------------------------------

def test_e2e_phantom_file_failed():
    repo = make_repo()
    summary = "Created ghost_module.py with the fix."
    code, out = run_cli("verify", summary, "--repo", repo)
    assert code == 1
    assert "FAILED" in out
    assert "phantom" in out


def test_e2e_count_mismatch_failed():
    repo = make_repo()
    summary = "Modified auth.py. Ran pytest. 84 tests pass."
    code, out = run_cli("verify", summary, "--repo", repo,
                        "--session", os.path.join(FIX, "session_fail.jsonl"))
    assert code == 1
    assert "FAILED" in out


def test_e2e_command_never_ran_failed():
    repo = make_repo()
    summary = "Ran cargo test and all green."
    code, out = run_cli("verify", summary, "--repo", repo,
                        "--session", os.path.join(FIX, "session_pass.jsonl"))
    assert code == 1
    assert "FAILED" in out


# --- gates -----------------------------------------------------------------

def test_fail_under_blocks():
    repo = make_repo()
    # WARN (no session) => pass_rate 0.5 < 100
    summary = "Modified auth.py. 84 tests pass."
    code, _out = run_cli("verify", summary, "--repo", repo, "--fail-under", "100")
    assert code == 1


def test_fail_under_passes_when_met():
    repo = make_repo()
    summary = "Modified auth.py."
    code, _out = run_cli("verify", summary, "--repo", repo, "--fail-under", "100")
    assert code == 0


def test_fail_under_zero_always_passes():
    repo = make_repo()
    summary = "Created ghost_module.py."
    code, _out = run_cli("verify", summary, "--repo", repo, "--fail-under", "0")
    # FAILED verdict still exits 1 regardless of the gate.
    assert code == 1


# --- input modes -----------------------------------------------------------

def test_summary_file(tmp_path=None):
    repo = make_repo()
    fd, path = tempfile.mkstemp(suffix=".md")
    with os.fdopen(fd, "w") as fh:
        fh.write("Modified auth.py.")
    try:
        code, out = run_cli("verify", "--summary-file", path, "--repo", repo)
        assert code == 0 and "VERIFIED" in out
    finally:
        os.unlink(path)


def test_no_summary_exits_2(monkeypatch=None):
    # stdin is a tty in the test runner? Force empty by passing nothing and
    # ensuring stdin read returns "" — emulate via no args and closed stdin.
    import subprocess as sp
    proc = sp.run(
        [sys.executable, "-m", "receipts", "verify", "--repo", make_repo()],
        stdin=sp.DEVNULL, capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert proc.returncode == 2


def test_version_flag():
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            cli.main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    else:
        raise AssertionError("--version should exit 0")
    assert "receipts" in buf.getvalue()


def test_no_command_prints_help():
    code, out = run_cli()
    assert code == 2 and "verify" in out


# --- reporters -------------------------------------------------------------

def _rep():
    return Report(results=[
        Result(Claim(kind="file", text="t", value="a.py"), PASS, "in git diff (modified)"),
        Result(Claim(kind="test_count", text="t", value="4/4"), WARN, "no session"),
        Result(Claim(kind="file", text="t", value="ghost.py"), FAIL, "phantom file"),
    ], repo_root="/r", session_path="/s.jsonl")


def test_terminal_render_marks():
    out = render_terminal(_rep())
    assert "\u2705" in out and "\u26a0" in out and "\u274c" in out
    assert "PARTIAL" not in out and "FAILED" in out


def test_terminal_render_empty():
    out = render_terminal(Report(results=[]))
    assert "no verifiable claims" in out


def test_json_render_shape():
    payload = json.loads(render_json(_rep()))
    assert payload["verdict"] == "FAILED"
    assert payload["repo_root"] == "/r"
    assert len(payload["claims"]) == 3
    assert payload["claims"][0]["evidence"] == "in git diff (modified)"
