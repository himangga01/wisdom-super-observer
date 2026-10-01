"""Generate installed-package stubs directly from the canonical contracts proto."""

import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    if version("grpcio-tools") != "1.84.0":
        raise SystemExit("pinned grpcio-tools==1.84.0 required")
    root = Path(__file__).resolve().parents[1]
    source = root / "packages/contracts/proto"
    target = root / "services/tvt-bridge/src"
    # A virtual protoc source prefix gives both imports and message __module__
    # their real installed package identity; no sys.path or post-generation edits.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-Iwso_tvt_bridge/generated={source}",
            f"--python_out={target}",
            f"--grpc_python_out={target}",
            "wso_tvt_bridge/generated/tvt_bridge.proto",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
