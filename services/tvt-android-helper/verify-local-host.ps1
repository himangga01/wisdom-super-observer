param(
    [Parameter(Mandatory=$true)][string]$JdkBin,
    [string]$CaptureDirectory = ''
)
$ErrorActionPreference = 'Stop'
$localRoot = $PSScriptRoot
$localBuild = Join-Path $localRoot ('build/local-host-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $localBuild | Out-Null
if ($CaptureDirectory) { New-Item -ItemType Directory -Force -Path $CaptureDirectory | Out-Null }
$localSources = @(
    'src/main/java/com/tvt/network/NatTraveral.java',
    'src/main/java/com/wso/tvt/local/LocalSerialConfig.java',
    'src/main/java/com/wso/tvt/local/LocalSerialDriver.java',
    'src/main/java/com/wso/tvt/local/JniLocalSerialDriver.java',
    'src/main/java/com/wso/tvt/local/LocalSerialTransport.java',
    'tests/LocalSerialTransportTest.java'
) | ForEach-Object { Join-Path $localRoot $_ }
function Invoke-LocalChecked([string]$Label, [string]$Executable, [string[]]$Arguments) {
    $localOut = Join-Path $localBuild "$Label.stdout"
    $localErr = Join-Path $localBuild "$Label.stderr"
    $localStart = [DateTime]::UtcNow.ToString('o')
    # Redirected pipes keep host Java execution hidden; arguments use direct argv, no shell expansion.
    $localInfo = New-Object System.Diagnostics.ProcessStartInfo
    $localInfo.FileName = $Executable
    $localInfo.UseShellExecute = $false
    $localInfo.CreateNoWindow = $true
    $localInfo.RedirectStandardOutput = $true
    $localInfo.RedirectStandardError = $true
    foreach ($localArg in $Arguments) { $localInfo.ArgumentList.Add($localArg) }
    $localProcess = New-Object System.Diagnostics.Process
    $localProcess.StartInfo = $localInfo
    [void]$localProcess.Start()
    $localOutRead = $localProcess.StandardOutput.ReadToEndAsync()
    $localErrRead = $localProcess.StandardError.ReadToEndAsync()
    $localProcess.WaitForExit()
    $localExit = $localProcess.ExitCode
    $localStdout = $localOutRead.GetAwaiter().GetResult()
    $localStderr = $localErrRead.GetAwaiter().GetResult()
    [IO.File]::WriteAllText($localOut, $localStdout)
    [IO.File]::WriteAllText($localErr, $localStderr)
    $localCommand = @{
        argv = @($Executable) + $Arguments; cwd = (Get-Location).Path
        start_utc = $localStart; end_utc = [DateTime]::UtcNow.ToString('o'); exit_code = $localExit
        stdout = $localOut; stderr = $localErr; build_directory = $localBuild
    }
    $localCommand | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $localBuild "$Label.command.json") -Encoding UTF8
    if ($CaptureDirectory) {
        foreach ($localSuffix in @('stdout','stderr','command.json')) {
            Copy-Item -LiteralPath (Join-Path $localBuild "$Label.$localSuffix") -Destination (Join-Path $CaptureDirectory "$Label.$localSuffix")
        }
    }
    Write-Output $localStdout
    if ($localStderr) { Write-Output $localStderr }
    $localProcess.Dispose()
    if ($localExit -ne 0) { throw "$Label failed with exit code $localExit" }
}
Invoke-LocalChecked 'javac' (Join-Path $JdkBin 'javac.exe') (@('--release','8','-Xlint:all,-options','-Werror','-encoding','UTF-8','-d',$localBuild) + $localSources)
Invoke-LocalChecked 'transport' (Join-Path $JdkBin 'java.exe') @('-cp',$localBuild,'com.wso.tvt.local.LocalSerialTransportTest')
Invoke-LocalChecked 'quarantine' (Join-Path $JdkBin 'java.exe') @('-cp',$localBuild,'com.wso.tvt.local.LocalSerialTransportTest','quarantine')
Invoke-LocalChecked 'removal' (Join-Path $JdkBin 'java.exe') @('-cp',$localBuild,'com.wso.tvt.local.LocalSerialTransportTest','removal')
Invoke-LocalChecked 'allocation' (Join-Path $JdkBin 'java.exe') @('-cp',$localBuild,'com.wso.tvt.local.LocalSerialTransportTest','allocation')
Invoke-LocalChecked 'descriptors' (Join-Path $JdkBin 'javap.exe') @('-p','-s','-classpath',$localBuild,'com.tvt.network.NatTraveral')
