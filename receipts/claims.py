"""Deterministic, regex-based claim extraction from an agent's summary text.

Every extraction is pure and reproducible: the same input text always yields
the same claims in the same order. No LLM, no heuristics beyond the patterns
documented here.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Claim model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Claim:
    """One verifiable statement pulled from the agent's summary."""

    kind: str  # "file", "test_command", "test_count", "fix"
    text: str  # the matched fragment, for display
    value: str  # the normalized payload (path, command, "passed/total", subject)
    detail: Optional[str] = None  # extra context, e.g. "created" vs "modified"
    span: tuple = field(default=(0, 0), compare=False)  # char offsets in source


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# A plausible file path: something/something.ext or ./x.py or `quoted.py`.
# Requires a directory separator OR a known source extension to avoid matching
# bare English words.
_EXTENSIONS = (
    "py|pyi|js|jsx|ts|tsx|mjs|cjs|go|rs|java|rb|php|swift|kt|scala|c|h|cpp|hpp|"
    "cs|sh|bash|zsh|sql|md|rst|txt|json|yaml|yml|toml|ini|cfg|xml|html|css|"
    "scss|vue|svelte|lua|pl|pm|r|jl|dart|ex|exs|erl|hs|tf|dockerfile|makefile"
)
_PATH_RE = re.compile(
    r"""
    (?P<path>
        (?:[~.]?(?:/|\\)[A-Za-z0-9_.\-~]+(?:/[A-Za-z0-9_.\-~]+)+)   # a/b/c...
      | (?:[A-Za-z0-9_\-~]+(?:/[A-Za-z0-9_\-~]+)*\.(?:%s))            # name.ext
      | (?:[A-Za-z0-9_\-~]+(?:/[A-Za-z0-9_\-~]+)+)                    # a/b (no ext)
    )
    """ % _EXTENSIONS,
    re.VERBOSE,
)

# Verbs that introduce a file claim: "created src/x.py", "modified `a.py`".
_FILE_VERB_RE = re.compile(
    r"\b(?P<verb>created?|added?|modified?|updated?|edited?|deleted?|removed?|"
    r"wrote|rewrote|touched|fixed|patched)\b\s+"
    r"(?:the\s+|a\s+|an\s+)?"
    r"(?:file\s+)?"
    r"`?(?P<path>[^\s`'\"]+)`?",
    re.IGNORECASE,
)

# Backticked paths anywhere: "`src/app.py`".
_BACKTICK_PATH_RE = re.compile(r"`(?P<path>[^`\s][^`]*?)`")

# Test commands the agent claims to have run.
# The tempered token `(?:(?!\.\s)[^\n`|;&])*?` consumes the command but stops
# at sentence boundaries, pipes, semicolons and backticks — it never swallows
# the rest of the summary line.
_CMD_TAIL = r"(?:(?!\.\s)[^\n`|;&])*?"
_TEST_COMMAND_RES = [
    re.compile(r"\b(?P<cmd>python(?:3)?\s+-m\s+pytest\b%s)" % _CMD_TAIL, re.IGNORECASE),
    re.compile(r"\b(?P<cmd>pytest\b%s)" % _CMD_TAIL, re.IGNORECASE),
    re.compile(r"\b(?P<cmd>npm\s+test\b%s)" % _CMD_TAIL, re.IGNORECASE),
    re.compile(r"\b(?P<cmd>go\s+test\b%s)" % _CMD_TAIL, re.IGNORECASE),
    re.compile(r"\b(?P<cmd>cargo\s+test\b%s)" % _CMD_TAIL, re.IGNORECASE),
]
# "ran pytest", "executed npm test" phrasing.
_TEST_VERB_RE = re.compile(
    r"\b(?:ran|run|executed?|invoked?)\b\s+"
    r"`?(?P<cmd>(?:python(?:3)?\s+-m\s+)?pytest|npm\s+test|go\s+test|cargo\s+test)\b"
    r"(%s)" % _CMD_TAIL,
    re.IGNORECASE,
)

# Test-count claims: "84 tests pass", "69/69 passing", "all 32 tests pass".
_COUNT_RES = [
    # "84 tests pass" / "84 tests passed" / "all 84 tests pass"
    re.compile(
        r"\b(?:all\s+)?(?P<passed>\d+)\s+tests?\s+(?:pass(?:ed|ing)?|green)\b",
        re.IGNORECASE,
    ),
    # "69/69 passing" / "44/44 passed"
    re.compile(
        r"\b(?P<passed>\d+)\s*/\s*(?P<total>\d+)\s+(?:pass(?:ed|ing)?|tests?\b)",
        re.IGNORECASE,
    ),
    # "passing: 44/44"
    re.compile(
        r"\bpassing[:\s]+(?P<passed>\d+)\s*/\s*(?P<total>\d+)",
        re.IGNORECASE,
    ),
    # pytest summary pasted verbatim: "84 passed in 1.23s"
    re.compile(
        r"\b(?P<passed>\d+)\s+passed\b(?:\s*,\s*(?P<failed>\d+)\s+failed)?",
        re.IGNORECASE,
    ),
]

# "fixed X" / "resolved X" claims.
_FIX_RE = re.compile(
    r"\b(?P<verb>fixed|resolved|repaired)\b\s+(?:the\s+|a\s+|an\s+)?(?P<subject>[^.\n]{1,80})",
    re.IGNORECASE,
)


def _clean_path(raw: str) -> str:
    """Strip quotes, trailing punctuation, and leading ./ from a path candidate."""
    p = raw.strip().strip("`'\"")
    p = p.rstrip(".,;:!?")
    if p.startswith("./"):
        p = p[2:]
    return p


def _looks_like_path(candidate: str) -> bool:
    """Reject obvious non-paths (URLs, plain words, flags)."""
    c = candidate.strip()
    if not c or " " in c or "\n" in c:
        return False
    if c.startswith(("http://", "https://", "www.")):
        return False
    if c.startswith("-"):  # CLI flag
        return False
    if "/" in c or "\\" in c:
        return True
    # Bare filename must have a known extension.
    m = re.search(r"\.([A-Za-z0-9]+)$", c)
    return bool(m and m.group(1).lower() in _EXTENSIONS.split("|"))


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def extract_claims(text: str) -> List[Claim]:
    """Extract every verifiable claim from the summary, in document order."""
    found: List[Claim] = []
    seen = set()  # (kind, value) dedupe

    def add(kind: str, match_text: str, value: str, detail=None, span=(0, 0)):
        key = (kind, value.lower())
        if key in seen:
            return
        seen.add(key)
        found.append(Claim(kind=kind, text=match_text.strip(), value=value,
                           detail=detail, span=span))

    # 1. File claims via action verbs.
    for m in _FILE_VERB_RE.finditer(text):
        raw = _clean_path(m.group("path"))
        if _looks_like_path(raw):
            add("file", m.group(0), raw,
                detail=m.group("verb").lower(), span=m.span())

    # 2. Backticked paths (not already claimed).
    for m in _BACKTICK_PATH_RE.finditer(text):
        raw = _clean_path(m.group("path"))
        if _looks_like_path(raw):
            add("file", m.group(0), raw, detail="mentioned", span=m.span())

    # 3. Bare paths (not backticked, not already claimed).
    for m in _PATH_RE.finditer(text):
        # Skip the host/path tail of a URL ("https://example.com/docs"):
        # the match's leading "/" is URL anatomy when preceded by "/" or ":".
        if (m.group("path").startswith("/")
                and m.start() > 0 and text[m.start() - 1] in ("/", ":")):
            continue
        raw = _clean_path(m.group("path"))
        if _looks_like_path(raw):
            add("file", m.group(0), raw, detail="mentioned", span=m.span())

    # 4. Test commands.
    for rx in _TEST_COMMAND_RES:
        for m in rx.finditer(text):
            cmd = re.sub(r"\s+", " ", m.group("cmd")).strip().rstrip(".-")
            if cmd:
                add("test_command", m.group(0), cmd, span=m.span())
    for m in _TEST_VERB_RE.finditer(text):
        cmd = re.sub(r"\s+", " ", (m.group("cmd") + m.group(2))).strip().rstrip(".-")
        if cmd:
            add("test_command", m.group(0), cmd, span=m.span())

    # Drop command claims subsumed by a longer one ("pytest" inside
    # "python -m pytest tests/ -q" is the same claim, not two).
    cmds = [c for c in found if c.kind == "test_command"]
    keep_ids = set()
    for c in sorted(cmds, key=lambda c: len(c.value), reverse=True):
        if not any(c.value in k.value for k in
                   [x for x in cmds if id(x) in keep_ids]):
            keep_ids.add(id(c))
    found = [c for c in found
             if c.kind != "test_command" or id(c) in keep_ids]

    # 5. Test counts.
    for rx in _COUNT_RES:
        for m in rx.finditer(text):
            passed = m.group("passed")
            total = m.groupdict().get("total") or passed
            failed = m.groupdict().get("failed")
            value = "%s/%s" % (passed, total)
            detail = "failed=%s" % failed if failed else None
            add("test_count", m.group(0), value, detail=detail, span=m.span())

    # 6. Fix claims.
    for m in _FIX_RE.finditer(text):
        subject = m.group("subject").strip().rstrip(".,;:")
        # Skip if the subject is really a file path (already claimed as file).
        if subject and not _looks_like_path(subject.split()[0]):
            add("fix", m.group(0), subject,
                detail=m.group("verb").lower(), span=m.span())

    # Document order.
    found.sort(key=lambda c: c.span[0])
    return found
