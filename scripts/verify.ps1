param(
    [switch]$WithContainers,
    [switch]$WithBrowser
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
    Invoke-Checked python @('-m', 'uv', 'sync', '--all-packages', '--group', 'dev')
    Invoke-Checked pnpm @('install', '--frozen-lockfile')
    Invoke-Checked python @('-m', 'uv', 'run', 'pytest', '-m', 'not live', '-q')
    Invoke-Checked python @('-m', 'uv', 'run', 'ruff', 'check', 'services', 'packages', 'tests', 'scripts', 'infra/migrations')
    Invoke-Checked python @('-m', 'uv', 'run', 'mypy', 'services/api/src', 'packages/contracts/src', 'packages/core/src')
    Invoke-Checked pnpm @('-r', 'typecheck')
    Invoke-Checked pnpm @('-r', 'lint')
    Invoke-Checked pnpm @('-r', 'test')
    Invoke-Checked pnpm @('-r', 'build')

    $generated = Join-Path $root 'packages/contracts/generated'
    if (-not (Test-Path -LiteralPath $generated -PathType Container)) {
        throw 'Checked-in contract exports are missing.'
    }
    $expectedExports = @(
        'EventEnvelope.json', 'IncidentSummary.json', 'JobScope.json',
        'Money.json', 'ProductCandidate.json', 'SignedMoney.json',
        'StoreScope.json', 'TenantScope.json', 'VariantOption.json', 'openapi.json'
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
    Invoke-Checked python @('-m', 'uv', 'run', 'python', 'scripts/export_contracts.py')
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
    Invoke-Checked python @('-m', 'uv', 'run', 'python', 'scripts/export_contracts.py')
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
    Invoke-Checked python @('-m', 'uv', 'run', 'python', 'scripts/check_tvt_evidence.py', 'docs/integrations/tvt-parity-ledger.md')

    if ($WithBrowser) {
        Invoke-Checked pnpm @('exec', 'playwright', 'test', 'tests/tvt_parity/e2e')
    } else {
        Write-Host 'Browser preflight was not selected; platform gates are unverified.'
    }

    if ($WithContainers) {
        Invoke-Checked docker @('compose', '-f', 'infra/compose.yaml', '--profile', 'test', 'config', '--quiet')
        Invoke-Checked docker @('compose', '-f', 'infra/compose.yaml', '--profile', 'test', 'up', '-d', '--wait')
        Write-Host 'Container startup passed. Broker and S3 capability smoke remain separate gates.'
    } else {
        Write-Host 'Container checks were not selected; integration backends are unverified.'
    }

    Write-Host 'Implemented offline checks passed.'
} finally {
    Pop-Location
}
