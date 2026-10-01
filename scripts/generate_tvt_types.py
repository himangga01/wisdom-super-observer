"""Generate public TVT TypeScript from actual FastAPI OpenAPI, entirely offline."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from wso_api.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "packages/contracts/generated"
    )
    args = parser.parse_args()
    package = ROOT / "apps/web/node_modules/openapi-typescript"
    if (
        json.loads((package / "package.json").read_text(encoding="utf-8"))["version"]
        != "7.13.0"
    ):
        raise SystemExit("Installed openapi-typescript 7.13.0 required")
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Installed Node.js required")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    openapi = args.out_dir / "openapi.json"
    openapi.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    # stdin avoids the CLI resolver's percent-encoded Windows Unicode path bug.
    result = subprocess.run(
        [node, str(package / "bin/cli.js")],
        input=openapi.read_text(encoding="utf-8"),
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    (args.out_dir / "tvt.ts").write_text(result.stdout, encoding="utf-8")
    print("Generated tvt.ts with installed openapi-typescript 7.13.0")


if __name__ == "__main__":
    main()
