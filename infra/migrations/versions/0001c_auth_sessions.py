"""Opaque web sessions behind a dedicated function-only runtime role."""

from alembic import op

revision = "0001c_auth_sessions"
down_revision = "0001b_tenant_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = "
        "'wso_web_session') THEN CREATE ROLE wso_web_session LOGIN NOINHERIT "
        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; END IF; END $$"
    )
    op.execute(
        "ALTER ROLE wso_web_session LOGIN NOINHERIT NOSUPERUSER NOCREATEDB "
        "NOCREATEROLE NOREPLICATION NOBYPASSRLS"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_auth_members e JOIN pg_roles r "
        "ON r.oid = e.member WHERE r.rolname = 'wso_web_session') THEN RAISE "
        "EXCEPTION 'runtime role membership is forbidden'; END IF; END $$"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO wso_web_session")
    op.execute(
        "CREATE TABLE public.web_sessions ("
        "session_digest text PRIMARY KEY CHECK (session_digest ~ '^[0-9a-f]{64}$'), "
        "csrf_digest text NOT NULL CHECK (csrf_digest ~ '^[0-9a-f]{64}$'), "
        "exchange_digest text NOT NULL UNIQUE CHECK (exchange_digest ~ '^[0-9a-f]{64}$'), "
        "issuer varchar(255) NOT NULL, subject varchar(255) NOT NULL, "
        "user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE, "
        "expires_at timestamptz NOT NULL, revoked_at timestamptz, "
        "created_at timestamptz NOT NULL DEFAULT clock_timestamp(), "
        "CHECK (expires_at > created_at AND expires_at <= created_at + interval '8 hours'))"
    )
    op.execute(
        "CREATE INDEX ix_web_sessions_expiry ON public.web_sessions (expires_at)"
    )
    op.execute("ALTER TABLE public.web_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.web_sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY web_sessions_migration_policy ON public.web_sessions "
        "TO wso_migrator USING (true) WITH CHECK (true)"
    )
    op.execute("ALTER TABLE public.web_sessions OWNER TO wso_migrator")
    op.execute(
        "REVOKE ALL ON public.web_sessions FROM PUBLIC, wso_app, "
        "wso_identity_bootstrap, wso_web_session"
    )
    functions = {
        "wso_create_web_session(text,text,text,text,uuid,timestamptz,text)": """
CREATE FUNCTION public.wso_create_web_session(
    p_digest text, p_csrf text, p_issuer text, p_subject text,
    p_user_id uuid, p_expires_at timestamptz, p_exchange_digest text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $wso$
DECLARE affected integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_user_id
        AND u.oidc_issuer = p_issuer AND u.oidc_subject = p_subject)
        OR p_expires_at IS NULL
        OR p_expires_at > clock_timestamp() + interval '8 hours'
    THEN RAISE EXCEPTION 'session rejected'; END IF;
    IF p_expires_at <= clock_timestamp() THEN RETURN false; END IF;
    INSERT INTO public.web_sessions(session_digest, csrf_digest, issuer, subject,
        user_id, expires_at, exchange_digest) VALUES (p_digest, p_csrf, p_issuer, p_subject,
        p_user_id, p_expires_at, p_exchange_digest) ON CONFLICT(exchange_digest) DO NOTHING;
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected = 1;
END; $wso$
""",
        "wso_get_web_session(text)": """
CREATE FUNCTION public.wso_get_web_session(p_digest text)
RETURNS TABLE(issuer text, subject text, user_id uuid, csrf_digest text, expires_at timestamptz)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog AS $wso$
    SELECT s.issuer::text, s.subject::text, s.user_id, s.csrf_digest, s.expires_at
    FROM public.web_sessions s WHERE s.session_digest = p_digest
    AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp()
$wso$
""",
        "wso_revoke_web_session(text,text)": """
CREATE FUNCTION public.wso_revoke_web_session(p_digest text, p_csrf text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $wso$
DECLARE affected integer;
BEGIN
    UPDATE public.web_sessions s SET revoked_at = clock_timestamp()
    WHERE s.session_digest = p_digest AND s.csrf_digest = p_csrf
    AND s.revoked_at IS NULL AND s.expires_at > clock_timestamp();
    GET DIAGNOSTICS affected = ROW_COUNT;
    RETURN affected = 1;
END; $wso$
""",
    }
    for signature, ddl in functions.items():
        op.execute(ddl)
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO wso_migrator")
        op.execute(
            f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC, wso_app, wso_identity_bootstrap"
        )
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO wso_web_session")


def downgrade() -> None:
    for signature in (
        "wso_revoke_web_session(text,text)",
        "wso_get_web_session(text)",
        "wso_create_web_session(text,text,text,text,uuid,timestamptz,text)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS public.{signature}")
    op.execute("DROP TABLE public.web_sessions")
    # Environment role/password lifecycle remains outside schema rollback.
