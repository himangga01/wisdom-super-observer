# Private CLI build. Requires PowerShell 7; never installs, launches or invokes JNI.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 is required' }
$helper = [System.IO.Path]::GetFullPath($PSScriptRoot)
$repo = [System.IO.Path]::GetFullPath((Join-Path $helper '../..'))
$jdk = 'C:/Android/tools/jdk-21.0.12.1+1'
$tools = 'C:/Android/build-tools/36.0.0'
$androidJar = 'C:/Android/platforms/android-36/android.jar'
$java = Join-Path $jdk 'bin/java.exe'
$javac = Join-Path $jdk 'bin/javac.exe'
$keytool = Join-Path $jdk 'bin/keytool.exe'
$aapt = Join-Path $tools 'aapt2.exe'
$align = Join-Path $tools 'zipalign.exe'
$d8 = Join-Path $tools 'lib/d8.jar'
$signer = Join-Path $tools 'lib/apksigner.jar'
foreach ($path in @($java, $javac, $keytool, $aapt, $align, $d8, $signer, $androidJar)) {
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required local tool missing: $path" }
}
function Assert-Identity([string]$Path, [long]$Bytes, [string]$Sha256) {
    $file = Get-Item -LiteralPath $Path
    if ($file.PSIsContainer -or $file.Length -ne $Bytes -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256) {
        throw "Accepted identity mismatch: $Path"
    }
}
$receiptPath = Join-Path $repo '.superpowers/sdd/2026-09-27-superlive-plus-web-parity-implementation-plan/W04-android-helper-fix2-reviewed-root-receipt.json'
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
if ($receipt.status -cne 'ACCEPTED_FIX2_SCOPED_HELPER_REVIEW' -or @($receipt.files.PSObject.Properties).Count -ne 20) {
    throw 'Approved 20-file helper receipt required'
}
foreach ($entry in $receipt.files.PSObject.Properties) {
    Assert-Identity (Join-Path $repo $entry.Name) $entry.Value.bytes $entry.Value.sha256
}
$native = @(
    @{ Abi = 'arm64-v8a'; Bytes = 3920784; Sha256 = 'c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717' },
    @{ Abi = 'armeabi-v7a'; Bytes = 3018084; Sha256 = '17d44c46654752f761d8117989c0101c7662fc494a8900ca2b307de1b234f23f' }
)
foreach ($entry in $native) {
    Assert-Identity (Join-Path $helper "build/native/$($entry.Abi)/libNetClientProtocal.so") $entry.Bytes $entry.Sha256
}
$manifest = Join-Path $helper 'android/AndroidManifest.xml'
$activity = Join-Path $helper 'android/src/com/wso/tvt/probe/LoadProbeActivity.java'
$inventory = Join-Path $helper 'tests/apk-descriptors.txt'
[xml]$manifestXml = Get-Content -Raw -LiteralPath $manifest
$ns = 'http://schemas.android.com/apk/res/android'
if ($manifestXml.manifest.package -cne 'com.wso.tvt.loadprobe' -or
    $manifestXml.SelectNodes('/manifest/uses-permission').Count -ne 0 -or
    $manifestXml.SelectNodes('/manifest/application/activity').Count -ne 1 -or
    $manifestXml.manifest.'uses-sdk'.GetAttribute('minSdkVersion', $ns) -cne '26' -or
    $manifestXml.manifest.'uses-sdk'.GetAttribute('targetSdkVersion', $ns) -cne '36' -or
    $manifestXml.manifest.application.activity.GetAttribute('name', $ns) -cne 'com.wso.tvt.probe.LoadProbeActivity' -or
    $manifestXml.manifest.application.activity.GetAttribute('exported', $ns) -cne 'true') {
    throw 'Fixed diagnostic manifest requirements failed'
}
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $helper 'build'))
$owned = [System.IO.Path]::GetFullPath((Join-Path $buildRoot ('load-probe-' + [guid]::NewGuid().ToString('N'))))
if (!$owned.StartsWith($buildRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $owned)) { throw 'Unique owned build path validation failed' }
New-Item -ItemType Directory -Path $owned | Out-Null
$classes = Join-Path $owned 'classes'
$dex = Join-Path $owned 'dex'
$assets = Join-Path $owned 'assets'
$private = Join-Path $owned 'private'
$capture = Join-Path $owned 'captures'
foreach ($path in @($classes, $dex, $assets, $private, $capture)) { New-Item -ItemType Directory -Path $path | Out-Null }
Copy-Item -LiteralPath $inventory -Destination (Join-Path $assets 'apk-descriptors.txt')
function Invoke-LocalTool([string]$Name, [string]$Exe, [string[]]$ToolArgs, [hashtable]$ProcessEnvironment = @{}) {
    $start = [System.Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Exe
    $start.WorkingDirectory = $owned
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($argument in $ToolArgs) { $start.ArgumentList.Add($argument) }
    foreach ($key in $ProcessEnvironment.Keys) { $start.Environment[$key] = $ProcessEnvironment[$key] }
    $command = [ordered]@{ executable = $Exe; arguments = $ToolArgs; workingDirectory = $owned; environmentNames = @($ProcessEnvironment.Keys) }
    $command | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $capture "$Name-command.json") -Encoding utf8
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $start
    try {
        if (!$process.Start()) { throw "Unable to start $Name" }
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $text = $stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        $text | Set-Content -LiteralPath (Join-Path $capture "$Name.log") -Encoding utf8
        if ($process.ExitCode -ne 0) { throw "$Name failed with exit $($process.ExitCode); inspect retained capture" }
        Write-Host "$Name PASS"
        return $text
    } finally { $process.Dispose() }
}
$null = Invoke-LocalTool 'java-version' $java @('-version')
$null = Invoke-LocalTool 'javac-version' $javac @('-version')
$null = Invoke-LocalTool 'aapt2-version' $aapt @('version')
$null = Invoke-LocalTool 'd8-version' $java @('-cp', $d8, 'com.android.tools.r8.D8', '--version')
$null = Invoke-LocalTool 'apksigner-version' $java @('-jar', $signer, 'version')
$sources = @(
    (Join-Path $helper 'src/main/java/com/tvt/network/NetClientProtocal.java'),
    (Join-Path $helper 'src/main/java/com/wso/tvt/CallbackKind.java'),
    (Join-Path $helper 'src/main/java/com/wso/tvt/CallbackSink.java'), $activity
)
$null = Invoke-LocalTool 'javac' $javac (@('--release', '8', '-encoding', 'UTF-8', '-classpath', $androidJar, '-d', $classes) + $sources)
$classFiles = @(Get-ChildItem -LiteralPath $classes -Recurse -File -Filter '*.class' | Sort-Object FullName | ForEach-Object FullName)
$null = Invoke-LocalTool 'd8' $java (@('-cp', $d8, 'com.android.tools.r8.D8', '--min-api', '26', '--lib', $androidJar, '--output', $dex) + $classFiles)
$unsigned = Join-Path $owned 'load-probe-unsigned.apk'
$aligned = Join-Path $owned 'load-probe-aligned.apk'
$apk = Join-Path $owned 'wso-tvt-load-probe.apk'
# Native Windows tools need ASCII relative filenames within the Unicode worktree.
$null = Invoke-LocalTool 'aapt2-link' $aapt @('link', '-o', 'load-probe-unsigned.apk', '-I', $androidJar, '--manifest', '../../android/AndroidManifest.xml', '-A', 'assets')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::Open($unsigned, [System.IO.Compression.ZipArchiveMode]::Update)
try {
    $null = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, (Join-Path $dex 'classes.dex'), 'classes.dex')
    foreach ($entry in $native) {
        $null = [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,
            (Join-Path $helper "build/native/$($entry.Abi)/libNetClientProtocal.so"), "lib/$($entry.Abi)/libNetClientProtocal.so")
    }
} finally { $archive.Dispose() }
$null = Invoke-LocalTool 'zipalign' $align @('-P', '16', '4', 'load-probe-unsigned.apk', 'load-probe-aligned.apk')
$key = Join-Path $private 'ephemeral-development.p12'
$passwordBytes = [byte[]]::new(32)
[System.Security.Cryptography.RandomNumberGenerator]::Fill($passwordBytes)
$signingPassword = [Convert]::ToBase64String($passwordBytes)
[Array]::Clear($passwordBytes, 0, $passwordBytes.Length)
try {
    $signingEnv = @{ WSO_LOAD_PROBE_SIGN_PASSWORD = $signingPassword }
    $null = Invoke-LocalTool 'keytool-development' $keytool @('-genkeypair', '-keystore', $key,
        '-storetype', 'PKCS12', '-alias', 'load-probe-development', '-keyalg', 'RSA', '-keysize', '2048',
        '-validity', '7', '-dname', 'CN=WSO Load Probe DEVELOPMENT', '-storepass:env', 'WSO_LOAD_PROBE_SIGN_PASSWORD',
        '-keypass:env', 'WSO_LOAD_PROBE_SIGN_PASSWORD', '-noprompt') $signingEnv
    $null = Invoke-LocalTool 'apksigner-sign' $java @('-jar', $signer, 'sign', '--ks', $key,
        '--ks-key-alias', 'load-probe-development', '--ks-pass', 'env:WSO_LOAD_PROBE_SIGN_PASSWORD',
        '--key-pass', 'env:WSO_LOAD_PROBE_SIGN_PASSWORD', '--out', $apk, $aligned) $signingEnv
} finally {
    $signingPassword = $null
    if (Get-Variable -Name signingEnv -ErrorAction SilentlyContinue) { $signingEnv.Clear() }
    if (Test-Path -LiteralPath $key -PathType Leaf) { Remove-Item -LiteralPath $key }
}
$null = Invoke-LocalTool 'signature-verify' $java @('-jar', $signer, 'verify', '--verbose', '--print-certs', $apk)
$null = Invoke-LocalTool 'alignment-verify' $align @('-c', '-P', '16', '-v', '4', 'wso-tvt-load-probe.apk')
$badging = Invoke-LocalTool 'manifest-badging' $aapt @('dump', 'badging', 'wso-tvt-load-probe.apk')
$permissions = Invoke-LocalTool 'manifest-permissions' $aapt @('dump', 'permissions', 'wso-tvt-load-probe.apk')
$null = Invoke-LocalTool 'manifest-tree' $aapt @('dump', 'xmltree', 'wso-tvt-load-probe.apk', '--file', 'AndroidManifest.xml')
if ($badging -notmatch "package: name='com.wso.tvt.loadprobe'" -or $badging -notmatch "sdkVersion:'26'" -or
    $badging -notmatch "targetSdkVersion:'36'" -or $permissions -match 'uses-permission') { throw 'Packaged manifest verification failed' }
$archive = [System.IO.Compression.ZipFile]::OpenRead($apk)
try {
    $expectedEntries = @(
        @{ Path = 'assets/apk-descriptors.txt'; Sha256 = '296b120477dfa7cbed05d656b6feaba4be60d9ca4526d62130315f19a3415119'; Bytes = 2481 }
    ) + @($native | ForEach-Object { @{ Path = "lib/$($_.Abi)/libNetClientProtocal.so"; Sha256 = $_.Sha256; Bytes = $_.Bytes } })
    $actualNative = @($archive.Entries | Where-Object { $_.FullName.StartsWith('lib/') })
    if ($actualNative.Count -ne 2) { throw 'Expected exactly two native ZIP entries' }
    foreach ($entry in $expectedEntries) {
        $matches = @($archive.Entries | Where-Object { $_.FullName -ceq $entry.Path })
        if ($matches.Count -ne 1 -or $matches[0].Length -ne $entry.Bytes) { throw 'Packaged entry uniqueness/size failed' }
        $stream = $matches[0].Open()
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try { $digest = [Convert]::ToHexString($hasher.ComputeHash($stream)).ToLowerInvariant() }
        finally { $stream.Dispose(); $hasher.Dispose() }
        if ($digest -cne $entry.Sha256) { throw 'Packaged accepted entry digest mismatch' }
    }
    $entryNames = @($archive.Entries | ForEach-Object FullName)
} finally { $archive.Dispose() }
foreach ($entry in $receipt.files.PSObject.Properties) {
    Assert-Identity (Join-Path $repo $entry.Name) $entry.Value.bytes $entry.Value.sha256
}
$sourceHashes = [ordered]@{}
foreach ($path in @($manifest, $activity, $PSCommandPath, (Join-Path $helper 'android/README.md'))) {
    $sourceHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
$result = [ordered]@{
    status = 'BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED'; package = 'com.wso.tvt.loadprobe'; apk = $apk
    apkSha256 = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
    apkBytes = (Get-Item -LiteralPath $apk).Length; captures = $capture; sourceHashes = $sourceHashes
    nativeEntries = $native; packagedEntries = $entryNames; approvedFilesVerified = 20
    developmentKeyDeleted = !(Test-Path -LiteralPath $key); deviceExecution = 'NOT_EXECUTED'
    limits = 'Load/reflection only; no JNI binding invocation, network, context, transport or feature acceptance.'
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $owned 'build-result.json') -Encoding utf8
$result | ConvertTo-Json -Depth 6
