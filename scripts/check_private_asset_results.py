"""Require all fourteen actual private asset cases with zero skips or failures."""

import argparse
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

if __package__:
    from .asset_provider_receipt import parse_provider_receipt
else:
    from asset_provider_receipt import (  # type: ignore[import-not-found, no-redef]
        parse_provider_receipt,
    )

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


def verify_green(
    junit: Path, provider_receipt: Path, *, pytest_exit: int
) -> dict[str, object]:
    """Require successful pytest, healthy exact14 JUnit, and canonical provider13."""
    if type(pytest_exit) is not int or pytest_exit != 0:
        raise ValueError("private asset pytest did not succeed")
    count = verify_results(junit)
    try:
        with provider_receipt.open("rb") as stream:
            payload = stream.read(16 * 1024 + 1)
        provider = parse_provider_receipt(payload)
    except (OSError, ValueError):
        raise ValueError("provider receipt is invalid") from None
    return {
        "schema_version": 1,
        "provider": provider,
        "junit": {
            "tests": count,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "classname": CLASSNAME,
            "names": sorted(REQUIRED_CASES),
        },
    }


class _GateArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's normal errors echo arbitrary supplied arguments and paths.
        self.exit(2, "Private asset gate failed: invalid command arguments.\n")


def main() -> None:
    parser = _GateArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--pytest-exit", type=int)
    parser.add_argument("--provider-receipt", type=Path)
    parser.add_argument("--emit-public-proof", action="store_true")
    arguments = parser.parse_args()
    combined = arguments.pytest_exit is not None
    if combined != (arguments.provider_receipt is not None):
        parser.error("combined mode requires pytest exit and provider receipt")
    if arguments.emit_public_proof and not combined:
        parser.error("public proof requires combined mode")
    try:
        if combined:
            proof = verify_green(
                arguments.junit,
                arguments.provider_receipt,
                pytest_exit=arguments.pytest_exit,
            )
            count = len(REQUIRED_CASES)
        else:
            count = verify_results(arguments.junit)
    except ValueError as error:
        parser.exit(1, f"Private asset gate failed: {error}.\n")
    print(f"Required Linux private asset cases passed: {count}; zero skips.")
    if arguments.emit_public_proof:
        print(
            "WSO_PUBLIC_ASSET_GREEN_PROOF="
            + json.dumps(proof, sort_keys=True, separators=(",", ":"))
        )


if __name__ == "__main__":
    main()
