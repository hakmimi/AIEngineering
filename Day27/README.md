# Day 27 – CI (GitHub Actions)

[![CI](https://github.com/hakmimi/AIEngineering/actions/workflows/ci.yml/badge.svg)](https://github.com/hakmimi/AIEngineering/actions/workflows/ci.yml)
<sub>(the badge turns green only after this workflow has run on GitHub – see "Verification")</sub>

## Goal

Every push runs the same checks automatically – lint, secret scan, the full offline test suite and a coverage gate – so a broken change is visible immediately. Also: configuration and secrets handled safely (`.env.example`, nothing hard-coded).

```text
Code push → GitHub Actions → install dependencies → ruff → secret scan → pytest + coverage gate → pass/fail signal
```

## What changed (vs Day 26)

| File | Change |
|---|---|
| `../.github/workflows/ci.yml` (new, at the **repo root**, where GitHub reads it) | one job: checkout → Python 3.13 (+ pip cache) → `pip install -r requirements-dev.txt` → `ruff check .` → `python -m scripts.check_secrets` → `pytest --cov --cov-fail-under=95`; runs in `Day27/`, triggered by pushes to `main` / `development/**` and PRs touching `Day27/**` |
| `pyproject.toml` (new) | ruff config: pyflakes-class errors, import order, bugbear |
| `.env.example` (new) | every environment variable the app reads, with safe defaults and comments |
| `scripts/check_secrets.py` (new) | fails on `sk-…` keys or a literal `OPENAI_API_KEY=` anywhere except the git-ignored `.env` |
| `tests/test_repo_hygiene.py` (new, 8 tests) | `.env.example` must list **exactly** the variables the code reads (no missing, no stale); no real secrets anywhere; scanner catches planted secrets; `.dockerignore` excludes `.env`; the CI file is valid YAML, runs lint/secrets/tests/coverage and references no repository secrets |
| `requirements-dev.txt` | + `pytest-cov`, `pyyaml` |
| `../.gitignore` (root) | added `!.env.example` – the existing `.env.*` rule would have silently ignored the example file |
| code | 35 lint findings fixed: import order, `zip(..., strict=True)` where lengths must match, ambiguous `l` variables, mid-file imports |

## How it was implemented

1. **What should CI verify?** Style/correctness (ruff), no secrets in the repo, behaviour (392+ offline tests), and that coverage does not silently erode (gate at 95 %; actual 99 %). It deliberately has **no API key**: the whole suite is offline, so a fork or a contributor's PR can be validated without secrets, and a leaked CI log cannot leak a key.
2. **Config management / why not hard-code secrets?** Secrets come from the environment (`.env` locally, `--env-file`/secret store in deployment); `.env.example` documents the contract, and a test keeps it in sync with the code, so a new setting without documentation fails CI.
3. **Lint choice** – narrow on purpose (correctness + import order + likely bugs). `ruff format --check` was left out: reformatting the whole code base would drown the real changes (the plan marks formatting optional).
4. **Where the workflow lives** – GitHub only reads `.github/workflows/` at the repository root, while each day is a folder, so the workflow points at one project folder through `env.PROJECT`.

## Verification – what was and was NOT done

I did **not** push, so the workflow has not run on GitHub yet. Instead the exact CI steps were executed locally in conditions matching the runner: a brand-new virtualenv, only `requirements-dev.txt` installed, a copy of the folder **without `.env`**, `OPENAI_API_KEY` unset:

| Step | Result |
|---|---|
| `ruff check .` | All checks passed |
| `python -m scripts.check_secrets` | no secrets found |
| `pytest --cov=. --cov-fail-under=95` | **400 passed**, coverage **99.21 %** ("Required test coverage of 95% reached") |

The first simulated run would have failed on GitHub for a missing `pyyaml` in the dev requirements – found and fixed only because of this simulation. Possible remaining differences on GitHub: Linux vs Windows path/line-ending behaviour and action versions (`actions/checkout@v4`, `actions/setup-python@v5`).

## Run

```bash
cd Day27
pip install -r requirements-dev.txt
ruff check .
python -m scripts.check_secrets
python -m pytest --cov=. --cov-fail-under=95
cp .env.example .env     # then edit OPENAI_API_KEY
```
