"""Independent behavioral contracts for the combined public asset GREEN proof."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROVIDER = {
    "provider": "RustFS",
    "version": "1.0.0",
    "security_profile": "rustfs-inert-acl-dedicated-bucket-v1",
    "artifact_kind": "official-zip-server-local-scratch-image",
    "archive_sha256": "c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8",
    "archive_bytes": 194469895,
    "binary_sha256": "222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad",
    "binary_bytes": 264596736,
    "source_commit": "d47f54bfb2f39f48bd1adda334bd27e151fe85b8",
    "image_id": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "admin_bootstrap": "native-sigv4-iam-zip-v1",
    "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry/durable-prefix-pagination/restart",
    "owned_resource_mapping": True,
}
NAMES = [
    "test_asset_job_restart_and_wrong_tenant_reference",
    "test_cleanup_survives_actor_revocation_and_restart",
    "test_delete_during_upload_and_retryable_provider_failure",
    "test_download_revocation_and_stream_deadline",
    "test_encryption_key_rotation_and_missing_key_fail_closed",
    "test_expired_pending_asset_and_orphan_reconciliation",
    "test_multipart_and_adapter_capabilities_against_real_s3",
    "test_parent_crop_scope_retention_and_cleanup",
    "test_pending_ready_and_ticket_authorization_isolation",
    "test_photo_upload_does_not_require_a_store",
    "test_stored_bytes_are_encrypted_and_tamper_fails_closed",
    "test_upload_crash_recovery_and_abandoned_expiry",
    "test_upload_enforces_byte_pixel_dimension_and_frame_limits",
    "test_upload_validation_rejects_truncation_checksum_and_type",
]
CLASSNAME = "tests.integration.test_private_assets"
PREFIX = "WSO_PUBLIC_ASSET_GREEN_PROOF="
POISON = "PRIVATE_POISON_81a0_secret"
ROOT = Path(__file__).resolve().parents[2]
JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite tests="14" failures="0" errors="0" skipped="0">
<testcase classname="tests.integration.test_private_assets" name="test_photo_upload_does_not_require_a_store"/>
<testcase classname="tests.integration.test_private_assets" name="test_upload_validation_rejects_truncation_checksum_and_type"/>
<testcase classname="tests.integration.test_private_assets" name="test_upload_enforces_byte_pixel_dimension_and_frame_limits"/>
<testcase classname="tests.integration.test_private_assets" name="test_pending_ready_and_ticket_authorization_isolation"/>
<testcase classname="tests.integration.test_private_assets" name="test_stored_bytes_are_encrypted_and_tamper_fails_closed"/>
<testcase classname="tests.integration.test_private_assets" name="test_multipart_and_adapter_capabilities_against_real_s3"/>
<testcase classname="tests.integration.test_private_assets" name="test_upload_crash_recovery_and_abandoned_expiry"/>
<testcase classname="tests.integration.test_private_assets" name="test_download_revocation_and_stream_deadline"/>
<testcase classname="tests.integration.test_private_assets" name="test_parent_crop_scope_retention_and_cleanup"/>
<testcase classname="tests.integration.test_private_assets" name="test_asset_job_restart_and_wrong_tenant_reference"/>
<testcase classname="tests.integration.test_private_assets" name="test_cleanup_survives_actor_revocation_and_restart"/>
<testcase classname="tests.integration.test_private_assets" name="test_delete_during_upload_and_retryable_provider_failure"/>
<testcase classname="tests.integration.test_private_assets" name="test_expired_pending_asset_and_orphan_reconciliation"/>
<testcase classname="tests.integration.test_private_assets" name="test_encryption_key_rotation_and_missing_key_fail_closed"/>
</testsuite></testsuites>
"""


def test_verify_green_returns_complete_public_proof(tmp_path: Path) -> None:
    # Missing combined validation or an incomplete proof breaks this contract.
    from scripts.check_private_asset_results import verify_green

    junit = tmp_path / "results.xml"
    receipt = tmp_path / "provider.json"
    junit.write_bytes(JUNIT.encode("utf-8"))
    receipt.write_bytes(json.dumps(PROVIDER).encode("utf-8"))

    assert verify_green(junit, receipt, pytest_exit=0) == {
        "schema_version": 1,
        "provider": PROVIDER,
        "junit": {
            "tests": 14,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "classname": CLASSNAME,
            "names": NAMES,
        },
    }


def _expected_proof() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": PROVIDER.copy(),
        "junit": {
            "tests": 14,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "classname": CLASSNAME,
            "names": NAMES.copy(),
        },
    }


def _assert_exact_public_value(actual: object, expected: object) -> None:
    # Equality alone would allow bool/int substitutions and subclasses.
    assert type(actual) is type(expected)
    if type(expected) is dict:
        assert actual.keys() == expected.keys()
        assert all(type(key) is str for key in actual)
        for key, value in expected.items():
            _assert_exact_public_value(actual[key], value)
    elif type(expected) is list:
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected, strict=True):
            _assert_exact_public_value(actual_item, expected_item)
    else:
        assert actual == expected


def _inputs(tmp_path: Path, *, xml: str = JUNIT) -> tuple[Path, Path]:
    junit = tmp_path / f"{POISON}-results.xml"
    receipt = tmp_path / f"{POISON}-provider.json"
    junit.write_bytes(xml.encode("utf-8"))
    receipt.write_bytes(json.dumps(PROVIDER).encode("utf-8"))
    return junit, receipt


def _assert_sanitized_failure(
    junit: Path,
    receipt: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    pytest_exit: object = 0,
) -> str:
    from scripts.check_private_asset_results import verify_green

    with pytest.raises(ValueError) as caught:
        verify_green(junit, receipt, pytest_exit=pytest_exit)
    captured = capsys.readouterr()
    output = captured.out + captured.err + str(caught.value)
    assert PREFIX not in output
    assert POISON not in output
    assert str(junit) not in output
    assert str(receipt) not in output
    assert str(caught.value)
    return str(caught.value)


def test_verify_green_has_closed_native_shape_and_discards_xml_metadata(
    tmp_path: Path,
) -> None:
    from scripts.check_private_asset_results import verify_green

    xml = JUNIT.replace(
        '<testsuite tests="14"', f'<testsuite hostname="{POISON}" tests="14"'
    ).replace(
        "</testsuite>",
        f'<properties><property name="token" value="{POISON}"/></properties>'
        f"<system-out>{POISON}</system-out><system-err>{POISON}</system-err>"
        "</testsuite>",
    )
    junit, receipt = _inputs(tmp_path, xml=xml)

    proof = verify_green(junit, receipt, pytest_exit=0)

    _assert_exact_public_value(proof, _expected_proof())
    assert POISON not in json.dumps(proof)


@pytest.mark.parametrize("exit_value", [1, -1, 5, True, False, "0", 0.0, None])
def test_verify_green_rejects_nonzero_or_nonnative_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], exit_value: object
) -> None:
    junit, receipt = _inputs(tmp_path)

    _assert_sanitized_failure(junit, receipt, capsys, pytest_exit=exit_value)


@pytest.mark.parametrize("unavailable", ["missing", "directory"])
def test_verify_green_rejects_unavailable_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], unavailable: str
) -> None:
    junit, receipt = _inputs(tmp_path)
    receipt.unlink()
    if unavailable == "directory":
        receipt.mkdir()

    _assert_sanitized_failure(junit, receipt, capsys)


def test_verify_green_sanitizes_receipt_io_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    junit, receipt = _inputs(tmp_path)
    original_open = Path.open

    def open_input(path: Path, *args: object, **kwargs: object):
        if path == receipt:
            raise OSError(f"{POISON}: {path}")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_input)

    _assert_sanitized_failure(junit, receipt, capsys)


BAD_RECEIPTS = [
    pytest.param(b"", id="empty"),
    pytest.param(POISON.encode(), id="malformed"),
    pytest.param(b"[]", id="wrong-root"),
    pytest.param(b'"' + POISON.encode() + b'"', id="scalar-root"),
    pytest.param(b"\xff" + POISON.encode(), id="invalid-utf8"),
    pytest.param(json.dumps(PROVIDER).encode("utf-16"), id="utf16"),
    pytest.param(b"\xef\xbb\xbf" + json.dumps(PROVIDER).encode(), id="bom"),
    pytest.param(
        json.dumps(PROVIDER).encode()[:-1]
        + b', "provider":"'
        + POISON.encode()
        + b'"}',
        id="duplicate-field",
    ),
    pytest.param(
        json.dumps(PROVIDER).encode()[:-1] + b', "provider":"RustFS"}',
        id="duplicate-canonical-field",
    ),
    pytest.param(
        json.dumps({**PROVIDER, "secret": POISON}).encode(), id="extra-secret-field"
    ),
    pytest.param(
        json.dumps({**PROVIDER, "provider": POISON}).encode(),
        id="provider-substitution",
    ),
    pytest.param(
        json.dumps(
            {**PROVIDER, "archive_bytes": str(PROVIDER["archive_bytes"])}
        ).encode(),
        id="integer-as-string",
    ),
    pytest.param(
        json.dumps(
            {**PROVIDER, "archive_bytes": float(PROVIDER["archive_bytes"])}
        ).encode(),
        id="integer-as-float",
    ),
    pytest.param(
        json.dumps({**PROVIDER, "owned_resource_mapping": 1}).encode(),
        id="boolean-as-int",
    ),
    pytest.param(
        json.dumps({**PROVIDER, "image_id": "sha256:" + "A" * 64}).encode(),
        id="uppercase-image-hash",
    ),
    pytest.param(
        json.dumps({**PROVIDER, "image_id": POISON}).encode(), id="invalid-image-id"
    ),
    *[
        pytest.param(
            json.dumps(PROVIDER).encode()[:-1] + b', "secret":' + token + b"}",
            id=f"nonfinite-{token.decode()}",
        )
        for token in (b"NaN", b"Infinity", b"-Infinity")
    ],
    pytest.param(b" " * (16 * 1024 + 1) + POISON.encode(), id="oversized"),
]


@pytest.mark.parametrize("payload", BAD_RECEIPTS)
def test_verify_green_rejects_invalid_receipt_with_fixed_sanitized_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: bytes
) -> None:
    junit, receipt = _inputs(tmp_path)
    receipt.write_bytes(payload)
    invalid_error = _assert_sanitized_failure(junit, receipt, capsys)
    receipt.write_bytes(b"{}")

    assert _assert_sanitized_failure(junit, receipt, capsys) == invalid_error


def test_verify_green_accepts_receipt_at_exact_bound(tmp_path: Path) -> None:
    from scripts.check_private_asset_results import verify_green

    junit, receipt = _inputs(tmp_path)
    encoded = json.dumps(PROVIDER).encode()
    receipt.write_bytes(encoded + b" " * (16 * 1024 - len(encoded)))

    _assert_exact_public_value(
        verify_green(junit, receipt, pytest_exit=0), _expected_proof()
    )


def test_verify_green_bounds_receipt_read_before_rejecting_oversize(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    junit, receipt = _inputs(tmp_path)
    original_open = Path.open

    class BoundedReceipt(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            assert size == 16 * 1024 + 1
            return super().read(size)

    def open_input(path: Path, *args: object, **kwargs: object):
        if path == receipt:
            return BoundedReceipt(b" " * (16 * 1024 + 2))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_input)

    _assert_sanitized_failure(junit, receipt, capsys)


_FIRST_CASE = (
    '<testcase classname="tests.integration.test_private_assets" '
    'name="test_photo_upload_does_not_require_a_store"/>'
)
BAD_JUNIT = [
    pytest.param(JUNIT.replace(_FIRST_CASE, ""), id="partial"),
    pytest.param(JUNIT.replace(_FIRST_CASE, _FIRST_CASE * 2), id="duplicate"),
    pytest.param(
        JUNIT.replace("</testsuite>", f'<testcase name="{POISON}"/></testsuite>'),
        id="extra",
    ),
    *[
        pytest.param(
            JUNIT.replace(
                _FIRST_CASE, _FIRST_CASE[:-2] + f"><{tag}>{POISON}</{tag}></testcase>"
            ),
            id=tag,
        )
        for tag in ("skipped", "failure", "error")
    ],
]


@pytest.mark.parametrize("xml", BAD_JUNIT)
def test_verify_green_requires_unchanged_strict14_acceptance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], xml: str
) -> None:
    junit, receipt = _inputs(tmp_path, xml=xml)

    _assert_sanitized_failure(junit, receipt, capsys)


def _cli(mode: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    entry = (
        ["-m", "scripts.check_private_asset_results"]
        if mode == "package"
        else [str(ROOT / "scripts" / "check_private_asset_results.py")]
    )
    return subprocess.run(
        [sys.executable, *entry, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )


def _combined_arguments(junit: Path, receipt: Path) -> list[str]:
    return [str(junit), "--pytest-exit", "0", "--provider-receipt", str(receipt)]


def _assert_cli_failure(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert output
    assert PREFIX not in output
    assert POISON not in output


@pytest.mark.parametrize("mode", ["package", "direct"])
def test_combined_cli_emits_only_canonical_compact_public_proof(
    tmp_path: Path, mode: str
) -> None:
    junit, receipt = _inputs(tmp_path)

    result = _cli(mode, [*_combined_arguments(junit, receipt), "--emit-public-proof"])

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    proof_lines = [
        line for line in result.stdout.splitlines() if line.startswith(PREFIX)
    ]
    expected_json = json.dumps(_expected_proof(), sort_keys=True, separators=(",", ":"))
    assert proof_lines == [PREFIX + expected_json]
    _assert_exact_public_value(
        json.loads(proof_lines[0][len(PREFIX) :]), _expected_proof()
    )
    assert POISON not in result.stdout


@pytest.mark.parametrize("mode", ["package", "direct"])
def test_combined_cli_without_emit_does_not_publish_proof(
    tmp_path: Path, mode: str
) -> None:
    junit, receipt = _inputs(tmp_path)

    result = _cli(mode, _combined_arguments(junit, receipt))

    assert result.returncode == 0, result.stderr
    assert PREFIX not in result.stdout + result.stderr
    assert POISON not in result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["package", "direct"])
def test_positional_cli_preserves_junit_only_strict14_mode(
    tmp_path: Path, mode: str
) -> None:
    junit, receipt = _inputs(tmp_path)
    receipt.unlink()

    result = _cli(mode, [str(junit)])

    assert result.returncode == 0, result.stderr
    assert "14" in result.stdout
    assert "zero skips" in result.stdout
    assert PREFIX not in result.stdout + result.stderr
    assert POISON not in result.stdout + result.stderr


@pytest.mark.parametrize("mode", ["package", "direct"])
@pytest.mark.parametrize("guard", ["exit-only", "receipt-only", "emit-only"])
def test_cli_requires_paired_flags_and_combined_mode_for_emit(
    tmp_path: Path, mode: str, guard: str
) -> None:
    junit, receipt = _inputs(tmp_path)
    arguments = {
        "exit-only": [str(junit), "--pytest-exit", "0", "--emit-public-proof"],
        "receipt-only": [
            str(junit),
            "--provider-receipt",
            str(receipt),
            "--emit-public-proof",
        ],
        "emit-only": [str(junit), "--emit-public-proof"],
    }

    _assert_cli_failure(_cli(mode, arguments[guard]))


@pytest.mark.parametrize("mode", ["package", "direct"])
@pytest.mark.parametrize("payload", BAD_RECEIPTS)
def test_cli_never_emits_proof_or_poison_for_invalid_receipt(
    tmp_path: Path, mode: str, payload: bytes
) -> None:
    junit, receipt = _inputs(tmp_path)
    receipt.write_bytes(payload)

    _assert_cli_failure(
        _cli(mode, [*_combined_arguments(junit, receipt), "--emit-public-proof"])
    )


@pytest.mark.parametrize("mode", ["package", "direct"])
@pytest.mark.parametrize("xml", BAD_JUNIT)
def test_cli_never_emits_proof_or_poison_for_rejected_junit(
    tmp_path: Path, mode: str, xml: str
) -> None:
    junit, receipt = _inputs(tmp_path, xml=xml)

    _assert_cli_failure(
        _cli(mode, [*_combined_arguments(junit, receipt), "--emit-public-proof"])
    )


@pytest.mark.parametrize("mode", ["package", "direct"])
@pytest.mark.parametrize("exit_text", ["1", "-1", "5", "0.0", "True", POISON])
def test_cli_never_emits_proof_or_poison_for_invalid_exit(
    tmp_path: Path, mode: str, exit_text: str
) -> None:
    junit, receipt = _inputs(tmp_path)
    arguments = _combined_arguments(junit, receipt)
    arguments[2] = exit_text

    _assert_cli_failure(_cli(mode, [*arguments, "--emit-public-proof"]))


@pytest.mark.parametrize("mode", ["package", "direct"])
def test_cli_never_emits_proof_or_path_for_missing_receipt(
    tmp_path: Path, mode: str
) -> None:
    junit, receipt = _inputs(tmp_path)
    receipt.unlink()

    _assert_cli_failure(
        _cli(mode, [*_combined_arguments(junit, receipt), "--emit-public-proof"])
    )
