"""Require all fourteen actual private asset cases with zero skips or failures."""

import argparse
import re
from pathlib import Path
from xml.etree import ElementTree as ET

REQUIRED_CASES = frozenset(
    {
        "test_photo_upload_does_not_require_a_store",
        "test_upload_validation_rejects_truncation_checksum_and_type",
        "test_upload_enforces_byte_pixel_dimension_and_frame_limits",
        "test_pending_ready_and_ticket_authorization_isolation",
        "test_stored_bytes_are_encrypted_and_tamper_fails_closed",
        "test_multipart_and_adapter_capabilities_against_real_s3",
        "test_upload_crash_recovery_and_abandoned_expiry",
        "test_download_revocation_and_stream_deadline",
        "test_parent_crop_scope_retention_and_cleanup",
        "test_asset_job_restart_and_wrong_tenant_reference",
        "test_cleanup_survives_actor_revocation_and_restart",
        "test_delete_during_upload_and_retryable_provider_failure",
        "test_expired_pending_asset_and_orphan_reconciliation",
        "test_encryption_key_rotation_and_missing_key_fail_closed",
    }
)
CLASSNAME = "tests.integration.test_private_assets"


def _verify_counters(node: ET.Element, case_count: int) -> None:
    expected = {"tests": case_count, "failures": 0, "errors": 0, "skipped": 0}
    for name, count in expected.items():
        value = node.get(name)
        if value is None or re.fullmatch(r"[0-9]+", value) is None:
            raise ValueError("private asset result has missing or malformed counters")
        # Compare normalized digits without converting arbitrary-length input to int.
        if (value.lstrip("0") or "0") != str(count):
            raise ValueError("private asset result has inconsistent counters")


def verify_results(path: Path) -> int:
    try:
        bound = 4 * 1024 * 1024
        with path.open("rb") as stream:
            data = stream.read(bound + 1)
        if len(data) > bound:
            raise ValueError("private asset result file exceeds the bound")
        try:
            xml = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("private asset results use unsupported encoding") from None
        if "\0" in xml:
            raise ValueError("private asset results use unsupported encoding")
        declaration = re.match(r"<\?xml\s+[^?]*\?>", xml)
        if declaration is not None:
            encoding = re.search(r"\bencoding\s*=\s*(['\"])([^'\"]+)\1", declaration[0])
            if encoding is not None and encoding[2].lower() != "utf-8":
                raise ValueError("private asset results use unsupported encoding")
        if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
            raise ValueError("private asset results contain XML declarations")
        root = ET.fromstring(xml)
    except (OSError, ET.ParseError) as error:
        raise ValueError("private asset results are missing or malformed") from error
    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError("private asset results have an unexpected root")
    if any(node.tag in {"skipped", "failure", "error"} for node in root.iter()):
        raise ValueError("a selected private asset case was skipped or failed")
    allowed_children = {
        "testsuites": {"testsuite"},
        "testsuite": {"testcase", "properties", "system-out", "system-err"},
        "testcase": {"properties", "system-out", "system-err"},
        "properties": {"property"},
        "property": set(),
        "system-out": set(),
        "system-err": set(),
    }
    for parent in root.iter():
        if parent.tag not in allowed_children or any(
            child.tag not in allowed_children[parent.tag] for child in parent
        ):
            raise ValueError("private asset results have unsupported structure")
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
    if len(suites) != 1:
        raise ValueError("private asset results have unsupported structure")
    suite = suites[0]
    cases = suite.findall("testcase")
    observed = set()
    for case in cases:
        name = case.get("name", "")
        if case.get("classname") != CLASSNAME or name not in REQUIRED_CASES:
            raise ValueError("private asset result contains an unexpected case")
        if name in observed:
            raise ValueError("private asset result contains a duplicate case")
        observed.add(name)
    if observed != REQUIRED_CASES:
        raise ValueError("required private asset cases are missing")
    _verify_counters(suite, len(cases))
    if root.tag == "testsuites" and any(
        name in root.attrib for name in ("tests", "failures", "errors", "skipped")
    ):
        _verify_counters(root, len(cases))
    return len(observed)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    arguments = parser.parse_args()
    try:
        count = verify_results(arguments.junit)
    except ValueError as error:
        parser.exit(1, f"Private asset gate failed: {error}.\n")
    print(f"Required Linux private asset cases passed: {count}; zero skips.")


if __name__ == "__main__":
    main()
