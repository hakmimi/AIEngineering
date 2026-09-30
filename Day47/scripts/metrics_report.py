"""Print and store an operational metrics report from one or more audit databases.

    python -m scripts.metrics_report data/simulation/run2_audit.db [more.db ...] [--label run2]
"""
import argparse
import json

from config import settings
from metrics import check_alerts, load_audit_frame, markdown_report, summarize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dbs", nargs="*", default=[str(settings.audit_db_path)])
    parser.add_argument("--label", default="metrics")
    args = parser.parse_args()
    df = load_audit_frame(*args.dbs)
    summary = summarize(df)
    alerts = check_alerts(summary)
    text = markdown_report(summary, alerts, title=f"Operational metrics - {args.label}")
    out = settings.data_dir / "simulation"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.label}_metrics.md").write_text(text, encoding="utf8")
    (out / f"{args.label}_metrics.json").write_text(json.dumps({"summary": summary, "alerts": alerts}, indent=1, default=str), encoding="utf8")
    print(text)


if __name__ == "__main__":
    main()
