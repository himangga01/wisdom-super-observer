"""Exercise foundation selection and its real PowerShell PostgreSQL skip guard."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
NATIVE = "tests/integration/test_private_asset_diagnostics.py"
ORDINARY = "tests/integration/test_tenant_isolation.py"
ORDINARY_CASE = "test_database_role_cannot_read_another_tenant"


def powershell(body, *arguments):
    executable = shutil.which("pwsh")
    if executable is None:
        pytest.fail("foundation selection contract requires PowerShell 7 (pwsh)")
    # Parse the real script, without running dependency sync or any services.
    command = (
        """
    $ErrorActionPreference = 'Stop'
    $args = @(ConvertFrom-Json $env:WSO_SELECTION_ARGUMENTS)
    $tokens = $null; $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $args[0], [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count) { throw 'verify.ps1 parse failed' }
    """
        + body
    )
    environment = os.environ.copy()
    environment["WSO_SELECTION_ARGUMENTS"] = json.dumps(
        [str(ROOT / "scripts/verify.ps1"), *arguments]
    )
    return subprocess.run(
        [executable, "-NoProfile", "-Command", command],
        env=environment,
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def foundation_arguments():
    result = powershell("""
    $assignment = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $node.Left.Extent.Text -eq '$pytestArgs' -and $node.Operator -eq 'Equals'
    }, $true))
    if ($assignment.Count -ne 1) { throw 'foundation argument assignment missing' }
    $uvRun = @()
    . ([scriptblock]::Create($assignment[0].Extent.Text))
    ConvertTo-Json -InputObject @($pytestArgs) -Compress
    """)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)
    assert arguments[0] == "pytest"
    return arguments[1:]


def test_foundation_collects_ordinary_postgres_but_excludes_opt_in_native():
    arguments = foundation_arguments()
    # Bound collection to these two real modules, preserving the script's ignores.
    other_modules = [
        "--ignore=" + path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "tests/integration").glob("test_*.py"))
        if path.relative_to(ROOT).as_posix() not in {NATIVE, ORDINARY}
    ]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *arguments,
            "tests/integration",
            *other_modules,
            "--collect-only",
            "-k",
            f"native or {ORDINARY_CASE}",
        ],
        check=False,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{ORDINARY}::{ORDINARY_CASE}" in result.stdout
    assert NATIVE not in result.stdout, result.stdout


@pytest.mark.parametrize(
    ("classname", "skipped", "reject"),
    [
        ("tests.integration.test_unexpected", True, True),
        ("tests.integration.test_unexpected", False, False),
        ("tests.contract.test_optional", True, False),
    ],
)
def test_real_postgres_guard_rejects_selected_integration_skip(
    tmp_path, classname, skipped, reject
):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests="1", skipped=str(int(skipped)))
    case = ET.SubElement(suite, "testcase", classname=classname, name="test_case")
    if skipped:
        ET.SubElement(case, "skipped", message="controlled unexpected skip")
    report = tmp_path / "results.xml"
    ET.ElementTree(root).write(report, encoding="utf-8")
    result = powershell(
        """
    $guard = @($ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.IfStatementAst] -and
        $node.Clauses[0].Item1.Extent.Text -eq '$WithPostgres' -and
        $node.Clauses[0].Item2.Statements[0].Extent.Text.StartsWith('[xml]$testResults')
    }, $true))
    if ($guard.Count -ne 1) { throw 'PostgreSQL result guard missing' }
    $resultPath = $args[1]
    $WithPostgres = $true
    . ([scriptblock]::Create($guard[0].Extent.Text))
    """,
        str(report),
    )
    if reject:
        assert result.returncode != 0
        assert "A selected PostgreSQL integration test was skipped" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
