#!/usr/bin/env python3
"""Repository hygiene checks: secret scan and docs/link integrity.

Runs locally (`python scripts/repo_checks.py`) and in CI as the repo-checks
job. Exits non-zero on any finding.

Secret scan
    Pattern-based scan of text files for private keys and common API token
    formats. A line containing `repo-checks: allow` is skipped, for
    intentional test data only. This is a tripwire, not a guarantee — review
    diffs before pushing regardless.

Docs check
    Relative markdown links must resolve to files that exist, and a set of
    required repo files must be present.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    "htmlcov",
    ".idea",
    ".vscode",
}

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".cfg",
    ".ini",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".sh",
    ".ps1",
    ".bat",
}
NO_SUFFIX_FILES = {"LICENSE", ".gitignore", ".editorconfig", ".gitattributes"}

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key block"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key ID"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "API key literal (sk-...)"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "Slack token"),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b"),
        "JWT",
    ),
    (
        re.compile(r"(?i)\b(api_secret|client_secret|private_key)\b\s*[:=]\s*['\"][^'\"]{20,}['\"]"),
        "secret-looking assignment",
    ),
]

ALLOW_MARKER = "repo-checks: allow"

REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "SECURITY.md",
    ".gitignore",
    ".editorconfig",
    ".gitattributes",
    "architecture.md",
    "implementation.md",
    "sprint-roadmap.md",
    "vps-deployment.md",
    ".github/workflows/ci.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/CODEOWNERS",
    "scripts/repo_checks.py",
    "docs/adr/0001-record-architecture-decisions.md",
    "docs/risk-register.md",
    "docs/coinbase-verification-checklist.md",
    "docs/version-matrix.md",
    "docs/sprints/sprint-plan-template.md",
    "docs/sprints/sprint-01-repo-bootstrap.md",
]

MD_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def collect_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in NO_SUFFIX_FILES:
            files.append(path)
    return sorted(files)


def scan_secrets(files: list[Path], root: Path) -> list[str]:
    findings: list[str] = []
    for path in files:
        rel = path.relative_to(root)
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ALLOW_MARKER in line:
                continue
            for pattern, kind in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{rel}:{lineno}: possible {kind}")
                    break
    return findings


def check_markdown_links(files: list[Path], root: Path) -> list[str]:
    problems: list[str] = []
    for md in files:
        rel = md.relative_to(root)
        text = md.read_text(encoding="utf-8", errors="replace")
        for match in MD_LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            if not (md.parent / path_part).exists():
                problems.append(f"{rel}: broken link -> {target}")
    return problems


def check_required_files(root: Path) -> list[str]:
    missing = [name for name in REQUIRED_FILES if not (root / name).exists()]
    return [f"missing required file: {name}" for name in missing]


def main(argv: list[str]) -> int:
    root = (
        Path(argv[1]).resolve()
        if len(argv) > 1
        else Path(__file__).resolve().parent.parent
    )
    files = collect_files(root)
    findings = (
        scan_secrets(files, root)
        + check_markdown_links([p for p in files if p.suffix == ".md"], root)
        + check_required_files(root)
    )
    if findings:
        print(f"repo_checks: {len(findings)} problem(s) found:\n")
        for item in findings:
            print(f"  - {item}")
        print(f"\nFix the items above, or add '{ALLOW_MARKER}' on the line if it is intentional test data.")
        return 1
    print(f"repo_checks: OK — {len(files)} files scanned, no secrets, all links and required files present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
