"""Evidence gathering: git diffs, working tree, and session transcripts.

All evidence is collected deterministically from local, inspectable sources:
- ``git diff`` / ``git diff --cached`` / ``git status --porcelain``
- a session transcript in receipts' canonical JSONL format, or best-effort
  parsed Claude Code / Codex JSONL sessions.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Evidence model
# ---------------------------------------------------------------------------


@dataclass
class CommandEvidence:
    """One shell command observed in a session transcript."""

    command: str
    exit_code: Optional[int]  # None = seen, but exit status unknown
    output: str = ""


@dataclass
class Evidence:
    """Everything receipts knows how to check claims against."""

    diff_files: Dict[str, str]  # path -> status letter (M/A/D/R)
    tree_files: List[str]  # paths present in the working tree (relative)
    commands: List[CommandEvidence]  # commands observed in the session
    session_path: Optional[str] = None
    repo_root: Optional[str] = None


# ---------------------------------------------------------------------------
# Git evidence
# ---------------------------------------------------------------------------


def _run_git(args: List[str], cwd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def repo_root(cwd: str) -> Optional[str]:
    code, out = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if code != 0:
        return None
    return out.strip()


def collect_diff(root: str, base: str = "HEAD") -> Dict[str, str]:
    """Map of changed paths -> status letter, from staged + unstaged + base diff."""
    changed: Dict[str, str] = {}
    # Committed-but-unpushed style: base..working tree via `git diff base`
    # (covers staged + unstaged against base).
    for args in (
        ["diff", "--name-status", base],
        ["diff", "--cached", "--name-status"],
        ["diff", "--name-status"],
    ):
        code, out = _run_git(args, root)
        if code != 0:
            continue
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0][0]
            path = parts[-1]  # renames: old\tnew -> take new
            changed[path] = status
    return changed


def collect_tree(root: str) -> List[str]:
    """All tracked + untracked files under root, relative to root."""
    files: List[str] = []
    code, out = _run_git(["ls-files", "--others", "--cached", "--exclude-standard"], root)
    if code == 0:
        files = [ln for ln in out.splitlines() if ln]
    return files


# ---------------------------------------------------------------------------
# Session transcripts
# ---------------------------------------------------------------------------

# receipts' canonical JSONL line: {"type": "command", "command": "...",
#   "exit_code": 0, "output": "..."}


def _parse_canonical(lines: List[str]) -> List[CommandEvidence]:
    cmds: List[CommandEvidence] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "command" and obj.get("command"):
            ec = obj.get("exit_code")
            cmds.append(CommandEvidence(
                command=str(obj["command"]),
                exit_code=int(ec) if isinstance(ec, int) else None,
                output=str(obj.get("output", "")),
            ))
    return cmds


_BASH_TOOL_RE = re.compile(r'"command"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _unescape(s: str) -> str:
    try:
        return json.loads('"%s"' % s)
    except Exception:
        return s


def _parse_claude_code(lines: List[str]) -> List[CommandEvidence]:
    """Best-effort: pull Bash tool_use commands from Claude Code JSONL."""
    cmds: List[CommandEvidence] = []
    pending: Dict[str, str] = {}  # tool_use id -> command
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        msg = obj.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                tool_id = block.get("id", "")
                cmd_in = (block.get("input") or {}).get("command", "")
                if cmd_in:
                    pending[tool_id] = cmd_in
            elif block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "")
                cmd = pending.pop(tool_id, None)
                if cmd is None:
                    continue
                # Claude Code tool results rarely carry a structured exit code;
                # look for explicit markers in the text.
                text = ""
                inner = block.get("content")
                if isinstance(inner, str):
                    text = inner
                elif isinstance(inner, list):
                    text = " ".join(
                        b.get("text", "") for b in inner
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                ec = _guess_exit_code(text)
                cmds.append(CommandEvidence(command=cmd, exit_code=ec, output=text))
    # Commands issued without an observed result: seen, status unknown.
    for cmd in pending.values():
        cmds.append(CommandEvidence(command=cmd, exit_code=None))
    return cmds


def _guess_exit_code(text: str) -> Optional[int]:
    """Look for explicit exit-status markers in tool output text."""
    if re.search(r"\bexit(?:ed)?(?:\s+with)?\s+code\s+0\b", text, re.IGNORECASE):
        return 0
    m = re.search(r"\bexit\s+code\s+(\d{1,3})\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # pytest summary with no failures is strong evidence of exit 0.
    if re.search(r"\b\d+\s+passed\b", text) and not re.search(
        r"\b\d+\s+failed\b|\berror\b", text, re.IGNORECASE
    ):
        return 0
    if re.search(r"\bTraceback \(most recent call last\)", text):
        return 1
    return None


def _parse_codex(lines: List[str]) -> List[CommandEvidence]:
    """Best-effort: pull exec commands from Codex session JSONL."""
    cmds: List[CommandEvidence] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Codex exec events carry payload {"command": [...], "exit_code": N}
        payload = obj.get("payload") or {}
        if obj.get("type") in ("exec_command_begin", "event_msg"):
            cmd = payload.get("command") or obj.get("command")
            if isinstance(cmd, list):
                cmd = " ".join(str(c) for c in cmd)
            if cmd:
                ec = payload.get("exit_code", obj.get("exit_code"))
                cmds.append(CommandEvidence(
                    command=str(cmd),
                    exit_code=int(ec) if isinstance(ec, int) else None,
                    output=str(payload.get("output", "")),
                ))
    return cmds


def parse_session(path: str) -> List[CommandEvidence]:
    """Parse a session file, auto-detecting the format."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    canonical = _parse_canonical(lines)
    # If canonical parsing found real commands, trust it; otherwise try
    # the agent-format adapters.
    if canonical:
        return canonical
    claude = _parse_claude_code(lines)
    if claude:
        return claude
    return _parse_codex(lines)


def discover_session() -> Optional[str]:
    """Find the most recently modified session file under known agent dirs."""
    candidates: List[Tuple[float, str]] = []
    home = os.path.expanduser("~")
    search_roots = [
        os.path.join(home, ".claude", "projects"),
        os.path.join(home, ".codex", "sessions"),
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".jsonl"):
                    full = os.path.join(dirpath, fn)
                    try:
                        candidates.append((os.path.getmtime(full), full))
                    except OSError:
                        continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def gather(repo: str, session: Optional[str] = None,
           diff_base: str = "HEAD") -> Evidence:
    """Collect all evidence for a verification run."""
    root = repo_root(repo) or os.path.abspath(repo)
    diff_files = collect_diff(root, diff_base) if repo_root(repo) else {}
    tree_files = collect_tree(root) if repo_root(repo) else []
    commands: List[CommandEvidence] = []
    if session:
        commands = parse_session(session)
    return Evidence(
        diff_files=diff_files,
        tree_files=tree_files,
        commands=commands,
        session_path=session,
        repo_root=root,
    )
