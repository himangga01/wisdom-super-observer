"""A partial or skipped recovery suite must never pass the Linux gate."""

from importlib import import_module
from pathlib import Path
from types import ModuleType
from xml.etree import ElementTree as ET

import pytest

REQUIRED = (
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
)


@pytest.fixture
def gate() -> ModuleType:
    return import_module("scripts.check_job_recovery_results")


def report(path: Path, names: tuple[str, ...] = REQUIRED) -> Path:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests="999", skipped="0", failures="0")
    for name in names:
        ET.SubElement(
            suite,
            "testcase",
            name=name,
            classname="tests.jobs_recovery.test_job_broker_recovery",
        )
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def test_accepts_complete_parameterized_recovery_suite(gate: ModuleType, tmp_path):
    path = report(tmp_path / "results.xml", tuple(name + "[real]" for name in REQUIRED))
    assert gate.verify_results(path) == len(REQUIRED)


@pytest.mark.parametrize("missing", REQUIRED)
def test_missing_required_crash_case_fails(gate: ModuleType, tmp_path, missing):
    path = report(
        tmp_path / "results.xml", tuple(name for name in REQUIRED if name != missing)
    )
    with pytest.raises(ValueError):
        gate.verify_results(path)


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_aggregate_success_cannot_hide_skipped_or_failed_case(
    gate: ModuleType, tmp_path, status
):
    path = report(tmp_path / "results.xml")
    tree = ET.parse(path)
    ET.SubElement(next(tree.getroot().iter("testcase")), status)
    tree.write(path)
    with pytest.raises(ValueError):
        gate.verify_results(path)


def test_wrong_suite_cannot_supply_required_case_names(gate: ModuleType, tmp_path):
    path = report(tmp_path / "results.xml")
    tree = ET.parse(path)
    for case in tree.getroot().iter("testcase"):
        case.set("classname", "tests.contract.synthetic")
    tree.write(path)
    with pytest.raises(ValueError):
        gate.verify_results(path)


def test_zero_cases_fails_despite_nonzero_aggregate(gate: ModuleType, tmp_path):
    with pytest.raises(ValueError):
        gate.verify_results(report(tmp_path / "results.xml", ()))


def test_duplicate_testcase_receipt_fails(gate: ModuleType, tmp_path):
    with pytest.raises(ValueError):
        gate.verify_results(report(tmp_path / "results.xml", REQUIRED + REQUIRED[:1]))


def test_missing_or_malformed_report_fails(gate: ModuleType, tmp_path):
    path = tmp_path / "results.xml"
    with pytest.raises(ValueError):
        gate.verify_results(path)
    path.write_text("<broken>")
    with pytest.raises(ValueError):
        gate.verify_results(path)
