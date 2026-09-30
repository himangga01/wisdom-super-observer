"""Write disposable test keys with permissions accepted by the real provider."""

import os
import subprocess
from pathlib import Path


def secure_key(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    if os.name == "nt":
        literal = str(path).replace("'", "''")
        script = (
            "$p='"
            + literal
            + "'; $a=New-Object System.Security.AccessControl.FileSecurity; "
            "$s=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
            "$a.SetOwner($s);$a.SetAccessRuleProtection($true,$false); "
            "$r=New-Object System.Security.AccessControl.FileSystemAccessRule($s,'FullControl','Allow'); "
            "$a.AddAccessRule($r);[System.IO.File]::SetAccessControl($p,$a)"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        path.chmod(0o600)
    return path
