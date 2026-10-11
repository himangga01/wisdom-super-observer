"""Offline additive-schema contract; real PostgreSQL is a separate owned gate."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "infra/migrations/versions/0016_tvt_device_media_epochs.py"


def migration():
    assert MIGRATION.is_file(), "Task 5 additive migration has not been implemented"
    spec = importlib.util.spec_from_file_location("mux_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mux_schema_is_additive_and_preserves_historical_functions(monkeypatch):
    module = migration()
    assert module.down_revision == "0015_tvt_local_media_capacity"
    assert len(module.revision) <= 32
    statements = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    sql = "\n".join(statements)
    assert "CREATE OR REPLACE" not in sql.upper()
    assert "DROP INDEX" not in sql.upper()
    assert "ALTER FUNCTION public.wso_tvt_local_media_issue(" not in sql
    for table in module.TABLES:
        assert f"ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY" in sql
        assert f"ALTER TABLE wso_private.{table} OWNER TO wso_tvt_local_owner" in sql
    for name, args, _, _, grantee in module.FUNCTIONS:
        signature = f"{name}({args})".replace(" DEFAULT NULL", "")
        assert f"REVOKE ALL ON FUNCTION {signature} FROM {module.RUNTIME}" in sql
        assert grantee in {"", "wso_app", "wso_connection_worker"}
    assert sql.count("SECURITY DEFINER SET search_path=pg_catalog") == len(
        module.FUNCTIONS
    )


def test_mux_purposes_have_distinct_sql_entrypoints():
    module = migration()
    names = {name.rsplit("_media_", 1)[-1] for name, *_ in module.FUNCTIONS}
    assert {
        "wall_issue",
        "wall_read",
        "wall_stop_issue",
        "shared_issue",
        "master_reserve",
        "master_login",
        "master_activate",
        "master_observe",
        "slot_reserve",
        "slot_observe",
        "viewer_admit",
        "viewer_observe",
        "viewer_activate",
        "viewer_close",
        "epoch_close",
        "focus_issue",
        "focus_redeem",
        "focus_settle",
        "wall_control_issue",
        "wall_control_redeem",
        "focus_settle_issue",
        "focus_settle_redeem",
        "viewer_selection",
        "wall_heartbeat_redeem",
        "focus_read",
    } <= names


def test_mux_downgrade_only_removes_its_own_schema(monkeypatch):
    module = migration()
    statements = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.downgrade()
    sql = "\n".join(statements)
    assert "CASCADE" not in sql.upper()
    assert "DROP TABLE wso_private.tvt_local_media_leases" not in sql
    assert "DROP FUNCTION public.wso_tvt_local_media_issue(" not in sql
