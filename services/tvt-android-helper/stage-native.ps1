param(
    [Parameter(Mandatory=$true)][string]$ApkPath,
    [Parameter(Mandatory=$true)][ValidateSet('arm64-v8a', 'armeabi-v7a')][string]$Abi
)
# Local packaging utility only. This script never loads or executes the binary.
$ErrorActionPreference = 'Stop'
$apkFile = Get-Item -LiteralPath $ApkPath
if ($apkFile.PSIsContainer -or $apkFile.Length -ne 170064551) { throw 'APK size mismatch' }
if ((Get-FileHash -LiteralPath $apkFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281') { throw 'APK digest mismatch' }
$identities = @{
    'arm64-v8a' = @{ Size = 3920784; Digest = 'c1f25867b0c97ba6bb7b519f969b1f56e2a15ac7b1677fb669d7a6920fa05717' }
    'armeabi-v7a' = @{ Size = 3018084; Digest = '17d44c46654752f761d8117989c0101c7662fc494a8900ca2b307de1b234f23f' }
}
$identity = $identities[$Abi]
$zipPath = "lib/$Abi/libNetClientProtocal.so"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($apkFile.FullName)
try {
    $nativeEntries = @($archive.Entries | Where-Object { $_.FullName -ceq $zipPath })
    if ($nativeEntries.Count -ne 1 -or $nativeEntries[0].Length -ne $identity.Size -or $nativeEntries[0].CompressedLength -gt $identity.Size) { throw 'Native ZIP path, uniqueness or size mismatch' }
    $stream = $nativeEntries[0].Open()
    try {
        $buffer = New-Object byte[] $identity.Size
        $offset = 0
        while ($offset -lt $buffer.Length) {
            $read = $stream.Read($buffer, $offset, $buffer.Length - $offset)
            if ($read -le 0) { throw 'Native ZIP entry truncated' }
            $offset += $read
        }
        if ($stream.ReadByte() -ne -1) { throw 'Native ZIP entry exceeds exact bound' }
    } finally { $stream.Dispose() }
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try { $digest = ([System.BitConverter]::ToString($hasher.ComputeHash($buffer))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    if ($digest -ne $identity.Digest) { throw 'Native digest mismatch' }
    $destinationDirectory = Join-Path $PSScriptRoot "build/native/$Abi"
    New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
    $destination = Join-Path $destinationDirectory 'libNetClientProtocal.so'
    [System.IO.File]::WriteAllBytes($destination, $buffer)
    Write-Output "Staged verified $Abi native library into ignored build directory; SHA256=$digest"
} finally { $archive.Dispose() }
