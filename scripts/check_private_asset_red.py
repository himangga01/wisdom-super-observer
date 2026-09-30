"""Verify a genuine missing-feature baseline failure, never asset acceptance."""

import argparse
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

BASELINE_SHA = "6565929776c2ff5b9ff55670bc4567b6d2cf4821"
CASE_NAME = "test_photo_upload_does_not_require_a_store"
CLASSNAME = "tests.integration.test_private_assets"
EXPECTED_FAILURE = "authenticated POST /api/v1/assets returned 404; expected 201"


def _bounded_read(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("baseline RED input exceeds its size bound")
        return data
    except OSError:
        raise ValueError("baseline RED input is unavailable") from None


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("baseline RED receipt has duplicate keys")
        result[key] = value
    return result


def _verify_receipt(path: Path) -> None:
    try:
        observed = json.loads(
            _bounded_read(path, 16 * 1024), object_pairs_hook=_unique_keys
        )
        if not isinstance(observed, dict) or not isinstance(
            observed.get("provider"), dict
        ):
            raise TypeError("baseline RED receipt shape is invalid")
        digest = observed["provider"].get("digest")
        if not isinstance(digest, str) or not re.fullmatch(
            r"(?:docker.io/)?chrislusf/seaweedfs@sha256:[0-9a-f]{64}", digest
        ):
            raise ValueError("baseline RED provider digest is invalid")
        expected = {
            "schema_version": 1,
            "baseline_sha": BASELINE_SHA,
            "stage": "ASSET_REQUEST_OBSERVED",
            "provider": {
                "provider": "SeaweedFS",
                "version": "4.47",
                "security_profile": "seaweedfs-private-iam-ownership-v1",
                "digest": digest,
                "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry",
                "owned_resource_mapping": True,
            },
            "http_preflight": {
                "authenticated_tenants": 2,
                "me_statuses": [200, 200],
                "store_counts": [0, 0],
                "csrf_missing_status": 403,
                "csrf_valid_status": 204,
            },
            "asset_begin": {"expected_status": 201, "actual_status": 404},
        }
        # Canonical JSON distinguishes bool/int and forbids extra secret fields.
        if json.dumps(observed, sort_keys=True, allow_nan=False) != json.dumps(
            expected, sort_keys=True, allow_nan=False
        ):
            raise ValueError("baseline RED preflight evidence is incomplete or invalid")
    except (TypeError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("baseline RED receipt is malformed") from None


def _verify_junit(path: Path) -> None:
    try:
        data = _bounded_read(path, 4 * 1024 * 1024).decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("baseline RED JUnit must be UTF-8") from None
    if "\x00" in data or "<!DOCTYPE" in data.upper() or "<!ENTITY" in data.upper():
        raise ValueError("baseline RED XML declarations are forbidden")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ValueError("baseline RED JUnit is malformed") from None
    allowed_children = {
        "testsuites": {"testsuite"},
        "testsuite": {"testcase", "properties", "system-out", "system-err"},
        "testcase": {"failure", "properties", "system-out", "system-err"},
        "properties": {"property"},
        "property": set(),
        "failure": set(),
        "system-out": set(),
        "system-err": set(),
    }
    if root.tag not in {"testsuites", "testsuite"} or any(
        child.tag not in allowed_children.get(node.tag, set())
        for node in root.iter()
        for child in node
    ):
        raise ValueError("baseline RED JUnit hierarchy is unsupported")
    suites = list(root.iter("testsuite"))
    cases = list(root.iter("testcase"))
    if (
        len(suites) != 1
        or len(cases) != 1
        or suites[0].find("testcase") is not cases[0]
    ):
        raise ValueError("baseline RED requires exactly one selected case")
    expected_counts = {"tests": 1, "failures": 1, "errors": 0, "skipped": 0}
    for summary in [root] if root is suites[0] else [root, suites[0]]:
        for counter, expected in expected_counts.items():
            value = summary.get(counter)
            if value is None and summary is not suites[0]:
                # Pytest's testsuites wrapper has no counters; validate any supplied.
                continue
            if value is None or re.fullmatch(r"[0-9]+", value) is None:
                raise ValueError("baseline RED JUnit counters are invalid")
            try:
                actual = int(value)
            except ValueError:
                raise ValueError("baseline RED JUnit counters are invalid") from None
            if actual != expected:
                raise ValueError("baseline RED JUnit counters disagree with the case")
    case = cases[0]
    failures = list(root.iter("failure"))
    if (
        case.get("name") != CASE_NAME
        or case.get("classname") != CLASSNAME
        or len(failures) != 1
        or case.find("failure") is not failures[0]
        or next(root.iter("error"), None) is not None
        or next(root.iter("skipped"), None) is not None
        or EXPECTED_FAILURE not in "".join(failures[0].itertext())
    ):
        raise ValueError("baseline RED is not the authenticated missing-route failure")


def verify_baseline_red(junit: Path, receipt: Path, *, pytest_exit: int) -> str:
    if type(pytest_exit) is not int or pytest_exit != 1:
        raise ValueError("baseline RED requires pytest assertion failure exit 1")
    _verify_receipt(receipt)
    _verify_junit(junit)
    return BASELINE_SHA


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--pytest-exit", type=int, required=True)
    arguments = parser.parse_args()
    try:
        baseline = verify_baseline_red(
            arguments.junit, arguments.receipt, pytest_exit=arguments.pytest_exit
        )
    except ValueError as error:
        parser.exit(1, f"Baseline asset RED proof rejected: {error}.\n")
    print(
        f"Authenticated missing-feature RED observed on baseline {baseline}. "
        "S3/HTTP preflight passed; asset implementation acceptance remains pending."
    )


if __name__ == "__main__":
    main()
