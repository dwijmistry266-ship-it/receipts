"""Reporters: terminal and JSON output for verification reports."""

import json

from .claims import Claim
from .verifiers import FAIL, PASS, WARN, Report, Result

_MARK = {PASS: "\u2705", WARN: "\u26a0\ufe0f", FAIL: "\u274c"}
_KIND_LABEL = {
    "file": "file",
    "test_command": "tests ran",
    "test_count": "test count",
    "fix": "fix claim",
}


def _claim_label(claim: Claim) -> str:
    return _KIND_LABEL.get(claim.kind, claim.kind)


def render_terminal(report: Report) -> str:
    lines = []
    lines.append("RECEIPTS — claim verification")
    if report.repo_root:
        lines.append("repo: %s" % report.repo_root)
    if report.session_path:
        lines.append("session: %s" % report.session_path)
    lines.append("")
    if not report.results:
        lines.append("no verifiable claims found in the summary.")
    for r in report.results:
        mark = _MARK[r.verdict]
        lines.append("%s [%s] %s" % (mark, _claim_label(r.claim), r.claim.value))
        lines.append("    \u2514\u2500 %s" % r.evidence)
    lines.append("")
    c = report.counts
    lines.append(
        "verdict: %s  (%d passed, %d warnings, %d failed of %d claims)"
        % (report.verdict, c[PASS], c[WARN], c[FAIL], len(report.results))
    )
    if report.verdict == "FAILED":
        lines.append("Receipts or it didn't happen.")
    return "\n".join(lines)


def render_json(report: Report) -> str:
    payload = {
        "verdict": report.verdict,
        "pass_rate": round(report.pass_rate, 4),
        "repo_root": report.repo_root,
        "session_path": report.session_path,
        "claims": [
            {
                "kind": r.claim.kind,
                "text": r.claim.text,
                "value": r.claim.value,
                "detail": r.claim.detail,
                "verdict": r.verdict,
                "evidence": r.evidence,
            }
            for r in report.results
        ],
    }
    return json.dumps(payload, indent=2)
