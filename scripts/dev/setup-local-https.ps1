# User-authorized Windows localhost TLS setup. No browser validation flags.
[CmdletBinding()]
param([string]$Directory = (Join-Path $env:LOCALAPPDATA 'WisdomSuperObserver/local-https'))
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'Windows PowerShell 7 is required.' }
$tlsRoot = [System.IO.Path]::GetFullPath($Directory)
if ([System.IO.Path]::GetPathRoot($tlsRoot) -eq $tlsRoot) { throw 'A dedicated directory is required.' }
if (Test-Path -LiteralPath $tlsRoot) {
    if ((Get-Item -LiteralPath $tlsRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse directory rejected.' }
} else { [void][IO.Directory]::CreateDirectory($tlsRoot) }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = [Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true, $false)
foreach ($principal in @($sid, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
    $rule = [Security.AccessControl.FileSystemAccessRule]::new($principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
$existingAcl = Get-Acl -LiteralPath $tlsRoot
$expectedSids = @($sid.Value, 'S-1-5-18')
$rules = @($existingAcl.Access)
$privateAcl = $existingAcl.AreAccessRulesProtected -and $rules.Count -eq 2
foreach ($rule in $rules) {
    $ruleSid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    $privateAcl = $privateAcl -and ($ruleSid -in $expectedSids) -and $rule.AccessControlType -eq 'Allow' -and $rule.FileSystemRights -eq 'FullControl' -and $rule.InheritanceFlags -eq 'ContainerInherit,ObjectInherit'
}
if (-not $privateAcl) { Set-Acl -LiteralPath $tlsRoot -AclObject $acl }
foreach ($name in @('bin', 'ca', 'server')) {
    $path = Join-Path $tlsRoot $name
    if (Test-Path -LiteralPath $path) {
        if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse child rejected.' }
    } else { [void][IO.Directory]::CreateDirectory($path) }
}
# Official release, checksum from Microsoft's winget-pkgs manifest for x64 1.4.4.
$expected = 'D2660B50A9ED59EADA480750561C96ABC2ED4C9A38C6A24D93E30E0977631398'
$binary = Join-Path $tlsRoot 'bin/mkcert-v1.4.4-windows-amd64.exe'
if (-not (Test-Path -LiteralPath $binary)) {
    Invoke-WebRequest -Uri 'https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe' -OutFile $binary
}
if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $expected) { throw 'mkcert checksum mismatch.' }
$caPath = Join-Path $tlsRoot 'ca/rootCA.pem'
$serverPath = Join-Path $tlsRoot 'server/server.pem'
$serverKey = Join-Path $tlsRoot 'server/server.key'
$previousCAROOT = $env:CAROOT
try {
    $env:CAROOT = Join-Path $tlsRoot 'ca'
    $generate = -not ((Test-Path -LiteralPath $serverPath) -and (Test-Path -LiteralPath $serverKey) -and (Test-Path -LiteralPath $caPath))
    if (-not $generate) {
        $leaf = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText($serverPath))
        $generate = $leaf.NotAfter.ToUniversalTime() -le [DateTime]::UtcNow.AddDays(7)
        $leaf.Dispose()
    }
    if ($generate) {
        & $binary -cert-file $serverPath -key-file $serverKey localhost 127.0.0.1 ::1 *> (Join-Path $tlsRoot 'mkcert-setup.log')
        if ($LASTEXITCODE -ne 0) { throw 'Local certificate generation failed.' }
    }
} finally { $env:CAROOT = $previousCAROOT }
Copy-Item -LiteralPath $caPath -Destination (Join-Path $tlsRoot 'server/ca.pem') -Force
$ca = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPem([IO.File]::ReadAllText($caPath))
$store = [Security.Cryptography.X509Certificates.X509Store]::new('Root', 'CurrentUser')
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    if ($store.Certificates.Find('FindByThumbprint', $ca.Thumbprint, $false).Count -eq 0) { $store.Add($ca) }
    if ($store.Certificates.Find('FindByThumbprint', $ca.Thumbprint, $false).Count -ne 1) { throw 'Current-user trust installation failed.' }
} finally { $store.Close() }
$leaf = [Security.Cryptography.X509Certificates.X509Certificate2]::CreateFromPemFile($serverPath, $serverKey)
$chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
try {
    $chain.ChainPolicy.RevocationMode = 'NoCheck'
    [void]$chain.ChainPolicy.ExtraStore.Add($ca)
    if (-not $chain.Build($leaf)) { throw 'Windows local trust chain verification failed.' }
    $result = [ordered]@{ schema=1; directory=$tlsRoot; browserTlsDirectory=(Join-Path $tlsRoot 'server'); trustStore='CurrentUser/Root'; caThumbprint=$ca.Thumbprint; leafThumbprint=$leaf.Thumbprint; expiresUtc=$leaf.NotAfter.ToUniversalTime().ToString('o'); mkcertSha256=$expected; windowsChainVerified=$true }
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $tlsRoot 'setup-receipt.json') -Encoding utf8
    $result | ConvertTo-Json -Compress
} finally { $chain.Dispose(); $leaf.Dispose(); $ca.Dispose() }
