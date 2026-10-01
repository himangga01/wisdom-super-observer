param(
    [switch]$WithContainers,
    [switch]$WithBrowser,
    [switch]$WithPostgres,
    [switch]$WithTvtDomain,
    [switch]$WithAuthBrowser,
    [switch]$WithJobBroker
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-Host ('> ' + $Name + ' ' + ($Arguments -join ' '))
    & $Name @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

try {
    if ($WithTvtDomain -and -not $WithPostgres) {
        throw 'TVT domain acceptance requires -WithPostgres.'
    }
    if ($WithJobBroker -and (-not $WithPostgres -or -not $IsLinux -or $env:CI -ne 'true')) {
        throw 'Real job recovery requires the explicit Linux CI PostgreSQL gate.'
    }
    $syncArgs = @('-m', 'uv', 'sync', '--all-packages', '--group', 'dev')
    $uvRun = @('-m', 'uv', 'run')
    if ($env:CI -eq 'true') {
        $syncArgs += '--locked'
        $uvRun += '--locked'
    }
    Invoke-Checked python $syncArgs
    Invoke-Checked pnpm @('install', '--frozen-lockfile')
    $pytestArgs = $uvRun + @(
        'pytest', '-m', 'not live', '--ignore=tests/jobs_recovery',
        '--ignore=tests/integration/test_private_assets.py',
        '--ignore=tests/integration/test_tvt_domain_scope.py',
        '--ignore=tests/integration/test_tvt_domain_credentials.py', '-q'
    )
    if ($WithPostgres) {
        $roles = @(
            'ADMIN', 'APP', 'IDENTITY', 'MIGRATOR', 'SESSION', 'WORKER', 'DISPATCH', 'JOB',
            'ASSET_MAINTENANCE'
        )
        $provided = @($roles | Where-Object {
            -not [string]::IsNullOrWhiteSpace(
                [Environment]::GetEnvironmentVariable("WSO_TEST_${_}_DATABASE_URL")
            )
        })
        if ($provided.Count -eq 0) {
            $loader = Join-Path $root '.superpowers/runtime/postgresql17/env.ps1'
            if (-not (Test-Path -LiteralPath $loader -PathType Leaf)) {
                throw 'Provide all PostgreSQL role URLs or create the local test runtime.'
            }
            . $loader
        } elseif ($provided.Count -ne $roles.Count) {
            throw 'Explicit PostgreSQL configuration requires all nine role URLs.'
        }
        foreach ($role in $roles) {
            $url = [Environment]::GetEnvironmentVariable("WSO_TEST_${role}_DATABASE_URL")
            if ([string]::IsNullOrWhiteSpace($url)) {
                throw "PostgreSQL integration requires the $role role URL."
            }
        }
        $resultDir = Join-Path $root '.superpowers/verification'
        New-Item -ItemType Directory -Force -Path $resultDir | Out-Null
        $resultPath = Join-Path $resultDir 'pytest-postgres.xml'
        $pytestArgs += "--junitxml=$resultPath"
    }
    Invoke-Checked python $pytestArgs
    if ($WithPostgres) {
        [xml]$testResults = Get-Content -LiteralPath $resultPath -Raw
        $skippedIntegration = @($testResults.SelectNodes(
            '//testcase[starts-with(@classname, "tests.integration.") and skipped]'
        ))
        if ($skippedIntegration.Count -gt 0) {
            throw 'A selected PostgreSQL integration test was skipped; its gate is unverified.'
        }
    }
    if ($WithTvtDomain) {
        $domainResultPath = Join-Path $resultDir 'pytest-tvt-domain.xml'
        if (Test-Path -LiteralPath $domainResultPath) {
            Remove-Item -LiteralPath $domainResultPath
        }
        $previousDomainAcceptance = [Environment]::GetEnvironmentVariable(
            'WSO_TEST_W02_DOMAIN_ACCEPTANCE'
        )
        try {
            $env:WSO_TEST_W02_DOMAIN_ACCEPTANCE = '1'
            Invoke-Checked python ($uvRun + @(
                'pytest', 'tests/integration/test_tvt_domain_scope.py',
                'tests/integration/test_tvt_domain_credentials.py', '-q',
                "--junitxml=$domainResultPath"
            ))
            [xml]$domainResults = Get-Content -LiteralPath $domainResultPath -Raw
            $suites = @($domainResults.SelectNodes('//testsuite[not(testsuite)]'))
            $cases = @($domainResults.SelectNodes('//testcase'))
            $selectedCount = 0
            if ($suites.Count -eq 0) {
                throw 'TVT domain JUnit has no test suites; its gate is unverified.'
            }
            foreach ($suite in $suites) {
                foreach ($metric in @('tests', 'failures', 'errors', 'skipped')) {
                    $value = 0
                    if (-not [int]::TryParse($suite.GetAttribute($metric), [ref]$value) -or
                        $value -lt 0) {
                        throw 'TVT domain JUnit has invalid counts; its gate is unverified.'
                    }
                    if ($metric -eq 'tests') {
                        $selectedCount += $value
                    } elseif ($value -ne 0) {
                        throw 'TVT domain JUnit reports failure, error or skip; its gate is unverified.'
                    }
                }
            }
            $scopeCases = @($cases | Where-Object {
                $_.GetAttribute('classname') -eq 'tests.integration.test_tvt_domain_scope'
            })
            $credentialCases = @($cases | Where-Object {
                $_.GetAttribute('classname') -eq 'tests.integration.test_tvt_domain_credentials'
            })
            $unsuccessfulCases = @($domainResults.SelectNodes(
                '//testcase[failure or error or skipped]'
            ))
            if ($selectedCount -ne 42 -or $cases.Count -ne 42 -or
                $scopeCases.Count -ne 3 -or $credentialCases.Count -ne 39 -or
                $unsuccessfulCases.Count -ne 0) {
                throw 'TVT domain acceptance requires exactly 3 scope and 39 credential cases with zero failures, errors or skips.'
            }
        } finally {
            if ($null -eq $previousDomainAcceptance) {
                Remove-Item -LiteralPath Env:WSO_TEST_W02_DOMAIN_ACCEPTANCE
            } else {
                [Environment]::SetEnvironmentVariable(
                    'WSO_TEST_W02_DOMAIN_ACCEPTANCE', $previousDomainAcceptance
                )
            }
        }
    }
    if ($WithJobBroker) {
        $recoveryPath = Join-Path $resultDir 'pytest-jobs-recovery.xml'
        Invoke-Checked python ($uvRun + @(
            'pytest', 'tests/jobs_recovery', '-m', 'jobs_recovery', '-q',
            "--junitxml=$recoveryPath"
        ))
        Invoke-Checked python ($uvRun + @('scripts/check_job_recovery_results.py', $recoveryPath))
    }
    Invoke-Checked python ($uvRun + @('ruff', 'check', 'services', 'packages', 'tests', 'scripts', 'infra/migrations'))
    Invoke-Checked python ($uvRun + @('mypy', 'services/api/src', 'packages/contracts/src', 'packages/core/src'))
    Invoke-Checked pnpm @('-r', 'typecheck')
    Invoke-Checked pnpm @('-r', 'lint')
    Invoke-Checked pnpm @('-r', 'test')
    Invoke-Checked pnpm @('-r', 'build')

    $generated = Join-Path $root 'packages/contracts/generated'
    if (-not (Test-Path -LiteralPath $generated -PathType Container)) {
        throw 'Checked-in contract exports are missing.'
    }
    $expectedExports = @(
        'Asset.json', 'BeginUpload.json', 'Checksum.json', 'DownloadTicket.json',
        'DispatchReference.json', 'EventEnvelope.json', 'ImportJobPayload.json',
        'IncidentSummary.json', 'JobItemView.json', 'JobScope.json', 'JobView.json',
        'Money.json', 'ProductCandidate.json', 'SignedMoney.json',
        'RegistrationJobPayload.json',
        'StoreScope.json', 'TenantScope.json', 'UploadSession.json', 'VariantOption.json',
        'openapi.json'
    )
    $actualExports = @(Get-ChildItem -LiteralPath $generated -File -Recurse |
        ForEach-Object { [IO.Path]::GetRelativePath($generated, $_.FullName) })
    if (@(Compare-Object -ReferenceObject $expectedExports -DifferenceObject $actualExports).Count -ne 0) {
        throw 'Checked-in contract export file set differs from the expected schema set.'
    }
    $before = @(Get-ChildItem -LiteralPath $generated -File -Recurse | ForEach-Object {
        [pscustomobject]@{
            Path = [IO.Path]::GetRelativePath($generated, $_.FullName)
            Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } | Sort-Object Path)
    if ($before.Count -eq 0) {
        throw 'Checked-in contract exports are empty.'
    }
    Invoke-Checked python ($uvRun + @('python', 'scripts/export_contracts.py'))
    $first = @(Get-ChildItem -LiteralPath $generated -File -Recurse | ForEach-Object {
        [pscustomobject]@{
            Path = [IO.Path]::GetRelativePath($generated, $_.FullName)
            Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } | Sort-Object Path)
    if ((ConvertTo-Json -InputObject $before -Depth 3 -Compress) -ne
        (ConvertTo-Json -InputObject $first -Depth 3 -Compress)) {
        throw 'Checked-in contract exports are stale; regenerate and review them.'
    }
    Invoke-Checked python ($uvRun + @('python', 'scripts/export_contracts.py'))
    $second = @(Get-ChildItem -LiteralPath $generated -File -Recurse | ForEach-Object {
        [pscustomobject]@{
            Path = [IO.Path]::GetRelativePath($generated, $_.FullName)
            Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
        }
    } | Sort-Object Path)
    if ((ConvertTo-Json -InputObject $first -Depth 3 -Compress) -ne
        (ConvertTo-Json -InputObject $second -Depth 3 -Compress)) {
        throw 'Contract export changed on its second run.'
    }
    Invoke-Checked python ($uvRun + @('python', 'scripts/check_tvt_evidence.py', 'docs/integrations/tvt-parity-ledger.md'))

    if ($WithBrowser) {
        Invoke-Checked pnpm @('exec', 'playwright', 'test', 'tests/tvt_parity/e2e')
    } else {
        Write-Host 'Browser preflight was not selected; platform gates are unverified.'
    }

    if ($WithAuthBrowser) {
        Invoke-Checked pnpm @('exec', 'playwright', 'test', '--config', 'playwright.auth.config.ts')
    } else {
        Write-Host 'HTTPS authentication browser checks were not selected.'
    }

    if ($WithContainers) {
        Invoke-Checked docker @('compose', '-f', 'infra/compose.yaml', '--profile', 'test', 'config', '--quiet')
        Invoke-Checked docker @('compose', '-f', 'infra/compose.yaml', '--profile', 'test', 'up', '-d', '--wait')
        Write-Host 'Container startup passed. Broker and S3 capability smoke remain separate gates.'
    } else {
        Write-Host 'Container checks were not selected; integration backends are unverified.'
    }

    Write-Host 'Selected implementation checks passed.'
} finally {
    Pop-Location
}
