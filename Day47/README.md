# Day 47 - Config file + mode selector

## Goal
Make behaviour configurable instead of hard-coded: one config file for tunables, environment overrides for deployment, and a
single `/decide` entry point that can run the agent as **baseline** (rules), **ai** (rules + LLM) or **graph** (full workflow).
Every run must be traceable to the exact configuration that produced it.

## What changed
| Area | Change |
|---|---|
| `config.py` | `load_settings(env, config_file)` layers **defaults < `config.yaml` < environment**. Values are cast/validated at start-up (bad value = refuse to start). Secrets are read from the environment only (a secret in YAML is ignored with a warning that never prints it). Unknown YAML keys warn. `snapshot()` gives a secret-free view. Data file paths derive from `DATA_DIR` + file names. |
| `config.yaml` | Documented non-secret defaults (a test asserts it equals the code defaults, so they cannot drift). |
| `modes.py` | `decide_with_mode(tx, mode)`; `resolve_mode` gives 422 for unknown and 403 for disabled modes; every run logs a `run_config` event and returns `mode`, `config`, `safety_layers`. |
| `main.py` | `POST /decide?mode=`, `GET /config` (protected, never shows secrets), `active_config` log at start-up. |
| `llm.py` | `temperature` comes from settings (sync + async). |
| `data_loader.py`, `policy.py`, `dashboard.py` | Paths come from settings (`DASHBOARD_DB` for the dashboard). |
| Tests | `tests/test_config_modes.py` (35 tests). Suite: 454. |
| `scripts/compare_modes.py` | Same 45 eval cases through all three modes. |

## How it was implemented
- `Settings` stays a frozen dataclass; the loader merges three dicts and casts each field by its declared type (`bool` accepts true/false/1/0/yes/no).
- **Modes share code, not copies**: `baseline` = Day 31 engine + template explanation, `ai` = Day 32/33 pipeline, `graph` = the LangGraph workflow.
- `allowed_modes` defaults to `graph`. The other two lack the policy gate, fallback routes, guard and audit trail, so production refuses them (403).
  They exist for experiments, and are enabled explicitly (`ALLOWED_MODES=baseline,ai,graph`).
- The default mode must be among the allowed modes, otherwise start-up fails.

## Results (live LLM, 45 cases, fast path off)
| Mode | Pass | Unsafe errors | Over-cautious | Explanation score | p50 latency | Cost |
|---|---|---|---|---|---|---|
| baseline | 75.6% | 10 | 0 | 10.0 | 0.2 ms | $0 |
| ai | 73.3% | 9 | 1 | 9.67 | 1.8 s | $0.028 |
| graph | **100%** | **0** | 0 | 9.49 | 1.8 s | $0.023 |

- The safety layers, not the LLM, make the difference: `ai` fixes almost none of the baseline failures (sanctioned country, over-limit amounts and
  unknown country are handled by the policy gate / fallback route only in `graph`). A sanctioned-country payment is **not declined** without the policy gate.
- `ai` lost one case (`n11_only_option_bank_br`, over-cautious) versus a previous run - LLM variance at temperature 0 is small but not zero.

## Caveats
- 45 hand-made cases; the 100% is on a set the rules were tuned against.
- `baseline`/`ai` are deliberately unsafe modes; do not enable them in production.
- The mode table is a single run; a second run can differ by a case in the LLM-dependent modes.
