"""Fail (exit 1) if a real-looking secret is committed anywhere in the project.

    python -m scripts.check_secrets            # used by CI

Flags OpenAI-style keys (sk-...) and `OPENAI_API_KEY=<long value>` assignments in any text file except the
git-ignored .env itself. `.env.example` may only contain obvious placeholders.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "venv", ".venv", "data"}
SKIP_FILES = {".env"}                                    # local secrets file: git-ignored on purpose
KEY_PATTERN = re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")
ASSIGNMENT = re.compile(r"OPENAI_API_KEY\s*=\s*['\"]?([^\s'\"#]{12,})")
PLACEHOLDERS = ("your-key-here", "xxxxxxxx", "<", "changeme")


def scan_text(text: str) -> list[str]:
    findings = []
    for match in KEY_PATTERN.finditer(text):
        if not any(p in match.group(0).lower() for p in PLACEHOLDERS):
            findings.append(f"key-like token {match.group(0)[:8]}...")
    for match in ASSIGNMENT.finditer(text):
        if not any(p in match.group(1).lower() for p in PLACEHOLDERS):
            findings.append("OPENAI_API_KEY assigned a literal value")
    return findings


def scan_project(root: Path = ROOT) -> dict[str, list[str]]:
    problems: dict[str, list[str]] = {}
    for path in root.rglob("*"):
        if path.is_dir() or path.name in SKIP_FILES or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue                                       # binary file (FAISS index, sqlite)
        if found := scan_text(text):
            problems[str(path.relative_to(root))] = found
    return problems


def main() -> int:
    problems = scan_project()
    for file, findings in problems.items():
        print(f"SECRET? {file}: {'; '.join(findings)}")
    print("no secrets found" if not problems else f"{len(problems)} file(s) contain secret-like values")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
