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


def verify_results(path: Path) -> int:
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("private asset result file exceeds the bound")
        data = path.read_bytes()
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
    cases = (
        root.findall("testsuite/testcase")
        if root.tag == "testsuites"
        else root.findall("testcase")
    )
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
