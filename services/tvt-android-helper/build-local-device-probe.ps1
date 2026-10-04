# PowerShell 7, local compile/package only. Root supplies independent acceptance.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$ApprovedApk,
    [Parameter(Mandatory)][string]$TransportReceipt,
    [Parameter(Mandatory)][string]$BootstrapReceipt,
    [Parameter(Mandatory)][string]$DiscoveryReceipt,
    [string]$JdkRoot = 'C:/Android/tools/jdk-21.0.12.1+1',
    [string]$BuildTools = 'C:/Android/build-tools/36.0.0',
    [string]$AndroidJar = 'C:/Android/platforms/android-36/android.jar'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$script:RetainedBuildChildren = @{}
trap {
    if ($script:RetainedBuildChildren.Count) {
        [Console]::Error.WriteLine('Build child cleanup uncertain; owner remains alive with original handles until process and pipes finish.')
        # The build stops here. Passive custody never retries kill, targets a PID,
        # or disposes an unconfirmed process/pipe. Root supervises this owner.
        while ($script:RetainedBuildChildren.Count) {
            foreach ($nameKey in @($script:RetainedBuildChildren.Keys)) {
                $entry = $script:RetainedBuildChildren[$nameKey]
                $outDone = !$entry.stdout -or $entry.stdout.task.IsCompleted
                $errDone = !$entry.stderr -or $entry.stderr.task.IsCompleted
                if ($entry.process.HasExited -and $outDone -and $errDone) {
                    $entry.record.ownerCompletionObserved = [datetime]::UtcNow.ToString('o')
                    $entry.record.ownerExit = $entry.process.ExitCode
                    $entry.record.ownerReaped = $true
                    $entry.record.ownerPipesCompleted = $true
                    $entry.record.ownerCaptureComplete = $entry.stdout -and $entry.stderr -and !$entry.stdout.Failed -and !$entry.stderr.Failed
                    $entry.record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $entry.capture "$nameKey-ownership.json") -Encoding utf8
                    if ($entry.stdout) { [IO.File]::WriteAllBytes((Join-Path $entry.capture "$nameKey.stdout"),$entry.stdout.Snapshot()) }
                    else { $entry.process.StandardOutput.Dispose() }
                    if ($entry.stderr) { [IO.File]::WriteAllBytes((Join-Path $entry.capture "$nameKey.stderr"),$entry.stderr.Snapshot()) }
                    else { $entry.process.StandardError.Dispose() }
                    $entry.process.Dispose()
                    $script:RetainedBuildChildren.Remove($nameKey)
                }
            }
            if ($script:RetainedBuildChildren.Count) { Start-Sleep -Milliseconds 100 }
        }
    }
    break
}
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell 7 required' }
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$transportPaths = @(
    'services/tvt-android-helper/src/main/java/com/tvt/network/NatTraveral.java',
    'services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialConfig.java',
    'services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialDriver.java',
    'services/tvt-android-helper/src/main/java/com/wso/tvt/local/JniLocalSerialDriver.java',
    'services/tvt-android-helper/src/main/java/com/wso/tvt/local/LocalSerialTransport.java',
    'services/tvt-android-helper/tests/LocalSerialTransportTest.java',
    'services/tvt-android-helper/verify-local-host.ps1',
    'docs/integrations/tvt-local-serial-transport.md'
)
function Assert-Identity([string]$Path, [long]$Bytes, [string]$Sha256) {
    $file = Get-Item -LiteralPath $Path
    if ($file.PSIsContainer -or $file.LinkType -or $file.Length -ne $Bytes -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha256) {
        throw 'Accepted file identity mismatch'
    }
}
function Read-Receipt {
    if (![IO.Path]::IsPathFullyQualified($TransportReceipt) -or
        !(Test-Path -LiteralPath $TransportReceipt -PathType Leaf) -or
        (Get-Item -LiteralPath $TransportReceipt).Length -gt 65536) { throw 'Root-reviewed transport receipt required' }
    $value = Get-Content -Raw -LiteralPath $TransportReceipt | ConvertFrom-Json
    if ($value.status -cne 'ACCEPTED_LOCAL_SERIAL_TRANSPORT_ROOT_REVIEW' -or
        @($value.files.PSObject.Properties).Count -ne 8 -or
        (Compare-Object ($transportPaths | Sort-Object) (@($value.files.PSObject.Properties.Name) | Sort-Object))) {
        throw 'Root-reviewed transport receipt required'
    }
    foreach ($relative in $transportPaths) {
        $identity = $value.files.$relative
        if ($identity.sha256 -cnotmatch '^[a-f0-9]{64}$' -or $identity.bytes -le 0) { throw 'Root-reviewed transport receipt required' }
        Assert-Identity (Join-Path $repo $relative) $identity.bytes $identity.sha256
    }
    return $value
}
$bootstrapPaths=@('packages/core/src/wso_core/tvt/local_bootstrap.py','tests/tvt_parity/test_local_bootstrap.py','docs/integrations/tvt-local-bootstrap-profile.md')
$discoveryPaths=@(
 'services/tvt-android-helper/android-local-device/AndroidManifest.xml',
 'services/tvt-android-helper/android-local-device/src/com/wso/tvt/local/LocalDeviceProbeActivity.java',
 'services/tvt-android-helper/build-local-device-probe.ps1',
 'services/tvt-bridge/src/wso_tvt_bridge/windows_local_device.py',
 'tests/contract/test_windows_local_device.py',
 'docs/integrations/tvt-windows-local-device.md')
function Read-ExactReceipt([string]$Path,[string]$Status,[string[]]$Expected) {
 if (![IO.Path]::IsPathFullyQualified($Path) -or !(Test-Path -LiteralPath $Path -PathType Leaf) -or
     (Get-Item -LiteralPath $Path).Length -gt 65536 -or (Get-Item -LiteralPath $Path).LinkType) { throw 'Root-reviewed exact source receipt required' }
 $v=Get-Content -Raw -LiteralPath $Path | ConvertFrom-Json
 if($v.status -cne $Status -or @($v.files.PSObject.Properties).Count -ne $Expected.Count -or
    (Compare-Object ($Expected|Sort-Object) (@($v.files.PSObject.Properties.Name)|Sort-Object))) { throw 'Root-reviewed exact source receipt required' }
 foreach($relative in $Expected) {
   $id=$v.files.$relative
   if($id.bytes -le 0 -or $id.sha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'Root-reviewed exact source receipt required' }
   Assert-Identity (Join-Path $repo $relative) $id.bytes $id.sha256
 }
 return $v
}
$bootstrap=Read-ExactReceipt $BootstrapReceipt 'SOURCE_ACCEPTED_UNPUBLISHED' $bootstrapPaths
$discovery=Read-ExactReceipt $DiscoveryReceipt 'ACCEPTED_WINDOWS_LOCAL_DEVICE_ROOT_REVIEW' $discoveryPaths
$bootstrapHash=(Get-FileHash -LiteralPath $BootstrapReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
$discoveryHash=(Get-FileHash -LiteralPath $DiscoveryReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
$receipt = Read-Receipt
foreach($group in @('transport','bootstrap')) {
 $expectedMap=if($group -ceq 'transport'){$receipt.files}else{$bootstrap.files}
 $actualMap=$discovery.dependencies.$group
 if(!$actualMap -or @($actualMap.PSObject.Properties).Count -ne @($expectedMap.PSObject.Properties).Count -or
    (Compare-Object (@($expectedMap.PSObject.Properties.Name)|Sort-Object) (@($actualMap.PSObject.Properties.Name)|Sort-Object))) { throw 'Explicit independently reviewed dependency maps required' }
 foreach($name in $expectedMap.PSObject.Properties.Name) {
  if($actualMap.$name.bytes -ne $expectedMap.$name.bytes -or $actualMap.$name.sha256 -cne $expectedMap.$name.sha256) { throw 'Reviewed dependency receipt mismatch' }
 }
}
$receiptHash = (Get-FileHash -LiteralPath $TransportReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
if (![IO.Path]::IsPathFullyQualified($ApprovedApk)) { throw 'Explicit approved private APK path required' }
Assert-Identity $ApprovedApk 170064551 'f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281'
$java = Join-Path $JdkRoot 'bin/java.exe'
$javac = Join-Path $JdkRoot 'bin/javac.exe'
$keytool = Join-Path $JdkRoot 'bin/keytool.exe'
$aapt = Join-Path $BuildTools 'aapt2.exe'
$align = Join-Path $BuildTools 'zipalign.exe'
$d8 = Join-Path $BuildTools 'lib/d8.jar'
$signer = Join-Path $BuildTools 'lib/apksigner.jar'
foreach ($path in @($java,$javac,$keytool,$aapt,$align,$d8,$signer,$AndroidJar)) {
    if (![IO.Path]::IsPathFullyQualified($path) -or !(Test-Path -LiteralPath $path -PathType Leaf)) { throw 'Existing explicit local tools required' }
}
$native = @(
    @{path='lib/arm64-v8a/libNatTraveral.so'; bytes=4199472; sha256='b2fd23fb466410c688938581cb2c2ab1e63e8fded084cf62e55ecf4f3f2c32eb'},
    @{path='lib/armeabi-v7a/libNatTraveral.so'; bytes=3198404; sha256='89e14fb830b9c86349a8b1a3e00622ba882bf0232cb58acb2bf61fb5535fd3f6'}
)
$manifest = Join-Path $PSScriptRoot 'android-local-device/AndroidManifest.xml'
$activity = Join-Path $PSScriptRoot 'android-local-device/src/com/wso/tvt/local/LocalDeviceProbeActivity.java'
[xml]$xml = Get-Content -Raw -LiteralPath $manifest
$ns = 'http://schemas.android.com/apk/res/android'
if ($xml.manifest.package -cne 'com.wso.tvt.localdevice' -or
    $xml.SelectNodes('/manifest/uses-permission').Count -ne 2 -or
    (Compare-Object @('android.permission.INTERNET','android.permission.ACCESS_NETWORK_STATE') @($xml.SelectNodes('/manifest/uses-permission') | ForEach-Object { $_.GetAttribute('name',$ns) })) -or
    $xml.SelectNodes('/manifest/application/*').Count -ne 1 -or
    $xml.SelectNodes('/manifest/application/activity').Count -ne 1 -or
    $xml.SelectNodes('/manifest/application/activity/*').Count -ne 0 -or
    $xml.manifest.'uses-sdk'.GetAttribute('minSdkVersion',$ns) -cne '23' -or
    $xml.manifest.'uses-sdk'.GetAttribute('targetSdkVersion',$ns) -cne '36' -or
    $xml.manifest.application.GetAttribute('debuggable',$ns) -cne 'true' -or
    $xml.manifest.application.activity.GetAttribute('name',$ns) -cne 'com.wso.tvt.local.LocalDeviceProbeActivity' -or
    $xml.manifest.application.activity.GetAttribute('exported',$ns) -cne 'true') { throw 'Fixed private discovery manifest required' }
$buildRoot = [IO.Path]::GetFullPath((Join-Path $repo '.superpowers/runtime/windows-local-device-probe'))
$owned = [IO.Path]::GetFullPath((Join-Path $buildRoot ('build-' + [guid]::NewGuid().ToString('N'))))
if (!$owned.StartsWith($buildRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $owned)) { throw 'Unique owned build directory required' }
foreach ($relativeParent in @('.superpowers','.superpowers/runtime','.superpowers/runtime/windows-local-device-probe')) {
    $parent = Join-Path $repo $relativeParent
    if ((Test-Path -LiteralPath $parent) -and (Get-Item -LiteralPath $parent).LinkType) { throw 'Owned build ancestors cannot be links' }
}
New-Item -ItemType Directory -Path $owned | Out-Null
foreach ($name in @('input','classes','dex','private','captures')) { New-Item -ItemType Directory -Path (Join-Path $owned $name) | Out-Null }
$capture = Join-Path $owned 'captures'
$sourceHashes = [ordered]@{}
$sources = @()
foreach ($relative in $transportPaths[0..4]) {
    $source = Join-Path $repo $relative
    $copy = Join-Path $owned ('input/' + [IO.Path]::GetFileName($relative))
    Copy-Item -LiteralPath $source -Destination $copy
    Assert-Identity $copy $receipt.files.$relative.bytes $receipt.files.$relative.sha256
    $sources += $copy
    $sourceHashes[$relative] = $receipt.files.$relative.sha256
}
foreach ($path in @($activity,$manifest,$PSCommandPath)) { $sourceHashes[$path] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
Copy-Item -LiteralPath $activity -Destination (Join-Path $owned 'input/LocalDeviceProbeActivity.java')
Copy-Item -LiteralPath $manifest -Destination (Join-Path $owned 'input/AndroidManifest.xml')
foreach ($pair in @(@{source=$activity;copy=(Join-Path $owned 'input/LocalDeviceProbeActivity.java')},@{source=$manifest;copy=(Join-Path $owned 'input/AndroidManifest.xml')})) {
    if ((Get-FileHash -LiteralPath $pair.copy -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sourceHashes[$pair.source]) { throw 'Probe input snapshot differs from source' }
}
$sources += (Join-Path $owned 'input/LocalDeviceProbeActivity.java')
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Assert-ZipInventory($Archive, [switch]$Packaged) {
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    if ($Archive.Entries.Count -gt 20000) { throw 'ZIP entry count bound exceeded' }
    foreach ($entry in $Archive.Entries) {
        if (!$names.Add($entry.FullName)) { throw 'Duplicate ZIP entry rejected' }
    }
    if ($Packaged -and @($Archive.Entries | Where-Object { $_.FullName.StartsWith('lib/') }).Count -ne 2) { throw 'Exact native APK inventory required' }
    foreach ($expected in $native) {
        $entry = $Archive.GetEntry($expected.path)
        if (!$entry -or $entry.Length -ne $expected.bytes) { throw 'Native entry exact size required' }
        $stream = $entry.Open(); $hash = [Security.Cryptography.SHA256]::Create()
        try { $digest = [Convert]::ToHexString($hash.ComputeHash($stream)).ToLowerInvariant() }
        finally { $stream.Dispose(); $hash.Dispose() }
        if ($digest -cne $expected.sha256) { throw 'Native entry digest mismatch' }
    }
}
$archive = [IO.Compression.ZipFile]::OpenRead($ApprovedApk)
try {
    Assert-ZipInventory $archive
    foreach ($expected in $native) {
        $destination = Join-Path $owned $expected.path
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
        # Literal allowlist only, no ExtractToDirectory or APK-controlled destination.
        [IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry($expected.path),$destination,$false)
        Assert-Identity $destination $expected.bytes $expected.sha256
    }
} finally { $archive.Dispose() }
function Invoke-Tool([string]$Name,[string]$Exe,[string[]]$ToolArgs,[hashtable]$ChildEnvironment=@{},
    [int]$TimeoutMilliseconds=180000,[int]$ReapMilliseconds=5000,[int]$PipeMilliseconds=2000) {
    if (!(Get-Variable -Name RetainedBuildChildren -Scope Script -ErrorAction SilentlyContinue)) { $script:RetainedBuildChildren = @{} }
    if ($script:RetainedBuildChildren.Count -or $TimeoutMilliseconds -le 0 -or $TimeoutMilliseconds -gt 180000 -or
        $ReapMilliseconds -lt 0 -or $ReapMilliseconds -gt 5000 -or $PipeMilliseconds -lt 0 -or $PipeMilliseconds -gt 2000) {
        throw 'Retained child ownership or invalid local deadlines prevent next tool'
    }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName=$Exe; $start.WorkingDirectory=$owned; $start.UseShellExecute=$false
    $start.CreateNoWindow=$true; $start.RedirectStandardOutput=$true; $start.RedirectStandardError=$true
    foreach ($argument in $ToolArgs) { $start.ArgumentList.Add($argument) }
    foreach ($nameKey in $ChildEnvironment.Keys) { $start.Environment[$nameKey]=$ChildEnvironment[$nameKey] }
    $record = [ordered]@{executable=$Exe;arguments=$ToolArgs;cwd=$owned;environmentNames=@($ChildEnvironment.Keys)
        started=[datetime]::UtcNow.ToString('o');ended=$null;exit=$null;startedChild=$false;pid=$null;ownerPid=$PID
        timedOut=$false;killAttempted=$false;killFailed=$false;reaped=$false;pipesCompleted=$false
        captureComplete=$false;captureTruncated=$false;ownershipRetained=$false;failure='none'
        timeoutMilliseconds=$TimeoutMilliseconds;reapMilliseconds=$ReapMilliseconds;pipeMilliseconds=$PipeMilliseconds;captureByteLimit=65536;stdoutBytes=0;stderrBytes=0}
    $process=[Diagnostics.Process]::new(); $process.StartInfo=$start
    $stdout=$null; $stderr=$null; $outBytes=[byte[]]::new(0); $errBytes=[byte[]]::new(0)
    try {
        if (!('WsoLocalNativeProbeBoundedPipeV1' -as [type])) {
            Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Threading.Tasks;
public sealed class WsoLocalNativeProbeBoundedPipeV1 {
    private readonly object gate = new object();
    private readonly MemoryStream retained = new MemoryStream();
    private bool failed, truncated;
    public Task task { get; private set; }
    public bool Failed { get { lock(gate) return failed; } }
    public bool Truncated { get { lock(gate) return truncated; } }
    public byte[] Snapshot() { lock(gate) return retained.ToArray(); }
    public WsoLocalNativeProbeBoundedPipeV1(Stream pipe) {
        task = Task.Run(async () => {
            byte[] chunk = new byte[4096];
            try {
                int count;
                while((count = await pipe.ReadAsync(chunk,0,chunk.Length)) != 0) {
                    lock(gate) {
                        int keep = Math.Min(count, 65536-(int)retained.Length);
                        if(keep > 0) retained.Write(chunk,0,keep);
                        if(keep < count) truncated = true;
                    }
                }
            } catch { lock(gate) failed = true; }
            finally { try { pipe.Dispose(); } catch { lock(gate) failed = true; } }
        });
    }
}
'@
        }
        if (!$process.Start()) { $record.failure='start_failed'; throw 'Local child start failed' }
        $record.startedChild=$true; $record.pid=$process.Id
        $stdout=[WsoLocalNativeProbeBoundedPipeV1]::new($process.StandardOutput.BaseStream)
        $stderr=[WsoLocalNativeProbeBoundedPipeV1]::new($process.StandardError.BaseStream)
        $record.reaped=$process.WaitForExit($TimeoutMilliseconds)
        if (!$record.reaped) {
            $record.timedOut=$true; $record.killAttempted=$true
            try { $process.Kill() } catch { $record.killFailed=$true }
            $record.reaped=$process.WaitForExit($ReapMilliseconds)
        }
        $null=[Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdout.task,$stderr.task),$PipeMilliseconds)
    } catch {
        if ($record.failure -ceq 'none') { $record.failure=if ($record.startedChild) {'child_exception'} else {'start_failed'} }
    } finally {
        if ($record.startedChild -and $process.HasExited) { $record.reaped=$true; $record.exit=$process.ExitCode }
        if ($stdout -and $stderr) {
            $outBytes=$stdout.Snapshot(); $errBytes=$stderr.Snapshot()
            $record.pipesCompleted=$stdout.task.IsCompleted -and $stderr.task.IsCompleted
            $record.captureComplete=$record.pipesCompleted -and !$stdout.Failed -and !$stderr.Failed
            $record.captureTruncated=$stdout.Truncated -or $stderr.Truncated
        }
        $record.ownershipRetained=$record.startedChild -and (!$record.reaped -or !$record.pipesCompleted)
        if ($record.failure -ceq 'none') {
            if ($record.timedOut) { $record.failure='timeout' }
            elseif (!$record.reaped) { $record.failure='unreaped' }
            elseif (!$record.captureComplete) { $record.failure='capture_incomplete' }
            elseif ($record.captureTruncated) { $record.failure='capture_bound' }
            elseif ($record.exit -ne 0) { $record.failure='child_exit' }
        }
        [IO.File]::WriteAllBytes((Join-Path $capture "$Name.stdout"),$outBytes)
        [IO.File]::WriteAllBytes((Join-Path $capture "$Name.stderr"),$errBytes)
        $record.stdoutBytes=$outBytes.Length; $record.stderrBytes=$errBytes.Length
        $record.ended=[datetime]::UtcNow.ToString('o')
        $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $capture "$Name-command.json") -Encoding utf8
        if ($record.ownershipRetained) {
            $script:RetainedBuildChildren[$Name]=@{process=$process;stdout=$stdout;stderr=$stderr;capture=$capture;record=$record}
        } else { $process.Dispose() }
    }
    if ($record.failure -cne 'none') { throw 'Local build stage failed; structured private evidence retained' }
    return [Text.Encoding]::UTF8.GetString($outBytes)
}
$null=Invoke-Tool 'javac' $javac (@('--release','8','-encoding','UTF-8','-classpath',$AndroidJar,'-d',(Join-Path $owned 'classes')) + $sources)
$classes=@(Get-ChildItem -LiteralPath (Join-Path $owned 'classes') -Recurse -File -Filter '*.class' | Sort-Object FullName | ForEach-Object FullName)
$null=Invoke-Tool 'd8' $java (@('-cp',$d8,'com.android.tools.r8.D8','--min-api','23','--lib',$AndroidJar,'--output',(Join-Path $owned 'dex')) + $classes)
$null=Invoke-Tool 'aapt2-link' $aapt @('link','-o','unsigned.apk','-I',$AndroidJar,'--manifest','input/AndroidManifest.xml')
$archive=[IO.Compression.ZipFile]::Open((Join-Path $owned 'unsigned.apk'),[IO.Compression.ZipArchiveMode]::Update)
try {
    $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,(Join-Path $owned 'dex/classes.dex'),'classes.dex')
    foreach ($expected in $native) { $null=[IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,(Join-Path $owned $expected.path),$expected.path) }
} finally { $archive.Dispose() }
$null=Invoke-Tool 'zipalign' $align @('-P','16','4','unsigned.apk','aligned.apk')
$key=Join-Path $owned 'private/ephemeral-development.p12'
$passwordBytes=[byte[]]::new(32); [Security.Cryptography.RandomNumberGenerator]::Fill($passwordBytes)
$password=[Convert]::ToBase64String($passwordBytes); [Array]::Clear($passwordBytes,0,$passwordBytes.Length)
$signEnv=@{WSO_LOCAL_DEVICE_SIGN_PASSWORD=$password}
try {
    $null=Invoke-Tool 'keytool' $keytool @('-genkeypair','-keystore',$key,'-storetype','PKCS12','-alias','local-development','-keyalg','RSA','-keysize','2048','-validity','7','-dname','CN=WSO Local NAT DEVELOPMENT','-storepass:env','WSO_LOCAL_DEVICE_SIGN_PASSWORD','-keypass:env','WSO_LOCAL_DEVICE_SIGN_PASSWORD','-noprompt') $signEnv
    $null=Invoke-Tool 'sign' $java @('-jar',$signer,'sign','--ks',$key,'--ks-key-alias','local-development','--ks-pass','env:WSO_LOCAL_DEVICE_SIGN_PASSWORD','--key-pass','env:WSO_LOCAL_DEVICE_SIGN_PASSWORD','--out','wso-tvt-local-device.apk','aligned.apk') $signEnv
} finally {
    $password=$null; $signEnv.Clear()
    if (Test-Path -LiteralPath $key -PathType Leaf) { Remove-Item -LiteralPath $key }
}
$apk=Join-Path $owned 'wso-tvt-local-device.apk'
$null=Invoke-Tool 'verify-signature' $java @('-jar',$signer,'verify','--verbose','--print-certs',$apk)
$null=Invoke-Tool 'verify-alignment' $align @('-c','-P','16','-v','4','wso-tvt-local-device.apk')
$badging=Invoke-Tool 'manifest-badging' $aapt @('dump','badging','wso-tvt-local-device.apk')
$permissions=Invoke-Tool 'manifest-permissions' $aapt @('dump','permissions','wso-tvt-local-device.apk')
$tree=Invoke-Tool 'manifest-tree' $aapt @('dump','xmltree','wso-tvt-local-device.apk','--file','AndroidManifest.xml')
if ($badging -notmatch "package: name='com.wso.tvt.localdevice'" -or $badging -notmatch "sdkVersion:'23'" -or
    $badging -notmatch "targetSdkVersion:'36'" -or @([regex]::Matches($permissions,'uses-permission:')).Count -ne 2 -or
    $permissions -notmatch 'android.permission.INTERNET' -or $permissions -notmatch 'android.permission.ACCESS_NETWORK_STATE'  -or
    $tree -notmatch 'com.wso.tvt.local.LocalDeviceProbeActivity' -or $tree -match 'E: (service|receiver|provider|intent-filter)') { throw 'Packaged manifest requirements failed' }
$archive=[IO.Compression.ZipFile]::OpenRead($apk)
try { Assert-ZipInventory $archive -Packaged; $entries=@($archive.Entries | ForEach-Object FullName) }
finally { $archive.Dispose() }
$null=Read-Receipt
$null=Read-ExactReceipt $BootstrapReceipt 'SOURCE_ACCEPTED_UNPUBLISHED' $bootstrapPaths
$null=Read-ExactReceipt $DiscoveryReceipt 'ACCEPTED_WINDOWS_LOCAL_DEVICE_ROOT_REVIEW' $discoveryPaths
if((Get-FileHash -LiteralPath $BootstrapReceipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $bootstrapHash -or
   (Get-FileHash -LiteralPath $DiscoveryReceipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $discoveryHash) { throw 'Root-reviewed receipts changed during build' }
if ((Get-FileHash -LiteralPath $TransportReceipt -Algorithm SHA256).Hash.ToLowerInvariant() -cne $receiptHash) { throw 'Root receipt changed during build' }
Assert-Identity $ApprovedApk 170064551 'f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281'
foreach ($path in @($activity,$manifest,$PSCommandPath)) {
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sourceHashes[$path]) { throw 'Probe source changed during build' }
}
$result=[ordered]@{
    schemaVersion=1;status='BUILT_HOST_VERIFIED_DEVICE_NOT_EXECUTED';package='com.wso.tvt.localdevice';apk=$apk
    apkBytes=(Get-Item -LiteralPath $apk).Length;apkSha256=(Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
    developmentOnly=$true;signatureVerified=$true;manifestVerified=$true;nativeVerified=$true
    sourceHashes=$sourceHashes;transportReceiptSha256=$receiptHash;bootstrapReceiptSha256=$bootstrapHash;discoveryReceiptSha256=$discoveryHash;dependencies=@{transport=$receipt.files;bootstrap=$bootstrap.files};nativeEntries=$native;packagedEntries=$entries
    captures=$capture;developmentKeyDeleted=!(Test-Path -LiteralPath $key);deviceExecution='NOT_EXECUTED';MATCHED=0;release_ready=$false
}
$result | ConvertTo-Json -Depth 7 | Set-Content -LiteralPath (Join-Path $owned 'build-result.json') -Encoding utf8
$result | ConvertTo-Json -Depth 7
