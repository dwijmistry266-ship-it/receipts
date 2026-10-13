"""Tests for evidence gathering: transcripts, git, discovery."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receipts import evidence
from receipts.evidence import (
    CommandEvidence,
    Evidence,
    _guess_exit_code,
    collect_diff,
    collect_tree,
    discover_session,
    parse_session,
)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    return os.path.join(FIX, name)


# --- canonical JSONL -------------------------------------------------------

def test_parse_canonical():
    cmds = parse_session(fixture("session_pass.jsonl"))
    assert len(cmds) == 2
    assert cmds[0].command == "python -m pytest tests/ -q"
    assert cmds[0].exit_code == 0
    assert "84 passed" in cmds[0].output


def test_parse_canonical_exit_1():
    cmds = parse_session(fixture("session_fail.jsonl"))
    assert cmds[0].exit_code == 1
    assert "3 failed" in cmds[0].output


def test_parse_canonical_missing_exit_code():
    cmds = parse_session(fixture("session_partial.jsonl"))
    assert len(cmds) == 1
    assert cmds[0].exit_code is None


def test_parse_skips_blank_and_garbage():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write("\nnot json\n")
        fh.write('{"type": "command", "command": "pytest"}\n')
        fh.write('{"type": "note", "text": "hi"}\n')
        path = fh.name
    try:
        cmds = parse_session(path)
        assert len(cmds) == 1 and cmds[0].command == "pytest"
    finally:
        os.unlink(path)


# --- Claude Code format ----------------------------------------------------

def test_parse_claude_code():
    cmds = parse_session(fixture("claude_session.jsonl"))
    assert len(cmds) == 1
    assert cmds[0].command == "python -m pytest tests/ -q"
    # "44 passed" in output implies exit 0 via the guesser.
    assert cmds[0].exit_code == 0


def test_claude_pending_command_without_result():
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        fh.write(json.dumps({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "id": "t9", "name": "Bash",
                "input": {"command": "pytest -x"},
            }]},
        }) + "\n")
        path = fh.name
    try:
        cmds = parse_session(path)
        assert len(cmds) == 1
        assert cmds[0].command == "pytest -x"
        assert cmds[0].exit_code is None
    finally:
        os.unlink(path)


# --- Codex format ----------------------------------------------------------

def test_parse_codex():
    cmds = parse_session(fixture("codex_session.jsonl"))
    assert any(c.command == "pytest tests/" and c.exit_code == 0 for c in cmds)


# --- exit code guessing ----------------------------------------------------

def test_guess_explicit_exit_0():
    assert _guess_exit_code("done. exit code 0") == 0


def test_guess_explicit_exit_2():
    assert _guess_exit_code("exit code 2") == 2


def test_guess_pytest_passed():
    assert _guess_exit_code("44 passed in 0.87s") == 0


def test_guess_pytest_failed_not_zero():
    assert _guess_exit_code("81 passed, 3 failed") is None  # ambiguous -> None


def test_guess_traceback():
    assert _guess_exit_code("Traceback (most recent call last):\n  boom") == 1


def test_guess_nothing():
    assert _guess_exit_code("hello world") is None


# --- git evidence ----------------------------------------------------------

def _make_repo():
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
    with open(os.path.join(tmp, "a.py"), "w") as fh:
        fh.write("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp, check=True)
    return tmp


def test_collect_diff_unstaged():
    repo = _make_repo()
    with open(os.path.join(repo, "a.py"), "a") as fh:
        fh.write("y = 2\n")
    diff = collect_diff(repo)
    assert diff.get("a.py") == "M"


def test_collect_diff_staged_new_file():
    repo = _make_repo()
    with open(os.path.join(repo, "b.py"), "w") as fh:
        fh.write("z = 3\n")
    subprocess.run(["git", "add", "b.py"], cwd=repo, check=True)
    diff = collect_diff(repo)
    assert diff.get("b.py") == "A"


def test_collect_diff_clean_repo():
    repo = _make_repo()
    assert collect_diff(repo) == {}


def test_collect_tree_lists_files():
    repo = _make_repo()
    assert "a.py" in collect_tree(repo)


def test_collect_tree_includes_untracked():
    repo = _make_repo()
    with open(os.path.join(repo, "new.py"), "w") as fh:
        fh.write("n = 0\n")
    assert "new.py" in collect_tree(repo)


def test_repo_root_none_outside_repo():
    tmp = tempfile.mkdtemp()
    assert evidence.repo_root(tmp) is None


# --- session discovery -----------------------------------------------------

def test_discover_session_finds_newest():
    tmp = tempfile.mkdtemp()
    proj = os.path.join(tmp, ".claude", "projects", "p1")
    os.makedirs(proj)
    old = os.path.join(proj, "old.jsonl")
    new = os.path.join(proj, "new.jsonl")
    with open(old, "w") as fh:
        fh.write("{}\n")
    with open(new, "w") as fh:
        fh.write("{}\n")
    os.utime(old, (1, 1))
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = tmp
    try:
        found = discover_session()
    finally:
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = old_home
    assert found == new


def test_discover_session_none_when_empty():
    tmp = tempfile.mkdtemp()
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = tmp
    try:
        assert discover_session() is None
    finally:
        if old_home is None:
            del os.environ["HOME"]
        else:
            os.environ["HOME"] = old_home
