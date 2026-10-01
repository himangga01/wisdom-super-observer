param(
    [Parameter(Mandatory=$true)][string]$JdkBin,
    [string]$CaptureDirectory = ''
)
$ErrorActionPreference = 'Stop'
$helperRoot = $PSScriptRoot
$compiler = Join-Path $JdkBin 'javac.exe'
$runtime = Join-Path $JdkBin 'java.exe'
$inspector = Join-Path $JdkBin 'javap.exe'
$classDirectory = Join-Path $helperRoot 'build/classes'
New-Item -ItemType Directory -Force -Path $classDirectory | Out-Null
if ($CaptureDirectory) { New-Item -ItemType Directory -Force -Path $CaptureDirectory | Out-Null }
function Invoke-Checked([string]$Label, [string]$Executable, [string[]]$Arguments) {
    $lines = @(& $Executable @Arguments 2>&1)
    $result = $LASTEXITCODE
    if ($CaptureDirectory) { $lines | Set-Content -LiteralPath (Join-Path $CaptureDirectory "$Label.log") -Encoding UTF8 }
    $lines | ForEach-Object { Write-Output $_ }
    if ($result -ne 0) { throw "$Label failed with exit code $result" }
}
$sources = @(Get-ChildItem -LiteralPath (Join-Path $helperRoot 'src/main/java') -Recurse -Filter '*.java' | ForEach-Object FullName)
$sources += @(Get-ChildItem -LiteralPath (Join-Path $helperRoot 'tests') -Recurse -Filter '*.java' | ForEach-Object FullName)
Invoke-Checked 'javac' $compiler (@('--release', '8', '-Xlint:all,-options', '-Werror', '-d', $classDirectory) + $sources)
Invoke-Checked 'startup' $runtime @('-cp', $classDirectory, 'RedLifecycleTest')
Invoke-Checked 'lifecycle' $runtime @('-cp', $classDirectory, 'HelperTest')
Invoke-Checked 'configuration' $runtime @('-cp', $classDirectory, 'com.wso.tvt.ConfigTest')
Invoke-Checked 'descriptors' $runtime @('-cp', $classDirectory, 'DescriptorTest', (Join-Path $helperRoot 'tests/apk-descriptors.txt'))
foreach ($stage in @(@('close', '1'), @('disconnect', '2'), @('stop', '4'), @('quit', '8'))) {
    Invoke-Checked "cleanup-$($stage[0])" $runtime @('-cp', $classDirectory, 'CleanupFailureTest', $stage[0], $stage[1])
}
Invoke-Checked 'cancel-failure' $runtime @('-cp', $classDirectory, 'CleanupFailureTest', 'close', '1', 'cancel')
Invoke-Checked 'javap' $inspector @('-p', '-s', '-classpath', $classDirectory, 'com.tvt.network.NetClientProtocal')
