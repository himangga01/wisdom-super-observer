"""Fixed W07 test source approval only; grants no production or SQL authority."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PARENT = "a8c39baf215e3b8fea4b92e5df96c21bf1701b9edbb7d61f62e27860af2e5958"
FAMILY = "W07-protected-directory10-and-RPC9-Fix1"
CI_FIXTURE = "tests/tvt_parity/fixtures/directory-approved-sources.json"
LOCAL_RECEIPT = (
    ".superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/"
    "W07-directory-api-evidence/composition-gate.json"
)
# Separately reviewed root input identities; never derived from current sources.
CI_FIXTURE_IDENTITIES = frozenset(
    {
        "03064a0906958dc2b318fa819bac3aa93c7c35834eb49b1034e45c2dbb4f1c44",
        "194562c6ea78099c8f5900320a1a2cf41d3d36c1461a601c1b11b73d4ea023d9",
    }
)
LOCAL_RECEIPT_IDENTITY = (
    "5055717c1d5d1b962ffa56f8b76630328278c9c842fae8c563c8c21ad8bc652c"
)
SOURCE_PATHS = frozenset(
    {
        "packages/contracts/src/wso_contracts/tvt/directory.py",
        "infra/migrations/versions/0011_tvt_directory_read_tickets.py",
        "packages/core/src/wso_core/tvt/directory_admission.py",
        "services/api/src/wso_api/tvt/device_service.py",
        "tests/tvt_parity/test_directory_service.py",
        "tests/integration/test_tvt_directory_admission.py",
        "tests/integration/test_tenant_isolation.py",
        "tests/integration/test_tvt_account_flow_admission.py",
        "tests/contract/test_flow_fixture_portability.py",
        "docs/integrations/tvt-directory-service.md",
        "packages/contracts/proto/tvt_bridge.proto",
        "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2.py",
        "services/tvt-bridge/src/wso_tvt_bridge/generated/tvt_bridge_pb2_grpc.py",
        "services/tvt-bridge/src/wso_tvt_bridge/client.py",
        "services/tvt-bridge/src/wso_tvt_bridge/server.py",
        "services/tvt-bridge/src/wso_tvt_bridge/selected.py",
        "services/tvt-bridge/src/wso_tvt_bridge/directory_config.py",
        "tests/tvt_parity/test_directory_rpc.py",
        "docs/integrations/tvt-directory-rpc.md",
    }
)


def _strict_text(raw, *, recorded_source=False):
    assert not raw.startswith(b"\xef\xbb\xbf"), "source BOM refused"
    raw.decode("utf-8", errors="strict")
    if b"\r" in raw:
        rest = raw.replace(b"\r\n", b"")
        assert b"\r" not in rest, "stray CR refused"
        assert recorded_source or b"\n" not in rest, "nonuniform EOL refused"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, "duplicate source gate key refused"
        result[key] = value
    return result


def _fixed_json(relative, identities):
    raw = (ROOT / relative).read_bytes()
    _strict_text(raw)
    data = json.loads(raw, object_pairs_hook=_unique_object)
    assert hashlib.sha256(raw).hexdigest() in identities, "unreviewed gate refused"
    assert type(data) is dict
    return data


def _source_matches(relative, identities):
    assert all(
        type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in identities
    ), "invalid source identity"
    raw = (ROOT / relative).read_bytes()
    # Hash actual bytes. A new CRLF/mixed variant is never normalized to approval.
    assert hashlib.sha256(raw).hexdigest() in identities, "unreviewed source refused"
    # The reviewed RPC document raw identity includes its historical LF/CRLF suffix.
    # This exception admits those exact pinned bytes, never a newly mixed variant.
    _strict_text(raw, recorded_source=True)


def verify_directory_source_gate():
    """Fail before DB import/creation unless fixed source and activation agree."""
    flags = {
        "WSO_TEST_W07_DIRECTORY_ACCEPTANCE": "1",
        "WSO_TEST_W07_API_ACCEPTANCE": "1",
        "WSO_TEST_W07_PARENT_SHA256": PARENT,
    }
    if all(os.environ.get(name) is None for name in flags):
        pytest.skip("requires explicit root accepted sources and owned W07 activation")
    assert all(os.environ.get(name) == value for name, value in flags.items()), (
        "complete exact W07 activation required"
    )
    _source_matches("infra/migrations/versions/0010_tvt_account_flows.py", {PARENT})
    if sys.platform == "linux":
        assert all(
            os.environ.get(name) == value
            for name, value in {
                "CI": "true",
                "WSO_CI_DISPOSABLE_POSTGRES": "1",
                "WSO_TEST_RECOVERY_DATABASE_NAME": "wso_ci_test",
                "WSO_TEST_RECOVERY_DATABASE_OWNER": "postgres",
            }.items()
        ), "explicit managed Linux CI source required"
        assert re.fullmatch(
            r"[0-9a-f]{32}", os.environ.get("WSO_CI_RUNTIME_OWNER", "")
        ), "managed Linux CI owner required"
        gate = _fixed_json(CI_FIXTURE, CI_FIXTURE_IDENTITIES)
        assert set(gate) == {
            "source_family",
            "root_source_approval",
            "parent_sha256",
            "sources",
        }
        assert gate["source_family"] == FAMILY and gate["root_source_approval"] is True
        assert gate["parent_sha256"] == PARENT
        assert type(gate["sources"]) is dict and set(gate["sources"]) == SOURCE_PATHS
        for relative, aliases in gate["sources"].items():
            assert type(aliases) is dict and set(aliases) == {
                "raw_sha256",
                "canonical_lf_sha256",
            }
            _source_matches(relative, set(aliases.values()))
    else:
        assert sys.platform == "win32", "owned Windows or managed Linux CI required"
        gate = _fixed_json(LOCAL_RECEIPT, {LOCAL_RECEIPT_IDENTITY})
        assert set(gate) == {
            "root_explicitly_accepted",
            "scope",
            "sources",
            "parent_sha256",
            "worker_review",
            "rpc_review",
            "vendor_or_APK_acceptance",
        }
        assert gate["root_explicitly_accepted"] is True
        assert gate["parent_sha256"] == PARENT
        assert type(gate["sources"]) is dict and set(gate["sources"]) == SOURCE_PATHS
        for relative, digest in gate["sources"].items():
            _source_matches(relative, {digest})
