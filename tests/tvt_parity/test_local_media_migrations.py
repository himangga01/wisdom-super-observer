"""Static media migration checks; no database. Guarded SQL runs elsewhere."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "infra/migrations/versions"
LOCKS = re.compile(r" FOR SHARE(?: OF [a-z]+(?:,[a-z]+)*)?;")


def migration(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0014_live_read_equals_live_without_locks():
    leases = migration("0013_tvt_local_media_leases")
    hot = migration("0014_tvt_local_media_hot_authority")
    # The file stem exceeds alembic_version's varchar(32): a shorter revision id.
    assert hot.revision == "0014_tvt_local_media_hot_auth"
    assert len(hot.revision) <= 32
    assert hot.down_revision == leases.revision
    # 0013's LIVE takes ten share locks; live_read is the same text without them.
    assert len(LOCKS.findall(leases.LIVE)) == 10
    assert hot.LIVE_READ == LOCKS.sub(";", leases.LIVE)
    assert not re.search(r"\bFOR\s+(SHARE|UPDATE|NO KEY|KEY)\b", hot.LIVE_READ)
    # observe is 0013's worker view on live_read, for NEGOTIATING/PLAYING only.
    assert hot.OBSERVE == leases.WORKER_VIEW.replace(
        "x.native_generation=p_native;",
        "x.native_generation=p_native AND x.state IN ('NEGOTIATING','PLAYING');",
    ).replace("wso_tvt_local_media_live(l)", "wso_tvt_local_media_live_read(l)")
    # Same function options as every 0013 function, owner and runtime roles.
    source = (VERSIONS / "0013_tvt_local_media_leases.py").read_text()
    assert f"RETURNS {{returns}} {hot.OPTIONS} AS $media$" in source
    assert hot.OWNER == leases.OWNER and hot.RUNTIME == leases.RUNTIME
    assert [
        (name, args, returns, grantee)
        for name, args, returns, _, grantee in hot.FUNCTIONS
    ] == [
        (
            "wso_private.wso_tvt_local_media_live_read",
            "l wso_private.tvt_local_media_leases",
            "boolean",
            "",
        ),
        (
            "public.wso_tvt_local_media_observe",
            "p_authority text,p_worker uuid,p_native uuid",
            "jsonb",
            "wso_connection_worker",
        ),
    ]
    assert [body for *_, body, _ in hot.FUNCTIONS] == [hot.LIVE_READ, hot.OBSERVE]


def test_0015_changes_only_caps(monkeypatch):
    path = VERSIONS / "0015_tvt_local_media_capacity.py"
    assert path.is_file(), "capacity migration is missing"
    leases = migration("0013_tvt_local_media_leases")
    capacity = migration("0015_tvt_local_media_capacity")
    assert capacity.revision == "0015_tvt_local_media_capacity"
    assert len(capacity.revision) <= 32
    assert capacity.down_revision == "0014_tvt_local_media_hot_auth"
    assert capacity.ISSUE == leases.ISSUE.replace(">=32\n", ">=64\n").replace(
        ">=4 THEN", ">=16 THEN"
    )
    assert capacity.ORIGINAL_ISSUE == leases.ISSUE
    emitted = []
    monkeypatch.setattr(capacity.op, "execute", emitted.append)
    capacity.upgrade()
    upgrade = emitted.copy()
    emitted.clear()
    capacity.downgrade()
    assert len(upgrade) == len(emitted) == 1
    assert upgrade[0] == emitted[0].replace(leases.ISSUE, capacity.ISSUE)
    assert upgrade[0].startswith(
        "CREATE OR REPLACE FUNCTION public.wso_tvt_local_media_issue("
    )
