"""Tests for the claim verifiers."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receipts.claims import Claim, extract_claims
from receipts.evidence import CommandEvidence, Evidence
from receipts.verifiers import (
    FAIL,
    PASS,
    WARN,
    Report,
    Result,
    verify,
    verify_file,
    verify_fix,
    verify_test_command,
    verify_test_count,
)


def ev(diff=None, tree=None, commands=None, session_path=None, root="/repo"):
    return Evidence(
        diff_files=diff or {},
        tree_files=tree or [],
        commands=commands or [],
        session_path=session_path,
        repo_root=root,
    )


def file_claim(path, detail="modified"):
    return Claim(kind="file", text="x", value=path, detail=detail)


# --- file verifier ---------------------------------------------------------

def test_file_in_diff_modified():
    r = verify_file(file_claim("src/a.py"), ev(diff={"src/a.py": "M"}))
    assert r.verdict == PASS and "modified" in r.evidence


def test_file_in_diff_added():
    r = verify_file(file_claim("new.py"), ev(diff={"new.py": "A"}))
    assert r.verdict == PASS and "added" in r.evidence


def test_file_in_tree_not_diff_warns():
    r = verify_file(file_claim("src/a.py"), ev(tree=["src/a.py"]))
    assert r.verdict == WARN and "working tree" in r.evidence


def test_phantom_file_fails():
    r = verify_file(file_claim("nope/missing.py"), ev())
    assert r.verdict == FAIL and "phantom" in r.evidence


def test_path_variant_matching():
    # Claim with ./ prefix still matches diff entry.
    r = verify_file(file_claim("./src/a.py"), ev(diff={"src/a.py": "M"}))
    assert r.verdict == PASS


# --- test command verifier -------------------------------------------------

def _cmd(command, exit_code=0, output=""):
    return CommandEvidence(command=command, exit_code=exit_code, output=output)


def test_command_exit_zero_passes():
    c = Claim(kind="test_command", text="x", value="python -m pytest tests/ -q")
    r = verify_test_command(c, ev(commands=[_cmd("python -m pytest tests/ -q", 0)]))
    assert r.verdict == PASS and "exit code 0" in r.evidence


def test_command_unknown_exit_warns():
    c = Claim(kind="test_command", text="x", value="pytest")
    r = verify_test_command(c, ev(commands=[_cmd("pytest tests/", None)]))
    assert r.verdict == WARN and "unknown" in r.evidence


def test_command_nonzero_fails():
    c = Claim(kind="test_command", text="x", value="pytest")
    r = verify_test_command(c, ev(commands=[_cmd("pytest", 1, "FAILED")]))
    assert r.verdict == FAIL and "exit code 1" in r.evidence


def test_command_absent_fails():
    c = Claim(kind="test_command", text="x", value="pytest")
    r = verify_test_command(c, ev(commands=[_cmd("ls -la", 0)], session_path="s.jsonl"))
    assert r.verdict == FAIL and "not found" in r.evidence


def test_command_no_session_warns():
    c = Claim(kind="test_command", text="x", value="pytest")
    r = verify_test_command(c, ev())
    assert r.verdict == WARN and "no session" in r.evidence


def test_command_loose_runner_match():
    # Claimed "pytest -q", session ran "pytest tests/ -q" — same runner,
    # different args: honest WARN, not a false FAIL.
    c = Claim(kind="test_command", text="x", value="pytest -q")
    r = verify_test_command(c, ev(commands=[_cmd("pytest tests/ -q", 0)]))
    assert r.verdict == WARN and "different args" in r.evidence


# --- test count verifier ---------------------------------------------------

def test_count_match_passes():
    c = Claim(kind="test_count", text="x", value="84/84")
    cmds = [_cmd("pytest", 0, "84 passed in 1.2s")]
    r = verify_test_count(c, ev(commands=cmds, session_path="s.jsonl"))
    assert r.verdict == PASS


def test_count_mismatch_fails():
    c = Claim(kind="test_count", text="x", value="84/84")
    cmds = [_cmd("pytest", 0, "79 passed in 1.2s")]
    r = verify_test_count(c, ev(commands=cmds, session_path="s.jsonl"))
    assert r.verdict == FAIL and "79" in r.evidence


def test_count_with_failures_in_output_fails():
    c = Claim(kind="test_count", text="x", value="81/84")
    cmds = [_cmd("pytest", 1, "81 passed, 3 failed in 2s")]
    r = verify_test_count(c, ev(commands=cmds, session_path="s.jsonl"))
    assert r.verdict == FAIL and "failed" in r.evidence


def test_count_no_session_warns():
    c = Claim(kind="test_count", text="x", value="84/84")
    r = verify_test_count(c, ev())
    assert r.verdict == WARN


def test_count_no_summary_warns():
    c = Claim(kind="test_count", text="x", value="84/84")
    cmds = [_cmd("pytest", 0, "some output without numbers")]
    r = verify_test_count(c, ev(commands=cmds, session_path="s.jsonl"))
    assert r.verdict == WARN


# --- fix verifier ----------------------------------------------------------

def test_fix_naming_file_delegates():
    c = Claim(kind="fix", text="x", value="the login bug in src/auth.py")
    r = verify_fix(c, ev(diff={"src/auth.py": "M"}))
    assert r.verdict == PASS


def test_fix_without_file_warns():
    c = Claim(kind="fix", text="x", value="the login redirect bug")
    r = verify_fix(c, ev())
    assert r.verdict == WARN and "nothing to check" in r.evidence


# --- report ----------------------------------------------------------------

def _report(verdicts):
    results = [
        Result(Claim(kind="file", text="x", value="a"), v, "e") for v in verdicts
    ]
    return Report(results=results)


def test_report_verified():
    assert _report([PASS, PASS]).verdict == "VERIFIED"


def test_report_partial():
    assert _report([PASS, WARN]).verdict == "PARTIAL"


def test_report_failed():
    assert _report([PASS, WARN, FAIL]).verdict == "FAILED"


def test_report_pass_rate():
    r = _report([PASS, PASS, WARN, FAIL])
    assert r.pass_rate == 0.5


def test_report_pass_rate_empty():
    assert _report([]).pass_rate == 1.0


def test_report_counts():
    r = _report([PASS, WARN, FAIL, FAIL])
    assert r.counts == {PASS: 1, WARN: 1, FAIL: 2}


def test_verify_dispatches_all_kinds():
    claims = extract_claims(
        "Created src/a.py. Ran pytest. 44 tests pass. Fixed the widget."
    )
    kinds = {c.kind for c in claims}
    assert {"file", "test_command", "test_count", "fix"} <= kinds
    report = verify(claims, ev())
    assert len(report.results) == len(claims)
