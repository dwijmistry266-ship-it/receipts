# receipts

Verify your claims against the evidence before you report done.

## When to use

Run receipts at the end of any coding task, before you tell the user
"fixed, tests pass". It cross-checks every verifiable claim in your
summary — files touched, test commands run, test counts — against hard
evidence: the git diff, the working tree, and your session transcript.

## How to run

```bash
receipts verify "Fixed auth.py, 84 tests pass" --session
receipts verify --summary-file SUMMARY.md --session ~/.claude/projects/x.jsonl
echo "$SUMMARY" | receipts verify --session
```

- `--session` with no value auto-discovers your most recent session under
  `~/.claude/projects` or `~/.codex/sessions`.
- `--json` for machine-readable output.
- `--fail-under 100` as a CI gate: fail unless every claim verifies.

## Reading the verdict

- **✅ PASS** — evidence confirms the claim (file in the diff, command ran
  with exit code 0, count matches test output).
- **⚠️ WARN** — inconclusive. The claim may be true but there's no evidence
  trail (e.g. no session provided). Treat warnings as "unproven".
- **❌ FAIL** — evidence contradicts the claim: phantom file, command never
  ran, count mismatch, tests failed.

Overall: **VERIFIED** (all pass) / **PARTIAL** (warnings only) / **FAILED**
(any fail). A FAILED verdict means: don't report done yet — go produce the
missing evidence.

## CI usage

```yaml
- run: pip install receipts-py
- run: receipts verify "$AGENT_SUMMARY" --session --fail-under 100
```

## Honest limits

receipts is deterministic, not omniscient. It verifies *that* things
happened, not *that they were correct*. A test suite can pass and still
be wrong. "Fixed the bug" with no named file or test is unverifiable by
design — name the file, name the test, keep the receipts.
