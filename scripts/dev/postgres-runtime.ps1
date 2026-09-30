param(
    [ValidateSet('Setup', 'Start', 'Stop', 'Status', 'Provision')]
    [string]$Action = 'Setup',
    [string]$Python
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $root '.superpowers/runtime/postgresql17'
if (-not $Python) {
    $Python = Join-Path $root '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Pass -Python with a Python 3.12 executable containing psycopg, sqlalchemy and alembic; synchronize the workspace first.'
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

# The helper, credentials, binaries, cluster and logs all stay in ignored storage.
# No password is passed as a command-line argument or emitted to stdout.
$helper = @'
from __future__ import annotations

import hashlib
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import urllib.request
from urllib.parse import quote
import zipfile

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = Path(__file__).resolve().parent
BIN = RUNTIME / 'pgsql' / 'bin'
DATA = RUNTIME / 'data'
STATE = RUNTIME / 'credentials.json'
ARCHIVE = RUNTIME / 'postgresql-17.11-4-windows-x64-binaries.zip'
URL = 'https://get.enterprisedb.com/postgresql/postgresql-17.11-4-windows-x64-binaries.zip'
# EDB maintainer checksum: https://github.com/EnterpriseDB/edb-installers/issues/706
SHA256 = 'b9424ee7bc60b52450ff910a3630225df32e633f3cb29c1d126d9299d59aea28'
ROLES = {
    'ADMIN': 'postgres',
    'APP': 'wso_app',
    'IDENTITY': 'wso_identity_bootstrap',
    'MIGRATOR': 'wso_migrator',
    'SESSION': 'wso_web_session',
    'WORKER': 'wso_connection_worker',
    'DISPATCH': 'wso_dispatcher',
    'JOB': 'wso_job_worker',
}


def run(executable: Path, args: list[str], log: str, *, check: bool = True) -> int:
    with (RUNTIME / log).open('ab') as output:
        result = subprocess.run(
            [str(executable), *args], cwd=ROOT, stdout=output,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    if check and result.returncode:
        raise RuntimeError(f'{executable.name} failed; inspect ignored {log}')
    return result.returncode


def load() -> dict:
    if not STATE.is_file():
        raise RuntimeError('Runtime is not initialized; run Setup first')
    state = json.loads(STATE.read_text(encoding='utf-8'))
    # Extend older clusters without rotating saved secrets, URLs or metadata.
    changed = False
    for key in ('WORKER', 'DISPATCH', 'JOB'):
        role = ROLES[key]
        if role not in state['passwords']:
            state['passwords'][role] = secrets.token_urlsafe(36)
            changed = True
        if f'WSO_TEST_{key}_DATABASE_URL' not in state.get('urls', {}):
            changed = True
    if changed:
        write_loader(state)
    return state


def map_runtime(state: dict) -> None:
    global BIN, DATA
    drive = state.get('drive')
    if not drive:
        drive = next((f'{letter}:' for letter in 'ZYXWVUTSRQPONMLKJIHGFED'
                      if not Path(f'{letter}:/').exists()), None)
        if not drive:
            raise RuntimeError('No free drive letter for temporary runtime alias')
        state['drive'] = drive
        STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    view = Path(drive + '/')
    if view.exists():
        if not view.samefile(RUNTIME):
            raise RuntimeError('Runtime alias drive is occupied by another location')
    else:
        result = subprocess.run(
            ['subst.exe', drive, str(RUNTIME)], capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW, check=False,
        )
        if result.returncode:
            raise RuntimeError('Could not create temporary runtime drive alias')
    BIN = view / 'pgsql' / 'bin'
    DATA = view / 'data'


def connect(state: dict, role: str = 'postgres', dbname: str | None = None):
    return psycopg.connect(
        host='127.0.0.1', port=state['port'], user=role,
        password=state['passwords'][role], dbname=dbname or state['database'],
        connect_timeout=5, autocommit=True,
    )


def download() -> None:
    if not ARCHIVE.is_file():
        partial = ARCHIVE.with_suffix('.partial')
        urllib.request.urlretrieve(URL, partial)
        partial.replace(ARCHIVE)
    with ARCHIVE.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != SHA256:
        raise RuntimeError('EDB archive SHA-256 mismatch; refusing extraction')
    (RUNTIME / 'download.json').write_text(json.dumps({
        'source': URL, 'sha256': digest, 'bytes': ARCHIVE.stat().st_size,
    }, indent=2), encoding='utf-8')
    if BIN.joinpath('postgres.exe').is_file():
        return
    with zipfile.ZipFile(ARCHIVE) as archive:
        for member in archive.infolist():
            if not member.filename.startswith(('pgsql/bin/', 'pgsql/lib/', 'pgsql/share/')):
                continue
            target = (RUNTIME / member.filename).resolve()
            if not target.is_relative_to(RUNTIME.resolve()):
                raise RuntimeError('Unsafe path in archive')
            archive.extract(member, RUNTIME)


def initialize() -> dict:
    if STATE.is_file():
        state = load()
        map_runtime(state)
        if DATA.joinpath('PG_VERSION').is_file():
            if DATA.joinpath('PG_VERSION').read_text().strip() != '17':
                raise RuntimeError('Existing cluster is not PostgreSQL 17')
            if not state.get('initialized'):
                configure(state)
            return state
        if state.get('initialized'):
            raise RuntimeError('Initialized cluster is missing; refusing reinitialization')
    else:
        if DATA.exists() and any(DATA.iterdir()):
            raise RuntimeError('Existing data without credentials; refusing to overwrite')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        state = {
            'port': port, 'database': 'wso_test',
            'passwords': {role: secrets.token_urlsafe(36) for role in ROLES.values()},
        }
        map_runtime(state)
    if DATA.exists() and any(DATA.iterdir()):
        raise RuntimeError('Existing incomplete data; refusing to overwrite')
    # Persist before initdb so failures never silently replace an existing cluster.
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    pwfile = DATA.parent / 'initdb-password.txt'
    pwfile.write_text(state['passwords']['postgres'] + '\n', encoding='utf-8')
    try:
        run(BIN / 'initdb.exe', [
            '-D', str(DATA), '-U', 'postgres', '--encoding=UTF8', '--locale=C',
            '--auth=scram-sha-256', '--pwfile', str(pwfile),
        ], 'initdb.log')
    finally:
        pwfile.unlink(missing_ok=True)
    configure(state)
    return state


def configure(state: dict) -> None:
    config = f"""
# Disposable WSO integration runtime: loopback only, no Windows service.
listen_addresses = '127.0.0.1'
port = {state['port']}
password_encryption = 'scram-sha-256'
log_statement = 'none'
log_min_error_statement = 'panic'
log_connections = off
log_disconnections = off
"""
    with DATA.joinpath('postgresql.conf').open('a', encoding='utf-8') as output:
        output.write(config)
    DATA.joinpath('pg_hba.conf').write_text(
        'host all all 127.0.0.1/32 scram-sha-256\n', encoding='utf-8',
    )
    state['initialized'] = True
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def start(state: dict) -> None:
    if run(BIN / 'pg_ctl.exe', ['-D', str(DATA), 'status'], 'pg_ctl.log', check=False) == 0:
        return
    run(BIN / 'pg_ctl.exe', [
        '-D', str(DATA), '-l', str(DATA.parent / 'server.log'),
        '-o', f'-h 127.0.0.1 -p {state["port"]}', '-w', '-t', '30', 'start',
    ], 'pg_ctl.log')


def write_loader(state: dict) -> None:
    urls = state.setdefault('urls', {})
    for key, role in ROLES.items():
        urls.setdefault(f'WSO_TEST_{key}_DATABASE_URL', (
            f'postgresql+psycopg://{role}:{quote(state["passwords"][role], safe="")}'
            f'@127.0.0.1:{state["port"]}/{state["database"]}'
        ))
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')
    RUNTIME.joinpath('env.ps1').write_text(
        "$runtimeCredentials = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'credentials.json') -Raw | ConvertFrom-Json\n"
        "foreach ($entry in $runtimeCredentials.urls.PSObject.Properties) {\n"
        "    [Environment]::SetEnvironmentVariable($entry.Name, [string]$entry.Value, 'Process')\n"
        "}\n"
        "Remove-Variable runtimeCredentials, entry -ErrorAction SilentlyContinue\n",
        encoding='utf-8',
    )


def existing_application_roles(connection) -> list[str]:
    applied = connection.execute('SELECT version_num FROM alembic_version').fetchall()
    if len(applied) != 1:
        raise RuntimeError('Expected a single applied migration revision')
    jobs_required = applied[0][0] not in (
        '0001_tenants', '0001b_tenant_grants', '0001c_auth_sessions', '0002_connections',
    )
    roles = []
    for role in list(ROLES.values())[1:]:
        exists = connection.execute(
            'SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)', (role,),
        ).fetchone()[0]
        if exists:
            roles.append(role)
            continue
        if role in ('wso_web_session', 'wso_connection_worker'):
            continue
        if role in ('wso_dispatcher', 'wso_job_worker'):
            # Before 0003 these roles are optional. After it (or a later head),
            # absence indicates a damaged migration and must fail closed.
            if not jobs_required:
                continue
        raise RuntimeError(f'Migration-created role missing: {role}')
    return roles


def provision(state: dict, bootstrap: bool = False) -> None:
    with connect(state, dbname='postgres') as connection:
        exists = connection.execute(
            'SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)',
            (state['database'],),
        ).fetchone()[0]
        if not exists:
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(state['database'])))
    if bootstrap:
        from alembic import command
        from alembic.config import Config
        config = Config(str(ROOT / 'infra' / 'alembic.ini'))
        config.set_main_option('sqlalchemy.url', state['urls']['WSO_TEST_ADMIN_DATABASE_URL'])
        # Roles belong to migrations. Apply just the stable initial revision;
        # the integration suite owns upgrades to subsequent revisions.
        with connect(state) as connection:
            ready = connection.execute("SELECT to_regrole('wso_app') IS NOT NULL").fetchone()[0]
        if not ready:
            command.upgrade(config, '0001_tenants')
    provisioned = []
    with connect(state) as connection:
        for role in existing_application_roles(connection):
            # Utility statements cannot use server placeholders. psycopg's
            # composable Identifier/Literal safely quote both identifier and secret.
            connection.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(
                sql.Identifier(role), sql.Literal(state['passwords'][role]),
            ))
            provisioned.append(role)
        connection.execute(sql.SQL('GRANT CREATE ON DATABASE {} TO {}').format(
            sql.Identifier(state['database']), sql.Identifier('wso_migrator'),
        ))
    state['provisioned_roles'] = provisioned
    write_loader(state)
    print('Provisioned migration-created roles: ' + ', '.join(provisioned))


def status(state: dict) -> None:
    with connect(state) as connection:
        row = connection.execute(
            "SELECT version(), current_setting('listen_addresses'), current_setting('port')"
        ).fetchone()
        if not row[0].startswith('PostgreSQL 17.') or row[1] != '127.0.0.1':
            raise RuntimeError('Runtime version or loopback binding validation failed')
        print(f'{row[0]} | listen={row[1]} | port={row[2]}')
        # Catalog existence is authoritative even if the saved provisioned list
        # predates a new migration. Optional roles may be absent before upgrade.
        existing_roles = existing_application_roles(connection)
    for role in existing_roles:
        with connect(state, role) as connection:
            row = connection.execute(
                'SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls, rolinherit, rolcanlogin '
                'FROM pg_roles WHERE rolname = current_user'
            ).fetchone()
            if any(row[1:7]) or not row[7]:
                raise RuntimeError(f'Unsafe runtime role: {role}')
            if role in ('wso_app', 'wso_identity_bootstrap'):
                memberships = connection.execute(
                    'SELECT count(*) FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s)',
                    (role,),
                ).fetchone()[0]
                if memberships:
                    raise RuntimeError(f'Unexpected runtime role membership: {role}')
            if role in ('wso_connection_worker', 'wso_dispatcher', 'wso_job_worker'):
                memberships = connection.execute(
                    'SELECT count(*) FROM pg_auth_members '
                    'WHERE member = (SELECT oid FROM pg_roles WHERE rolname = %s) '
                    'OR roleid = (SELECT oid FROM pg_roles WHERE rolname = %s)',
                    (role, role),
                ).fetchone()[0]
                if memberships:
                    raise RuntimeError(f'Unexpected runtime role membership: {role}')
            print(f'{role}: login OK; privileged flags false')
    print('Environment loader: ' + str(RUNTIME / 'env.ps1'))


class PinnedProcess:
    """Hold the process object so Windows cannot recycle its PID during Stop."""

    def __init__(self, pid: int):
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
            'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            'QueryFullProcessImageNameW': ([wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            'GetProcessTimes': ([wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        # Query + synchronize only: this handle cannot terminate a process.
        self.handle = self.api.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle:
            raise RuntimeError('Stop refused: postmaster process cannot be inspected')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.api.CloseHandle(self.handle)

    def running(self) -> bool:
        return self.api.WaitForSingleObject(self.handle, 0) == 258

    def image(self) -> Path:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not self.api.QueryFullProcessImageNameW(self.handle, 0, buffer, ctypes.byref(length)):
            raise RuntimeError('Stop refused: postmaster executable cannot be inspected')
        return Path(buffer.value)

    def created_at(self) -> float:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not self.api.GetProcessTimes(self.handle, *[ctypes.byref(value) for value in times]):
            raise RuntimeError('Stop refused: process creation time cannot be inspected')
        ticks = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
        return ticks / 10_000_000 - 11_644_473_600

    def wait_for_exit(self, milliseconds: int) -> None:
        if self.api.WaitForSingleObject(self.handle, milliseconds) != 0:
            raise RuntimeError('Postmaster shutdown was not confirmed; alias retained')


def process_parent(pid: int) -> int:
    """Read the SQL backend's parent while that backend connection is alive."""
    class Entry(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260),
        ]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    for name in ('Process32FirstW', 'Process32NextW'):
        function = getattr(api, name)
        function.argtypes, function.restype = [wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL
    snapshot = api.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise RuntimeError('Stop refused: process parent cannot be inspected')
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(entry)
        found = api.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32ProcessID == pid:
                return entry.th32ParentProcessID
            found = api.Process32NextW(snapshot, ctypes.byref(entry))
        raise RuntimeError('Stop refused: authenticated backend process was not found')
    finally:
        api.CloseHandle(snapshot)


@contextmanager
def verified_postmaster(state: dict):
    pidfile = DATA / 'postmaster.pid'
    original = pidfile.read_bytes()
    lines = original.decode('utf-8').splitlines()
    if len(lines) < 4:
        raise RuntimeError('Stop refused: incomplete runtime PID file')
    pid, started, port = int(lines[0]), int(lines[2]), int(lines[3])
    if pid <= 0 or port != state['port'] or not Path(lines[1]).samefile(DATA):
        raise RuntimeError('Stop refused: runtime PID file identity mismatch')
    with PinnedProcess(pid) as process:
        if not process.running() or not process.image().samefile(BIN / 'postgres.exe'):
            raise RuntimeError('Stop refused: PID does not name the runtime postmaster')
        # initdb/postgres records whole seconds; the OS creation occurs slightly
        # before postmaster startup. SQL backend parent verification below proves
        # the exact instance even if two servers started within this interval.
        if not -1 <= started - process.created_at() <= 60:
            raise RuntimeError('Stop refused: stale PID file process creation time')
        with connect(state) as connection:
            directory, sql_start, backend, listener, sql_port = connection.execute(
                "SELECT current_setting('data_directory'), EXTRACT(EPOCH FROM pg_postmaster_start_time()), "
                "pg_backend_pid(), current_setting('listen_addresses'), current_setting('port')"
            ).fetchone()
            if (not Path(directory).samefile(DATA) or int(sql_start) != started
                    or listener != '127.0.0.1' or int(sql_port) != state['port']
                    or process_parent(backend) != pid):
                raise RuntimeError('Stop refused: authenticated server is a different cluster or process')
        if pidfile.read_bytes() != original or not process.running():
            raise RuntimeError('Stop refused: postmaster identity changed during validation')
        yield process, pid


def stop(state: dict) -> None:
    with verified_postmaster(state) as (process, pid):
        # Signal the verified, pinned PID directly. pg_ctl stop would reread a
        # mutable PID file after validation and could signal a different PID.
        run(BIN / 'pg_ctl.exe', ['kill', 'INT', str(pid)], 'pg_ctl.log')
        process.wait_for_exit(30_000)
    view = Path(state['drive'] + '/')
    if not view.exists() or not view.samefile(RUNTIME):
        raise RuntimeError('Server stopped; alias identity changed, so alias retained')
    result = subprocess.run(
        ['subst.exe', state['drive'], '/D'], capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW, check=False,
    )
    if result.returncode:
        raise RuntimeError('Server stopped but temporary runtime alias removal failed')
    print('PostgreSQL runtime stopped; data preserved')


def main() -> None:
    action = sys.argv[1].lower()
    if action == 'setup':
        download()
        state = initialize()
        write_loader(state)
        start(state)
        provision(state, bootstrap=True)
        status(state)
        return
    state = load()
    if action == 'stop' and not DATA.joinpath('postmaster.pid').is_file():
        raise RuntimeError('Stop refused: no live runtime PID file; alias untouched')
    map_runtime(state)
    if action == 'stop':
        stop(state)
    elif action == 'start':
        start(state)
        status(state)
    elif action == 'provision':
        provision(state)
        status(state)
    else:
        status(state)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid printing a driver exception containing a SQL statement or URL.
        print(f'PostgreSQL runtime {sys.argv[1]} failed ({type(error).__name__}); inspect ignored runtime logs.', file=sys.stderr)
        sys.exit(1)
'@
$helperPath = Join-Path $runtime 'runtime.py'
[IO.File]::WriteAllText($helperPath, $helper, [Text.UTF8Encoding]::new($false))
& $Python $helperPath $Action
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL runtime action failed: $Action"
}
