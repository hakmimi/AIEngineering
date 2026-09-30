"""Deployment files are code too: they are checked for the mistakes that only show up on the first deploy (Docker itself is not needed)."""
import re
from dataclasses import fields

import pytest

from config import Settings, settings

ROOT = settings.base_dir
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf8").splitlines()
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf8")


def test_env_example_lists_only_real_settings():
    names = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE, flags=re.M))
    known = {f.name.upper() for f in fields(Settings)} | {"LOG_FORMAT"}
    assert names and names <= known, f"unknown variables in .env.example: {names - known}"


def test_env_example_contains_no_secret_values():
    assert not re.search(r"sk-[A-Za-z0-9]{10,}", ENV_EXAMPLE)
    for line in ENV_EXAMPLE.splitlines():
        if line.startswith(("OPENAI_API_KEY=", "APP_API_KEY=")):
            assert line.split("=", 1)[1] == "", line


def test_env_file_is_kept_out_of_git_and_out_of_the_image():
    assert ".env" in DOCKERIGNORE and "!.env.example" in DOCKERIGNORE
    gitignore_path = next((d / ".gitignore" for d in (ROOT, ROOT.parent) if (d / ".gitignore").exists()), None)
    if gitignore_path is None:
        pytest.skip("no .gitignore next to the project (copied out of its repository)")
    gitignore = gitignore_path.read_text(encoding="utf8")
    assert re.search(r"^\.env$", gitignore, flags=re.M)


def test_dockerfile_installs_dependencies_before_copying_code_and_runs_unprivileged():
    assert DOCKERFILE.index("COPY requirements.txt") < DOCKERFILE.index("pip install") < DOCKERFILE.index("COPY . .")
    assert "USER agent" in DOCKERFILE and DOCKERFILE.index("USER agent") > DOCKERFILE.index("COPY . .")
    assert "requirements-dev" not in DOCKERFILE


def test_dockerfile_has_no_secrets_and_a_healthcheck_on_readiness():
    assert "OPENAI_API_KEY" not in DOCKERFILE and "sk-" not in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE and "/ready" in DOCKERFILE


def test_single_worker_because_the_queue_is_in_process():
    cmd = DOCKERFILE.splitlines()[-1]
    assert "uvicorn" in cmd and "--workers" not in cmd


def test_container_databases_live_on_the_volume():
    assert "AUDIT_DB_PATH=/var/lib/agent/" in DOCKERFILE and "VOLUME" in DOCKERFILE
    assert "/var/lib/agent" in COMPOSE and "env_file: .env" in COMPOSE
    assert "OPENAI_API_KEY" not in COMPOSE


def test_files_the_app_needs_at_runtime_are_not_excluded_from_the_image():
    needed = [settings.providers_path, settings.risk_tables_path, settings.policies_path, settings.transactions_path, ROOT / "config.yaml",
              ROOT / "main.py"]
    for path in needed:
        rel = path.relative_to(ROOT).as_posix()
        assert path.exists() and rel not in DOCKERIGNORE and not any(rel.startswith(x.rstrip("/")) for x in DOCKERIGNORE if x.endswith("/")), rel


def test_every_imported_local_module_is_shipped():
    """The image copies everything except .dockerignore entries: a runtime import of an excluded directory would crash the container."""
    excluded = {x.rstrip("/") for x in DOCKERIGNORE if x.endswith("/")}
    runtime_modules = [p for p in ROOT.glob("*.py") if p.name != "dashboard.py"]
    for module in runtime_modules:
        for imported in re.findall(r"^(?:from|import)\s+(\w+)", module.read_text(encoding="utf8"), flags=re.M):
            assert imported not in excluded, f"{module.name} imports {imported}, which the image excludes"


def test_readiness_endpoint_reports_state(api, settings_override):
    ok = api.get("/ready")
    assert ok.status_code == 200 and ok.json()["status"] == "ready" and ok.json()["checks"]["data"] == "ok"
    settings_override(openai_api_key=None)
    body = api.get("/ready").json()
    assert body["status"] == "ready" and body["checks"]["llm"].startswith("not configured")          # no key is degraded, not down


def test_readiness_fails_when_data_or_audit_are_unusable(api, monkeypatch):
    import main
    monkeypatch.setattr(main, "load_providers", lambda: (_ for _ in ()).throw(FileNotFoundError("x")))
    r = api.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["data"] == "error: FileNotFoundError" and r.json()["status"] == "not_ready"
    monkeypatch.undo()

    class Broken:
        def count(self):
            raise RuntimeError("disk full")
    monkeypatch.setattr(main, "audit_store", Broken())
    assert api.get("/ready").status_code == 503
