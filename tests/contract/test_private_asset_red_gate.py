"""Setup failures and unrelated failures cannot satisfy baseline lifecycle RED."""

import fnmatch
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from scripts.check_private_asset_red import (
    BASELINE_SHA,
    CASE_NAME,
    CLASSNAME,
    EXPECTED_FAILURE,
    main,
    verify_baseline_red,
)


def evidence():
    return {
        "schema_version": 1,
        "baseline_sha": BASELINE_SHA,
        "stage": "ASSET_REQUEST_OBSERVED",
        "provider": {
            "provider": "RustFS",
            "version": "1.0.0",
            "security_profile": "rustfs-inert-acl-dedicated-bucket-v1",
            "artifact_kind": "official-zip-server-local-scratch-image",
            "archive_sha256": "c30a95b76546f25122c9ca387090ddb30c391ca5605621b0d7c881703c0f21c8",
            "archive_bytes": 194469895,
            "binary_sha256": "222eedc3d9baabf6516702d9fbf230270c3ca49b50f562d3461c96e2cc6ae6ad",
            "binary_bytes": 264596736,
            "source_commit": "d47f54bfb2f39f48bd1adda334bd27e151fe85b8",
            "image_id": "sha256:" + "a" * 64,
            "admin_bootstrap": "native-sigv4-iam-zip-v1",
            "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry/durable-prefix-pagination/restart",
            "owned_resource_mapping": True,
        },
        "http_preflight": {
            "authenticated_tenants": 2,
            "me_statuses": [200, 200],
            "store_counts": [0, 0],
            "csrf_missing_status": 403,
            "csrf_valid_status": 204,
        },
        "asset_begin": {"expected_status": 201, "actual_status": 404},
    }


def files(tmp_path, *, status="failure", message=None):
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root, "testsuite", tests="1", failures="1", errors="0", skipped="0"
    )
    case = ET.SubElement(
        suite,
        "testcase",
        name="test_photo_upload_does_not_require_a_store",
        classname="tests.integration.test_private_assets",
    )
    if status:
        ET.SubElement(case, status).text = message or (
            "AssertionError: authenticated POST /api/v1/assets returned 404; expected 201"
        )
    junit = tmp_path / "red.xml"
    ET.ElementTree(root).write(junit, encoding="utf-8")
    receipt = tmp_path / "evidence.json"
    receipt.write_text(json.dumps(evidence()), encoding="utf-8")
    return junit, receipt


def test_exact_authenticated_missing_route_is_baseline_red(tmp_path):
    assert verify_baseline_red(*files(tmp_path), pytest_exit=1) == BASELINE_SHA


@pytest.mark.parametrize("suite_root", [False, True])
def test_pytest_junit_format_is_accepted(tmp_path, suite_root):
    junit, receipt = files(tmp_path)
    # Match pytest's emitted hierarchy/metadata, with the named baseline failure.
    junit.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests">'
        '<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="1" '
        'time="0.146" timestamp="2026-09-30T22:44:26.755964+09:00" '
        'hostname="fixture-host">'
        '<testcase classname="tests.integration.test_private_assets" '
        'name="test_photo_upload_does_not_require_a_store" time="0.007">'
        '<properties><property name="fixture" value="baseline" /></properties>'
        '<failure message="AssertionError: authenticated POST /api/v1/assets '
        'returned 404; expected 201">'
        "AssertionError: authenticated POST /api/v1/assets returned 404; expected 201"
        "</failure><system-out>captured output</system-out>"
        "<system-err>captured stderr</system-err></testcase>"
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    if suite_root:
        root = ET.parse(junit).getroot()
        ET.ElementTree(root[0]).write(junit, encoding="utf-8")
    assert verify_baseline_red(junit, receipt, pytest_exit=1) == BASELINE_SHA


@pytest.mark.parametrize(
    "mutation",
    [
        "no_suite",
        "wrapped_suite",
        "wrapped_case",
        "nested_suite",
        "extra_empty_suite",
        "unknown_suite_child",
        "unknown_case_child",
    ],
)
def test_unsupported_junit_hierarchy_is_refused(tmp_path, mutation):
    junit, receipt = files(tmp_path)
    tree = ET.parse(junit)
    root = tree.getroot()
    suite = root[0]
    case = suite[0]
    if mutation == "no_suite":
        root.remove(suite)
        ET.SubElement(root, "unsupported").append(case)
    elif mutation == "wrapped_suite":
        root.remove(suite)
        ET.SubElement(root, "unsupported").append(suite)
    elif mutation == "wrapped_case":
        suite.remove(case)
        ET.SubElement(suite, "unsupported").append(case)
    elif mutation == "nested_suite":
        root.remove(suite)
        ET.SubElement(root, "testsuite").append(suite)
    elif mutation == "extra_empty_suite":
        ET.SubElement(
            root, "testsuite", tests="0", failures="0", errors="0", skipped="0"
        )
    elif mutation == "unknown_suite_child":
        ET.SubElement(suite, "unsupported")
    else:
        ET.SubElement(case, "unsupported")
    tree.write(junit, encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize("target", ["testsuite", "testsuites"])
@pytest.mark.parametrize(
    "counter,value",
    [
        ("tests", "0"),
        ("tests", "2"),
        ("failures", "0"),
        ("failures", "2"),
        ("errors", "1"),
        ("skipped", "1"),
        ("tests", "-1"),
        ("failures", "1.0"),
        ("errors", ""),
        ("skipped", "PRIVATE_REPORT_VALUE"),
    ],
)
def test_incoherent_junit_counters_are_refused(tmp_path, target, counter, value):
    junit, receipt = files(tmp_path)
    tree = ET.parse(junit)
    summary = next(tree.getroot().iter(target))
    summary.set(counter, value)
    tree.write(junit, encoding="utf-8")
    with pytest.raises(ValueError) as rejected:
        verify_baseline_red(junit, receipt, pytest_exit=1)
    assert "PRIVATE_REPORT_VALUE" not in str(rejected.value)


@pytest.mark.parametrize("counter", ["tests", "failures", "errors", "skipped"])
def test_missing_suite_counter_is_refused(tmp_path, counter):
    junit, receipt = files(tmp_path)
    tree = ET.parse(junit)
    del tree.getroot()[0].attrib[counter]
    tree.write(junit, encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize("pytest_exit", [0, 2, 3, 4, 5, -1, True])
def test_wrong_pytest_exit_is_refused(tmp_path, pytest_exit):
    with pytest.raises(ValueError):
        verify_baseline_red(*files(tmp_path), pytest_exit=pytest_exit)


@pytest.mark.parametrize("status", ["error", "skipped", ""])
def test_setup_skip_and_green_are_not_baseline_red(tmp_path, status):
    with pytest.raises(ValueError):
        verify_baseline_red(*files(tmp_path, status=status), pytest_exit=1)


def test_unrelated_failure_is_refused(tmp_path):
    with pytest.raises(ValueError):
        verify_baseline_red(
            *files(tmp_path, message="AssertionError: provider refused capability"),
            pytest_exit=1,
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("baseline_sha", "b" * 40),
        ("stage", "PROVIDER_PREFLIGHT_PASSED"),
        ("schema_version", True),
        ("unknown", "secret"),
        ("provider", {}),
        ("http_preflight", {}),
        ("asset_begin", {"expected_status": 201, "actual_status": 403}),
    ],
)
def test_incomplete_or_substituted_receipt_is_refused(tmp_path, key, value):
    junit, receipt = files(tmp_path)
    body = evidence()
    body[key] = value
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize(
    "key,value",
    [
        ("image_id", "minio-local:fixture"),
        ("version", "DEVELOPMENT.GOGET"),
        ("binary_sha256", "b" * 64),
        ("client_binary_sha256", "b" * 64),
        ("source_commit", "b" * 40),
        ("client_version", "unknown"),
        ("artifact_kind", "official-container-repodigest"),
        ("owned_resource_mapping", 1),
        ("capabilities", "unverified"),
        ("security_profile", "aws-public-access-block-v1"),
        ("security_profile", None),
        ("endpoint", "http://private"),
    ],
)
def test_wrong_or_unsanitized_provider_receipt_is_refused(tmp_path, key, value):
    junit, receipt = files(tmp_path)
    body = evidence()
    body["provider"][key] = value
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


def test_receipt_without_actual_privacy_profile_is_refused(tmp_path):
    junit, receipt = files(tmp_path)
    body = evidence()
    del body["provider"]["security_profile"]
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


def test_excluded_seaweed_profile_cannot_satisfy_new_baseline_gate(tmp_path):
    junit, receipt = files(tmp_path)
    body = evidence()
    body["provider"] = {
        "provider": "SeaweedFS",
        "version": "4.47",
        "security_profile": "seaweedfs-private-iam-ownership-v1",
        "digest": "chrislusf/seaweedfs@sha256:" + "a" * 64,
        "capabilities": "private IAM/put/get/head/delete/multipart/list/abort/presign-expiry",
        "owned_resource_mapping": True,
    }
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize(
    "profile",
    [
        "minio-inert-acl-dedicated-bucket-v1",
        "minio-inert-acl-dedicated-bucket-v2",
    ],
)
def test_legacy_minio_profiles_cannot_satisfy_rustfs_baseline_gate(tmp_path, profile):
    junit, receipt = files(tmp_path)
    body = evidence()
    body["provider"]["security_profile"] = profile
    receipt.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


def test_cli_public_proof_flag_emits_exact_validated_proof(
    tmp_path, monkeypatch, capsys
):
    junit, receipt = files(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_private_asset_red.py",
            str(junit),
            str(receipt),
            "--pytest-exit",
            "1",
            "--emit-public-proof",
        ],
    )
    main()
    output = capsys.readouterr().out
    proof_line = next(
        line
        for line in output.splitlines()
        if line.startswith("WSO_PUBLIC_ASSET_RED_PROOF=")
    )
    assert json.loads(proof_line.removeprefix("WSO_PUBLIC_ASSET_RED_PROOF=")) == {
        "schema_version": 1,
        "receipt": evidence(),
        "junit": {
            "tests": 1,
            "failures": 1,
            "errors": 0,
            "skipped": 0,
            "classname": CLASSNAME,
            "name": CASE_NAME,
            "failure": EXPECTED_FAILURE,
        },
    }


def test_cli_default_success_does_not_emit_public_proof(tmp_path, monkeypatch, capsys):
    junit, receipt = files(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["check_private_asset_red.py", str(junit), str(receipt), "--pytest-exit", "1"],
    )
    main()
    assert "WSO_PUBLIC_ASSET_RED_PROOF=" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "status,message",
    [
        ("error", None),
        ("failure", "AssertionError: unrelated failure"),
    ],
)
def test_cli_rejected_setup_or_unrelated_failure_emits_no_proof(
    tmp_path, monkeypatch, capsys, status, message
):
    junit, receipt = files(tmp_path, status=status, message=message)
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_private_asset_red.py",
            str(junit),
            str(receipt),
            "--pytest-exit",
            "1",
            "--emit-public-proof",
        ],
    )
    with pytest.raises(SystemExit) as rejected:
        main()
    captured = capsys.readouterr()
    assert rejected.value.code == 1
    assert "WSO_PUBLIC_ASSET_RED_PROOF=" not in captured.out
    assert "WSO_PUBLIC_ASSET_RED_PROOF=" not in captured.err


def test_cli_public_proof_omits_arbitrary_junit_details(tmp_path, monkeypatch, capsys):
    junit, receipt = files(tmp_path)
    private_marker = "PRIVATE_SYNTHETIC_JUNIT_DETAIL"
    tree = ET.parse(junit)
    failure = next(tree.getroot().iter("failure"))
    failure.text = EXPECTED_FAILURE + "\n" + private_marker
    ET.SubElement(
        next(tree.getroot().iter("testcase")), "system-out"
    ).text = private_marker
    ET.SubElement(
        next(tree.getroot().iter("testcase")), "system-err"
    ).text = private_marker
    tree.write(junit, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_private_asset_red.py",
            str(junit),
            str(receipt),
            "--pytest-exit",
            "1",
            "--emit-public-proof",
        ],
    )
    main()
    output = capsys.readouterr().out
    assert private_marker not in output
    assert EXPECTED_FAILURE in output


@pytest.mark.parametrize("mutation", ["duplicate", "foreign", "extra_error"])
def test_extra_or_substituted_testcase_is_refused(tmp_path, mutation):
    junit, receipt = files(tmp_path)
    tree = ET.parse(junit)
    case = next(tree.getroot().iter("testcase"))
    if mutation == "duplicate":
        next(tree.getroot().iter("testsuite")).append(ET.fromstring(ET.tostring(case)))
    elif mutation == "foreign":
        case.set("classname", "tests.contract.test_private_assets")
    else:
        ET.SubElement(case, "error").text = "teardown failed"
    tree.write(junit)
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


def test_duplicate_json_keys_are_refused(tmp_path):
    junit, receipt = files(tmp_path)
    receipt.write_text(
        receipt.read_text().replace(
            '"schema_version": 1', '"schema_version": 1, "schema_version": 1'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize("target", ["junit", "receipt"])
def test_missing_and_oversized_input_are_refused(tmp_path, target):
    junit, receipt = files(tmp_path)
    path = junit if target == "junit" else receipt
    path.unlink()
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


def test_xml_entity_declarations_are_refused(tmp_path):
    junit, receipt = files(tmp_path)
    junit.write_text('<!DOCTYPE testsuites [<!ENTITY x "private">]><testsuites/>')
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-32"])
def test_non_utf8_xml_cannot_bypass_declaration_guard(tmp_path, encoding):
    junit, receipt = files(tmp_path)
    body = junit.read_text()
    body = '<!DOCTYPE testsuites [<!ENTITY x "private">]>' + body
    junit.write_bytes(body.encode(encoding))
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize(
    "entrypoint",
    [
        ["scripts/check_private_asset_red.py"],
        ["-m", "scripts.check_private_asset_red"],
    ],
)
@pytest.mark.parametrize("mutation", [None, "duplicate", "private", "junit_error"])
def test_real_cli_modes_validate_raw_inputs_before_public_proof(
    tmp_path, entrypoint, mutation
):
    junit, receipt = files(tmp_path)
    if mutation == "duplicate":
        payload = receipt.read_text(encoding="utf-8")
        payload = payload.replace(
            '"provider": "RustFS"', '"provider": "RustFS", "provider": "RustFS"'
        )
        receipt.write_text(payload, encoding="utf-8")
    elif mutation == "private":
        body = evidence()
        body["provider"]["endpoint"] = "PRIVATE_SENTINEL"
        receipt.write_text(json.dumps(body), encoding="utf-8")
    elif mutation == "junit_error":
        tree = ET.parse(junit)
        ET.SubElement(tree.getroot()[0][0], "error").text = "PRIVATE_SENTINEL"
        tree.write(junit, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            *entrypoint,
            str(junit),
            str(receipt),
            "--pytest-exit",
            "1",
            "--emit-public-proof",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert "PRIVATE_SENTINEL" not in combined
    proof_lines = [
        line
        for line in result.stdout.splitlines()
        if line.startswith("WSO_PUBLIC_ASSET_RED_PROOF=")
    ]
    if mutation is None:
        assert result.returncode == 0, result.stderr
        assert result.stderr == ""
        assert len(proof_lines) == 1
        proof = json.loads(proof_lines[0].split("=", 1)[1])
        assert proof == {
            "schema_version": 1,
            "receipt": evidence(),
            "junit": {
                "tests": 1,
                "failures": 1,
                "errors": 0,
                "skipped": 0,
                "classname": CLASSNAME,
                "name": CASE_NAME,
                "failure": EXPECTED_FAILURE,
            },
        }
    else:
        assert result.returncode == 1
        assert proof_lines == []
        assert "WSO_PUBLIC_ASSET_RED_PROOF=" not in result.stderr
        assert "Traceback" not in combined


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
def test_outer_receipt_requires_strict_utf8_without_bom(tmp_path, encoding):
    junit, receipt = files(tmp_path)
    receipt.write_bytes(json.dumps(evidence()).encode(encoding))
    with pytest.raises(ValueError):
        verify_baseline_red(junit, receipt, pytest_exit=1)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"PRIVATE_SENTINEL":{"x":1,"x":1}}',
        b'{"PRIVATE_SENTINEL":NaN}',
        b'{"PRIVATE_SENTINEL":Infinity}',
        b"[" * 2000 + b"]" * 2000,
    ],
)
def test_outer_receipt_malformed_values_are_sanitized(tmp_path, payload):
    junit, receipt = files(tmp_path)
    receipt.write_bytes(payload)
    with pytest.raises(ValueError) as rejected:
        verify_baseline_red(junit, receipt, pytest_exit=1)
    assert "PRIVATE_SENTINEL" not in str(rejected.value)


def test_sealed_workflow_copies_only_reviewed_infrastructure(tmp_path):
    import math
    import os
    import shutil
    import textwrap
    import time

    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/private-assets.yml"
    ).read_text(encoding="utf-8")
    # Read YAML step boundaries and scalar properties rather than matching names.
    steps = []
    for block in re.split(
        r"^      - ", workflow.split("    steps:\n", 1)[1], flags=re.MULTILINE
    )[1:]:
        scalar = dict(re.findall(r"^        ([\w-]+): ([^\n]+)$", block, re.MULTILINE))
        run = re.search(
            r"^        run: \|\n((?:          .*\n|\n)+)", block, re.MULTILINE
        )
        scalar["run"] = textwrap.dedent(run.group(1)) if run else ""
        scalar["with"] = dict(
            re.findall(r"^          ([\w-]+): ([^\n]+)$", block, re.MULTILINE)
        )
        steps.append(scalar)
    checkouts = [
        step for step in steps if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1, "full14 must use one current-HEAD checkout"
    assert checkouts[0]["uses"].split()[0] == (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    )
    assert checkouts[0]["with"].get("persist-credentials") == "false"
    assert "ref" not in checkouts[0]["with"]
    assert "path" not in checkouts[0]["with"]
    assert re.findall(r"^    timeout-minutes: (\d+)$", workflow, re.MULTILINE) == [
        "100"
    ]
    assert re.findall(r"^  cancel-in-progress: (\w+)$", workflow, re.MULTILINE) == [
        "false"
    ]
    concurrency = re.search(r"^  group: (.+)$", workflow, re.MULTILINE).group(1)
    assert "${{ github.ref }}" in concurrency
    assert re.findall(r"^    runs-on: (.+)$", workflow, re.MULTILINE) == [
        "ubuntu-24.04"
    ]
    assert "full14" in workflow.splitlines()[0].lower()
    assert "green" in workflow.splitlines()[0].lower()
    assert ".superpowers/ci-private-assets-red" not in workflow
    assert not re.search(r"\b(?:for task_path|git -C|cp --)\b", workflow)
    assert not any("upload-artifact@" in step.get("uses", "") for step in steps)
    assert re.findall(r"^      WSO_TEST_PYTHON: (.+)$", workflow, re.MULTILINE) == [
        "${{ github.workspace }}/.venv/bin/python"
    ]
    setup = [
        step
        for step in steps
        if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert len(setup) == 1
    assert setup[0]["uses"].split()[0] == (
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    )
    assert setup[0]["with"].get("python-version") == "'3.12.10'"
    assert steps[0]["shell"] == "bash"
    assert steps[0]["working-directory"] == "${{ runner.workspace }}"

    pytest_steps = [step for step in steps if "-m pytest " in step["run"]]
    cleanup_steps = [
        step
        for step in steps
        if shlex.split(step["run"])
        == ["bash", "scripts/dev/owned-ci-postgres.sh", "cleanup"]
    ]
    verifier_steps = [
        step
        for step in steps
        if "scripts/check_private_asset_results.py" in step["run"]
    ]
    assert len(pytest_steps) == len(cleanup_steps) == len(verifier_steps) == 1
    pytest_step, cleanup_step, verifier_step = (
        pytest_steps[0],
        cleanup_steps[0],
        verifier_steps[0],
    )
    assert (
        steps.index(pytest_step)
        < steps.index(cleanup_step)
        < steps.index(verifier_step)
    )
    assert cleanup_step["if"] == "always()"
    assert "always()" in verifier_step["if"]
    assert pytest_step.get("id")
    assert cleanup_step.get("id")
    verifier_env = verifier_step["with"]
    assert verifier_env["WSO_PYTEST_EXIT"] == (
        "${{ steps." + pytest_step["id"] + ".outputs.pytest_exit }}"
    )
    assert verifier_env["WSO_POSTGRES_CLEANUP_OUTCOME"] == (
        "${{ steps." + cleanup_step["id"] + ".outcome }}"
    )

    # Execute only shell configuration with controlled commands, never the fixture.
    bash = shutil.which("bash")
    if sys.platform == "win32":
        git_bash = (
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Git/bin/bash.exe"
        )
        if git_bash.is_file():
            bash = str(git_bash)
    assert bash is not None, "configuration shell contract requires bash"
    command_dir = tmp_path / "commands"
    command_dir.mkdir()
    for name in ("python", "python3"):
        wrapper = command_dir / name
        wrapper.write_text(
            "#!/bin/bash\nexec "
            + shlex.quote(sys.executable.replace("\\", "/"))
            + ' "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(command_dir) + os.pathsep + env["PATH"]
    env_file = tmp_path / "github-env"
    env["GITHUB_ENV"] = str(env_file).replace("\\", "/")
    before = time.monotonic()
    anchor = subprocess.run(
        [bash, "-c", steps[0]["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    after = time.monotonic()
    assert anchor.returncode == 0, anchor.stderr
    key, value = env_file.read_text(encoding="utf-8").strip().split("=", 1)
    assert key == "WSO_TEST_ASSET_SUITE_STARTED_MONOTONIC"
    assert re.fullmatch(r"\d+\.\d+", value)
    assert math.isfinite(float(value)) and before <= float(value) <= after

    python_stub = tmp_path / ".venv/bin/python"
    python_stub.parent.mkdir(parents=True)
    python_stub.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$WSO_COMMAND_CAPTURE"\nexit 7\n',
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    capture = tmp_path / "captured-command"
    output = tmp_path / "github-output"
    env.update(
        {
            "WSO_COMMAND_CAPTURE": str(capture).replace("\\", "/"),
            "GITHUB_OUTPUT": str(output).replace("\\", "/"),
        }
    )
    captured = subprocess.run(
        [bash, "-c", pytest_step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert captured.returncode == 0, captured.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "-m",
        "pytest",
        "tests/integration/test_private_assets.py",
        "-q",
        "--tb=short",
        "--junitxml=.superpowers/verification/private-assets-green.xml",
    ]
    assert output.read_text(encoding="utf-8").splitlines() == ["pytest_exit=7"]

    python_stub.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$@" > "$WSO_COMMAND_CAPTURE"\nexit 0\n',
        encoding="utf-8",
    )
    for cleanup_outcome in ("success", "failure", "skipped", "cancelled", ""):
        env.update(
            {"WSO_PYTEST_EXIT": "7", "WSO_POSTGRES_CLEANUP_OUTCOME": cleanup_outcome}
        )
        verified = subprocess.run(
            [bash, "-c", verifier_step["run"]],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        args = capture.read_text(encoding="utf-8").splitlines()
        assert args[:6] == [
            "scripts/check_private_asset_results.py",
            ".superpowers/verification/private-assets-green.xml",
            "--pytest-exit",
            "7",
            "--provider-receipt",
            ".superpowers/verification/private-assets-green-provider.json",
        ]
        assert args[6:] == (
            ["--emit-public-proof"] if cleanup_outcome == "success" else []
        )
        assert (verified.returncode == 0) == (cleanup_outcome == "success")


def test_workflow_changes_to_both_new_helpers_select_the_baseline_gate():
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/private-assets.yml"
    ).read_text(encoding="utf-8")
    paths = workflow.split("    paths:\n", 1)[1].split("\npermissions:", 1)[0]
    patterns = re.findall(r"      - '([^']+)'", paths)
    assert patterns and len(patterns) == len(set(patterns))
    required_changes = [
        ".github/workflows/private-assets.yml",
        "scripts/dev/owned-ci-postgres.sh",
        "scripts/check_private_asset_results.py",
        "scripts/asset_provider_receipt.py",
        "tests/support/asset_provider.py",
        "tests/support/asset_rustfs.py",
        "tests/support/asset_harness.py",
        "tests/support/asset_process.py",
        "tests/support/asset_job_handlers.py",
        "tests/support/asset_broker.py",
        "tests/support/asset_faults.py",
        "tests/integration/test_private_assets.py",
        "tests/contract/test_asset_faults.py",
        "tests/contract/test_asset_job_fixture.py",
        "tests/contract/test_asset_suite_lifetime.py",
        "tests/contract/test_private_asset_gate.py",
        "tests/contract/test_private_asset_green_proof.py",
        "tests/contract/test_private_asset_red_gate.py",
        "packages/core/pyproject.toml",
        "packages/core/src/wso_core/assets.py",
        "pyproject.toml",
        "uv.lock",
    ]
    for changed in required_changes:
        assert any(fnmatch.fnmatchcase(changed, pattern) for pattern in patterns), (
            changed
        )
