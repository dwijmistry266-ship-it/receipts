"""Verifiers: check each extracted claim against the gathered evidence.

Verdicts per claim:
  PASS — evidence confirms the claim.
  WARN — evidence is inconclusive (claim may be true, can't prove it).
  FAIL — evidence contradicts the claim, or the claim is unverifiable-by-design
         in a way that matters (phantom files).

Overall verdict: VERIFIED (all PASS) / PARTIAL (WARNs, no FAILs) /
FAILED (any FAIL).
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .claims import Claim
from .evidence import CommandEvidence, Evidence

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


@dataclass
class Result:
    claim: Claim
    verdict: str  # PASS | WARN | FAIL
    evidence: str  # one-line explanation


@dataclass
class Report:
    results: List[Result] = field(default_factory=list)
    session_path: Optional[str] = None
    repo_root: Optional[str] = None

    @property
    def counts(self):
        c = {PASS: 0, WARN: 0, FAIL: 0}
        for r in self.results:
            c[r.verdict] += 1
        return c

    @property
    def verdict(self) -> str:
        c = self.counts
        if c[FAIL]:
            return "FAILED"
        if c[WARN]:
            return "PARTIAL"
        return "VERIFIED"

    @property
    def pass_rate(self) -> float:
        """Fraction of claims that fully passed (for --fail-under)."""
        if not self.results:
            return 1.0
        return self.counts[PASS] / len(self.results)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm_cmd(cmd: str) -> str:
    """Normalize a command for comparison: collapse whitespace, strip."""
    return re.sub(r"\s+", " ", cmd).strip()


def _cmd_base(cmd: str) -> str:
    """First two tokens — the executable identity (e.g. 'python -m')."""
    return " ".join(_norm_cmd(cmd).split()[:2])


def _path_variants(path: str) -> List[str]:
    """Plausible relative forms of a claimed path."""
    p = path.strip().lstrip("./")
    variants = {p, p.lstrip("/")}
    # Also try without a leading directory (claim said src/x.py, tree has x.py).
    parts = p.split("/")
    if len(parts) > 1:
        variants.add("/".join(parts[1:]))
    return sorted(variants)


def _pytest_summary_numbers(output: str) -> Optional[dict]:
    """Parse 'N passed[, M failed][, K errors]' from pytest output."""
    m = re.search(
        r"(?P<passed>\d+)\s+passed"
        r"(?:\s*,\s*(?P<failed>\d+)\s+failed)?"
        r"(?:\s*,\s*(?P<errors>\d+)\s+errors?)?",
        output,
    )
    if not m:
        return None
    return {
        "passed": int(m.group("passed")),
        "failed": int(m.group("failed") or 0),
        "errors": int(m.group("errors") or 0),
    }


# ---------------------------------------------------------------------------
# Verifiers
# ---------------------------------------------------------------------------


def verify_file(claim: Claim, ev: Evidence) -> Result:
    variants = _path_variants(claim.value)
    for v in variants:
        if v in ev.diff_files:
            status = ev.diff_files[v]
            word = {"M": "modified", "A": "added", "D": "deleted"}.get(status, "changed")
            return Result(claim, PASS, "in git diff (%s)" % word)
    for v in variants:
        if v in ev.tree_files:
            return Result(claim, WARN, "exists in working tree, not in git diff")
    # Last resort: absolute filesystem check under repo root.
    if ev.repo_root:
        for v in variants:
            full = os.path.join(ev.repo_root, v)
            if os.path.exists(full):
                return Result(claim, WARN, "exists on disk, not tracked by git")
    return Result(claim, FAIL, "phantom file — not in diff, tree, or disk")


def _runner(cmd: str) -> str:
    """The test-runner identity: 'python -m pytest' and 'pytest' are both pytest."""
    c = re.sub(r"^python3?\s+-m\s+", "", _norm_cmd(cmd))
    return c.split()[0] if c else ""


def _find_command(claim_cmd: str, ev: Evidence):
    """Find the session command matching a claimed test command.

    Returns (CommandEvidence | None, exact: bool). Tier 1 is an exact or
    prefix match; tier 2 is the same test runner with different args.
    """
    want = _norm_cmd(claim_cmd)
    for c in ev.commands:
        got = _norm_cmd(c.command)
        if got == want or got.startswith(want) or want.startswith(got):
            return c, True
    want_runner = _runner(want)
    for c in ev.commands:
        if want_runner and _runner(_norm_cmd(c.command)) == want_runner:
            return c, False
    return None, False


def verify_test_command(claim: Claim, ev: Evidence) -> Result:
    if not ev.commands:
        if ev.session_path:
            return Result(claim, WARN, "session parsed but no commands found")
        return Result(claim, WARN, "no session provided — cannot verify")
    found, exact = _find_command(claim.value, ev)
    if found is None:
        return Result(claim, FAIL, "command not found in session transcript")
    if not exact:
        return Result(claim, WARN,
                      "similar command ran with different args: %s" % found.command)
    if found.exit_code == 0:
        return Result(claim, PASS, "executed in session, exit code 0")
    if found.exit_code is None:
        return Result(claim, WARN, "executed in session, exit status unknown")
    return Result(claim, FAIL, "executed in session, exit code %d" % found.exit_code)


def verify_test_count(claim: Claim, ev: Evidence) -> Result:
    claimed_passed, _, claimed_total = claim.value.partition("/")
    if not ev.commands:
        if ev.session_path:
            return Result(claim, WARN, "session parsed but no commands found")
        return Result(claim, WARN, "no session provided — cannot verify")
    # Look for a pytest summary in any command output.
    for c in ev.commands:
        nums = _pytest_summary_numbers(c.output)
        if nums is None:
            continue
        if nums["failed"] or nums["errors"]:
            return Result(
                claim, FAIL,
                "test output shows %d failed / %d errors"
                % (nums["failed"], nums["errors"]),
            )
        if str(nums["passed"]) == claimed_passed:
            return Result(
                claim, PASS,
                "session output confirms %s passed" % nums["passed"],
            )
        return Result(
            claim, FAIL,
            "claimed %s passed, session shows %d" % (claimed_passed, nums["passed"]),
        )
    # Fallback: exit-code-0 pytest run without a parseable summary.
    found, _exact = _find_command("pytest", ev)
    if found is not None and found.exit_code == 0:
        return Result(claim, WARN, "tests ran clean, count not parseable from output")
    return Result(claim, WARN, "no test summary found in session output")


_FIX_FILE_RE = re.compile(
    r"`?([A-Za-z0-9_\-~]+(?:/[A-Za-z0-9_\-~]+)*\.[A-Za-z0-9]+)`?"
)


def verify_fix(claim: Claim, ev: Evidence) -> Result:
    # If the fix subject names a file, delegate to the file check.
    m = _FIX_FILE_RE.search(claim.value)
    if m:
        sub = Claim(kind="file", text=claim.text, value=m.group(1))
        r = verify_file(sub, ev)
        return Result(claim, r.verdict,
                      "fix subject names %s: %s" % (m.group(1), r.evidence))
    return Result(claim, WARN, "no file or test named — nothing to check against")


def verify(claims: List[Claim], ev: Evidence) -> Report:
    results: List[Result] = []
    for claim in claims:
        if claim.kind == "file":
            results.append(verify_file(claim, ev))
        elif claim.kind == "test_command":
            results.append(verify_test_command(claim, ev))
        elif claim.kind == "test_count":
            results.append(verify_test_count(claim, ev))
        elif claim.kind == "fix":
            results.append(verify_fix(claim, ev))
        else:
            results.append(Result(claim, WARN, "unknown claim kind"))
    return Report(results=results, session_path=ev.session_path,
                  repo_root=ev.repo_root)
