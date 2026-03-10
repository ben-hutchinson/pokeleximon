from __future__ import annotations

import json
from pathlib import Path

from app.main import app


def main() -> None:
    out_dir = Path(__file__).resolve().parents[1] / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)

    schema = app.openapi()
    out_path = out_dir / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
