"""Repository hygiene: config documentation stays in sync, secrets stay out, CI config stays valid."""
import re
from pathlib import Path

import yaml

from scripts import check_secrets

ROOT = Path(__file__).resolve().parent.parent
SOURCE_FILES = [p for p in ROOT.rglob("*.py") if not any(part in {"tests", "scripts", "__pycache__", "venv", ".venv"} for part in p.parts)]


def _env_vars_used_in_code() -> set[str]:
    names = set()
    for path in SOURCE_FILES:
        names |= set(re.findall(r'getenv\("([A-Z][A-Z0-9_]+)"', path.read_text(encoding="utf8")))
    return names


def _env_vars_in_example() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE))


def test_env_example_lists_every_variable_the_code_reads():
    used, documented = _env_vars_used_in_code(), _env_vars_in_example()
    assert used, "found no getenv calls - the scan is broken"
    assert not used - documented, f"missing from .env.example: {sorted(used - documented)}"


def test_env_example_has_no_unknown_variables():
    assert not _env_vars_in_example() - _env_vars_used_in_code(), "stale entries in .env.example"


def test_env_example_contains_no_real_secret():
    assert not check_secrets.scan_text((ROOT / ".env.example").read_text(encoding="utf8"))


def test_project_contains_no_committed_secrets():
    assert check_secrets.scan_project(ROOT) == {}


FAKE_KEY = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz0123456789"      # assembled at runtime so this file is not itself flagged


def test_scanner_detects_planted_secrets():
    assert check_secrets.scan_text(f'client = OpenAI(api_key="{FAKE_KEY}")')
    assert check_secrets.scan_text("OPENAI_API_KEY" + "=abcdefghijklmnop1234")
    assert not check_secrets.scan_text("OPENAI_API_KEY=sk-your-key-here")
    assert not check_secrets.scan_text("OPENAI_API_KEY=")


def test_scanner_skips_the_local_env_file_but_not_others(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=" + FAKE_KEY, encoding="utf8")
    (tmp_path / "settings.py").write_text(f'KEY = "{FAKE_KEY}"', encoding="utf8")
    assert list(check_secrets.scan_project(tmp_path)) == ["settings.py"]


def test_dockerignore_keeps_env_files_out_of_images():
    assert ".env" in (ROOT / ".dockerignore").read_text(encoding="utf8").splitlines()


def test_ci_workflow_is_valid_and_runs_lint_secrets_and_tests():
    workflow = ROOT.parent / ".github" / "workflows" / "ci.yml"
    if not workflow.exists():
        return                                          # the project may be checked out on its own
    config = yaml.safe_load(workflow.read_text(encoding="utf8"))
    steps = " ".join(str(s.get("run", "")) for job in config["jobs"].values() for s in job["steps"])
    assert "ruff check" in steps and "check_secrets" in steps and "pytest" in steps and "--cov-fail-under" in steps
    assert "secrets." not in workflow.read_text(encoding="utf8")           # CI must not need (or store) any secret
