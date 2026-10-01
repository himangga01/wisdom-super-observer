"""Opt-in, three-case native evidence; never full14 or aged acceptance.

No provider imports occur until the explicit diagnostic gate is admitted.
The CLI keeps pytest output private and emits only checked enum/numeric facts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import pytest

CASES = ("after-read", "after-commit", "parent-delete")
CODES = {
    "ASSET_CONFLICT",
    "ASSET_NOT_FOUND",
    "ASSET_EXPIRED",
    "ASSET_UNAVAILABLE",
    "UNAUTHORIZED",
    "FORBIDDEN",
    "ASSET_FORBIDDEN",
    "ABSENT",
    "OTHER",
}
STATES = {
    "PENDING",
    "UPLOADING",
    "READY",
    "DELETE_REQUESTED",
    "DELETING",
    "DELETED",
    "REJECTED",
    "FAILED",
    "UNKNOWN",
}
RECEIPT_DIR = Path(".superpowers/verification/private-asset-diagnostics")


def response_facts(response):
    code = "ABSENT"
    try:
        if len(response.content) > 8192:
            raise ValueError("bounded response exceeded")
        payload = response.json()
        candidate = (
            payload.get("error", {}).get("code") if isinstance(payload, dict) else None
        )
        if candidate is not None:
            code = (
                candidate if type(candidate) is str and candidate in CODES else "OTHER"
            )
    except (ValueError, AttributeError, TypeError):
        code = "OTHER"
    length = len(response.content)
    return {
        "http_status": response.status_code,
        "code": code,
        "image": response.headers.get("content-type", "").lower().startswith("image/"),
        "bytes": "EMPTY" if length == 0 else "LE_4K" if length <= 4096 else "GT_4K",
    }


def _receipt(case):
    return {
        "schema_version": 1,
        "case": case,
        "outcome": "SETUP_FAILED",
        "stage": "SETUP",
        "cleanup": "NOT_STARTED",
        "inventory": "NOT_CHECKED",
        "diagnostic": None,
        "first_exception": "NONE",
        "cleanup_exception": "NONE",
        "cleanup_diagnostics": [],
        "http_status": 0,
        "code": "ABSENT",
        "image": False,
        "bytes": "EMPTY",
        "child_state": "UNKNOWN",
        "physical_cleanup": False,
    }


def _execute(case, tmp_path, scenario):
    if os.environ.get("WSO_TEST_PRIVATE_ASSET_DIAGNOSTICS") != "1":
        pytest.skip("native asset diagnostics require explicit opt-in")
    from tests.support.asset_broker import exception_category
    from tests.support.asset_harness import AssetHarness

    os.chmod(tmp_path, 0o700)
    h = AssetHarness(tmp_path)
    # Dedicated output; diagnostics never mint the full14 provider proof.
    h.provider_evidence = RECEIPT_DIR / (case + "-provider-private.json")
    receipt, assets = _receipt(case), []
    first, cleanup_error, entered, jobs = None, None, False, None
    try:
        h.__enter__()
        entered = True
        h.prepare_case()
        receipt["stage"] = "SCENARIO"
        receipt["outcome"] = "DEFECT"
        scenario(h, receipt, assets)
        receipt["outcome"] = "PASSED"
    except BaseException as error:  # noqa: BLE001 -- preserve privately; never render payload.
        first = error
        receipt["first_exception"] = exception_category(error)
    finally:
        jobs = h.jobs_context
        if entered:
            try:
                if jobs is not None:
                    jobs.__exit__(type(first), first, None)
                # Cleanup only exact scenario assets after owned callers settle.
                if assets:
                    h.erase(*assets)
                    for asset in assets:
                        h.assert_deleted(asset)
                    receipt["physical_cleanup"] = True
                h.assert_foreign_preserved()
                h.assert_seed_database_absence(h.age_seeds)
                if h.physical_inventory() != h.seed_inventory:
                    raise RuntimeError("diagnostic inventory mismatch")
                receipt["inventory"] = "ORIGINAL_6_5"
            except BaseException as error:  # noqa: BLE001 -- separate cleanup cause.
                cleanup_error = error
            try:
                h.__exit__(type(first or cleanup_error), first or cleanup_error, None)
            except BaseException as error:  # noqa: BLE001 -- native custody must remain refused.
                cleanup_error = cleanup_error or error
                receipt["cleanup"] = "TARGET_RETAINED"
            else:
                receipt["cleanup"] = "SETTLED" if cleanup_error is None else "FAILED"
        else:
            # __enter__ already performs its guarded cleanup on failure.
            receipt["cleanup"] = "SETUP_FAILED"
        if jobs is not None and jobs.diagnostic is not None:
            receipt["diagnostic"] = jobs.diagnostic.public()
            receipt["cleanup_diagnostics"] = [
                d.public() for d in jobs.cleanup_diagnostics
            ]
        if cleanup_error is not None:
            receipt["cleanup_exception"] = exception_category(cleanup_error)
            if receipt["outcome"] == "PASSED":
                receipt["outcome"] = "DEFECT"
        RECEIPT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = RECEIPT_DIR / (case + ".json")
        with target.open("w", encoding="utf-8") as stream:
            os.chmod(target, 0o600)
            json.dump(receipt, stream, sort_keys=True)
    if first is not None or cleanup_error is not None:
        failure = RuntimeError(
            "native asset diagnostic failed; inspect bounded receipt"
        )
        failure.initiating_cause = first
        failure.cleanup_cause = cleanup_error
        failure.prefork_diagnostic = jobs.diagnostic if jobs is not None else None
        raise failure from None


def _prefork(h, receipt, assets, position):
    asset = h.upload(h.image())
    assets.append(asset)
    jobs = h.jobs()
    # Keep custody reachable even if context entry or recovery fails.
    jobs.__enter__()
    jobs.assert_registry_and_runtime_denials()
    jobs.crash_and_recover(asset, position, recovery_seconds=160)
    jobs.assert_settled()


def test_native_prefork_after_read(tmp_path):
    _execute(
        "after-read",
        tmp_path,
        lambda h, receipt, assets: _prefork(h, receipt, assets, "after-read"),
    )


def test_native_prefork_after_commit(tmp_path):
    _execute(
        "after-commit",
        tmp_path,
        lambda h, receipt, assets: _prefork(h, receipt, assets, "after-commit"),
    )


def _parent_delete(h, receipt, assets):
    parent = h.upload(h.image())
    assets.append(parent)
    child = h.upload(h.image(), purpose="IMPORT_CROP", parent_asset_id=parent["id"])
    assets.append(child)
    ticket = h.require_ticket(child["id"])
    if h.delete(parent["id"]).status_code != 202:
        raise RuntimeError("parent delete refused")
    response = h.download(child["id"], ticket=ticket)
    receipt.update(response_facts(response))
    state = h.row(child["id"])["state"]
    receipt["child_state"] = state if state in STATES else "UNKNOWN"
    if response.status_code not in {401, 403, 404, 410} or receipt["image"]:
        receipt["outcome"] = "CONTRACT_MISMATCH"
        raise RuntimeError("parent read denial contract mismatch")


def test_native_parent_delete_child_read(tmp_path):
    _execute("parent-delete", tmp_path, _parent_delete)


def validate_receipt(row, case):
    from tests.support.asset_broker import DIAGNOSTIC_STAGES, PROC_STATES

    if type(row) is not dict or set(row) != set(_receipt(case)) or row["case"] != case:
        raise ValueError("invalid diagnostic receipt")
    enums = {
        "outcome": {"SETUP_FAILED", "DEFECT", "CONTRACT_MISMATCH", "PASSED"},
        "stage": {"SETUP", "SCENARIO"},
        "cleanup": {
            "NOT_STARTED",
            "SETUP_FAILED",
            "TARGET_RETAINED",
            "SETTLED",
            "FAILED",
        },
        "inventory": {"NOT_CHECKED", "ORIGINAL_6_5"},
        "code": CODES,
        "bytes": {"EMPTY", "LE_4K", "GT_4K"},
        "child_state": STATES,
        "first_exception": {
            "NONE",
            "DEADLINE",
            "CONTRACT",
            "TIMEOUT",
            "OS",
            "VALUE",
            "ASSERTION",
            "RUNTIME",
            "OTHER",
        },
        "cleanup_exception": {
            "NONE",
            "DEADLINE",
            "CONTRACT",
            "TIMEOUT",
            "OS",
            "VALUE",
            "ASSERTION",
            "RUNTIME",
            "OTHER",
        },
    }
    if any(
        type(row[k]) is not str or row[k] not in values for k, values in enums.items()
    ):
        raise ValueError("invalid diagnostic receipt")
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != 1
        or type(row["http_status"]) is not int
        or not (row["http_status"] == 0 or 100 <= row["http_status"] <= 599)
        or any(type(row[k]) is not bool for k in ("image", "physical_cleanup"))
    ):
        raise ValueError("invalid diagnostic receipt")
    if (
        type(row["cleanup_diagnostics"]) is not list
        or len(row["cleanup_diagnostics"]) > 16
    ):
        raise ValueError("invalid diagnostic receipt")
    diagnostics = row["cleanup_diagnostics"] + (
        [] if row["diagnostic"] is None else [row["diagnostic"]]
    )
    for item in diagnostics:
        fields = {
            "stage",
            "exception",
            "pidfd_ready",
            "proc_state",
            "cutoff",
            "children",
            "parents",
            "observers",
            "callers",
            "helpers",
            "helpers_complete",
        }
        if type(item) is not dict or set(item) != fields:
            raise ValueError("invalid diagnostic receipt")
        for key, choices in {
            "stage": DIAGNOSTIC_STAGES,
            "proc_state": PROC_STATES,
            "exception": {
                "DEADLINE",
                "CONTRACT",
                "TIMEOUT",
                "OS",
                "VALUE",
                "ASSERTION",
                "RUNTIME",
                "OTHER",
            },
            "cutoff": {"EXPIRED", "LE_3S", "GT_3S"},
        }.items():
            if type(item[key]) is not str or item[key] not in choices:
                raise ValueError("invalid diagnostic receipt")
        if any(
            item[k] is not None and type(item[k]) is not bool
            for k in ("pidfd_ready", "helpers_complete")
        ):
            raise ValueError("invalid diagnostic receipt")
        if any(
            type(item[k]) is not int or not -1 <= item[k] <= 999
            for k in ("children", "parents", "observers", "callers", "helpers")
        ):
            raise ValueError("invalid diagnostic receipt")
    return row


def check_results(directory, *, pytest_exit, postgres_cleanup, source, cases=CASES):
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("invalid source binding")
    rows = []
    for case in cases:
        path = directory / (case + ".json")
        if path.stat().st_size > 32768:
            raise ValueError("invalid diagnostic receipt")
        rows.append(validate_receipt(json.loads(path.read_bytes()), case))
    passed = (
        pytest_exit == 0
        and postgres_cleanup == "success"
        and all(
            row["outcome"] == "PASSED"
            and row["cleanup"] == "SETTLED"
            and row["inventory"] == "ORIGINAL_6_5"
            and row["physical_cleanup"]
            and row["diagnostic"] is None
            and row["first_exception"] == row["cleanup_exception"] == "NONE"
            and not row["cleanup_diagnostics"]
            and (
                row["case"] != "parent-delete"
                or (row["http_status"] in {401, 403, 404, 410} and not row["image"])
            )
            for row in rows
        )
    )
    # All row fields above have strict finite allowlists or bounded numeric types.
    print(
        "ASSET_DIAGNOSTICS source="
        + source
        + " status="
        + ("FOCUSED_PASS" if passed else "FAILED")
        + " pytest_exit="
        + str(pytest_exit)
        + " postgres_cleanup="
        + ("SETTLED" if postgres_cleanup == "success" else "FAILED")
    )
    for row in rows:
        print("ASSET_DIAGNOSTIC " + json.dumps(row, sort_keys=True))
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--pytest-exit", type=int, default=1)
    args = parser.parse_args()
    try:
        if not 0 <= args.pytest_exit <= 255:
            raise ValueError("invalid diagnostic exit")
        return check_results(
            RECEIPT_DIR,
            pytest_exit=args.pytest_exit,
            postgres_cleanup=os.environ.get("WSO_POSTGRES_CLEANUP_OUTCOME", ""),
            source=os.environ.get("GITHUB_SHA", ""),
            cases=(args.case,) if args.case else CASES,
        )
    except Exception:  # noqa: BLE001 -- malformed private data never enters public output.
        print("ASSET_DIAGNOSTICS status=INVALID_OR_MISSING_RECEIPT")
        return 1


if __name__ == "__main__":
    sys.exit(main())
