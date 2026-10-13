"""Tests for deterministic claim extraction."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receipts.claims import Claim, extract_claims


def kinds(text):
    return [(c.kind, c.value) for c in extract_claims(text)]


# --- file claims -----------------------------------------------------------

def test_verb_created_path():
    cs = extract_claims("Created src/auth.py with the login flow.")
    assert ("file", "src/auth.py") in kinds("Created src/auth.py with the login flow.")


def test_verb_modified_backticked():
    cs = kinds("Modified `receipts/cli.py` to add --json.")
    assert ("file", "receipts/cli.py") in cs


def test_verb_deleted():
    cs = kinds("Deleted old_cache.py.")
    assert ("file", "old_cache.py") in cs


def test_bare_path_mentioned():
    cs = kinds("The fix lives in src/handlers/auth.py and tests cover it.")
    assert ("file", "src/handlers/auth.py") in cs


def test_dedupe_same_path_twice():
    cs = extract_claims("Fixed src/a.py. Also updated `src/a.py` again.")
    assert [c.value for c in cs if c.kind == "file"].count("src/a.py") == 1


def test_url_not_a_path():
    cs = kinds("See https://example.com/docs for details.")
    assert not [c for c in cs if c[0] == "file"]


def test_cli_flag_not_a_path():
    cs = kinds("Ran with --fail-under 80 and it passed.")
    assert not [c for c in cs if c.kind == "file"]


def test_plain_english_not_a_path():
    cs = kinds("Fixed the bug and all tests pass.")
    assert not [c for c in cs if c[0] == "file"]


def test_leading_dot_slash_stripped():
    cs = kinds("Edited ./src/main.py today.")
    assert ("file", "src/main.py") in cs


def test_trailing_punctuation_stripped():
    cs = kinds("Updated config.yaml, then restarted.")
    assert ("file", "config.yaml") in cs


# --- test command claims ---------------------------------------------------

def test_pytest_command():
    cs = kinds("Ran pytest tests/ -q and everything passed.")
    assert any(c[0] == "test_command" and "pytest" in c[1] for c in cs)


def test_python_m_pytest():
    cs = kinds("Executed `python -m pytest tests/ -x -q`.")
    assert any(c[0] == "test_command" and "python -m pytest" in c[1] for c in cs)


def test_npm_test():
    cs = kinds("ran npm test -- --watchAll=false")
    assert any(c[0] == "test_command" and c[1].startswith("npm test") for c in cs)


def test_go_test():
    cs = kinds("go test ./... passed")
    assert any(c[0] == "test_command" for c in cs)


# --- test count claims -----------------------------------------------------

def test_count_tests_pass():
    cs = kinds("84 tests pass.")
    assert ("test_count", "84/84") in cs


def test_count_all_tests_pass():
    cs = kinds("All 32 tests pass on 3.11.")
    assert ("test_count", "32/32") in cs


def test_count_slash_passing():
    cs = kinds("69/69 passing, no failures.")
    assert ("test_count", "69/69") in cs


def test_count_pytest_summary():
    cs = kinds("Summary: 84 passed in 1.23s")
    assert ("test_count", "84/84") in cs


def test_count_with_failures_noted():
    cs = kinds("81 passed, 3 failed in 2.01s")
    found = [c for c in extract_claims("81 passed, 3 failed in 2.01s")
             if c.kind == "test_count"]
    assert found and found[0].detail == "failed=3"


# --- fix claims ------------------------------------------------------------

def test_fix_claim():
    cs = kinds("Fixed the login redirect bug.")
    assert any(c[0] == "fix" for c in cs)


def test_fix_with_file_delegates():
    # A fix naming a file should not double-claim it as a bare fix.
    cs = extract_claims("Fixed src/auth.py.")
    files = [c for c in cs if c.kind == "file"]
    assert ("src/auth.py" in [c.value for c in files])


# --- ordering & determinism ------------------------------------------------

def test_document_order():
    text = "84 tests pass. Fixed src/b.py. Created src/a.py."
    cs = extract_claims(text)
    spans = [c.span[0] for c in cs]
    assert spans == sorted(spans)


def test_deterministic():
    text = "Created src/a.py. Ran pytest. 44 tests pass. Fixed the widget."
    first = [(c.kind, c.value) for c in extract_claims(text)]
    second = [(c.kind, c.value) for c in extract_claims(text)]
    assert first == second


def test_empty_text_no_claims():
    assert extract_claims("") == []
    assert extract_claims("   \n  ") == []


def test_claim_spans_point_at_text():
    text = "Created src/a.py yesterday."
    cs = extract_claims(text)
    assert cs and text[cs[0].span[0]:cs[0].span[1]].startswith("Created")
