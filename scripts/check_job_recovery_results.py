"""Require the complete, skip-free Linux process/broker recovery suite."""

import argparse
from pathlib import Path
from xml.etree import ElementTree as ET

REQUIRED_CASES = frozenset(
    {
        "test_producer_crash_after_commit_before_publication",
        "test_dispatcher_crash_after_publication_before_ack",
        "test_worker_child_crash_before_effect",
        "test_worker_process_crash_before_effect",
        "test_worker_crash_after_effect_before_ack",
        "test_valkey_aof_restart_preserves_delivery",
        "test_empty_broker_rebuilds_published_and_running_jobs",
        "test_external_write_crash_reconciles_without_resubmit",
        "test_unresolved_external_write_blocks_resubmit",
        "test_queue_isolation_prevents_starvation",
    }
)


def verify_results(path: Path) -> int:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("recovery result file exceeds the bound")
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError("recovery results are missing or malformed") from error
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("no recovery cases were executed")
    observed: set[str] = set()
    receipts: set[tuple[str, str]] = set()
    for case in cases:
        name = case.get("name", "")
        classname = case.get("classname", "")
        if not name or not classname.startswith("tests.jobs_recovery."):
            raise ValueError("recovery result contains an unexpected test suite")
        receipt = (classname, name)
        if receipt in receipts:
            raise ValueError("recovery result contains a duplicate test receipt")
        receipts.add(receipt)
        if any(
            case.find(status) is not None for status in ("skipped", "failure", "error")
        ):
            raise ValueError("a selected recovery case was skipped or failed")
        observed.add(name.split("[", 1)[0])
    if not REQUIRED_CASES.issubset(observed):
        raise ValueError("required recovery cases are missing")
    return len(cases)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    arguments = parser.parse_args()
    try:
        count = verify_results(arguments.junit)
    except ValueError as error:
        parser.exit(1, f"Recovery gate failed: {error}.\n")
    print(f"Required Linux recovery cases passed: {count}; zero skips.")


if __name__ == "__main__":
    main()
