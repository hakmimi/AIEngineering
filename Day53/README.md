# Day 53 - Docker / deployment config, `.env.example`, fresh-run test

## Goal
Anyone can run the service from a clean checkout with one command, secrets never enter the image or git, and we *prove* the dependency list and shipped data are complete.

## What changed
| File | Change |
|---|---|
| `Dockerfile` | `python:3.13-slim`; dependencies installed before code (layer cache); runs as unprivileged user `agent`; databases on a `/var/lib/agent` volume; `HEALTHCHECK` on `/ready`; **one** uvicorn worker (the job queue is in-process). |
| `docker-compose.yml` | One service, `env_file: .env`, named volume for the audit and job databases, `restart: unless-stopped`. |
| `.dockerignore` | Keeps `.env`, tests, docs, scripts, local databases, caches, dev requirements out of the image. |
| `.env.example` | Every variable, secrets empty, behaviour variables commented out with defaults. |
| `main.py` | `GET /ready` (readiness): 503 if reference data or the audit store is unusable; a missing OpenAI key is reported as "rules-only operation" but is *not* a failure. `/health` stays pure liveness. |
| `scripts/fresh_run.py` | Fresh-checkout test: copy project (no `.env`, no databases) to a temp folder, NEW venv, `pip install -r requirements-dev.txt`, full test suite, start the real server **without an OpenAI key**, real HTTP calls. |
| `tests/test_deployment.py` (11 tests) | `.env.example` lists only real settings and no secret values; Dockerfile order/user/healthcheck/worker count; `.env` excluded from image and git; runtime files and imported modules not excluded by `.dockerignore`; `/ready` behaviour. |
| `tests/conftest.py` | `stub_llm` now also stubs the async LLM function (see findings). |
Suite: 490 tests.

## Fresh-run result
```
pip install: 61 s
tests: 487 passed, 3 skipped          (streamlit not installed: 2 dashboard tests skip; 1 skips: no .gitignore beside the copy)
ready: ready {'data': 'ok', 'audit_store': 'ok', 'llm': 'not configured (rules-only operation)'}
decision: decline ['POLICY_BLOCK'] | audit integrity: True
FRESH RUN PASSED
```

## What the fresh run found (the point of doing it)
1. `docs/API.md` was stale after adding `/ready` - the Day 50 doc test caught it in the copy (and in the repo). Regenerated.
2. `test_async_endpoint_has_the_same_shape` (Day 52) **made a live OpenAI call** on my machine because the stub covered only the sync LLM function; with no key it failed. Fixed: the stub covers both. (Cost: a few requests at ~$0.0004.)
3. A test read `../.gitignore`, which does not exist outside the repository - it now skips in that case.
4. First attempt excluded `data/eval` and `data/simulation` from the copy and 29 tests failed: several tests use stored evidence files. They are part of the repo, so the copy must include them.

## How to run
```
cp .env.example .env        # add OPENAI_API_KEY
docker compose up --build   # http://localhost:8000/docs, /ready
```

## NOT verified - be honest
- **Docker is not installed on this machine: the image was never built and the container never run.** The Dockerfile follows standard practice and the tests above check its content, but a build could still fail (for example on a platform-specific wheel).
- The healthcheck command was not executed inside a container.
- `docker compose` volume permissions (the `agent` user writing to the named volume) are the usual first-deploy problem; the Dockerfile creates and chowns the directory, but this is untested.
- The fresh run used Windows and Python 3.13; a Linux container is a different environment.
