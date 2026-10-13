# BUILD REPORT — receipts v0.1.0

**Repo:** https://github.com/dwijmistry266-ship-it/receipts
**Date:** 2026-10-14
**Commits:**
- `f8dec7e3c5ff486918bbbbfed1c7b209a11196b3` — init (README seed)
- `f5b2bf4bb9794047a07ca1390c4f5c5e1aa87180` — feat: receipts v0.1.0 (25 files)

## What was built

**receipts** — verify your agent's claims against the evidence, deterministically.
The #1 pain of the agent era is the "false done" ("fixed, tests pass" — but it
isn't). receipts takes the agent's summary and cross-checks every verifiable
claim against hard evidence: git diffs, the working tree, session transcripts.

### Package (`receipts/`, stdlib only, Python 3.9+)
- `claims.py` — deterministic regex-based claim extraction: file paths
  (verb-led, backticked, bare), test commands (pytest / `python -m pytest` /
  npm / go / cargo), test counts ("84 tests pass", "69/69 passing",
  "84 passed"), "fixed X" statements. Same input → same claims, every time.
  Guards against URL tails, CLI flags, and plain English.
- `evidence.py` — git diff (staged + unstaged vs `--diff` base), working-tree
  inventory, and session transcript parsing: a canonical JSONL command format
  plus best-effort Claude Code (`~/.claude/projects`) and Codex
  (`~/.codex/sessions`) adapters with exit-code guessing. `--session` with no
  value auto-discovers the latest session.
- `verifiers.py` — per-claim verdicts: ✅ PASS (confirmed), ⚠️ WARN
  (inconclusive — treated as unproven), ❌ FAIL (contradicted: phantom files,
  commands never run, count mismatches, failing tests). Conservative by
  design: a warning beats a false pass. Overall VERIFIED / PARTIAL / FAILED.
- `reporters.py` — terminal and JSON output.
- `cli.py` — `receipts verify` with summary via arg / `--summary-file` /
  stdin; flags `--session`, `--repo`, `--diff`, `--json`, `--fail-under`
  (CI gate, mirroring slopscan).
- `skill.md` — agent skill for Claude Code, Codex, Cursor: self-verify before
  reporting done.

### Tests — 86/86 passing
- `test_claims.py` (25): extraction, dedupe, URL/flag rejection, ordering,
  determinism.
- `test_evidence.py` (24): canonical/Claude/Codex parsing, exit-code guessing,
  real temp git repos for diff/tree, session auto-discovery.
- `test_verifiers.py` (22): every verifier's pass/warn/fail branches,
  phantom files, count mismatches, report aggregation.
- `test_e2e.py` (15): end-to-end CLI runs on temp git repos with canned
  sessions — VERIFIED/FAILED paths, `--json`, `--fail-under`, stdin/file/arg
  input, reporters.
- `tests/run_tests.py` — stdlib runner (no pytest needed); `scripts/self_scan.py`
  — the dogfood gate: receipts verifies its own test run (VERIFIED).

### CI (`.github/workflows/ci.yml`)
- Tests on Python 3.9–3.13 (`pytest` with stdlib-runner fallback).
- Dogfood job: `scripts/self_scan.py` must report VERIFIED or the build fails.

### Theme — CLASSIFIED DOSSIER (new profile aesthetic)
- `assets/banner.svg` — 1200×360: dossier black + faint grid, amber EVIDENCE
  tape strip, giant typewriter wordmark, red CONFIDENTIAL rubber stamp (−8°,
  distressed dashed inner border), redacted `SUBJECT: ████████████` privacy
  joke, `SLOP-DETECTION DIVISION // AI-DEV-TOOLS UNIT`, `FILED: 2026-10-14`,
  generated barcode, perforated cut line.
- `scripts/gen_banner.py` — reusable generator (`--title`, `--case-no`,
  `--tagline`, `--filed`, `--redacted`, `--output`) for future repos.
- README opens as **CASE FILE #002** with the exact 3-line hook, flat-square
  dossier badges (red), and an honest-limits section.

### Packaging
- `pyproject.toml` — distribution name `receipts-py` (bare `receipts` is
  owned by a dead 2014 Mozilla package; `receipts-py` verified 404 on PyPI
  at build time). Console script `receipts`. MIT license (Dwij Mistry).

## Verification log
- PyPI: `receipts-py` → 404 (free) ✅ · `receipts` → 200 (taken, as expected) ✅
- Tests: 86/86 pass via stdlib runner ✅
- Self-scan: `scripts/self_scan.py` → VERIFIED ✅
- Live CLI self-check on own repo: correct PARTIAL (count claim warns without
  a session — the honest behavior) ✅
- GitHub repo created public via API; pushed via git-API pattern (no
  force-push; ref re-checked before PATCH) ✅
- Remote tree verified: 26 files on `main` ✅
- Banner SVG validated as well-formed XML ✅

## Not yet done (needs Dwij)
- **PyPI publish** — must run from his machine: `python -m build && twine upload dist/*`
- **CI green** — workflow will run on first push; not yet observed
- **X launch post** — needs his explicit approval (standing rule)
- slopscan retroactively becoming CASE FILE #001 — separate task, not touched
