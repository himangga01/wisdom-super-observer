"""First TVT/Tyco metadata slice; no credential or operation admission."""

from alembic import op

revision = "0004_tvt_domain"
down_revision = "0003a_assets"
branch_labels = None
depends_on = None

OWNER = "wso_domain_owner"
RUNTIME = (
    "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,"
    "wso_job_worker,wso_dispatcher,wso_asset_maintenance"
)
TABLES = (
    "tvt_identities",
    "tvt_device_links",
    "tvt_channels",
    "tvt_device_store_links",
    "tvt_identity_grants",
    "tvt_upstream_grants",
    "tvt_capability_snapshots",
    "tyco_identities",
    "tyco_panels",
    "tyco_identity_grants",
    "tyco_upstream_grants",
    "tyco_capability_snapshots",
)
READS = {
    "wso_private.tenant_contexts": "backend_pid,transaction_id,tenant_id,user_id,role",
    "public.memberships": "tenant_id,user_id,role",
    "public.stores": "tenant_id,id,active",
    "public.store_memberships": "tenant_id,user_id,store_id",
    "public.connections": "tenant_id,id,kind,status,generation",
}
SIGNATURE = "wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text)"


def upgrade() -> None:
    op.execute(f"""
      DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{OWNER}') THEN
          CREATE ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
        END IF;
      END $$;
      ALTER ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
        NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_auth_members
          WHERE member='{OWNER}'::regrole OR roleid='{OWNER}'::regrole) THEN
          RAISE EXCEPTION 'domain role membership is forbidden';
        END IF;
      END $$;
      GRANT USAGE ON SCHEMA public,wso_private TO {OWNER};
      ALTER TABLE public.connections ADD CONSTRAINT tvt_connection_kind_fk_key
        UNIQUE(tenant_id,id,kind);
    """)
    for domain, connection in (("tvt", "TVT_ACCOUNT"), ("tyco", "TYCO_ACCOUNT")):
        op.execute(f"""
          CREATE TABLE wso_private.{domain}_identities(
            id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
            connection_id uuid NOT NULL, connection_kind text NOT NULL DEFAULT '{connection}'
              CHECK(connection_kind='{connection}'),
            region varchar(64) NOT NULL CHECK(region ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{{0,63}}$'),
            brand varchar(64) NOT NULL CHECK(brand ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{{0,63}}$'),
            active boolean NOT NULL DEFAULT true,
            UNIQUE(tenant_id,id), UNIQUE(tenant_id,connection_id),
            FOREIGN KEY(tenant_id,connection_id,connection_kind)
              REFERENCES public.connections(tenant_id,id,kind) ON DELETE CASCADE
          );
        """)
    op.execute("""
      CREATE TABLE wso_private.tvt_device_links(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL,
        active boolean NOT NULL DEFAULT true,
        UNIQUE(tenant_id,identity_id,id),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tvt_identities(tenant_id,id) ON DELETE CASCADE
      );
      CREATE TABLE wso_private.tvt_channels(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL, device_id uuid NOT NULL,
        active boolean NOT NULL DEFAULT true,
        UNIQUE(tenant_id,identity_id,device_id,id),
        FOREIGN KEY(tenant_id,identity_id,device_id) REFERENCES wso_private.tvt_device_links(tenant_id,identity_id,id) ON DELETE CASCADE
      );
      CREATE TABLE wso_private.tvt_device_store_links(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL,
        device_id uuid NOT NULL, channel_id uuid, store_id uuid NOT NULL,
        revision bigint NOT NULL CHECK(revision>0), active boolean NOT NULL DEFAULT true,
        UNIQUE(tenant_id,identity_id,id),
        UNIQUE NULLS NOT DISTINCT(tenant_id,identity_id,device_id,channel_id,store_id),
        FOREIGN KEY(tenant_id,identity_id,device_id) REFERENCES wso_private.tvt_device_links(tenant_id,identity_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,identity_id,device_id,channel_id) REFERENCES wso_private.tvt_channels(tenant_id,identity_id,device_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,store_id) REFERENCES public.stores(tenant_id,id)
      );
      CREATE TABLE wso_private.tvt_identity_grants(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL, actor_id uuid NOT NULL,
        action text NOT NULL CHECK(action IN ('account.read','device.read','media.live')),
        link_id uuid, revision bigint NOT NULL CHECK(revision>0), expires_at timestamptz NOT NULL,
        CHECK((action='account.read' AND link_id IS NULL) OR (action IN ('device.read','media.live') AND link_id IS NOT NULL)),
        UNIQUE NULLS NOT DISTINCT(tenant_id,identity_id,actor_id,action,link_id),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tvt_identities(tenant_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,identity_id,link_id) REFERENCES wso_private.tvt_device_store_links(tenant_id,identity_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,actor_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE
      );
      CREATE TABLE wso_private.tyco_panels(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL,
        active boolean NOT NULL DEFAULT true, UNIQUE(tenant_id,identity_id,id),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tyco_identities(tenant_id,id) ON DELETE CASCADE
      );
      CREATE TABLE wso_private.tyco_identity_grants(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL, actor_id uuid NOT NULL,
        action text NOT NULL CHECK(action IN ('account.read','panel.read')), panel_id uuid,
        revision bigint NOT NULL CHECK(revision>0), expires_at timestamptz NOT NULL,
        CHECK((action='account.read' AND panel_id IS NULL) OR (action='panel.read' AND panel_id IS NOT NULL)),
        UNIQUE NULLS NOT DISTINCT(tenant_id,identity_id,actor_id,action,panel_id),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tyco_identities(tenant_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,identity_id,panel_id) REFERENCES wso_private.tyco_panels(tenant_id,identity_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,actor_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE
      );
    """)
    # Both independent observations must be present. These are local semantics,
    # not guessed upstream flag names. No runtime role can assert verification.
    for name in ("tvt_upstream_grants", "tvt_capability_snapshots"):
        op.execute(f"""
          CREATE TABLE wso_private.{name}(
            id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL,
            device_id uuid, channel_id uuid,
            action text NOT NULL CHECK(action IN ('account.read','device.read','media.live')),
            verified boolean NOT NULL DEFAULT false,
            connection_generation bigint NOT NULL CHECK(connection_generation>0),
            revision bigint NOT NULL CHECK(revision>0), observed_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK(expires_at>observed_at),
            CHECK((action='account.read' AND device_id IS NULL AND channel_id IS NULL)
              OR (action='device.read' AND device_id IS NOT NULL)
              OR (action='media.live' AND device_id IS NOT NULL AND channel_id IS NOT NULL)),
            UNIQUE NULLS NOT DISTINCT(tenant_id,identity_id,device_id,channel_id,action),
            FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tvt_identities(tenant_id,id) ON DELETE CASCADE,
            FOREIGN KEY(tenant_id,identity_id,device_id) REFERENCES wso_private.tvt_device_links(tenant_id,identity_id,id) ON DELETE CASCADE,
            FOREIGN KEY(tenant_id,identity_id,device_id,channel_id) REFERENCES wso_private.tvt_channels(tenant_id,identity_id,device_id,id) ON DELETE CASCADE
          );
        """)
    for name in ("tyco_upstream_grants", "tyco_capability_snapshots"):
        op.execute(f"""
          CREATE TABLE wso_private.{name}(
            id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL, panel_id uuid,
            action text NOT NULL CHECK(action IN ('account.read','panel.read')),
            verified boolean NOT NULL DEFAULT false,
            connection_generation bigint NOT NULL CHECK(connection_generation>0),
            revision bigint NOT NULL CHECK(revision>0), observed_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK(expires_at>observed_at),
            CHECK((action='account.read' AND panel_id IS NULL) OR (action='panel.read' AND panel_id IS NOT NULL)),
            UNIQUE NULLS NOT DISTINCT(tenant_id,identity_id,panel_id,action),
            FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tyco_identities(tenant_id,id) ON DELETE CASCADE,
            FOREIGN KEY(tenant_id,identity_id,panel_id) REFERENCES wso_private.tyco_panels(tenant_id,identity_id,id) ON DELETE CASCADE
          );
        """)
    for table in TABLES:
        op.execute(f"""
          ALTER TABLE wso_private.{table}
            ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();
          ALTER TABLE wso_private.{table} OWNER TO {OWNER};
          ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
          GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY domain_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY domain_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);
        """)
    for table, columns in READS.items():
        op.execute(f"GRANT SELECT({columns}) ON {table} TO {OWNER}")
        op.execute(
            f"CREATE POLICY domain_metadata_read ON {table} FOR SELECT TO {OWNER} USING(true)"
        )
    # R41: an independent assignment must not be writable by its STAFF subject.
    # Restrictive write policies compose with the existing tenant policy; they
    # neither change SELECT visibility nor replace legacy OWNER management.
    op.execute("""
      CREATE FUNCTION public.wso_domain_assignment_owner(p_tenant uuid) RETURNS boolean
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT EXISTS(
          SELECT 1 FROM wso_private.tenant_contexts c
          JOIN public.memberships m ON m.tenant_id=c.tenant_id AND m.user_id=c.user_id
          WHERE c.backend_pid=pg_backend_pid() AND c.transaction_id=txid_current()
            AND c.tenant_id=p_tenant AND c.role='OWNER' AND m.role=c.role
        )
      $wso$;
      CREATE POLICY domain_assignment_insert ON public.store_memberships
        AS RESTRICTIVE FOR INSERT TO wso_app
        WITH CHECK(public.wso_domain_assignment_owner(tenant_id));
      CREATE POLICY domain_assignment_update ON public.store_memberships
        AS RESTRICTIVE FOR UPDATE TO wso_app
        USING(public.wso_domain_assignment_owner(tenant_id))
        WITH CHECK(public.wso_domain_assignment_owner(tenant_id));
      CREATE POLICY domain_assignment_delete ON public.store_memberships
        AS RESTRICTIVE FOR DELETE TO wso_app
        USING(public.wso_domain_assignment_owner(tenant_id));
    """)
    op.execute(
        f"ALTER FUNCTION public.wso_domain_assignment_owner(uuid) OWNER TO {OWNER}"
    )
    op.execute(
        f"REVOKE ALL ON FUNCTION public.wso_domain_assignment_owner(uuid) FROM {RUNTIME}"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_domain_assignment_owner(uuid) TO wso_app"
    )
    # No privilege elevation or table IO is needed to maintain NEW's timestamps.
    op.execute("""
      CREATE FUNCTION wso_private.wso_domain_timestamps() RETURNS trigger
      LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $wso$
      DECLARE stamped timestamptz := clock_timestamp();
      BEGIN
        IF TG_OP='INSERT' THEN
          NEW.created_at:=stamped;
        ELSE
          NEW.created_at:=OLD.created_at;
        END IF;
        NEW.updated_at:=stamped;
        RETURN NEW;
      END; $wso$;
    """)
    op.execute(f"ALTER FUNCTION wso_private.wso_domain_timestamps() OWNER TO {OWNER}")
    op.execute(
        f"REVOKE ALL ON FUNCTION wso_private.wso_domain_timestamps() FROM {RUNTIME}"
    )
    for table in TABLES:
        op.execute(f"""
          CREATE TRIGGER domain_timestamps BEFORE INSERT OR UPDATE ON wso_private.{table}
          FOR EACH ROW EXECUTE FUNCTION wso_private.wso_domain_timestamps();
        """)
    op.execute("""
      CREATE FUNCTION public.wso_authorize_domain(
        p_domain text,p_identity uuid,p_device uuid,p_channel uuid,p_store uuid,p_panel uuid,p_action text)
      RETURNS TABLE(tenant_id uuid,actor_id uuid,role text,domain text,identity_id uuid,
        device_id uuid,channel_id uuid,store_id uuid,panel_id uuid,action text,
        member boolean,store_assigned boolean,identity_granted boolean,linked boolean,
        upstream_allowed boolean,capability_verified boolean,grant_id uuid,grant_revision bigint,
        capability_revision bigint,upstream_revision bigint,link_revision bigint,
        connection_generation bigint,valid_until timestamptz)
      LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      DECLARE ctx record; selected record;
      BEGIN
        -- Reject repeatable snapshots that could retain revoked metadata.
        IF current_setting('transaction_isolation') <> 'read committed' THEN RETURN; END IF;
        SELECT c.tenant_id,c.user_id,c.role INTO ctx FROM wso_private.tenant_contexts c
          JOIN public.memberships m ON m.tenant_id=c.tenant_id AND m.user_id=c.user_id AND m.role=c.role
          WHERE c.backend_pid=pg_backend_pid() AND c.transaction_id=txid_current();
        IF NOT FOUND OR p_domain IS NULL OR p_domain NOT IN ('TVT','TYCO') OR p_action IS NULL
          OR p_action NOT IN ('account.login','account.read','device.read','media.live','panel.read') THEN RETURN; END IF;
        tenant_id:=ctx.tenant_id; actor_id:=ctx.user_id; role:=ctx.role; domain:=p_domain;
        identity_id:=p_identity; device_id:=p_device; channel_id:=p_channel;
        store_id:=p_store; panel_id:=p_panel; action:=p_action; member:=true;
        store_assigned:=false; identity_granted:=false; linked:=false;
        upstream_allowed:=false; capability_verified:=false;
        grant_revision:=0; capability_revision:=0; upstream_revision:=0;
        link_revision:=0; connection_generation:=0;
        IF p_action='account.login' THEN
          IF p_identity IS NULL AND p_device IS NULL AND p_channel IS NULL AND p_store IS NULL AND p_panel IS NULL THEN RETURN NEXT; END IF;
          RETURN;
        END IF;
        IF p_identity IS NULL THEN RETURN; END IF;
        IF p_domain='TVT' THEN
          IF p_panel IS NOT NULL OR p_action='panel.read'
            OR (p_action='account.read' AND (p_device IS NOT NULL OR p_store IS NOT NULL OR p_channel IS NOT NULL))
            OR (p_action IN ('device.read','media.live') AND (p_device IS NULL OR p_store IS NULL))
            OR (p_action='media.live' AND p_channel IS NULL) THEN RETURN; END IF;
          SELECT g.id,g.revision AS gr,u.revision AS ur,v.revision AS vr,
            coalesce(l.revision,0) AS lr,c.generation AS cg,
            least(g.expires_at,u.expires_at,v.expires_at) AS expiry INTO selected
          FROM wso_private.tvt_identities i
          JOIN public.connections c ON c.tenant_id=i.tenant_id AND c.id=i.connection_id
            AND c.kind='TVT_ACCOUNT' AND c.status='NOT_VERIFIED'
          JOIN wso_private.tvt_identity_grants g ON g.tenant_id=i.tenant_id AND g.identity_id=i.id
            AND g.actor_id=ctx.user_id AND g.action=p_action
          LEFT JOIN wso_private.tvt_device_store_links l ON l.tenant_id=g.tenant_id AND l.identity_id=g.identity_id AND l.id=g.link_id
          JOIN wso_private.tvt_upstream_grants u ON u.tenant_id=i.tenant_id AND u.identity_id=i.id
            AND u.device_id IS NOT DISTINCT FROM p_device AND u.channel_id IS NOT DISTINCT FROM p_channel AND u.action=p_action
          JOIN wso_private.tvt_capability_snapshots v ON v.tenant_id=i.tenant_id AND v.identity_id=i.id
            AND v.device_id IS NOT DISTINCT FROM p_device AND v.channel_id IS NOT DISTINCT FROM p_channel AND v.action=p_action
          WHERE i.tenant_id=ctx.tenant_id AND i.id=p_identity AND i.active AND u.verified AND v.verified
            AND u.connection_generation=c.generation AND v.connection_generation=c.generation
            AND u.observed_at<=clock_timestamp() AND v.observed_at<=clock_timestamp()
            AND least(g.expires_at,u.expires_at,v.expires_at)>clock_timestamp()
            AND ((p_action='account.read' AND g.link_id IS NULL) OR
              (l.active AND l.device_id=p_device AND l.channel_id IS NOT DISTINCT FROM p_channel AND l.store_id=p_store
               AND EXISTS(SELECT 1 FROM public.stores s JOIN public.store_memberships sm ON sm.tenant_id=s.tenant_id AND sm.store_id=s.id
                 WHERE s.tenant_id=ctx.tenant_id AND s.id=p_store AND s.active AND sm.user_id=ctx.user_id)
               AND EXISTS(SELECT 1 FROM wso_private.tvt_device_links d WHERE d.tenant_id=i.tenant_id AND d.identity_id=i.id AND d.id=p_device AND d.active)
               AND (p_channel IS NULL OR EXISTS(SELECT 1 FROM wso_private.tvt_channels ch WHERE ch.tenant_id=i.tenant_id AND ch.identity_id=i.id AND ch.device_id=p_device AND ch.id=p_channel AND ch.active))));
          IF NOT FOUND THEN RETURN; END IF;
          store_assigned:=p_device IS NOT NULL; linked:=p_device IS NOT NULL;
        ELSE
          IF p_device IS NOT NULL OR p_channel IS NOT NULL OR p_store IS NOT NULL
            OR p_action NOT IN ('account.read','panel.read')
            OR (p_action='account.read' AND p_panel IS NOT NULL)
            OR (p_action='panel.read' AND p_panel IS NULL) THEN RETURN; END IF;
          SELECT g.id,g.revision AS gr,u.revision AS ur,v.revision AS vr,
            0::bigint AS lr,c.generation AS cg,least(g.expires_at,u.expires_at,v.expires_at) AS expiry INTO selected
          FROM wso_private.tyco_identities i
          JOIN public.connections c ON c.tenant_id=i.tenant_id AND c.id=i.connection_id
            AND c.kind='TYCO_ACCOUNT' AND c.status='NOT_VERIFIED'
          JOIN wso_private.tyco_identity_grants g ON g.tenant_id=i.tenant_id AND g.identity_id=i.id AND g.actor_id=ctx.user_id
            AND g.action=p_action AND g.panel_id IS NOT DISTINCT FROM p_panel
          JOIN wso_private.tyco_upstream_grants u ON u.tenant_id=i.tenant_id AND u.identity_id=i.id
            AND u.panel_id IS NOT DISTINCT FROM p_panel AND u.action=p_action
          JOIN wso_private.tyco_capability_snapshots v ON v.tenant_id=i.tenant_id AND v.identity_id=i.id
            AND v.panel_id IS NOT DISTINCT FROM p_panel AND v.action=p_action
          WHERE i.tenant_id=ctx.tenant_id AND i.id=p_identity AND i.active AND u.verified AND v.verified
            AND u.connection_generation=c.generation AND v.connection_generation=c.generation
            AND u.observed_at<=clock_timestamp() AND v.observed_at<=clock_timestamp()
            AND least(g.expires_at,u.expires_at,v.expires_at)>clock_timestamp()
            AND (p_panel IS NULL OR EXISTS(SELECT 1 FROM wso_private.tyco_panels p WHERE p.tenant_id=i.tenant_id AND p.identity_id=i.id AND p.id=p_panel AND p.active));
          IF NOT FOUND THEN RETURN; END IF;
        END IF;
        IF selected.expiry<=clock_timestamp() THEN RETURN; END IF;
        identity_granted:=true; upstream_allowed:=true; capability_verified:=true;
        grant_id:=selected.id; grant_revision:=selected.gr; capability_revision:=selected.vr;
        upstream_revision:=selected.ur; link_revision:=selected.lr;
        connection_generation:=selected.cg; valid_until:=selected.expiry;
        RETURN NEXT;
      END; $wso$;
    """)
    op.execute(f"ALTER FUNCTION public.{SIGNATURE} OWNER TO {OWNER}")
    op.execute(f"REVOKE ALL ON FUNCTION public.{SIGNATURE} FROM {RUNTIME}")
    op.execute(f"GRANT EXECUTE ON FUNCTION public.{SIGNATURE} TO wso_app")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION public.{SIGNATURE}")
    for action in ("insert", "update", "delete"):
        op.execute(
            f"DROP POLICY domain_assignment_{action} ON public.store_memberships"
        )
    op.execute("DROP FUNCTION public.wso_domain_assignment_owner(uuid)")
    # Explicit reverse dependency order; no CASCADE into foundation objects.
    for table in (
        "tyco_capability_snapshots",
        "tyco_upstream_grants",
        "tyco_identity_grants",
        "tyco_panels",
        "tyco_identities",
        "tvt_capability_snapshots",
        "tvt_upstream_grants",
        "tvt_identity_grants",
        "tvt_device_store_links",
        "tvt_channels",
        "tvt_device_links",
        "tvt_identities",
    ):
        op.execute(f"DROP TABLE wso_private.{table}")
    op.execute("DROP FUNCTION wso_private.wso_domain_timestamps()")
    for table, columns in READS.items():
        op.execute(f"DROP POLICY domain_metadata_read ON {table}")
        op.execute(f"REVOKE SELECT({columns}) ON {table} FROM {OWNER}")
    op.execute(
        "ALTER TABLE public.connections DROP CONSTRAINT tvt_connection_kind_fk_key"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public,wso_private FROM {OWNER}")
