"""Exercise the verification gate with only external processes intercepted."""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCOPE = "tests/integration/test_tvt_domain_scope.py"
CREDENTIALS = "tests/integration/test_tvt_domain_credentials.py"
ROLES = (
    "ADMIN",
    "APP",
    "IDENTITY",
    "MIGRATOR",
    "SESSION",
    "WORKER",
    "DISPATCH",
    "JOB",
    "ASSET_MAINTENANCE",
)


def junit(mode):
    suite = Element("testsuite", tests="42", failures="0", errors="0", skipped="0")
    for module, count in (("scope", 3), ("credentials", 39)):
        for index in range(count):
            SubElement(
                suite,
                "testcase",
                classname=f"tests.integration.test_tvt_domain_{module}",
                name=f"test_{index}",
                time="0.001",
            )
    if mode == "count":
        suite.set("tests", "43")
    elif mode == "deselected":
        suite.remove(suite[-1])
        suite.set("tests", "41")
    elif mode == "wrong_module":
        suite[-1].set("classname", "tests.integration.test_unrelated")
    elif mode in {"failure", "error", "skipped"}:
        SubElement(suite[-1], mode)
        suite.set({"failure": "failures", "error": "errors"}.get(mode, mode), "1")
    elif mode in {"hidden_failure", "hidden_error", "hidden_skipped"}:
        SubElement(suite[-1], mode.removeprefix("hidden_"))
    elif mode == "summary_skipped":
        suite.set("skipped", "1")
    wrapper = Element("testsuites")
    wrapper.append(suite)
    return tostring(wrapper, encoding="unicode")


@pytest.fixture
def gate(tmp_path):
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell 7 is required to verify scripts/verify.ps1 behavior"
    (tmp_path / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/verify.ps1", tmp_path / "scripts/verify.ps1")
    shutil.copytree(
        ROOT / "packages/contracts/generated", tmp_path / "packages/contracts/generated"
    )

    def run(*switches, mode="success", prior=None, missing_role=None):
        environment = os.environ.copy()
        environment.pop("CI", None)
        environment.pop("WSO_TEST_W02_DOMAIN_DIAGNOSTIC", None)
        environment.pop("WSO_TEST_W02_DOMAIN_ACCEPTANCE", None)
        if prior is not None:
            environment["WSO_TEST_W02_DOMAIN_ACCEPTANCE"] = prior
        for role in ROLES:
            # No database process is invoked and these values are never printed.
            environment[f"WSO_TEST_{role}_DATABASE_URL"] = "intercepted-role-url"
        if missing_role:
            environment.pop(f"WSO_TEST_{missing_role}_DATABASE_URL")
        environment["GATE_ROOT"] = str(tmp_path)
        environment["GATE_MODE"] = mode
        environment["GATE_JUNIT"] = junit(mode)
        if mode == "missing":
            verification = tmp_path / ".superpowers/verification"
            verification.mkdir(parents=True, exist_ok=True)
            (verification / "pytest-tvt-domain.xml").write_text(
                junit("success"), encoding="utf-8"
            )
        script = r"""
$global:gateCalls = [Collections.Generic.List[object]]::new()
function global:python {
    $arguments = @($args)
    $global:gateCalls.Add([pscustomobject]@{
        name='python'; arguments=$arguments
        acceptance=[Environment]::GetEnvironmentVariable('WSO_TEST_W02_DOMAIN_ACCEPTANCE')
    })
    $global:LASTEXITCODE = 0
    $junitArg = @($arguments | Where-Object { $_ -like '--junitxml=*' })
    if ($junitArg.Count -gt 0) {
        $path = $junitArg[0].Substring('--junitxml='.Length)
        $domain = $arguments -contains 'tests/integration/test_tvt_domain_scope.py'
        if ($domain -and $env:GATE_MODE -eq 'exit') { $global:LASTEXITCODE = 7; return }
        if ($domain -and $env:GATE_MODE -eq 'missing') { return }
        $xml = if ($domain) { $env:GATE_JUNIT } else {
            '<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0"><testcase classname="tests.integration.test_foundation" name="test_ok" /></testsuite></testsuites>'
        }
        Set-Content -LiteralPath $path -Value $xml
    }
}
function global:pnpm {
    $global:gateCalls.Add([pscustomobject]@{
        name='pnpm'; arguments=@($args)
        acceptance=[Environment]::GetEnvironmentVariable('WSO_TEST_W02_DOMAIN_ACCEPTANCE')
    })
    $global:LASTEXITCODE = 0
}
$failure = $null
try { & (Join-Path $env:GATE_ROOT 'scripts/verify.ps1') SWITCHES }
catch { $failure = $_.Exception.Message }
[pscustomobject]@{
    failure=$failure; calls=@($global:gateCalls.ToArray())
    restored=[Environment]::GetEnvironmentVariable('WSO_TEST_W02_DOMAIN_ACCEPTANCE')
} | ConvertTo-Json -Depth 8 -Compress | Write-Output
""".replace("SWITCHES", " ".join(switches))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            [pwsh, "-NoLogo", "-NoProfile", "-EncodedCommand", encoded],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout.splitlines()[-1])

    return run


def pytest_calls(result):
    return [call for call in result["calls"] if "pytest" in call["arguments"]]


@pytest.mark.parametrize("switches", [(), ("-WithPostgres",)])
def test_foundation_excludes_only_dormant_domain_modules(gate, switches):
    result = gate(*switches, prior="1")
    assert result["failure"] is None
    calls = pytest_calls(result)
    assert len(calls) == 1
    args = calls[0]["arguments"]
    assert {arg for arg in args if arg.startswith("--ignore=")} == {
        "--ignore=tests/jobs_recovery",
        "--ignore=tests/integration/test_private_assets.py",
        f"--ignore={SCOPE}",
        f"--ignore={CREDENTIALS}",
    }
    assert args[args.index("pytest") + 1 : args.index("pytest") + 3] == [
        "-m",
        "not live",
    ]
    assert result["restored"] == "1"


def test_domain_requires_postgres_before_any_dependency_invocation(gate):
    result = gate("-WithTvtDomain")
    assert result["failure"] and "Postgres" in result["failure"]
    assert result["calls"] == []


@pytest.mark.parametrize("prior", [None, "previous-value"])
def test_domain_packet_is_explicit_and_acceptance_environment_is_scoped(gate, prior):
    result = gate("-WithPostgres", "-WithTvtDomain", prior=prior)
    assert result["failure"] is None
    foundation, domain = pytest_calls(result)
    assert f"--ignore={SCOPE}" in foundation["arguments"]
    assert foundation["acceptance"] == prior
    args = domain["arguments"]
    assert args[args.index("pytest") + 1 : -1] == [SCOPE, CREDENTIALS, "-q"]
    assert args[-1].endswith("pytest-tvt-domain.xml")
    assert domain["acceptance"] == "1"
    assert result["restored"] == prior
    assert all(
        call["acceptance"] == prior for call in result["calls"] if call != domain
    )


@pytest.mark.parametrize(
    "mode",
    [
        "count",
        "deselected",
        "wrong_module",
        "failure",
        "error",
        "skipped",
        "hidden_failure",
        "hidden_error",
        "hidden_skipped",
        "summary_skipped",
        "missing",
        "exit",
    ],
)
@pytest.mark.parametrize("prior", [None, "previous-value"])
def test_domain_rejects_unverified_packet_and_restores_environment(gate, mode, prior):
    result = gate("-WithPostgres", "-WithTvtDomain", mode=mode, prior=prior)
    assert result["failure"] is not None
    assert len(pytest_calls(result)) == 2
    assert result["restored"] == prior
    assert pytest_calls(result)[-1]["acceptance"] == "1"


def test_domain_preserves_nine_role_url_requirement(gate):
    result = gate("-WithPostgres", "-WithTvtDomain", missing_role="ASSET_MAINTENANCE")
    assert "all nine role URLs" in result["failure"]
    assert pytest_calls(result) == []
