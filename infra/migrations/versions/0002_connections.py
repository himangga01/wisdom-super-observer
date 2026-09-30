"""Encrypted connection lifecycle and function-only worker capabilities."""

from alembic import op

revision = "0002_connections"
down_revision = "0001c_auth_sessions"
branch_labels = None
depends_on = None


def function(signature, sql, role):
    op.execute(sql)
    op.execute(f"ALTER FUNCTION public.{signature} OWNER TO wso_migrator")
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    if role:
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")


def upgrade():
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='wso_connection_worker') THEN CREATE ROLE wso_connection_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; END IF; END $$"
    )
    op.execute(
        "ALTER ROLE wso_connection_worker LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member='wso_connection_worker'::regrole OR roleid='wso_connection_worker'::regrole) THEN RAISE EXCEPTION 'worker role membership is forbidden'; END IF; END $$"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO wso_connection_worker")
    op.execute("""
        CREATE TABLE public.connections (
            id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES public.tenants(id),
            kind text NOT NULL CHECK(kind IN ('TVT_ACCOUNT','TVT_DEVICE','TYCO_ACCOUNT')),
            alias varchar(200) NOT NULL CHECK(length(alias)>0), site varchar(500) NOT NULL CHECK(length(site)>0),
            status text NOT NULL CHECK(status IN ('NOT_VERIFIED','DISCONNECTED')),
            last_success timestamptz, generation bigint NOT NULL CHECK(generation>0),
            UNIQUE(tenant_id,id));
        CREATE TABLE public.store_connections (
            tenant_id uuid NOT NULL, connection_id uuid NOT NULL, store_id uuid NOT NULL,
            PRIMARY KEY(tenant_id,connection_id,store_id),
            FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id) ON DELETE CASCADE,
            FOREIGN KEY(tenant_id,store_id) REFERENCES public.stores(tenant_id,id));
        CREATE TABLE wso_private.connection_secrets (
            connection_id uuid PRIMARY KEY REFERENCES public.connections(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL, version_id uuid NOT NULL UNIQUE,
            nonce bytea NOT NULL CHECK(octet_length(nonce)=12), ciphertext bytea NOT NULL CHECK(octet_length(ciphertext)>=16),
            FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id) ON DELETE CASCADE);
        CREATE TABLE wso_private.connection_handles (
            digest bytea PRIMARY KEY, tenant_id uuid NOT NULL, connection_id uuid NOT NULL REFERENCES public.connections(id) ON DELETE CASCADE,
            actor_id uuid NOT NULL, generation bigint NOT NULL, version_id uuid NOT NULL, expires_at timestamptz NOT NULL);
        CREATE TABLE wso_private.connection_leases (
            digest bytea PRIMARY KEY, tenant_id uuid NOT NULL, connection_id uuid NOT NULL REFERENCES public.connections(id) ON DELETE CASCADE,
            actor_id uuid NOT NULL, generation bigint NOT NULL, version_id uuid NOT NULL, expires_at timestamptz NOT NULL);
        CREATE TABLE wso_private.connection_revocations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(), tenant_id uuid NOT NULL,
            connection_id uuid NOT NULL, generation bigint NOT NULL, reason text NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT clock_timestamp());
    """)
    for schema, names in (
        ("public", ("connections", "store_connections")),
        (
            "wso_private",
            (
                "connection_secrets",
                "connection_handles",
                "connection_leases",
                "connection_revocations",
            ),
        ),
    ):
        for table in names:
            op.execute(f"ALTER TABLE {schema}.{table} OWNER TO wso_migrator")
            op.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_migration_policy ON {schema}.{table} TO wso_migrator USING(true) WITH CHECK(true)"
            )
            op.execute(
                f"REVOKE ALL ON {schema}.{table} FROM PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker"
            )
    function(
        "wso_connection_owner()",
        """
    CREATE FUNCTION public.wso_connection_owner() RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE tenant uuid; actor uuid;
    BEGIN
        tenant := public.wso_current_tenant_id();
        SELECT user_id INTO actor FROM wso_private.tenant_contexts
        WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current()
        AND tenant_id=tenant AND role='OWNER';
        RETURN actor;
    END; $wso$""",
        "wso_app",
    )
    for table in ("connections", "store_connections"):
        op.execute(f"GRANT SELECT ON public.{table} TO wso_app")
        op.execute(
            f"CREATE POLICY {table}_owner_policy ON public.{table} TO wso_app USING(tenant_id=public.wso_current_tenant_id() AND public.wso_connection_owner() IS NOT NULL)"
        )
    function(
        "wso_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text)",
        """
    CREATE FUNCTION public.wso_mutate_connection(p_id uuid,p_expected bigint,p_action text,p_data jsonb,p_version uuid,p_nonce bytea,p_cipher bytea,p_correlation text)
    RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE tenant uuid; actor uuid; current_row public.connections%ROWTYPE; next_generation bigint; store_id uuid;
    BEGIN
        tenant := public.wso_current_tenant_id(); actor := public.wso_connection_owner();
        IF tenant IS NULL OR actor IS NULL THEN RAISE EXCEPTION 'connection denied' USING ERRCODE='42501'; END IF;
        IF p_action NOT IN ('create','update','disconnect','delete') THEN RAISE EXCEPTION 'invalid action' USING ERRCODE='22023'; END IF;
        IF p_action='create' THEN
            IF p_expected IS DISTINCT FROM 0 OR p_version IS NULL OR p_nonce IS NULL OR p_cipher IS NULL THEN RAISE EXCEPTION 'invalid credentials' USING ERRCODE='22023'; END IF;
            next_generation := 1;
            INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation)
            VALUES(p_id,tenant,p_data->>'kind',p_data->>'alias',p_data->>'site','NOT_VERIFIED',1);
        ELSE
            SELECT * INTO current_row FROM public.connections WHERE id=p_id AND tenant_id=tenant FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'connection missing' USING ERRCODE='P0002'; END IF;
            IF current_row.generation IS DISTINCT FROM p_expected THEN RAISE EXCEPTION 'generation conflict' USING ERRCODE='40001'; END IF;
            next_generation := current_row.generation+1;
            INSERT INTO wso_private.connection_revocations(tenant_id,connection_id,generation,reason) VALUES(tenant,p_id,current_row.generation,p_action);
            DELETE FROM wso_private.connection_handles WHERE connection_id=p_id;
            DELETE FROM wso_private.connection_leases WHERE connection_id=p_id;
            IF p_action IN ('disconnect','delete') THEN DELETE FROM wso_private.connection_secrets WHERE connection_id=p_id; END IF;
            IF p_action='delete' THEN DELETE FROM public.connections WHERE id=p_id;
            ELSE UPDATE public.connections SET generation=next_generation,
                alias=COALESCE(p_data->>'alias',alias), site=COALESCE(p_data->>'site',site),
                status=CASE WHEN p_action='disconnect' THEN 'DISCONNECTED' WHEN p_version IS NOT NULL THEN 'NOT_VERIFIED' ELSE status END,
                last_success=NULL WHERE id=p_id;
            END IF;
        END IF;
        IF p_action IN ('create','update') THEN
            IF p_version IS NOT NULL THEN
                INSERT INTO wso_private.connection_secrets(connection_id,tenant_id,version_id,nonce,ciphertext) VALUES(p_id,tenant,p_version,p_nonce,p_cipher)
                ON CONFLICT(connection_id) DO UPDATE SET version_id=EXCLUDED.version_id,nonce=EXCLUDED.nonce,ciphertext=EXCLUDED.ciphertext;
            END IF;
            IF p_data ? 'store_ids' THEN
                DELETE FROM public.store_connections WHERE connection_id=p_id;
                FOR store_id IN SELECT value::uuid FROM jsonb_array_elements_text(p_data->'store_ids') LOOP
                    PERFORM 1 FROM public.stores WHERE id=store_id AND tenant_id=tenant AND active FOR SHARE;
                    IF NOT FOUND THEN RAISE EXCEPTION 'store missing' USING ERRCODE='P0002'; END IF;
                    INSERT INTO public.store_connections(tenant_id,connection_id,store_id) VALUES(tenant,p_id,store_id) ON CONFLICT DO NOTHING;
                END LOOP;
            END IF;
        END IF;
        INSERT INTO public.audit_events(id,tenant_id,actor_user_id,action,entity_type,entity_id,correlation_id,result)
        VALUES(gen_random_uuid(),tenant,actor,'connections:'||p_action,'connection',p_id,p_correlation,'success');
        RETURN next_generation;
    END; $wso$""",
        "wso_app",
    )
    function(
        "wso_issue_connection_handle(uuid,bigint)",
        """
    CREATE FUNCTION public.wso_issue_connection_handle(p_id uuid,p_generation bigint) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE tenant uuid; actor uuid; version uuid; token text;
    BEGIN
        tenant := public.wso_current_tenant_id(); actor := public.wso_connection_owner();
        IF actor IS NULL THEN RETURN NULL; END IF;
        PERFORM 1 FROM public.connections WHERE id=p_id AND tenant_id=tenant AND generation=p_generation AND status='NOT_VERIFIED' FOR SHARE;
        IF NOT FOUND THEN RETURN NULL; END IF;
        SELECT version_id INTO version FROM wso_private.connection_secrets WHERE connection_id=p_id;
        IF NOT FOUND THEN RETURN NULL; END IF;
        token := replace(gen_random_uuid()::text,'-','') || replace(gen_random_uuid()::text,'-','');
        INSERT INTO wso_private.connection_handles VALUES(sha256(convert_to(token,'UTF8')),tenant,p_id,actor,p_generation,version,clock_timestamp()+interval '30 seconds');
        RETURN token;
    END; $wso$""",
        "wso_app",
    )
    function(
        "wso_redeem_connection_handle(text,text)",
        """
    CREATE FUNCTION public.wso_redeem_connection_handle(p_token text,p_lease text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE h wso_private.connection_handles%ROWTYPE; member_role text;
    BEGIN
        SELECT * INTO h FROM wso_private.connection_handles WHERE digest=sha256(convert_to(p_token,'UTF8'));
        IF NOT FOUND OR h.expires_at<=clock_timestamp() OR p_lease !~ '^[0-9a-f]{64}$' THEN RETURN false; END IF;
        SELECT role INTO member_role FROM public.memberships WHERE tenant_id=h.tenant_id AND user_id=h.actor_id FOR SHARE;
        IF member_role IS DISTINCT FROM 'OWNER' THEN RETURN false; END IF;
        PERFORM 1 FROM public.connections WHERE id=h.connection_id AND tenant_id=h.tenant_id AND generation=h.generation AND status='NOT_VERIFIED' FOR SHARE;
        IF NOT FOUND THEN RETURN false; END IF;
        DELETE FROM wso_private.connection_handles WHERE digest=h.digest AND expires_at>clock_timestamp() RETURNING * INTO h;
        IF NOT FOUND THEN RETURN false; END IF;
        INSERT INTO wso_private.connection_leases VALUES(sha256(convert_to(p_lease,'UTF8')),h.tenant_id,h.connection_id,h.actor_id,h.generation,h.version_id,h.expires_at);
        RETURN true;
    END; $wso$""",
        "wso_connection_worker",
    )
    function(
        "wso_use_connection_lease(text)",
        """
    CREATE FUNCTION public.wso_use_connection_lease(p_lease text)
    RETURNS TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE h wso_private.connection_leases%ROWTYPE; member_role text;
    BEGIN
        SELECT * INTO h FROM wso_private.connection_leases WHERE digest=sha256(convert_to(p_lease,'UTF8'));
        IF NOT FOUND OR h.expires_at<=clock_timestamp() THEN RETURN; END IF;
        SELECT role INTO member_role FROM public.memberships WHERE memberships.tenant_id=h.tenant_id AND user_id=h.actor_id FOR SHARE;
        IF member_role IS DISTINCT FROM 'OWNER' THEN RETURN; END IF;
        PERFORM 1 FROM public.connections c WHERE c.id=h.connection_id AND c.tenant_id=h.tenant_id AND c.generation=h.generation AND c.status='NOT_VERIFIED' FOR SHARE;
        IF NOT FOUND OR h.expires_at<=clock_timestamp() THEN RETURN; END IF;
        RETURN QUERY SELECT s.tenant_id,s.connection_id,s.version_id,s.nonce,s.ciphertext FROM wso_private.connection_secrets s WHERE s.connection_id=h.connection_id AND s.version_id=h.version_id;
    END; $wso$""",
        "wso_connection_worker",
    )


def downgrade():
    for signature in (
        "wso_use_connection_lease(text)",
        "wso_redeem_connection_handle(text,text)",
        "wso_issue_connection_handle(uuid,bigint)",
        "wso_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text)",
    ):
        op.execute(f"DROP FUNCTION public.{signature}")
    for table in (
        "connection_leases",
        "connection_handles",
        "connection_secrets",
        "connection_revocations",
    ):
        op.execute(f"DROP TABLE wso_private.{table}")
    op.execute("DROP TABLE public.store_connections")
    op.execute("DROP TABLE public.connections")
    op.execute("DROP FUNCTION public.wso_connection_owner()")
