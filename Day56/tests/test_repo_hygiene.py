"""Repository hygiene: no secrets committed, scanner works, CI config valid and pointing at this project."""
from pathlib import Path

import yaml

from scripts import check_secrets

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz0123456789"      # assembled at runtime so this file is not itself flagged


def test_project_contains_no_committed_secrets():
    assert check_secrets.scan_project(ROOT) == {}


def test_scanner_detects_planted_secrets():
    assert check_secrets.scan_text(f'client = OpenAI(api_key="{FAKE_KEY}")')
    assert check_secrets.scan_text("OPENAI_API_KEY" + "=abcdefghijklmnop1234")
    assert not check_secrets.scan_text("OPENAI_API_KEY=sk-your-key-here")
    assert not check_secrets.scan_text("OPENAI_API_KEY=")


def test_scanner_skips_the_local_env_file_but_not_others(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=" + FAKE_KEY, encoding="utf8")
    (tmp_path / "settings.py").write_text(f'KEY = "{FAKE_KEY}"', encoding="utf8")
    assert list(check_secrets.scan_project(tmp_path)) == ["settings.py"]


def test_ci_workflow_is_valid_and_targets_this_project():
    workflow = ROOT.parent / ".github" / "workflows" / "ci.yml"
    if not workflow.exists():
        return                                                     # project copied out of its repository
    cfg = yaml.safe_load(workflow.read_text(encoding="utf8"))
    assert cfg["env"]["PROJECT"] == ROOT.name
    steps = " ".join(str(s.get("run", "")) for s in cfg["jobs"]["test"]["steps"])
    assert "ruff check" in steps and "check_secrets" in steps and "pytest" in steps
    assert "OPENAI_API_KEY" not in str(cfg["jobs"]) and "secrets." not in workflow.read_text(encoding="utf8")      # the suite must pass without a key
