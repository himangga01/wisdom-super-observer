"""Write a validated deployment-owned account profile; never contact upstream."""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path

from wso_api.tvt.session_service import load_account_endpoints
from wso_core.tvt.account_projection import AccountFailure


def _regular(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    if (
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or (
            not stat.S_ISDIR(info.st_mode)
            if directory
            else not stat.S_ISREG(info.st_mode)
        )
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("Unsafe profile path")


def write_profile(
    root: Path,
    name: str,
    entries: Sequence[Mapping[str, str]],
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically install only a profile JSON under an existing trusted root."""
    root = Path(root).absolute()
    for parent in (root, *root.parents):
        _regular(parent, directory=True)
    if (
        not name
        or Path(name).name != name
        or any(c in name for c in "/\\:")
        or not name.endswith(".json")
        or name.startswith(".")
        or any(unicodedata.category(c).startswith("C") for c in name)
        or any(word in name.lower() for word in ("secret", "credential", "key", "env"))
    ):
        raise ValueError("Output must be a dedicated profile JSON filename")
    target = root / name
    if target.exists() or target.is_symlink():
        _regular(target)
        if not overwrite:
            raise ValueError("Profile exists; explicit overwrite required")
        # The overwrite flag never authorizes replacing arbitrary JSON secrets.
        load_account_endpoints(target)
    clean = []
    for item in entries:
        if any(
            type(value) is not str
            or any(unicodedata.category(c).startswith("C") for c in value)
            for value in item.values()
        ):
            raise ValueError("Invalid profile fields")
        clean.append(
            {
                k: v
                for k, v in item.items()
                if v or k not in ("customer_app_id", "customer_mark")
            }
        )
    raw = (
        json.dumps(clean, ensure_ascii=True, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    if len(raw) > 65536:
        raise ValueError("Profile exceeds maximum size")
    temporary: Path | None = None
    try:
        descriptor, filename = tempfile.mkstemp(
            prefix=".account-profile-", suffix=".tmp", dir=root
        )
        temporary = Path(filename)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        load_account_endpoints(temporary)
        if overwrite:
            if target.exists() or target.is_symlink():
                _regular(target)
                load_account_endpoints(target)
            os.replace(temporary, target)
        else:
            # link is atomic and fails if the target appeared after preflight.
            os.link(temporary, target)
        return target
    except (OSError, AccountFailure, ValueError, TypeError):
        raise ValueError("Profile could not be written safely") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="Existing deployment-owned directory"
    )
    parser.add_argument(
        "--output-name", required=True, help="Dedicated .json filename under root"
    )
    parser.add_argument(
        "--endpoint",
        nargs=6,
        action="append",
        required=True,
        metavar=(
            "REGION",
            "BRAND",
            "HTTPS_ORIGIN",
            "LANGUAGE",
            "COUNTRY",
            "APP_VERSION",
        ),
    )
    parser.add_argument("--customer-app-id", default="")
    parser.add_argument("--customer-mark", default="")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    keys = ("region", "brand", "origin", "language", "country", "app_version")
    entries = [
        dict(
            zip(keys, row, strict=True),
            customer_app_id=args.customer_app_id,
            customer_mark=args.customer_mark,
        )
        for row in args.endpoint
    ]
    try:
        write_profile(args.root, args.output_name, entries, overwrite=args.overwrite)
    except (ValueError, AccountFailure, OSError):
        parser.exit(
            2, "Profile rejected; check trusted arguments and output location.\n"
        )
    print("Validated account profile written. Upstream acceptance is unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
