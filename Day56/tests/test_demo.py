"""The final demo is a test too: if the story stops being true, the demo fails."""
import subprocess
import sys

from config import settings


def test_offline_demo_passes_end_to_end():
    result = subprocess.run([sys.executable, "-m", "scripts.demo", "--offline"], cwd=settings.base_dir, capture_output=True, text=True,
                            env={"PATH": __import__("os").environ["PATH"], "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""), "OPENAI_API_KEY": ""})
    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-1500:]
    assert "DEMO PASSED" in result.stdout and "[FAIL]" not in result.stdout
