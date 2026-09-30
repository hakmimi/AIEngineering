"""Generate the synthetic dataset and reference tables.

    python -m scripts.generate_data [n_rows] [seed]      (defaults: 1000 rows, seed 42)

Writes data/providers.json, data/risk_tables.json, data/transactions.csv and prints a summary for inspection.
"""
import json
import sys

from config import settings
from simulation import PROVIDERS, generate_transactions, risk_tables, summary_stats


def main(n: int = 1000, seed: int = 42) -> None:
    settings.data_dir.mkdir(exist_ok=True)
    (settings.data_dir / "providers.json").write_text(
        json.dumps([p.model_dump(mode="json") for p in PROVIDERS], indent=2), encoding="utf8")
    (settings.data_dir / "risk_tables.json").write_text(json.dumps(risk_tables(), indent=2), encoding="utf8")
    df = generate_transactions(n, seed)
    df.to_csv(settings.data_dir / "transactions.csv", index=False)
    stats = summary_stats(df)
    print(json.dumps(stats, indent=2))
    print("\nsample records:")
    print(df.head(5).to_string())


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
