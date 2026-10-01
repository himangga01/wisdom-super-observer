"""Protected user/profile startup preferences and versioned consent."""

from alembic import op

revision = "0006_tvt_startup"
down_revision = "0005_tvt_credentials"
branch_labels = None
depends_on = None

OWNER = "wso_domain_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = ("tvt_user_preferences", "tvt_user_consents")
FUNCTIONS = (
    "public.wso_tvt_startup_read(text,text)",
    "public.wso_tvt_preferences_write(text,text,text)",
    "public.wso_tvt_consent_write(text,text,text)",
    "public.wso_tvt_startup_accounts()",
    "wso_private.wso_tvt_startup_actor()",
)


def upgrade() -> None:
    # 0004 already established the private owner and exact metadata ACLs.
    # No existing ACL, function, policy or row is changed by this migration.
    op.execute("""
      CREATE TABLE wso_private.tvt_user_preferences(
        tenant_id uuid NOT NULL, user_id uuid NOT NULL,
        profile_id text NOT NULL CHECK(profile_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        locale text NOT NULL CHECK(length(locale)<=35 AND locale ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
        timezone text NOT NULL CHECK(length(timezone) BETWEEN 1 AND 64),
        updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(tenant_id,user_id,profile_id),
        FOREIGN KEY(tenant_id,user_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE
      );
      CREATE TABLE wso_private.tvt_user_consents(
        tenant_id uuid NOT NULL, user_id uuid NOT NULL,
        profile_id text NOT NULL CHECK(profile_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        version text NOT NULL CHECK(version ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        status text NOT NULL CHECK(status IN ('accepted','declined')),
        decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(tenant_id,user_id,profile_id,version),
        FOREIGN KEY(tenant_id,user_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE
      );
    """)
    for table in TABLES:
        op.execute(f"""
          ALTER TABLE wso_private.{table} OWNER TO {OWNER};
          ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
          GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY startup_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY startup_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);
        """)
    op.execute("""
      CREATE FUNCTION wso_private.wso_tvt_startup_actor()
      RETURNS TABLE(tenant_id uuid,user_id uuid)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT c.tenant_id,c.user_id FROM wso_private.tenant_contexts c
        JOIN public.memberships m ON m.tenant_id=c.tenant_id AND m.user_id=c.user_id AND m.role=c.role
        WHERE c.backend_pid=pg_backend_pid() AND c.transaction_id=txid_current()
          AND current_setting('transaction_isolation')='read committed'
      $wso$;
      CREATE FUNCTION public.wso_tvt_startup_read(p_profile text,p_version text)
      RETURNS TABLE(locale text,timezone text,status text,decided_at timestamptz)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT p.locale,p.timezone,s.status,s.decided_at
        FROM wso_private.wso_tvt_startup_actor() a
        LEFT JOIN wso_private.tvt_user_preferences p ON p.tenant_id=a.tenant_id AND p.user_id=a.user_id AND p.profile_id=p_profile
        LEFT JOIN wso_private.tvt_user_consents s ON s.tenant_id=a.tenant_id AND s.user_id=a.user_id AND s.profile_id=p_profile AND s.version=p_version
      $wso$;
      CREATE FUNCTION public.wso_tvt_preferences_write(p_profile text,p_locale text,p_timezone text)
      RETURNS TABLE(locale text,timezone text)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        INSERT INTO wso_private.tvt_user_preferences AS p(tenant_id,user_id,profile_id,locale,timezone)
        SELECT a.tenant_id,a.user_id,p_profile,p_locale,p_timezone
        FROM wso_private.wso_tvt_startup_actor() a
        WHERE EXISTS(SELECT 1 FROM pg_timezone_names z WHERE z.name=p_timezone)
        ON CONFLICT(tenant_id,user_id,profile_id) DO UPDATE
          SET locale=EXCLUDED.locale,timezone=EXCLUDED.timezone,updated_at=clock_timestamp()
        RETURNING p.locale,p.timezone
      $wso$;
      CREATE FUNCTION public.wso_tvt_consent_write(p_profile text,p_version text,p_status text)
      RETURNS TABLE(status text,decided_at timestamptz)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        INSERT INTO wso_private.tvt_user_consents AS s(tenant_id,user_id,profile_id,version,status)
        SELECT a.tenant_id,a.user_id,p_profile,p_version,p_status FROM wso_private.wso_tvt_startup_actor() a
        ON CONFLICT(tenant_id,user_id,profile_id,version) DO UPDATE
          SET status=EXCLUDED.status,decided_at=clock_timestamp()
        RETURNING s.status,s.decided_at
      $wso$;
      CREATE FUNCTION public.wso_tvt_startup_accounts()
      RETURNS TABLE(id uuid,brand text,region text)
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT i.id,i.brand::text,i.region::text
        FROM wso_private.wso_tvt_startup_actor() ctx
        JOIN wso_private.tvt_identities i ON i.tenant_id=ctx.tenant_id AND i.active
        CROSS JOIN LATERAL public.wso_authorize_domain('TVT',i.id,NULL,NULL,NULL,NULL,'account.read') a
        WHERE a.tenant_id=ctx.tenant_id AND a.actor_id=ctx.user_id
          AND a.member AND a.identity_granted AND a.upstream_allowed AND a.capability_verified
          AND a.grant_revision>0 AND a.upstream_revision>0 AND a.capability_revision>0
          AND a.connection_generation>0 AND a.valid_until>clock_timestamp()
        ORDER BY i.id
      $wso$;
    """)
    for signature in FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME}")
        if signature.startswith("public."):
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO wso_app")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    for table in TABLES:
        op.execute(f"DROP TABLE wso_private.{table}")
