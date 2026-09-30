"""Portfolio claims must stay tied to evidence; overclaiming words may appear only in the warnings."""
import json
import re
import subprocess
import sys

from config import settings

TEXT = (settings.base_dir / "docs" / "PORTFOLIO.md").read_text(encoding="utf8")
EVAL = settings.data_dir / "eval"


def test_headline_numbers_match_the_stored_evaluation():
    final = json.loads((EVAL / "full_v4.json").read_text(encoding="utf8"))["summary"]
    assert f"{final['baseline']['pass_rate']:.1%}" in TEXT and f"{final['baseline']['errors']['unsafe_error']} unsafe" in TEXT
    assert final["ai"]["pass_rate"] == 1.0 and final["ai"]["errors"].get("unsafe_error", 0) == 0


def test_mode_claim_matches_the_stored_comparison():
    modes = json.loads((EVAL / "modes_final.json").read_text(encoding="utf8"))["modes"]
    assert f"{modes['ai']['errors']['unsafe_error']} unsafe errors" in TEXT


def test_simulation_numbers_match_the_stored_run():
    sim = json.loads((settings.data_dir / "simulation" / "week3_analysis.json").read_text(encoding="utf8"))
    assert round(sim["cost"]["avg_usd"], 6) == 0.000385 and "$0.000385" in TEXT
    assert sim["failed"] == 0 and round(sim["latency_ms"]["server_p95"] / 1000, 1) == 2.5 and "p95 2.5 s" in TEXT
    checks = sim["scenario_checks"].values()
    assert sum(c["events"] for c in checks) == 17 and "17/17" in TEXT and all(not c["failed"] for c in checks)


def test_test_count_claim_is_close_to_reality():
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=settings.base_dir, capture_output=True, text=True).stdout
    collected = int(re.search(r"(\d+) tests? collected", out).group(1))
    claimed = int(re.search(r"(\d+) automated tests", TEXT).group(1))
    assert claimed <= collected < claimed + 15, (collected, claimed)          # the claim can never exceed reality


def test_overclaiming_phrases_only_appear_in_warnings():
    for line in TEXT.splitlines():
        if re.search(r"real customers|fraud detection|100% accurate|makes the decisions", line):
            assert "Never say" in line, line


def test_the_limits_are_stated():
    assert "synthetic" in TEXT and "Docker was not built" in TEXT and "Yours to complete" in TEXT
