"""W00 parity status must follow evidence, not static route declarations."""

import subprocess
import sys
from importlib import import_module, util
from pathlib import Path

import pytest


@pytest.fixture
def parity():
    try:
        return import_module("wso_contracts.tvt.parity")
    except ModuleNotFoundError as exc:
        pytest.fail(f"W00 parity model is missing: {exc}")


def case(parity, case_id="P03.1", status="REACHABLE", **overrides):
    values = {
        "case_id": case_id,
        "feature_id": "F03",
        "gate": "O/R/N",
        "apk_evidence": ["apk-audit/12-functional-parity-contracts.md#P03.1"],
        "expected_success": "correct channel frame",
        "expected_error": "offline or denied",
        "expected_side_effect": "media lease released",
        "reachability_status": status,
        "entry_proof": "signed-entry-digest",
        "reachability_reviewer": "entry-reviewer",
    }
    values.update(overrides)
    return parity.ParityCase(**values)


def matrix(parity, case_ids=("P03.1",), reviewed=True):
    return parity.SupportMatrix(
        version="candidate-v1",
        case_ids_by_matrix={"owner-ipc-chrome": set(case_ids)},
        reviewed_by="product-owner" if reviewed else None,
        reviewed_at="2026-09-27T00:00:00Z" if reviewed else None,
    )


def matched_run(parity, **overrides):
    values = {
        "run_id": "run-1",
        "case_id": "P03.1",
        "matrix_id": "owner-ipc-chrome",
        "attempt_number": 1,
        "attempted_at": "2026-09-27T00:00:00Z",
        "apk_build": "1.18.1-20267",
        "web_build": "test-build",
        "apk_hash": parity.FROZEN_APK_HASH,
        "fixture_digest": "f16d05ec6b29248d2c61adb1e9263f78e4f7bace1b955014a2d17872cfe4064d",
        "starting_state_proof": "signed-state-digest",
        "environment": {"browser": "Chrome", "firmware": "test"},
        "artifact_digest": "c7c5c1d70c5dec4416ab6158afd0b223ef40c29b1dc1f97ed9428b94d4cadb1c",
        "tolerance_digest": "41e1e73d5586f1b64bf65531f6710a01e83e83ca512345f6f650692510118f8f",
        "apk_observation": {"frame": "channel-1"},
        "web_observation": {"frame": "channel-1"},
        "observed": {
            "success": True,
            "error": "denied",
            "side_effect": "lease released",
        },
        "implementation_status": "IMPLEMENTED",
        "parity_status": "MATCHED",
        "comparator_version": "1",
        "reviewer": "independent-reviewer",
        "reviewed_at": "2026-09-27T00:00:00Z",
        "evidence_links": ["signed-artifact://run-1"],
    }
    values.update(overrides)
    return parity.ParityRun(**values)


def test_declared_only_not_counted_as_matched(parity):
    declared = case(parity, status="DECLARED")
    summary = parity.calculate_parity([declared], [matched_run(parity)], matrix(parity))
    assert summary.matched_count == 0
    assert summary.declared_ids == ("P03.1",)
    assert not summary.release_ready


def test_missing_runtime_evidence_cannot_match(parity):
    with pytest.raises(ValueError, match="MATCHED requires"):
        matched_run(parity, artifact_digest=None)


def test_blocked_case_prevents_100_percent(parity):
    blocked = case(
        parity, status="BLOCKED", reachability_reason="vendor access unavailable"
    )
    summary = parity.calculate_parity([blocked], [], matrix(parity))
    assert summary.blocked_ids == ("P03.1",)
    assert summary.percent_matched == 0
    assert not summary.release_ready


def test_na_requires_gate_proof(parity):
    with pytest.raises(ValueError, match="per case"):
        case(parity, status="NOT_APPLICABLE", reachability_reason="no gate")


def test_reachable_requires_runtime_entry_proof(parity):
    with pytest.raises(ValueError, match="entry proof"):
        case(parity, entry_proof=None)


def test_duplicate_case_id_rejected(parity):
    with pytest.raises(ValueError, match="duplicate case_id"):
        parity.calculate_parity([case(parity), case(parity)], [], matrix(parity))


def test_candidate_matrix_cannot_release_even_with_match(parity):
    summary = parity.calculate_parity(
        [case(parity)], [matched_run(parity)], matrix(parity, reviewed=False)
    )
    assert summary.matched_count == 0
    assert not summary.release_ready


def test_invalid_match_cannot_be_silently_ignored(parity):
    different_case = matched_run(parity, case_id="P04.2")
    with pytest.raises(ValueError, match="unknown run case"):
        parity.calculate_parity([case(parity)], [different_case], matrix(parity))


def ledger_table(row):
    return (
        "<!-- PARITY_CASES_START -->\n"
        "| Case | Feature | Owner | Gate | Static path | Reachability | Build | Parity | Source | Runtime evidence |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"{row}\n"
        "<!-- PARITY_CASES_END -->\n"
    )


def evidence_checker():
    path = Path(__file__).parents[2] / "scripts" / "check_tvt_evidence.py"
    if not path.exists():
        pytest.fail(f"W00 evidence checker is missing: {path}")
    spec = util.spec_from_file_location("check_tvt_evidence", path)
    assert spec and spec.loader
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checker_accepts_evidenced_static_row():
    checker = evidence_checker()
    row = "| P03.1 | F04 | W07/W08 | O/R/N | C | DECLARED | NOT_STARTED | UNTESTED | [12:P03.1](apk-audit/12-functional-parity-contracts.md) | — |"
    errors = checker.validate_ledger(ledger_table(row), {"P03.1"})
    assert errors == []


def test_checker_rejects_reachable_without_entry_proof():
    checker = evidence_checker()
    row = "| P03.1 | F04 | W07/W08 | O/R/N | C | REACHABLE | NOT_STARTED | UNTESTED | [12:P03.1](apk-audit/12-functional-parity-contracts.md) | — |"
    errors = checker.validate_ledger(ledger_table(row), {"P03.1"})
    assert any("REACHABLE" in error and "entry proof" in error for error in errors)


def test_checker_rejects_duplicate_or_unproven_status():
    checker = evidence_checker()
    row = "| P03.1 | F04 | W07/W08 | O/R/N | C | REACHABLE | NOT_STARTED | MATCHED | [12:P03.1](apk-audit/12-functional-parity-contracts.md) | — |"
    errors = checker.validate_ledger(ledger_table(row + "\n" + row), {"P03.1"})
    assert any("duplicate" in error for error in errors)
    assert any("MATCHED" in error for error in errors)


def test_checker_cli_reports_the_77_rows_it_checked():
    root = Path(__file__).parents[2]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/check_tvt_evidence.py"),
            str(root / "docs/integrations/tvt-parity-ledger.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "audit cases=77; ledger rows=77" in result.stdout


def test_checker_accepts_reviewed_runtime_discovered_branch():
    checker = evidence_checker()
    seed = "| P24.1 | F24 | W22 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P24.1](apk-audit/12-functional-parity-contracts.md) | — |"
    branch = "| P24.1.h5_read | F24 | W22 | U | C | REACHABLE | NOT_STARTED | UNTESTED | [12:P24.1](apk-audit/12-functional-parity-contracts.md) | entry-proof:sha256:abc; discovery-digest:sha256:def; reviewer:qa-1 |"
    assert checker.validate_ledger(ledger_table(seed + "\n" + branch), {"P24.1"}) == []


def test_checker_rejects_discovered_branch_without_provenance():
    checker = evidence_checker()
    seed = "| P24.1 | F24 | W22 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P24.1](apk-audit/12-functional-parity-contracts.md) | — |"
    branch = "| P24.1.h5_read | F24 | W22 | U | C | DECLARED | NOT_STARTED | UNTESTED | [12:P24.1](apk-audit/12-functional-parity-contracts.md) | — |"
    errors = checker.validate_ledger(ledger_table(seed + "\n" + branch), {"P24.1"})
    assert any("discovery" in error for error in errors)


def test_frozen_seed_ids_equal_the_77_atomic_audit_rows(parity):
    audit = (
        Path(__file__).parents[2]
        / "docs/integrations/apk-audit/12-functional-parity-contracts.md"
    ).read_text(encoding="utf-8")
    assert len(parity.FROZEN_SEED_IDS) == 77
    assert parity.FROZEN_SEED_IDS == evidence_checker().audit_ids(audit)


def test_subset_of_frozen_seed_cannot_be_release_ready(parity):
    summary = parity.calculate_parity(
        [case(parity)], [matched_run(parity)], matrix(parity)
    )
    assert "P01.1" in summary.missing_seed_ids
    assert len(summary.missing_seed_ids) == 76
    assert not summary.release_ready


def test_self_labeled_match_without_verifier_receipt_does_not_count(parity):
    summary = parity.calculate_parity(
        [case(parity)], [matched_run(parity)], matrix(parity)
    )
    assert summary.matched_count == 0
    assert summary.untested_ids == ("P03.1@owner-ipc-chrome",)


def test_unequal_apk_web_semantics_cannot_count_as_match(parity):
    run = matched_run(parity, web_observation={"frame": "wrong-channel"})
    summary = parity.calculate_parity([case(parity)], [run], matrix(parity))
    assert summary.matched_count == 0
    assert not summary.release_ready


def test_placeholder_digest_cannot_support_match(parity):
    with pytest.raises(ValueError, match="digest"):
        matched_run(parity, artifact_digest="c" * 64)


def test_not_applicable_gate_proof_only_excludes_its_matrix(parity):
    support = parity.SupportMatrix(
        version="candidate-v1",
        case_ids_by_matrix={"model-a": {"P03.1"}, "model-b": {"P03.1"}},
        not_applicable_by_matrix={
            "model-a": {
                "P03.1": {
                "gate_proof": "c974e17b8e7321ce8c12983de3d0ed4a289821f579bbe0925b0181a4bc8e8d80",
                    "reviewer": "reviewer-2",
                    "reason": "model-a lacks camera channel",
                }
            }
        },
    )
    summary = parity.calculate_parity([case(parity)], [], support)
    assert summary.not_applicable_ids == ()
    assert summary.unverified_gate_ids == ("P03.1@model-a",)
    assert summary.untested_ids == ("P03.1@model-a", "P03.1@model-b")


def test_newer_different_overrides_old_match_regardless_of_input_order(parity):
    old = matched_run(parity, attempt_number=1, attempted_at="2026-09-27T00:00:00Z")
    newer = matched_run(
        parity,
        run_id="run-2",
        attempt_number=2,
        attempted_at="2026-09-27T01:00:00Z",
        parity_status="DIFFERENT",
        web_observation={"frame": "wrong-channel"},
    )
    summary = parity.calculate_parity([case(parity)], [newer, old], matrix(parity))
    assert summary.different_ids == ("P03.1@owner-ipc-chrome",)
    assert summary.matched_count == 0


def test_duplicate_attempt_order_is_rejected(parity):
    first = matched_run(parity, attempt_number=1, attempted_at="2026-09-27T00:00:00Z")
    second = matched_run(
        parity,
        run_id="run-2",
        attempt_number=1,
        attempted_at="2026-09-27T01:00:00Z",
        parity_status="DIFFERENT",
    )
    with pytest.raises(ValueError, match="ambiguous attempt"):
        parity.calculate_parity([case(parity)], [first, second], matrix(parity))


def test_checker_rejects_global_na_marker_without_matrix_scope():
    checker = evidence_checker()
    row = "| P03.1 | F04 | W07/W08 | O/R/N | C | NOT_APPLICABLE | NOT_STARTED | UNTESTED | [12:P03.1](apk-audit/12-functional-parity-contracts.md) | gate-proof:sha256:abc; reviewer:qa-1 |"
    errors = checker.validate_ledger(ledger_table(row), {"P03.1"})
    assert any("matrix" in error for error in errors)


def test_receipt_must_bind_fixture_and_frozen_matrix(parity):
    support = matrix(parity)
    support.frozen_digest = support.digest()
    run = matched_run(parity)
    receipt_fields = {
        "run_id": "run-1",
        "case_id": "P03.1",
        "matrix_id": "owner-ipc-chrome",
        "attempt_number": 1,
        "apk_build": "1.18.1-20267",
        "web_build": "test-build",
        "fixture_digest": run.fixture_digest,
        "artifact_digest": run.artifact_digest,
        "matrix_digest": support.frozen_digest,
        "tolerance_digest": run.tolerance_digest,
        "comparator_version": "1",
        "verdict": "MATCHED",
        "verifier_id": "w24-test-verifier",
        "issued_at": "2026-09-27T02:00:00Z",
        "signature": "validated-test-receipt",
    }
    run.verification_receipt = parity.ComparisonReceipt(**receipt_fields)
    cases = [case(parity, input_digest=run.fixture_digest)]
    assert parity.calculate_parity(cases, [run], support).matched_count == 0
    assert parity.comparison_receipt_bindings_valid(
        cases[0], run, support.frozen_digest
    )
    assert not parity.calculate_parity(cases, [run], support).release_ready

    run.verification_receipt = parity.ComparisonReceipt(
        **{**receipt_fields, "fixture_digest": "d" * 64}
    )
    assert not parity.comparison_receipt_bindings_valid(
        cases[0], run, support.frozen_digest
    )
    run.verification_receipt = parity.ComparisonReceipt(**receipt_fields)
    support.case_ids_by_matrix["new-client"] = {"P03.1"}
    assert not support.is_frozen
    assert not parity.comparison_receipt_bindings_valid(
        cases[0], run, support.digest()
    )


def test_case_fixture_digest_mismatch_prevents_verified_match(parity):
    support = matrix(parity)
    support.frozen_digest = support.digest()
    run = matched_run(parity)
    run.verification_receipt = parity.ComparisonReceipt(
        run_id=run.run_id,
        case_id=run.case_id,
        matrix_id=run.matrix_id,
        attempt_number=run.attempt_number,
        apk_build=run.apk_build,
        web_build=run.web_build,
        fixture_digest=run.fixture_digest,
        artifact_digest=run.artifact_digest,
        matrix_digest=support.frozen_digest,
        tolerance_digest=run.tolerance_digest,
        comparator_version=run.comparator_version,
        verdict="MATCHED",
        verifier_id="w24-test-verifier",
        issued_at="2026-09-27T02:00:00Z",
        signature="validated-test-receipt",
    )
    wrong_fixture = "e" * 64
    assert not parity.comparison_receipt_bindings_valid(
        case(parity, input_digest=wrong_fixture), run, support.frozen_digest
    )


def test_unknown_run_case_is_rejected(parity):
    run = matched_run(parity, case_id="P24.1")
    with pytest.raises(ValueError, match="unknown run case"):
        parity.calculate_parity([case(parity)], [run], matrix(parity))


def test_unknown_run_matrix_is_rejected(parity):
    run = matched_run(parity, matrix_id="unlisted-client")
    with pytest.raises(ValueError, match="unknown run matrix"):
        parity.calculate_parity([case(parity)], [run], matrix(parity))


def test_run_case_outside_its_listed_matrix_is_rejected(parity):
    run = matched_run(parity)
    support = parity.SupportMatrix(
        version="candidate-v1",
        case_ids_by_matrix={"owner-ipc-chrome": {"P04.2"}},
    )
    with pytest.raises(ValueError, match="outside matrix"):
        parity.calculate_parity([case(parity)], [run], support)


def test_forged_gate_proofs_and_lambda_cannot_certify_release(parity):
    seed_ids = parity.FROZEN_SEED_IDS
    support = parity.SupportMatrix(
        version="candidate-v1",
        case_ids_by_matrix={"owner-ipc-chrome": set(seed_ids)},
        not_applicable_by_matrix={
            "owner-ipc-chrome": {
                case_id: {
                    "gate_proof": "c974e17b8e7321ce8c12983de3d0ed4a289821f579bbe0925b0181a4bc8e8d80",
                    "reviewer": "self",
                    "reason": "not here",
                }
                for case_id in seed_ids
                if case_id != "P03.1"
            }
        },
        reviewed_by="self",
        reviewed_at="2026-09-27T00:00:00Z",
    )
    support.frozen_digest = support.digest()
    run = matched_run(parity)
    run.verification_receipt = parity.ComparisonReceipt(
        run_id=run.run_id,
        case_id=run.case_id,
        matrix_id=run.matrix_id,
        attempt_number=run.attempt_number,
        apk_build=run.apk_build,
        web_build=run.web_build,
        fixture_digest=run.fixture_digest,
        artifact_digest=run.artifact_digest,
        matrix_digest=support.frozen_digest,
        tolerance_digest=run.tolerance_digest,
        comparator_version=run.comparator_version,
        verdict="MATCHED",
        verifier_id="self",
        issued_at="2026-09-27T02:00:00Z",
        signature="forged",
    )
    cases = [
        case(parity, case_id=case_id, input_digest=run.fixture_digest)
        for case_id in sorted(seed_ids)
    ]
    with pytest.raises(TypeError):
        parity.calculate_parity(cases, [run], support, lambda receipt: True)
    summary = parity.calculate_parity(cases, [run], support)
    assert not summary.release_ready
    assert summary.matched_count == 0
    assert len(summary.unverified_gate_ids) == 76


def test_placeholder_gate_proof_is_rejected(parity):
    with pytest.raises(ValueError, match="gate_proof"):
        parity.MatrixGateProof(gate_proof="x", reviewer="self", reason="not here")


def test_gate_receipt_bindings_include_case_matrix_and_frozen_digest(parity):
    support = parity.SupportMatrix(
        version="candidate-v1",
        case_ids_by_matrix={"model-a": {"P03.1"}},
        not_applicable_by_matrix={
            "model-a": {
                "P03.1": {
                    "gate_proof": "c974e17b8e7321ce8c12983de3d0ed4a289821f579bbe0925b0181a4bc8e8d80",
                    "reviewer": "qa-1",
                    "reason": "no camera",
                }
            }
        },
    )
    support.frozen_digest = support.digest()
    claim = support.not_applicable_by_matrix["model-a"]["P03.1"]
    claim.verification_receipt = parity.GateProofReceipt(
        case_id="P03.1",
        matrix_id="model-a",
        matrix_digest="d" * 64,
        gate_proof_digest=claim.gate_proof,
        reviewer="qa-1",
        verifier_id="w24",
        issued_at="2026-09-27T02:00:00Z",
        signature="not-validated",
    )
    assert not parity.gate_receipt_bindings_valid(support, "model-a", "P03.1")
    claim.verification_receipt.matrix_digest = support.frozen_digest
    assert parity.gate_receipt_bindings_valid(support, "model-a", "P03.1")
    claim.verification_receipt.case_id = "P04.2"
    assert not parity.gate_receipt_bindings_valid(support, "model-a", "P03.1")
