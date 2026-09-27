"""Evidence-gated parity case and run contracts for the frozen APK baseline."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Reachability = Literal["DECLARED", "REACHABLE", "BLOCKED", "NOT_APPLICABLE"]
Implementation = Literal["NOT_STARTED", "IMPLEMENTED"]
Verdict = Literal["UNTESTED", "MATCHED", "DIFFERENT"]

FROZEN_APK_HASH = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
_SEED_CASE_COUNTS = (2, 5, 2, 2, 3, 3, 2, 4, 2, 3, 4, 4, 1, 3, 2, 4, 6, 9, 4, 2, 1, 5, 3, 1)
FROZEN_SEED_IDS = frozenset(
    f"P{group:02d}.{item}"
    for group, count in enumerate(_SEED_CASE_COUNTS, start=1)
    for item in range(1, count + 1)
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _credible_digest(value: str | None) -> bool:
    return bool(value and _DIGEST.fullmatch(value) and len(set(value)) > 1)


class ParityCase(BaseModel):
    """One atomic APK behavior; static paths do not prove runtime success."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(pattern=r"^P\d{2}\.\d+(?:\.[a-z][a-z0-9_]*)?$")
    feature_id: str = Field(pattern=r"^F\d{2}$")
    gate: str
    input_digest: str | None = None
    apk_evidence: list[str] = Field(min_length=1)
    expected_success: str
    expected_error: str
    expected_side_effect: str
    reachability_status: Reachability
    reachability_reason: str | None = None
    entry_proof: str | None = None
    reachability_reviewer: str | None = None
    discovery_digest: str | None = None
    discovery_reviewer: str | None = None

    @model_validator(mode="after")
    def evidence_for_exclusion(self) -> ParityCase:
        if self.reachability_status == "REACHABLE" and not (
            self.entry_proof and self.reachability_reviewer
        ):
            raise ValueError("REACHABLE requires runtime entry proof and reviewer")
        if self.reachability_status == "BLOCKED" and not self.reachability_reason:
            raise ValueError("BLOCKED requires a concrete reason")
        if self.reachability_status == "NOT_APPLICABLE":
            raise ValueError("NOT_APPLICABLE requires proof per case × matrix")
        if self.case_id not in FROZEN_SEED_IDS:
            seed_id = re.match(r"^P\d{2}\.\d+", self.case_id)
            if not (
                seed_id
                and seed_id.group() in FROZEN_SEED_IDS
                and self.discovery_digest
                and self.discovery_reviewer
            ):
                raise ValueError("runtime-discovered case requires seed, digest and reviewer")
        return self


class ComparisonReceipt(BaseModel):
    """W24 verifier output; the record alone does not prove validity."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    matrix_id: str
    attempt_number: int = Field(ge=1)
    apk_build: str
    web_build: str
    fixture_digest: str
    artifact_digest: str
    matrix_digest: str
    tolerance_digest: str
    comparator_version: str
    verdict: Literal["MATCHED"]
    verifier_id: str
    issued_at: datetime
    signature: str


class ParityRun(BaseModel):
    """A single APK/web comparison attempt for one case and matrix row."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    case_id: str
    matrix_id: str
    attempt_number: int = Field(ge=1)
    attempted_at: datetime
    apk_build: str | None = None
    web_build: str | None = None
    apk_hash: str | None = None
    fixture_digest: str | None = None
    starting_state_proof: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)
    artifact_digest: str | None = None
    tolerance_digest: str | None = None
    apk_observation: dict[str, object] = Field(default_factory=dict)
    web_observation: dict[str, object] = Field(default_factory=dict)
    observed: dict[str, object] = Field(default_factory=dict)
    implementation_status: Implementation = "NOT_STARTED"
    parity_status: Verdict = "UNTESTED"
    comparator_version: str | None = None
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    evidence_links: list[str] = Field(default_factory=list)
    verification_receipt: ComparisonReceipt | None = None

    @model_validator(mode="after")
    def match_requires_comparison_evidence(self) -> ParityRun:
        if self.attempted_at.tzinfo is None:
            raise ValueError("attempted_at must include a time zone")
        if self.parity_status != "MATCHED":
            return self
        fields = (
            self.apk_build,
            self.web_build,
            self.starting_state_proof,
            self.apk_observation,
            self.web_observation,
            self.observed,
            self.comparator_version,
            self.reviewer,
            self.reviewed_at,
            self.evidence_links,
        )
        if self.implementation_status != "IMPLEMENTED" or not all(fields):
            raise ValueError("MATCHED requires runtime APK/web evidence and review")
        if not {"success", "error", "side_effect"}.issubset(self.observed):
            raise ValueError(
                "MATCHED requires success, error and side-effect observations"
            )
        if self.apk_hash != FROZEN_APK_HASH or not all(
            _credible_digest(value)
            for value in (self.fixture_digest, self.artifact_digest, self.tolerance_digest)
        ):
            raise ValueError("MATCHED requires baseline APK hash and nonplaceholder digests")
        return self


class GateProofReceipt(BaseModel):
    """Claim binding for a future W24-trusted gate-proof verifier."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    matrix_id: str
    matrix_digest: str
    gate_proof_digest: str
    reviewer: str
    verifier_id: str
    issued_at: datetime
    signature: str


class MatrixGateProof(BaseModel):
    """Reviewed gate absence for exactly one case × matrix row."""

    model_config = ConfigDict(extra="forbid")

    gate_proof: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    verification_receipt: GateProofReceipt | None = None

    @model_validator(mode="after")
    def proof_must_be_digest(self) -> MatrixGateProof:
        if not _credible_digest(self.gate_proof):
            raise ValueError("gate_proof requires a nonplaceholder SHA-256 digest")
        return self


class SupportMatrix(BaseModel):
    """Versioned applicability map; digest binds all rows and exclusions."""

    model_config = ConfigDict(extra="forbid")

    version: str
    case_ids_by_matrix: dict[str, set[str]]
    not_applicable_by_matrix: dict[str, dict[str, MatrixGateProof]] = Field(
        default_factory=dict
    )
    frozen_digest: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def exclusions_are_scoped(self) -> SupportMatrix:
        for matrix_id, excluded in self.not_applicable_by_matrix.items():
            if matrix_id not in self.case_ids_by_matrix:
                raise ValueError(f"unknown matrix for gate proof: {matrix_id}")
            for case_id in excluded:
                if case_id not in self.case_ids_by_matrix[matrix_id]:
                    raise ValueError(f"gate proof for nonmember: {case_id}@{matrix_id}")
        return self

    def digest(self) -> str:
        payload = {
            "version": self.version,
            "case_ids_by_matrix": {
                key: sorted(value) for key, value in self.case_ids_by_matrix.items()
            },
            "not_applicable_by_matrix": {
                key: {
                    case_id: proof.model_dump(
                        mode="json", exclude={"verification_receipt"}
                    )
                    for case_id, proof in sorted(value.items())
                }
                for key, value in sorted(self.not_applicable_by_matrix.items())
            },
        }
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    @property
    def is_frozen(self) -> bool:
        return bool(
            self.reviewed_by
            and self.reviewed_at
            and self.frozen_digest
            and self.frozen_digest == self.digest()
        )


def gate_receipt_bindings_valid(
    matrix: SupportMatrix, matrix_id: str, case_id: str
) -> bool:
    """Check receipt scope; this does not authenticate its issuer or gate fact."""
    proof = matrix.not_applicable_by_matrix.get(matrix_id, {}).get(case_id)
    receipt = proof.verification_receipt if proof else None
    return bool(
        proof
        and receipt
        and matrix.frozen_digest == matrix.digest()
        and receipt.case_id == case_id
        and receipt.matrix_id == matrix_id
        and receipt.matrix_digest == matrix.frozen_digest
        and receipt.gate_proof_digest == proof.gate_proof
        and receipt.reviewer == proof.reviewer
    )


class ParitySummary(BaseModel):
    matched_count: int
    total_applicable: int
    percent_matched: float
    missing_seed_ids: tuple[str, ...]
    blocked_ids: tuple[str, ...]
    untested_ids: tuple[str, ...]
    different_ids: tuple[str, ...]
    declared_ids: tuple[str, ...]
    not_applicable_ids: tuple[str, ...]
    unverified_gate_ids: tuple[str, ...]
    unverified_match_ids: tuple[str, ...]
    unmapped_case_ids: tuple[str, ...]
    matrix_frozen: bool
    release_ready: bool


def comparison_receipt_bindings_valid(
    case: ParityCase,
    run: ParityRun,
    matrix_digest: str,
) -> bool:
    receipt = run.verification_receipt
    if receipt is None or case.input_digest != run.fixture_digest:
        return False
    if run.apk_observation != run.web_observation:
        # W24 may add a reviewed tolerance comparator; W00 accepts exact semantics only.
        return False
    expected = (
        run.run_id,
        run.case_id,
        run.matrix_id,
        run.attempt_number,
        run.apk_build,
        run.web_build,
        run.fixture_digest,
        run.artifact_digest,
        matrix_digest,
        run.tolerance_digest,
        run.comparator_version,
    )
    actual = (
        receipt.run_id,
        receipt.case_id,
        receipt.matrix_id,
        receipt.attempt_number,
        receipt.apk_build,
        receipt.web_build,
        receipt.fixture_digest,
        receipt.artifact_digest,
        receipt.matrix_digest,
        receipt.tolerance_digest,
        receipt.comparator_version,
    )
    return expected == actual


def calculate_parity(
    cases: list[ParityCase],
    runs: list[ParityRun],
    support_matrix: SupportMatrix,
) -> ParitySummary:
    """Classify attempts; W00 cannot certify a release without W24 verifiers."""
    by_id: dict[str, ParityCase] = {}
    for listed_case in cases:
        if listed_case.case_id in by_id:
            raise ValueError(f"duplicate case_id: {listed_case.case_id}")
        by_id[listed_case.case_id] = listed_case
    missing_seed = sorted(FROZEN_SEED_IDS - set(by_id))

    run_ids: set[str] = set()
    grouped: dict[tuple[str, str], list[ParityRun]] = {}
    for listed_run in runs:
        if listed_run.case_id not in by_id:
            raise ValueError(f"unknown run case: {listed_run.case_id}")
        if listed_run.matrix_id not in support_matrix.case_ids_by_matrix:
            raise ValueError(f"unknown run matrix: {listed_run.matrix_id}")
        if listed_run.case_id not in support_matrix.case_ids_by_matrix[
            listed_run.matrix_id
        ]:
            raise ValueError(
                f"run case outside matrix: {listed_run.case_id}@{listed_run.matrix_id}"
            )
        if listed_run.run_id in run_ids:
            raise ValueError(f"duplicate run_id: {listed_run.run_id}")
        run_ids.add(listed_run.run_id)
        grouped.setdefault((listed_run.case_id, listed_run.matrix_id), []).append(
            listed_run
        )
    latest: dict[tuple[str, str], ParityRun] = {}
    for key, attempts in grouped.items():
        attempts.sort(key=lambda run: run.attempt_number)
        if any(
            newer.attempt_number == older.attempt_number
            or newer.attempted_at <= older.attempted_at
            for older, newer in pairwise(attempts)
        ):
            raise ValueError(f"ambiguous attempt order for {key[0]}@{key[1]}")
        latest[key] = attempts[-1]

    included = (
        set().union(*support_matrix.case_ids_by_matrix.values())
        if support_matrix.case_ids_by_matrix
        else set()
    )
    unmapped = sorted(set(by_id) - included)
    blocked: set[str] = set()
    untested: set[str] = set()
    different: set[str] = set()
    declared: set[str] = set()
    not_applicable: set[str] = set()
    unverified_gate: set[str] = set()
    unverified_match: set[str] = set()
    matched_count = 0
    total = 0

    for matrix_id, case_ids in support_matrix.case_ids_by_matrix.items():
        exclusions = support_matrix.not_applicable_by_matrix.get(matrix_id, {})
        for case_id in sorted(case_ids):
            case = by_id.get(case_id)
            pair_id = f"{case_id}@{matrix_id}"
            if case_id in exclusions:
                # A plausible digest and self-reported reviewer do not prove gate absence.
                unverified_gate.add(pair_id)
            total += 1
            if case is None:
                untested.add(pair_id)
            elif case.reachability_status == "DECLARED":
                declared.add(case_id)
            elif case.reachability_status == "BLOCKED":
                blocked.add(case_id)
            else:
                run = latest.get((case_id, matrix_id))
                if run is None or run.parity_status == "UNTESTED":
                    untested.add(pair_id)
                elif run.parity_status == "DIFFERENT":
                    different.add(pair_id)
                else:
                    # Receipt fields can be checked, but issuer, artifacts and
                    # semantic comparator cannot be trusted until W24 exists.
                    unverified_match.add(pair_id)
                    untested.add(pair_id)

    required = total + len(missing_seed) + len(unmapped)
    return ParitySummary(
        matched_count=matched_count,
        total_applicable=total,
        percent_matched=100 * matched_count / required if required else 0,
        missing_seed_ids=tuple(missing_seed),
        blocked_ids=tuple(sorted(blocked)),
        untested_ids=tuple(sorted(untested)),
        different_ids=tuple(sorted(different)),
        declared_ids=tuple(sorted(declared)),
        not_applicable_ids=tuple(sorted(not_applicable)),
        unverified_gate_ids=tuple(sorted(unverified_gate)),
        unverified_match_ids=tuple(sorted(unverified_match)),
        unmapped_case_ids=tuple(unmapped),
        matrix_frozen=support_matrix.is_frozen,
        release_ready=False,
    )
