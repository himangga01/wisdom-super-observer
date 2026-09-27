import copy
import csv
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/integrations/tvt-operation-contracts.yaml"
COVERAGE = ROOT / "docs/integrations/tvt-adapter-coverage.csv"
INVENTORY = ROOT / "docs/integrations/apk-audit/12-functional-parity-contracts.md"
ROUTE_INVENTORY = ROOT / "docs/integrations/tvt-request-route-inventory.csv"
JNI_INVENTORY = ROOT / "docs/integrations/tvt-jni-declaration-inventory.csv"
AUDIT = ROOT / "docs/integrations/apk-audit/02-protocol-api.md"
OPERATION_BASELINE = ROOT / "docs/integrations/tvt-frozen-operation-baseline.csv"
FROZEN_OPERATION_DIGEST = (
    "971c1a5d0aa5d4b34b55b43c47d18ce6d45a01f8eea1c691154656ab77c8be93"
)
FROZEN_APK_SHA256 = "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
REQUIRED = {
    "case_id",
    "matrix_id",
    "source_apk_hash",
    "entry_path",
    "upstream_operation",
    "transport_and_endpoint_class",
    "request_schema",
    "response_schema",
    "error_map",
    "callback_sequence",
    "callback_terminal_condition",
    "token_kind",
    "deadline_and_retry_rule",
    "success_condition",
    "authoritative_readback",
    "media_format",
    "adapter_path",
    "deployment_os_abi",
    "rights_reference",
    "fixture_digest",
    "reviewer",
    "status",
    "owner",
    "fixture_path",
}


def seed_ids():
    return set(
        re.findall(
            r"^\| (P\d{2}\.\d+) ", INVENTORY.read_text(encoding="utf-8"), re.MULTILINE
        )
    )


def validate_operation(op, root=ROOT):
    missing = REQUIRED - set(op)
    if missing:
        raise ValueError(f"missing handoff fields: {sorted(missing)}")
    if op["status"] not in {
        "UNMAPPED",
        "BLOCKED",
        "CONTRACT_CAPTURED",
        "NOT_APPLICABLE",
    }:
        raise ValueError("invalid status")
    if op["status"] == "CONTRACT_CAPTURED":
        for key in (
            "source_apk_hash",
            "matrix_id",
            "entry_path",
            "upstream_operation",
            "transport_and_endpoint_class",
            "request_schema",
            "response_schema",
            "error_map",
            "callback_sequence",
            "callback_terminal_condition",
            "token_kind",
            "deadline_and_retry_rule",
            "success_condition",
            "authoritative_readback",
            "adapter_path",
            "deployment_os_abi",
            "rights_reference",
            "fixture_digest",
            "reviewer",
            "outcome_digest",
            "account_role",
        ):
            if op.get(key) in (None, "", "UNKNOWN", "UNVERIFIED", "NOT_APPLICABLE"):
                raise ValueError(f"captured operation lacks {key}")
        if op.get("model_applicability") == "DEVICE" and op.get("model_firmware") in (
            None,
            "",
            "UNKNOWN",
        ):
            raise ValueError("captured device operation lacks model_firmware")
        for key in ("source_apk_hash", "fixture_digest", "outcome_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", op[key]):
                raise ValueError(f"captured operation has invalid {key}")
        if op["source_apk_hash"] != FROZEN_APK_SHA256:
            raise ValueError("captured operation differs from frozen APK baseline")
        for key in ("request_schema", "response_schema", "error_map"):
            if not isinstance(op[key], dict) or not op[key]:
                raise ValueError(f"captured operation needs structured {key}")
        if not isinstance(op["callback_sequence"], list) or not op["callback_sequence"]:
            raise ValueError("captured operation needs ordered callbacks")
        if op["adapter_path"] not in {"A", "B", "C"}:
            raise ValueError("captured operation needs selected adapter path")
        if op.get("reviewed_at") in (None, "", "UNKNOWN"):
            raise ValueError("captured operation needs independent review time")
        variants = {
            "success_1",
            "success_2",
            "authorization_failure",
            "offline_or_unsupported",
            "post_submit_timeout",
        }
        if not variants <= set(op.get("capture_variants", [])):
            raise ValueError("captured operation lacks required variants")
        relative = Path(op["fixture_path"])
        fixture_root = (root / "tests/tvt_parity/fixtures").resolve()
        fixture = (root / relative).resolve()
        if not fixture.is_relative_to(fixture_root) or fixture.suffix != ".json":
            raise ValueError("fixture path must be a JSON file in fixtures")
        if not fixture.is_file():
            raise ValueError("fixture file missing")
        raw = fixture.read_bytes()
        if hashlib.sha256(raw).hexdigest() != op["fixture_digest"]:
            raise ValueError("fixture digest mismatch")
        try:
            text = raw.decode("utf-8")
            captured = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("fixture must be UTF-8 JSON") from error
        if not isinstance(captured, dict) or captured.get("sanitized") is not True:
            raise ValueError("fixture lacks sanitized declaration")
        if re.search(
            r"(?i)data:(?:image|video|audio)/|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            text,
        ):
            raise ValueError("fixture contains raw media or key material")
        if re.search(
            r'(?i)"(?:password|access_token|refresh_token)"\s*:\s*"[A-Za-z0-9_+/=-]{16,}"'
            r"|(?:password|access_token|refresh_token)\s*=\s*[A-Za-z0-9_+/=-]{16,}",
            text,
        ):
            raise ValueError("fixture contains credential-like material")
        expected = {
            "operation_id": op["operation_id"],
            "apk_hash": op["source_apk_hash"],
            "matrix_id": op["matrix_id"],
            "entry_path": op["entry_path"],
            "account_role": op["account_role"],
            "request_schema": op["request_schema"],
            "response_schema": op["response_schema"],
            "error_map": op["error_map"],
            "callback_terminal_condition": op["callback_terminal_condition"],
            "token_kind": op["token_kind"],
            "rights_reference": op["rights_reference"],
            "deployment_os_abi": op["deployment_os_abi"],
            "authoritative_readback": op["authoritative_readback"],
            "outcome_digest": op["outcome_digest"],
        }
        if op["model_applicability"] == "DEVICE":
            expected["model_firmware"] = op["model_firmware"]
        for key, value in expected.items():
            if captured.get(key) != value:
                raise ValueError(f"fixture disagrees with {key}")
        observations = captured.get("observations")
        if not isinstance(observations, list):
            raise ValueError("fixture lacks required observations")
        observed = {}
        for item in observations:
            if not isinstance(item, dict) or not isinstance(item.get("variant"), str):
                raise TypeError("fixture has invalid observation")
            variant = item["variant"]
            digest = item.get("outcome_digest")
            if (
                variant in observed
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise ValueError("fixture has invalid observation outcome digest")
            observed[variant] = digest
        if not variants <= observed.keys():
            raise ValueError("fixture lacks required observations")
        for variant in ("success_1", "success_2"):
            if observed[variant] != op["outcome_digest"]:
                raise ValueError(f"fixture success outcome contradicts {variant}")
    if op["status"] == "NOT_APPLICABLE" and not op.get("not_applicable_evidence"):
        raise ValueError("not-applicable status lacks evidence")


def validate_coverage_row(row, case, op):
    expected = {
        "case_id": case["case_id"],
        "family": op["family"],
        "operation": op["candidate_operation"],
        "operation_id": op["operation_id"],
        "adapter_path": op["adapter_path"],
        "fixture_digest": op["fixture_digest"],
        "rights_reference": op["rights_reference"],
        "status": op["status"],
        "owner": op["owner"],
        "runtime_proof": "YES" if op["status"] == "CONTRACT_CAPTURED" else "NO",
    }
    for field, value in expected.items():
        if row.get(field) != value:
            raise ValueError(f"coverage CSV disagrees with {field}")


def validate_frozen_operation_baseline(data, coverage, baseline):
    fields = ("case_id", "operation_id", "candidate_operation")
    triples = sorted(tuple(row.get(field, "") for field in fields) for row in baseline)
    canonical = "".join("\t".join(row) + "\n" for row in triples)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    baseline_ids = {row[1] for row in triples}
    if (
        len(triples) != 199
        or len(baseline_ids) != 199
        or digest != FROZEN_OPERATION_DIGEST
    ):
        raise ValueError("frozen operation baseline manifest changed")
    handoff = {
        op["operation_id"]: (case["case_id"], op["candidate_operation"])
        for case in data["cases"]
        for op in case["operations"]
    }
    mirrored = {
        row["operation_id"]: (row["case_id"], row["operation"]) for row in coverage
    }
    for case_id, operation_id, label in triples:
        expected = (case_id, label)
        if (
            handoff.get(operation_id) != expected
            or mirrored.get(operation_id) != expected
        ):
            raise ValueError(f"frozen operation missing or renamed: {operation_id}")


class RuntimeFixtureSchemaTest(unittest.TestCase):
    def test_frozen_199_operations_survive_synchronized_yaml_csv_changes(self):
        validator = globals().get("validate_frozen_operation_baseline")
        self.assertIsNotNone(validator, "frozen operation validator missing")
        self.assertTrue(
            OPERATION_BASELINE.is_file(), "frozen operation baseline missing"
        )
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        with COVERAGE.open(encoding="utf-8-sig", newline="") as handle:
            coverage = list(csv.DictReader(handle))
        with OPERATION_BASELINE.open(encoding="utf-8", newline="") as handle:
            baseline = list(csv.DictReader(handle))
        validator(data, coverage, baseline)
        target = baseline[0]
        removed = copy.deepcopy(data)
        next(case for case in removed["cases"] if case["case_id"] == target["case_id"])[
            "operations"
        ] = [
            op
            for op in next(
                case
                for case in removed["cases"]
                if case["case_id"] == target["case_id"]
            )["operations"]
            if op["operation_id"] != target["operation_id"]
        ]
        removed_coverage = [
            row for row in coverage if row["operation_id"] != target["operation_id"]
        ]
        self.assertEqual(
            {
                op["operation_id"]
                for case in removed["cases"]
                for op in case["operations"]
            },
            {row["operation_id"] for row in removed_coverage},
        )
        with self.assertRaisesRegex(ValueError, "frozen operation"):
            validator(removed, removed_coverage, baseline)
        renamed = copy.deepcopy(data)
        op = next(
            op
            for case in renamed["cases"]
            for op in case["operations"]
            if op["operation_id"] == target["operation_id"]
        )
        op["candidate_operation"] = "renamed.candidate"
        renamed_coverage = [dict(row) for row in coverage]
        next(
            row
            for row in renamed_coverage
            if row["operation_id"] == target["operation_id"]
        )["operation"] = "renamed.candidate"
        with self.assertRaisesRegex(ValueError, "frozen operation"):
            validator(renamed, renamed_coverage, baseline)

    def test_all_77_seed_cases_have_family_and_operation(self):
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(77, len(seed_ids()))
        cases = data["cases"]
        self.assertTrue(seed_ids() <= {case["case_id"] for case in cases})
        self.assertEqual(len(cases), len({case["case_id"] for case in cases}))
        for case in cases:
            self.assertTrue(case["family"])
            self.assertTrue(case["entry_path"])
            self.assertTrue(case["operations"])
            for op in case["operations"]:
                self.assertEqual(case["case_id"], op["case_id"])
                validate_operation(op)

    def test_coverage_rows_match_operation_ids_and_proof_status(self):
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        ops = {
            (op["case_id"], op["operation_id"]): op
            for case in data["cases"]
            for op in case["operations"]
        }
        with COVERAGE.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        required = {
            "case_id",
            "family",
            "operation",
            "operation_id",
            "adapter_path",
            "fixture_digest",
            "rights_reference",
            "runtime_proof",
            "status",
            "owner",
        }
        self.assertTrue(required <= set(rows[0]))
        self.assertEqual(set(ops), {(r["case_id"], r["operation_id"]) for r in rows})
        self.assertEqual(len(ops), len(rows))
        for row in rows:
            op = ops[(row["case_id"], row["operation_id"])]
            case = next(c for c in data["cases"] if c["case_id"] == row["case_id"])
            validate_coverage_row(row, case, op)

    def test_captured_fixtures_fail_closed_when_evidence_missing(self):
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        sample = next(
            op
            for c in data["cases"]
            for op in c["operations"]
            if op["status"] == "UNMAPPED"
        )
        for family in (
            "login",
            "live",
            "playback",
            "talk",
            "control",
            "alarm",
            "cloud",
            "vas",
            "tyco",
            "h5",
        ):
            fake = dict(sample, family=family, status="CONTRACT_CAPTURED")
            with self.subTest(family=family), self.assertRaises(ValueError):
                validate_operation(fake)

    def test_each_captured_handoff_field_is_individually_required(self):
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        sample = next(
            op
            for c in data["cases"]
            for op in c["operations"]
            if op["status"] == "UNMAPPED"
        )
        valid = dict(sample)
        for key in REQUIRED:
            valid[key] = "observed"
        valid.update(
            status="CONTRACT_CAPTURED",
            source_apk_hash="a" * 64,
            fixture_digest="b" * 64,
            outcome_digest="c" * 64,
            account_role="owner",
            model_applicability="DEVICE",
            model_firmware="model/firmware",
            request_schema={"type": "object"},
            response_schema={"type": "object"},
            error_map={"permission": "FORBIDDEN"},
            callback_sequence=["request", "reply"],
            adapter_path="A",
            reviewed_at="2026-09-27T00:00:00Z",
            capture_variants=[
                "success_1",
                "success_2",
                "authorization_failure",
                "offline_or_unsupported",
                "post_submit_timeout",
            ],
        )
        for key in REQUIRED - {"status", "case_id"}:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_operation({k: v for k, v in valid.items() if k != key})

    def test_repository_artifacts_contain_no_obvious_secret_or_media_payload(self):
        for path in (CONTRACT, COVERAGE):
            contents = path.read_text(encoding="utf-8-sig")
            self.assertNotRegex(
                contents, r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
            )
            self.assertNotRegex(
                contents,
                r"(?i)(?:password|access_token|refresh_token)\s*[:=]\s*[A-Za-z0-9_+/=-]{16,}",
            )
            self.assertNotRegex(contents, r"(?i)data:(?:image|video|audio)/")

    def test_captured_contract_requires_real_sanitized_fixture_and_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fixture = root / "tests/tvt_parity/fixtures/sample.json"
            fixture.parent.mkdir(parents=True)
            payload = {
                "sanitized": True,
                "operation_id": "P02.1.op02",
                "apk_hash": FROZEN_APK_SHA256,
                "matrix_id": "matrix-1",
                "entry_path": "login",
                "account_role": "owner",
                "model_firmware": "model/fw",
                "request_schema": {"type": "object"},
                "response_schema": {"type": "object"},
                "error_map": {"denied": "FORBIDDEN"},
                "callback_terminal_condition": "reply",
                "token_kind": "user",
                "rights_reference": "vendor-grant-1",
                "deployment_os_abi": "linux/x86_64",
                "authoritative_readback": "profile",
                "outcome_digest": "c" * 64,
                "observations": [
                    {
                        "variant": variant,
                        "outcome_digest": (
                            "c" if variant.startswith("success") else "d"
                        )
                        * 64,
                    }
                    for variant in (
                        "success_1",
                        "success_2",
                        "authorization_failure",
                        "offline_or_unsupported",
                        "post_submit_timeout",
                    )
                ],
            }
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            op = {key: "observed" for key in REQUIRED} | {
                "operation_id": "P02.1.op02",
                "case_id": "P02.1",
                "status": "CONTRACT_CAPTURED",
                "source_apk_hash": FROZEN_APK_SHA256,
                "matrix_id": "matrix-1",
                "entry_path": "login",
                "request_schema": payload["request_schema"],
                "response_schema": payload["response_schema"],
                "error_map": payload["error_map"],
                "callback_sequence": ["request", "reply"],
                "callback_terminal_condition": "reply",
                "token_kind": "user",
                "rights_reference": "vendor-grant-1",
                "deployment_os_abi": "linux/x86_64",
                "authoritative_readback": "profile",
                "account_role": "owner",
                "model_applicability": "DEVICE",
                "model_firmware": "model/fw",
                "adapter_path": "A",
                "fixture_path": "tests/tvt_parity/fixtures/sample.json",
                "fixture_digest": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                "outcome_digest": "c" * 64,
                "reviewed_at": "2026-09-27T00:00:00Z",
                "capture_variants": [
                    "success_1",
                    "success_2",
                    "authorization_failure",
                    "offline_or_unsupported",
                    "post_submit_timeout",
                ],
            }
            fixture.unlink()
            with self.assertRaisesRegex(ValueError, "fixture"):
                validate_operation(op, root=root)
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            validate_operation(op, root=root)
            op["source_apk_hash"] = "a" * 64
            payload["apk_hash"] = "a" * 64
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            op["fixture_digest"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "frozen APK"):
                validate_operation(op, root=root)
            op["source_apk_hash"] = FROZEN_APK_SHA256
            payload["apk_hash"] = FROZEN_APK_SHA256
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            op["fixture_digest"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            for index in (0, 1):
                payload["observations"][index]["outcome_digest"] = "e" * 64
                fixture.write_text(json.dumps(payload), encoding="utf-8")
                op["fixture_digest"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "outcome"):
                    validate_operation(op, root=root)
                payload["observations"][index]["outcome_digest"] = "c" * 64
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            op["fixture_digest"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            op["fixture_digest"] = "d" * 64
            with self.assertRaisesRegex(ValueError, "digest"):
                validate_operation(op, root=root)
            payload["password"] = "x" * 24
            fixture.write_text(json.dumps(payload), encoding="utf-8")
            op["fixture_digest"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "credential"):
                validate_operation(op, root=root)

    def test_csv_mirror_rejects_each_mismatched_field(self):
        validator = globals().get("validate_coverage_row")
        self.assertIsNotNone(validator, "coverage row validator missing")
        data = json.loads(CONTRACT.read_text(encoding="utf-8"))
        case = data["cases"][0]
        op = case["operations"][0]
        with COVERAGE.open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        validator(row, case, op)
        for field in (
            "family",
            "operation",
            "adapter_path",
            "fixture_digest",
            "rights_reference",
            "owner",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validator({**row, field: "WRONG"}, case, op)

    def test_static_route_and_jni_inventories_trace_every_declaration(self):
        self.assertTrue(ROUTE_INVENTORY.is_file(), "request route inventory missing")
        self.assertTrue(JNI_INVENTORY.is_file(), "JNI declaration inventory missing")
        operation_ids = {
            op["operation_id"]
            for case in json.loads(CONTRACT.read_text(encoding="utf-8"))["cases"]
            for op in case["operations"]
        }
        audit_lines = AUDIT.read_text(encoding="utf-8").splitlines()
        for path, count, key in (
            (ROUTE_INVENTORY, 281, "request_class"),
            (JNI_INVENTORY, 299, "native_declaration"),
        ):
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(count, len(rows))
            self.assertEqual(count, len({r[key] for r in rows}))
            for row in rows:
                self.assertTrue(row["evidence_source"])
                self.assertTrue(row["audit_line"])
                self.assertEqual("NO", row["runtime_proof"])
                source_line = audit_lines[int(row["audit_line"]) - 1]
                if key == "request_class":
                    self.assertIn(row[key], source_line)
                else:
                    self.assertIn(row["method"], source_line)
                self.assertTrue(
                    row["static_disposition"]
                    in {"MAPPED", "UNREFERENCED", "BROKEN_STUB", "UNKNOWN"}
                )
                if row["static_disposition"] in {"UNREFERENCED", "BROKEN_STUB"}:
                    self.assertTrue(row["disposition_evidence"])
                if row["static_disposition"] == "MAPPED":
                    self.assertIn(row["operation_id"], operation_ids)
                else:
                    self.assertEqual("", row["operation_id"])

    def test_empty_cloud_callbacks_are_not_mapped_as_working_routes(self):
        with ROUTE_INVENTORY.open(encoding="utf-8", newline="") as handle:
            rows = {r["route"]: r for r in csv.DictReader(handle)}
        for route in (
            "/sdk/deviceCloudStorageIsValid",
            "/sdk/getValidCloudStorageChlList",
        ):
            with self.subTest(route=route):
                self.assertEqual("BROKEN_STUB", rows[route]["static_disposition"])
                self.assertEqual("", rows[route]["operation_id"])


if __name__ == "__main__":
    unittest.main()
