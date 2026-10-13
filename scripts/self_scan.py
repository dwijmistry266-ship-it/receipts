#!/usr/bin/env python3
"""Self-scan gate: receipts verifies its own test run.

Runs the test suite, records a canonical session, then verifies the
summary "<N> tests pass." against that session. Exits 0 only on VERIFIED.
Used by CI (the dogfood job) and locally.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from receipts.claims import extract_claims
from receipts.evidence import Evidence, parse_session
from receipts.verifiers import verify


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "tests/run_tests.py"],
        cwd=ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    m = re.search(r"(\d+) passed in [\d.]+s", output)
    if not m:
        print("self-scan: could not parse test count from output")
        print(output[-500:])
        return 1
    count = m.group(1)

    session_line = {
        "type": "command",
        "command": "python tests/run_tests.py",
        "exit_code": proc.returncode,
        "output": output,
    }
    fd, session_path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps(session_line) + "\n")

    summary = "%s tests pass." % count
    claims = extract_claims(summary)
    evidence = Evidence(
        diff_files={}, tree_files=[],
        commands=parse_session(session_path),
        session_path=session_path, repo_root=ROOT,
    )
    report = verify(claims, evidence)
    os.unlink(session_path)

    for r in report.results:
        mark = {"PASS": "ok", "WARN": "??", "FAIL": "XX"}[r.verdict]
        print("[%s] %s: %s" % (mark, r.claim.value, r.evidence))
    print("self-scan verdict:", report.verdict)
    return 0 if report.verdict == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
