"""Live failure drill: run one question through the graph and show how the failure is handled.

    OPENAI_API_KEY=sk-invalid  python -m scripts.failure_drill     # non-retryable: bad key
    OPENAI_BASE_URL=http://127.0.0.1:9 python -m scripts.failure_drill   # retryable: connection refused
"""
import logging
import sys

from graph import run_graph

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
question = " ".join(sys.argv[1:]) or "Where is Masada?"
result = run_graph(question)
print(f"\nsource={result['source']} total_ms={result['timings']['total_ms']}")
print(f"trace={result['graph']['trace']}\nerror={result.get('error')}\nanswer={result['answer']}")
