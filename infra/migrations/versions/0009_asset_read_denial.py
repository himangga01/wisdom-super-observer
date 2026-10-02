"""Translate only the asset live-lock read denial to a missing asset."""

from alembic import op

revision = "0009_asset_read_denial"
down_revision = "0008_tvt_operation_engine"
branch_labels = None
depends_on = None

# Exact reviewed 0003a prosrc, including the helper's surrounding whitespace.
LOCK_HASH = "447b1a8704e0671fc7407f1f94b971f5"
ORIGINAL = {
    "public.wso_redeem_asset_ticket(uuid,text,text)": "2c148adee010c8b83ede641e02590ed7",
    "public.wso_revalidate_asset_read(uuid,uuid,text)": "5ff913e0e067cf5ed07aa453fb54d568",
}
CHANGED = {
    "public.wso_redeem_asset_ticket(uuid,text,text)": "16bdec8728ce8124c2a328f703670e34",
    "public.wso_revalidate_asset_read(uuid,uuid,text)": "942a8e8b5878fb61d4b8046730020b16",
}
OLD = "a:=public.wso_asset_lock(p_id,p_session,true);"
NEW = """BEGIN
          a:=public.wso_asset_lock(p_id,p_session,true);
        EXCEPTION WHEN SQLSTATE '55000' THEN
          RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002';
        END;"""
OWNER_ACL = "{wso_asset_owner=X/wso_asset_owner}"
READ_ACL = "{wso_asset_owner=X/wso_asset_owner,wso_app=X/wso_asset_owner}"


def _literal(value):
    return "'" + value.replace("'", "''") + "'"


def _guarded_sql(*, upgrade):
    """Emit the same executable catalog guards in online and offline modes."""
    before, after = (OLD, NEW) if upgrade else (NEW, OLD)
    current, result = (ORIGINAL, CHANGED) if upgrade else (CHANGED, ORIGINAL)
    targets = [
        "("
        + ",".join(
            _literal(value)
            for value in (
                "public.wso_asset_lock(uuid,text,boolean)",
                LOCK_HASH,
                LOCK_HASH,
                OWNER_ACL,
            )
        )
        + ",false)"
    ]
    targets.extend(
        "("
        + ",".join(
            _literal(value)
            for value in (signature, current[signature], result[signature], READ_ACL)
        )
        + ",true)"
        for signature in ORIGINAL
    )
    return f"""DO $wso_read_denial$
    DECLARE
      spec record; original record; changed record;
      before_text text := {_literal(before)};
      after_text text := {_literal(after)};
    BEGIN
      FOR spec IN SELECT * FROM (VALUES {",".join(targets)})
        AS targets(signature,expected_hash,result_hash,expected_acl,replace_body)
      LOOP
        SELECT p.oid,p.prosrc,pg_catalog.pg_get_functiondef(p.oid) AS definition,
          p.proowner,p.proacl,p.prosecdef,p.proconfig,p.provolatile,l.lanname
          INTO original
          FROM pg_catalog.pg_proc p
          JOIN pg_catalog.pg_language l ON l.oid=p.prolang
          WHERE p.oid=pg_catalog.to_regprocedure(spec.signature);
        IF NOT FOUND THEN
          RAISE EXCEPTION 'asset read function missing';
        END IF;
        IF pg_catalog.pg_get_userbyid(original.proowner)
              IS DISTINCT FROM 'wso_asset_owner'
          OR original.proacl::text IS DISTINCT FROM spec.expected_acl
          OR original.prosecdef IS DISTINCT FROM true
          OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']
          OR original.provolatile IS DISTINCT FROM 'v'
          OR original.lanname IS DISTINCT FROM 'plpgsql' THEN
          RAISE EXCEPTION 'asset read function security precondition failed';
        END IF;
        IF pg_catalog.md5(original.prosrc) IS DISTINCT FROM spec.expected_hash THEN
          RAISE EXCEPTION 'asset read function source precondition failed';
        END IF;
        IF spec.replace_body THEN
          IF (length(original.prosrc)-length(replace(original.prosrc,before_text,'')))
                /length(before_text) <> 1
            OR (length(original.definition)
                -length(replace(original.definition,before_text,'')))
                /length(before_text) <> 1 THEN
            RAISE EXCEPTION 'asset read function replacement precondition failed';
          END IF;
          EXECUTE replace(original.definition,before_text,after_text);
          SELECT p.oid,p.prosrc,p.proowner,p.proacl,p.prosecdef,p.proconfig,
            p.provolatile,l.lanname INTO changed
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_language l ON l.oid=p.prolang
            WHERE p.oid=pg_catalog.to_regprocedure(spec.signature);
          IF NOT FOUND THEN
            RAISE EXCEPTION 'asset read function replacement verification failed';
          END IF;
          IF changed.oid IS DISTINCT FROM original.oid
            OR changed.proowner IS DISTINCT FROM original.proowner
            OR changed.proacl IS DISTINCT FROM original.proacl
            OR changed.prosecdef IS DISTINCT FROM original.prosecdef
            OR changed.proconfig IS DISTINCT FROM original.proconfig
            OR changed.provolatile IS DISTINCT FROM original.provolatile
            OR changed.lanname IS DISTINCT FROM original.lanname
            OR changed.prosrc IS DISTINCT FROM
                replace(original.prosrc,before_text,after_text)
            OR pg_catalog.md5(changed.prosrc) IS DISTINCT FROM spec.result_hash THEN
            RAISE EXCEPTION 'asset read function replacement verification failed';
          END IF;
        END IF;
      END LOOP;
    END;
    $wso_read_denial$;"""


def upgrade():
    op.execute(_guarded_sql(upgrade=True))


def downgrade():
    op.execute(_guarded_sql(upgrade=False))
