"""Generate docs/API.md from the FastAPI app's OpenAPI schema, so the endpoint reference cannot drift from the code.

    python -m scripts.make_api_docs
"""
from config import settings
from main import app

PUBLIC = {"/health", "/events/validate"}


def render() -> str:
    spec = app.openapi()
    lines = ["# API reference (generated - run `python -m scripts.make_api_docs`)", "",
             "Protected endpoints need the `X-API-Key` header when `APP_API_KEY` is set. Errors share one JSON shape: `{\"error\": {...}}`.", "",
             "| Method | Path | Auth | Summary |", "|---|---|---|---|"]
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            doc = (op.get("description") or op.get("summary") or "").strip().split("\n")[0]
            lines.append(f"| {method.upper()} | `{path}` | {'-' if path in PUBLIC else 'API key'} | {doc} |")
    lines += ["", "## Schemas", ""]
    for name, schema in sorted(spec.get("components", {}).get("schemas", {}).items()):
        if name in ("HTTPValidationError", "ValidationError"):
            continue
        props = schema.get("properties", {})
        if not props:
            continue                                             # enums: documented where they are used
        required = set(schema.get("required", []))
        lines += [f"### {name}", "", "| Field | Type | Required |", "|---|---|---|"]
        for field, p in props.items():
            kind = p.get("type") or ("enum" if "enum" in p else "/".join(x.get("type", "ref") for x in p.get("anyOf", [])) or "ref")
            lines.append(f"| `{field}` | {kind} | {'yes' if field in required else ''} |")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = settings.base_dir / "docs" / "API.md"
    out.write_text(render(), encoding="utf8")
    print(f"wrote {out}")
