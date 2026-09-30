# Final project checklist (Day 56)

Legend: [x] verified by a command run on Day 56, [~] verified only in part, [ ] not verified.

## Works
- [x] Full test suite passes (see Day 56 README for the count) and ruff is clean
- [x] `python -m scripts.demo` passes with the live model; `--offline` passes without a key
- [x] `python -m scripts.e2e_smoke`: 11/11 scenarios through the real API and real model
- [x] Fresh checkout: new venv, `pip install -r requirements-dev.txt`, tests, real server without an API key (`python -m scripts.fresh_run`)
- [x] Evaluation re-run on final code (`full_v4`): 100% / 0 unsafe errors; no regression against v3
- [x] Generated docs (`API.md`, `graph.md`, `FINAL_EVALUATION.md`) are current - enforced by tests

## Understandable
- [x] `README.md` explains what it is, how to run it, results and limits
- [x] `docs/` index, system diagrams, API reference, examples, evaluation, interview notes, portfolio story
- [x] Every day folder has Goal / What changed / How implemented

## Safe
- [x] No secrets in git-tracked files (`.env` ignored; `.env.example` has empty secrets; a test checks it)
- [x] TLS verification never disabled (system trust store via `truststore`)
- [x] The LLM can only escalate; invariants tested under a hostile stub over 150 generated events
- [ ] Nothing has been pushed or committed by the assistant - the repository state is yours to review

## Not verified (be explicit when presenting)
- [ ] Docker image build and container run (no Docker on the development machine)
- [~] CI: the workflow steps were run locally; the workflow itself has not run on GitHub
- [ ] Behaviour on real traffic or real labels
- [ ] Multi-instance operation

## Presenting it
- [ ] Practise the 2-minute explanation (`docs/PORTFOLIO.md`) and the 9-step demo (`scripts/demo.py`) aloud
- [ ] Add your own background sentence to the portfolio story
