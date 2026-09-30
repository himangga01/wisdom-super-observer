"""Replace caller-controlled tenant settings with protected one-use grants."""

from alembic import op

revision = "0001b_tenant_grants"
down_revision = "0001_tenants"
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "tenants",
    "memberships",
    "stores",
    "store_memberships",
    "audit_events",
)


def _function(signature: str, body: str, role: str) -> None:
    op.execute(body)
    op.execute(f"ALTER FUNCTION public.{signature} OWNER TO wso_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")


def upgrade() -> None:
    op.execute("CREATE SCHEMA wso_private AUTHORIZATION wso_migrator")
    op.execute(
        "REVOKE ALL ON SCHEMA wso_private FROM PUBLIC, wso_app, wso_identity_bootstrap"
    )
    op.execute("""
        CREATE TABLE wso_private.tenant_grants (
            token_hash bytea PRIMARY KEY,
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role text NOT NULL CHECK (role IN ('OWNER', 'MANAGER', 'STAFF')),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE wso_private.tenant_contexts (
            backend_pid integer PRIMARY KEY,
            transaction_id bigint NOT NULL,
            tenant_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role text NOT NULL CHECK (role IN ('OWNER', 'MANAGER', 'STAFF'))
        )
    """)
    for table in ("tenant_grants", "tenant_contexts"):
        op.execute(f"ALTER TABLE wso_private.{table} OWNER TO wso_migrator")
        op.execute(
            f"REVOKE ALL ON wso_private.{table} FROM PUBLIC, wso_app, wso_identity_bootstrap"
        )
        op.execute(f"ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_migration_policy ON wso_private.{table} "
            "TO wso_migrator USING (true) WITH CHECK (true)"
        )
    _function(
        "wso_issue_tenant_grant(uuid)",
        """
        CREATE FUNCTION public.wso_issue_tenant_grant(p_tenant_id uuid)
        RETURNS TABLE (grant_token text, user_id uuid, role text)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $wso$
        DECLARE member_user uuid; member_role text; token text;
        BEGIN
            -- Acquire grant locks before membership locks, like redemption.
            -- Expiry cleanup must never wait for a grant currently in use.
            WITH expired AS MATERIALIZED (
                SELECT token_hash FROM wso_private.tenant_grants
                WHERE expires_at < clock_timestamp()
                FOR UPDATE SKIP LOCKED
            )
            DELETE FROM wso_private.tenant_grants AS g USING expired AS e
            WHERE g.token_hash = e.token_hash;
            SELECT m.user_id, m.role INTO member_user, member_role
            FROM public.memberships AS m JOIN public.users AS u ON u.id = m.user_id
            WHERE m.tenant_id = p_tenant_id
              AND u.oidc_issuer = nullif(current_setting('app.oidc_issuer', true), '')
              AND u.oidc_subject = nullif(current_setting('app.oidc_subject', true), '')
            FOR SHARE OF m;
            IF NOT FOUND THEN RETURN; END IF;
            token := replace(gen_random_uuid()::text, '-', '') ||
                     replace(gen_random_uuid()::text, '-', '');
            INSERT INTO wso_private.tenant_grants
                (token_hash, tenant_id, user_id, role, expires_at)
            VALUES (sha256(convert_to(token, 'UTF8')), p_tenant_id, member_user,
                    member_role, clock_timestamp() + interval '30 seconds');
            RETURN QUERY SELECT token, member_user, member_role;
        END; $wso$
    """,
        "wso_identity_bootstrap",
    )
    _function(
        "wso_consume_tenant_grant(text, integer, bigint, uuid, uuid, text)",
        """
        CREATE FUNCTION public.wso_consume_tenant_grant(
            p_token text, p_backend_pid integer, p_transaction_id bigint,
            p_tenant_id uuid, p_user_id uuid, p_role text)
        RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $wso$
        DECLARE grant_row wso_private.tenant_grants%ROWTYPE; membership_role text;
                installed integer;
        BEGIN
            -- A different backend must commit consumption before the target can
            -- see its context. A target rollback therefore cannot revive a grant.
            IF p_token IS NULL OR length(p_token) <> 64
               OR p_backend_pid = pg_backend_pid()
               OR p_transaction_id IS NULL OR p_transaction_id <= 0
               OR p_transaction_id > txid_current()
               OR NOT EXISTS (
                   SELECT 1 FROM pg_stat_activity
                   WHERE pid = p_backend_pid AND usename = 'wso_app'
                     AND datname = current_database()
               ) OR NOT EXISTS (
                   SELECT 1 FROM pg_locks
                   WHERE pid = p_backend_pid AND locktype = 'transactionid'
                     AND mode = 'ExclusiveLock' AND granted
                     AND transactionid::text::bigint = p_transaction_id % 4294967296
               ) THEN RETURN false; END IF;
            SELECT * INTO grant_row FROM wso_private.tenant_grants
            WHERE token_hash = sha256(convert_to(p_token, 'UTF8')) FOR UPDATE;
            IF NOT FOUND OR grant_row.consumed_at IS NOT NULL
               OR grant_row.expires_at <= clock_timestamp()
               OR grant_row.tenant_id IS DISTINCT FROM p_tenant_id
               OR grant_row.user_id IS DISTINCT FROM p_user_id
               OR grant_row.role IS DISTINCT FROM p_role
            THEN RETURN false; END IF;
            SELECT m.role INTO membership_role FROM public.memberships AS m
            WHERE m.tenant_id = grant_row.tenant_id AND m.user_id = grant_row.user_id
            FOR SHARE;
            IF NOT FOUND OR membership_role IS DISTINCT FROM grant_row.role
            THEN RETURN false; END IF;
            -- ON CONFLICT locks and checks the latest row atomically. Two
            -- different grants racing for one PID/XID cannot replace scope.
            INSERT INTO wso_private.tenant_contexts AS existing
                (backend_pid, transaction_id, tenant_id, user_id, role)
            VALUES (p_backend_pid, p_transaction_id, grant_row.tenant_id,
                    grant_row.user_id, grant_row.role)
            ON CONFLICT (backend_pid) DO UPDATE SET
                transaction_id = EXCLUDED.transaction_id,
                tenant_id = EXCLUDED.tenant_id, user_id = EXCLUDED.user_id,
                role = EXCLUDED.role
            WHERE existing.transaction_id <> EXCLUDED.transaction_id;
            GET DIAGNOSTICS installed = ROW_COUNT;
            IF installed = 0 THEN RETURN false; END IF;
            UPDATE wso_private.tenant_grants SET consumed_at = clock_timestamp()
            WHERE token_hash = grant_row.token_hash;
            RETURN true;
        END; $wso$
    """,
        "wso_app",
    )
    _function(
        "wso_current_tenant_id()",
        """
        CREATE FUNCTION public.wso_current_tenant_id() RETURNS uuid
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog AS $wso$
        DECLARE context_row wso_private.tenant_contexts%ROWTYPE; membership_role text;
        BEGIN
            SELECT * INTO context_row FROM wso_private.tenant_contexts
            WHERE backend_pid = pg_backend_pid() AND transaction_id = txid_current();
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT m.role INTO membership_role FROM public.memberships AS m
            WHERE m.tenant_id = context_row.tenant_id AND m.user_id = context_row.user_id
            FOR SHARE;
            IF NOT FOUND OR membership_role IS DISTINCT FROM context_row.role
            THEN RETURN NULL; END IF;
            RETURN context_row.tenant_id;
        END; $wso$
    """,
        "wso_app",
    )
    for table in TENANT_TABLES:
        column = "id" if table == "tenants" else "tenant_id"
        predicate = f"{column} = public.wso_current_tenant_id()"
        op.execute(
            f"ALTER POLICY {table}_tenant_policy ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    # The old validation API is retained for reversible downgrade, but is no
    # longer an application capability or authority for any RLS policy.
    op.execute(
        "REVOKE ALL ON FUNCTION public.wso_validate_tenant_authorization(uuid, uuid, text) FROM wso_app"
    )


def downgrade() -> None:
    for table in TENANT_TABLES:
        column = "id" if table == "tenants" else "tenant_id"
        predicate = (
            f"{column} = nullif(current_setting('app.tenant_id', true), '')::uuid"
        )
        op.execute(
            f"ALTER POLICY {table}_tenant_policy ON {table} "
            f"USING ({predicate}) WITH CHECK ({predicate})"
        )
    op.execute("DROP FUNCTION public.wso_current_tenant_id()")
    op.execute(
        "DROP FUNCTION public.wso_consume_tenant_grant(text, integer, bigint, uuid, uuid, text)"
    )
    op.execute("DROP FUNCTION public.wso_issue_tenant_grant(uuid)")
    op.execute("DROP TABLE wso_private.tenant_contexts")
    op.execute("DROP TABLE wso_private.tenant_grants")
    op.execute("DROP SCHEMA wso_private")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_validate_tenant_authorization(uuid, uuid, text) TO wso_app"
    )
