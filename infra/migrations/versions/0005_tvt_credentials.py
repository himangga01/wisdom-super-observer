"""Explicit domain admission for T04 handles; no second secret vault."""

from __future__ import annotations

from alembic import op

revision = "0005_tvt_credentials"
down_revision = "0004_tvt_domain"
branch_labels = None
depends_on = None

OWNER = "wso_domain_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
FOUNDATION = (
    "wso_issue_connection_handle(uuid,bigint)",
    "wso_issue_job_connection_handle(uuid,text,uuid)",
    "wso_redeem_connection_handle(text,text)",
    "wso_use_connection_lease(text)",
)
COLS = "digest,tenant_id,connection_id,actor_id,generation,version_id,expires_at,job_id,job_lease_generation"


def _function(signature: str, sql: str, owner: str, grantee: str) -> None:
    op.execute(sql)
    op.execute(f"ALTER FUNCTION {signature} OWNER TO {owner}")
    op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME}")
    if grantee:
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {grantee}")


def _definition_sql(source: str, target: str, replacements=()) -> str:
    """Read and transform the installed definition when the DDL executes.

    pg_get_functiondef includes the complete body and function settings, but
    not ACL/ownership. CREATE OR REPLACE preserves those on public functions;
    only newly created private backup functions receive a new restricted ACL.
    The same block executes online and is emitted verbatim in offline scripts.
    """

    def literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    edits = []
    if source != target:
        edits.append((source.split("(")[0] + "(", target.split("(")[0] + "("))
    edits.extend(replacements)
    statements = []
    for old, new in edits:
        statements.append(f"""
          position := strpos(definition, {literal(old)});
          IF position = 0 THEN
            RAISE EXCEPTION 'credential foundation entry point not found';
          END IF;
          definition := overlay(definition placing {literal(new)}
            from position for length({literal(old)}));
        """)
    return f"""
      DO $credential_definition$
      DECLARE definition text; position integer;
      BEGIN
        definition := pg_catalog.pg_get_functiondef({literal(source)}::regprocedure);
        {"".join(statements)}
        EXECUTE definition;
      END;
      $credential_definition$;
    """


def upgrade() -> None:
    # Hold identity writers through backfill and trigger installation so a
    # concurrent identity cannot miss the persistent mapping record.
    op.execute(
        "LOCK TABLE wso_private.tvt_identities,wso_private.tyco_identities IN SHARE ROW EXCLUSIVE MODE"
    )
    # Save the exact installed T04/T05 bodies as private functions unavailable to runtime roles.
    # Downgrade restores these, including previously installed job fences.
    for signature in FOUNDATION:
        name = signature.split("(")[0]
        backup = signature.replace(name, "credential_original_" + name, 1)
        _function(
            "wso_private." + backup,
            _definition_sql("public." + signature, "wso_private." + backup),
            "wso_migrator",
            "",
        )
    op.execute("""
      CREATE TABLE wso_private.domain_credential_capabilities(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, actor_id uuid NOT NULL,
        connection_id uuid NOT NULL, generation bigint NOT NULL CHECK(generation>0),
        version_id uuid NOT NULL, purpose text NOT NULL
          CHECK(purpose IN ('account.read','device.read','media.live','panel.read')),
        facts jsonb NOT NULL CHECK(jsonb_typeof(facts)='object'),
        expires_at timestamptz NOT NULL,
        FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id) ON DELETE CASCADE
      );
      ALTER TABLE wso_private.domain_credential_capabilities OWNER TO wso_domain_owner;
      ALTER TABLE wso_private.domain_credential_capabilities ENABLE ROW LEVEL SECURITY;
      ALTER TABLE wso_private.domain_credential_capabilities FORCE ROW LEVEL SECURITY;
      REVOKE ALL ON wso_private.domain_credential_capabilities FROM PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance;
      GRANT ALL ON wso_private.domain_credential_capabilities TO wso_migrator;
      CREATE POLICY domain_owner ON wso_private.domain_credential_capabilities TO wso_domain_owner USING(true) WITH CHECK(true);
      CREATE POLICY domain_migrator ON wso_private.domain_credential_capabilities TO wso_migrator USING(true) WITH CHECK(true);
    """)
    op.execute("""
      CREATE TABLE wso_private.domain_credential_connections(
        connection_id uuid PRIMARY KEY, tenant_id uuid NOT NULL,
        FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id) ON DELETE CASCADE);
      ALTER TABLE wso_private.domain_credential_connections OWNER TO wso_domain_owner;
      ALTER TABLE wso_private.domain_credential_connections ENABLE ROW LEVEL SECURITY;
      ALTER TABLE wso_private.domain_credential_connections FORCE ROW LEVEL SECURITY;
      REVOKE ALL ON wso_private.domain_credential_connections FROM PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance;
      GRANT ALL ON wso_private.domain_credential_connections TO wso_migrator;
      CREATE POLICY domain_owner ON wso_private.domain_credential_connections TO wso_domain_owner USING(true) WITH CHECK(true);
      CREATE POLICY domain_migrator ON wso_private.domain_credential_connections TO wso_migrator USING(true) WITH CHECK(true);
      INSERT INTO wso_private.domain_credential_connections(connection_id,tenant_id)
        SELECT connection_id,tenant_id FROM wso_private.tvt_identities
        UNION SELECT connection_id,tenant_id FROM wso_private.tyco_identities;
    """)
    for table in ("connection_handles", "connection_leases"):
        op.execute(f"""ALTER TABLE wso_private.{table}
          ADD COLUMN admission_kind text NOT NULL DEFAULT 'LEGACY' CHECK(admission_kind IN ('LEGACY','DOMAIN')),
          ADD COLUMN domain_cap_id uuid REFERENCES wso_private.domain_credential_capabilities(id),
          ADD CONSTRAINT {table}_domain_admission CHECK(
            (admission_kind='LEGACY' AND domain_cap_id IS NULL) OR
            (admission_kind='DOMAIN' AND domain_cap_id IS NOT NULL AND job_id IS NULL AND job_lease_generation IS NULL));""")
    # SELECT ... FOR SHARE requires UPDATE on at least one column. These narrow
    # privileges are private to the existing NOLOGIN owner, never runtime roles.
    for table, col in (
        ("public.memberships", "role"),
        ("public.stores", "active"),
        ("public.store_memberships", "store_id"),
        ("public.connections", "generation"),
    ):
        op.execute(f"GRANT UPDATE({col}) ON {table} TO {OWNER}")
        op.execute(
            f"CREATE POLICY domain_credential_lock ON {table} FOR UPDATE TO {OWNER} USING(true) WITH CHECK(false)"
        )
    _function(
        "wso_private.wso_connection_is_domain(uuid)",
        """
      CREATE FUNCTION wso_private.wso_connection_is_domain(p_connection uuid) RETURNS boolean
      LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT EXISTS(SELECT 1 FROM wso_private.domain_credential_connections WHERE connection_id=p_connection)
          OR EXISTS(SELECT 1 FROM wso_private.tvt_identities WHERE connection_id=p_connection)
          OR EXISTS(SELECT 1 FROM wso_private.tyco_identities WHERE connection_id=p_connection)
      $wso$""",
        OWNER,
        "wso_migrator",
    )
    _function(
        "wso_private.wso_domain_mapping_fence()",
        """
      CREATE FUNCTION wso_private.wso_domain_mapping_fence() RETURNS trigger
      LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      BEGIN
        PERFORM 1 FROM public.connections WHERE id=NEW.connection_id FOR UPDATE;
        INSERT INTO wso_private.domain_credential_connections(connection_id,tenant_id)
          VALUES(NEW.connection_id,NEW.tenant_id) ON CONFLICT(connection_id) DO NOTHING;
        RETURN NEW;
      END; $wso$""",
        OWNER,
        "",
    )
    for domain in ("tvt", "tyco"):
        op.execute(
            f"CREATE TRIGGER credential_mapping_fence BEFORE INSERT OR UPDATE OF connection_id ON wso_private.{domain}_identities FOR EACH ROW EXECUTE FUNCTION wso_private.wso_domain_mapping_fence()"
        )
    _function(
        "wso_private.wso_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid)",
        VALIDATOR,
        OWNER,
        "wso_migrator",
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text) TO wso_migrator"
    )
    _function(
        "public.wso_issue_domain_connection_handle(jsonb,text,timestamptz)",
        ISSUER,
        "wso_migrator",
        "wso_app",
    )
    for bounded in (
        "wso_private.wso_domain_mapping_fence()",
        "wso_private.wso_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid)",
        "public.wso_issue_domain_connection_handle(jsonb,text,timestamptz)",
    ):
        op.execute(f"ALTER FUNCTION {bounded} SET lock_timeout TO '3s'")
    for signature in FOUNDATION:
        # R44: deny unsupported snapshots before any admission or authority read.
        isolation_reject = (
            "RETURN NULL"
            if signature.startswith("wso_issue_")
            else "RETURN false"
            if signature.startswith("wso_redeem_")
            else "RETURN"
        )
        replacements = [
            (
                "BEGIN",
                "BEGIN\n IF current_setting('transaction_isolation') IS DISTINCT FROM 'read committed' THEN "
                + isolation_reject
                + "; END IF;\n",
            )
        ]
        if signature.startswith("wso_issue_"):
            # 0003 already names the seven legacy columns in the owner issuer.
            # Only the job issuer still relies on positional insertion.
            if signature.startswith("wso_issue_job_"):
                replacements.append(
                    (
                        "INSERT INTO wso_private.connection_handles VALUES",
                        f"INSERT INTO wso_private.connection_handles({COLS}) VALUES",
                    )
                )
            connection = (
                "p_id"
                if signature.startswith("wso_issue_connection_handle")
                else "p_connection"
            )
            replacements.append(
                (
                    "SELECT version_id INTO version",
                    f"IF wso_private.wso_connection_is_domain({connection}) THEN RETURN NULL; END IF;\n SELECT version_id INTO version",
                )
            )
        else:
            reject = "RETURN false" if "redeem" in signature else "RETURN"
            start = "IF h.job_id IS NOT NULL THEN"
            end = (
                "DELETE FROM wso_private.connection_handles"
                if "redeem" in signature
                else "RETURN QUERY SELECT"
            )
            guard = f"""IF h.admission_kind='DOMAIN' THEN
              IF wso_private.wso_validate_domain_credential(h.domain_cap_id,h.tenant_id,h.actor_id,h.connection_id,h.generation,h.version_id) IS DISTINCT FROM true
                OR h.job_id IS NOT NULL THEN {reject}; END IF;
              PERFORM 1 FROM wso_private.connection_secrets s WHERE s.connection_id=h.connection_id
                AND s.tenant_id=h.tenant_id AND s.version_id=h.version_id FOR SHARE;
              IF NOT FOUND THEN {reject}; END IF;
            ELSIF h.admission_kind='LEGACY' AND h.domain_cap_id IS NULL THEN
              IF wso_private.wso_connection_is_domain(h.connection_id) THEN {reject}; END IF;
            """
            replacements.append((start, guard + start))
            replacements.append(
                (
                    end,
                    f"ELSE {reject}; END IF;\n IF h.expires_at<=clock_timestamp() THEN {reject}; END IF;\n "
                    + end,
                )
            )
            # Re-read mapping after legacy authorization has acquired its locks.
            replacements.append(
                (
                    end,
                    f"IF h.admission_kind='LEGACY' AND wso_private.wso_connection_is_domain(h.connection_id) THEN {reject}; END IF;\n "
                    + end,
                )
            )
            if "redeem" in signature:
                replacements.extend(
                    [
                        (
                            "INSERT INTO wso_private.connection_leases VALUES",
                            f"INSERT INTO wso_private.connection_leases({COLS},admission_kind,domain_cap_id) VALUES",
                        ),
                        (
                            "h.expires_at,h.job_id,h.job_lease_generation);",
                            "h.expires_at,h.job_id,h.job_lease_generation,h.admission_kind,h.domain_cap_id);",
                        ),
                    ]
                )
        # Replacing the existing public function retains its exact ACL and owner.
        op.execute(
            _definition_sql("public." + signature, "public." + signature, replacements)
        )


def downgrade() -> None:
    for table in ("connection_handles", "connection_leases"):
        op.execute(f"DELETE FROM wso_private.{table} WHERE admission_kind='DOMAIN'")
    for signature in FOUNDATION:
        name = signature.split("(")[0]
        backup = signature.replace(name, "credential_original_" + name, 1)
        op.execute(_definition_sql("wso_private." + backup, "public." + signature))
        op.execute("DROP FUNCTION wso_private." + backup)
    op.execute(
        "DROP FUNCTION public.wso_issue_domain_connection_handle(jsonb,text,timestamptz)"
    )
    op.execute(
        "DROP FUNCTION wso_private.wso_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid)"
    )
    op.execute("DROP FUNCTION wso_private.wso_connection_is_domain(uuid)")
    for domain in ("tvt", "tyco"):
        op.execute(
            f"DROP TRIGGER credential_mapping_fence ON wso_private.{domain}_identities"
        )
    op.execute("DROP FUNCTION wso_private.wso_domain_mapping_fence()")
    for table in ("connection_handles", "connection_leases"):
        op.execute(
            f"ALTER TABLE wso_private.{table} DROP COLUMN admission_kind,DROP COLUMN domain_cap_id"
        )
    op.execute("DROP TABLE wso_private.domain_credential_capabilities")
    op.execute("DROP TABLE wso_private.domain_credential_connections")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text) FROM wso_migrator"
    )
    for table, col in (
        ("public.memberships", "role"),
        ("public.stores", "active"),
        ("public.store_memberships", "store_id"),
        ("public.connections", "generation"),
    ):
        op.execute(f"DROP POLICY domain_credential_lock ON {table}")
        op.execute(f"REVOKE UPDATE({col}) ON {table} FROM {OWNER}")


VALIDATOR = """
CREATE FUNCTION wso_private.wso_validate_domain_credential(p_cap uuid,p_tenant uuid,p_actor uuid,p_connection uuid,p_generation bigint,p_version uuid)
RETURNS boolean LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
DECLARE cap wso_private.domain_credential_capabilities%ROWTYPE; f jsonb;
  ident uuid; dev uuid; channel uuid; store uuid; panel uuid; grant_id uuid;
  i record; g record; u record; v record; l record; member_role text;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
  SELECT * INTO cap FROM wso_private.domain_credential_capabilities WHERE id=p_cap FOR SHARE;
  IF NOT FOUND OR cap.tenant_id IS DISTINCT FROM p_tenant OR cap.actor_id IS DISTINCT FROM p_actor
    OR cap.connection_id IS DISTINCT FROM p_connection OR cap.generation IS DISTINCT FROM p_generation
    OR cap.version_id IS DISTINCT FROM p_version OR cap.expires_at<=clock_timestamp() THEN RETURN false; END IF;
  f:=cap.facts; ident:=(f->>'identity_id')::uuid; dev:=(f->>'device_id')::uuid;
  channel:=(f->>'channel_id')::uuid; store:=(f->>'store_id')::uuid; panel:=(f->>'panel_id')::uuid;
  grant_id:=(f->>'grant_id')::uuid;
  IF NOT (f ?& ARRAY['tenant_id','actor_id','role','domain','identity_id','device_id','channel_id',
      'store_id','panel_id','action','member','store_assigned','identity_granted','linked',
      'upstream_allowed','capability_verified','grant_id','grant_revision','capability_revision',
      'upstream_revision','link_revision','connection_generation','valid_until'])
    OR f-ARRAY['tenant_id','actor_id','role','domain','identity_id','device_id','channel_id',
      'store_id','panel_id','action','member','store_assigned','identity_granted','linked',
      'upstream_allowed','capability_verified','grant_id','grant_revision','capability_revision',
      'upstream_revision','link_revision','connection_generation','valid_until']<>'{}'::jsonb
    OR f->'member' IS DISTINCT FROM 'true'::jsonb
    OR f->'identity_granted' IS DISTINCT FROM 'true'::jsonb
    OR f->'upstream_allowed' IS DISTINCT FROM 'true'::jsonb
    OR f->'capability_verified' IS DISTINCT FROM 'true'::jsonb
    OR f->'store_assigned' IS DISTINCT FROM to_jsonb(dev IS NOT NULL)
    OR f->'linked' IS DISTINCT FROM to_jsonb(dev IS NOT NULL)
    OR (f->>'connection_generation')::bigint IS DISTINCT FROM p_generation
    OR (f->>'valid_until')::timestamptz IS NULL
    OR cap.expires_at>(f->>'valid_until')::timestamptz
    OR EXISTS(SELECT 1 FROM jsonb_each(f) e WHERE e.key IN
      ('grant_revision','capability_revision','upstream_revision','link_revision','connection_generation')
      AND jsonb_typeof(e.value)<>'number') THEN RETURN false; END IF;
  IF ident IS NULL OR grant_id IS NULL OR cap.purpose IS DISTINCT FROM f->>'action'
    OR (f->>'tenant_id')::uuid IS DISTINCT FROM p_tenant OR (f->>'actor_id')::uuid IS DISTINCT FROM p_actor THEN RETURN false; END IF;
  SELECT role INTO member_role FROM public.memberships WHERE tenant_id=p_tenant AND user_id=p_actor FOR SHARE;
  IF NOT FOUND OR member_role IS DISTINCT FROM f->>'role' THEN RETURN false; END IF;
  PERFORM 1 FROM public.connections WHERE id=p_connection AND tenant_id=p_tenant AND generation=p_generation AND status='NOT_VERIFIED' FOR SHARE;
  IF NOT FOUND THEN RETURN false; END IF;
  IF f->>'domain'='TVT' THEN
    IF panel IS NOT NULL OR cap.purpose NOT IN ('account.read','device.read','media.live')
      OR (cap.purpose='account.read' AND (dev IS NOT NULL OR channel IS NOT NULL OR store IS NOT NULL))
      OR (cap.purpose IN ('device.read','media.live') AND (dev IS NULL OR store IS NULL))
      OR (cap.purpose='media.live' AND channel IS NULL) THEN RETURN false; END IF;
    SELECT * INTO i FROM wso_private.tvt_identities WHERE id=ident AND tenant_id=p_tenant AND connection_id=p_connection AND active FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO g FROM wso_private.tvt_identity_grants WHERE id=grant_id AND tenant_id=p_tenant AND identity_id=ident AND actor_id=p_actor AND action=cap.purpose FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF dev IS NULL THEN
      IF g.link_id IS NOT NULL OR (f->>'link_revision')::bigint IS DISTINCT FROM 0 THEN RETURN false; END IF;
    ELSE
      PERFORM 1 FROM public.stores WHERE id=store AND tenant_id=p_tenant AND active FOR SHARE;
      IF NOT FOUND THEN RETURN false; END IF;
      PERFORM 1 FROM public.store_memberships WHERE tenant_id=p_tenant AND user_id=p_actor AND store_id=store FOR SHARE;
      IF NOT FOUND THEN RETURN false; END IF;
      SELECT * INTO l FROM wso_private.tvt_device_store_links WHERE id=g.link_id AND tenant_id=p_tenant AND identity_id=ident
        AND device_id=dev AND channel_id IS NOT DISTINCT FROM channel AND store_id=store AND active FOR SHARE;
      IF NOT FOUND OR l.revision IS DISTINCT FROM (f->>'link_revision')::bigint THEN RETURN false; END IF;
      PERFORM 1 FROM wso_private.tvt_device_links WHERE id=dev AND tenant_id=p_tenant AND identity_id=ident AND active FOR SHARE;
      IF NOT FOUND THEN RETURN false; END IF;
      IF channel IS NOT NULL THEN
        PERFORM 1 FROM wso_private.tvt_channels WHERE id=channel AND tenant_id=p_tenant AND identity_id=ident AND device_id=dev AND active FOR SHARE;
        IF NOT FOUND THEN RETURN false; END IF;
      END IF;
    END IF;
    SELECT * INTO u FROM wso_private.tvt_upstream_grants WHERE tenant_id=p_tenant AND identity_id=ident AND device_id IS NOT DISTINCT FROM dev AND channel_id IS NOT DISTINCT FROM channel AND action=cap.purpose FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO v FROM wso_private.tvt_capability_snapshots WHERE tenant_id=p_tenant AND identity_id=ident AND device_id IS NOT DISTINCT FROM dev AND channel_id IS NOT DISTINCT FROM channel AND action=cap.purpose FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
  ELSIF f->>'domain'='TYCO' THEN
    IF dev IS NOT NULL OR channel IS NOT NULL OR store IS NOT NULL OR cap.purpose NOT IN ('account.read','panel.read')
      OR (cap.purpose='account.read' AND panel IS NOT NULL) OR (cap.purpose='panel.read' AND panel IS NULL)
      OR (f->>'link_revision')::bigint IS DISTINCT FROM 0 THEN RETURN false; END IF;
    SELECT * INTO i FROM wso_private.tyco_identities WHERE id=ident AND tenant_id=p_tenant AND connection_id=p_connection AND active FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO g FROM wso_private.tyco_identity_grants WHERE id=grant_id AND tenant_id=p_tenant AND identity_id=ident AND actor_id=p_actor AND action=cap.purpose AND panel_id IS NOT DISTINCT FROM panel FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    IF panel IS NOT NULL THEN
      PERFORM 1 FROM wso_private.tyco_panels WHERE id=panel AND tenant_id=p_tenant AND identity_id=ident AND active FOR SHARE;
      IF NOT FOUND THEN RETURN false; END IF;
    END IF;
    SELECT * INTO u FROM wso_private.tyco_upstream_grants WHERE tenant_id=p_tenant AND identity_id=ident AND panel_id IS NOT DISTINCT FROM panel AND action=cap.purpose FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO v FROM wso_private.tyco_capability_snapshots WHERE tenant_id=p_tenant AND identity_id=ident AND panel_id IS NOT DISTINCT FROM panel AND action=cap.purpose FOR SHARE;
    IF NOT FOUND THEN RETURN false; END IF;
  ELSE RETURN false;
  END IF;
  RETURN g.revision IS NOT DISTINCT FROM (f->>'grant_revision')::bigint
    AND u.revision IS NOT DISTINCT FROM (f->>'upstream_revision')::bigint
    AND v.revision IS NOT DISTINCT FROM (f->>'capability_revision')::bigint
    AND u.verified AND v.verified AND u.connection_generation=p_generation AND v.connection_generation=p_generation
    AND u.observed_at<=clock_timestamp() AND v.observed_at<=clock_timestamp()
    AND least(cap.expires_at,g.expires_at,u.expires_at,v.expires_at)>clock_timestamp();
END; $wso$
"""

ISSUER = """
CREATE FUNCTION public.wso_issue_domain_connection_handle(p_expected jsonb,p_purpose text,p_deadline timestamptz)
RETURNS text LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
DECLARE f record; facts jsonb; conn uuid; version uuid; cap_id uuid; expiry timestamptz; token text;
BEGIN
  IF p_purpose IS NULL OR p_purpose NOT IN ('account.read','device.read','media.live') AND p_purpose<>'panel.read'
    OR p_deadline IS NULL OR p_deadline<=clock_timestamp() OR jsonb_typeof(p_expected) IS DISTINCT FROM 'object' THEN RETURN NULL; END IF;
  SELECT * INTO f FROM public.wso_authorize_domain(p_expected->>'domain',(p_expected->>'identity_id')::uuid,
    (p_expected->>'device_id')::uuid,(p_expected->>'channel_id')::uuid,(p_expected->>'store_id')::uuid,
    (p_expected->>'panel_id')::uuid,p_expected->>'action');
  IF NOT FOUND OR f.identity_id IS NULL OR f.action IS DISTINCT FROM p_purpose THEN RETURN NULL; END IF;
  facts:=to_jsonb(f);
  IF facts-'valid_until' IS DISTINCT FROM p_expected-'valid_until'
    OR f.valid_until IS DISTINCT FROM (p_expected->>'valid_until')::timestamptz THEN RETURN NULL; END IF;
  IF f.domain='TVT' THEN
    SELECT connection_id INTO conn FROM wso_private.tvt_identities WHERE id=f.identity_id AND tenant_id=f.tenant_id;
  ELSE
    SELECT connection_id INTO conn FROM wso_private.tyco_identities WHERE id=f.identity_id AND tenant_id=f.tenant_id;
  END IF;
  PERFORM 1 FROM public.connections WHERE id=conn AND tenant_id=f.tenant_id AND generation=f.connection_generation AND status='NOT_VERIFIED' FOR SHARE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  SELECT version_id INTO version FROM wso_private.connection_secrets WHERE connection_id=conn AND tenant_id=f.tenant_id FOR SHARE;
  IF NOT FOUND THEN RETURN NULL; END IF;
  expiry:=least(p_deadline,f.valid_until,clock_timestamp()+interval '30 seconds'); cap_id:=gen_random_uuid();
  INSERT INTO wso_private.domain_credential_capabilities(id,tenant_id,actor_id,connection_id,generation,version_id,purpose,facts,expires_at)
    VALUES(cap_id,f.tenant_id,f.actor_id,conn,f.connection_generation,version,p_purpose,facts,expiry);
  IF NOT wso_private.wso_validate_domain_credential(cap_id,f.tenant_id,f.actor_id,conn,f.connection_generation,version) THEN
    DELETE FROM wso_private.domain_credential_capabilities WHERE id=cap_id; RETURN NULL;
  END IF;
  token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
  INSERT INTO wso_private.connection_handles(digest,tenant_id,connection_id,actor_id,generation,version_id,expires_at,admission_kind,domain_cap_id)
    VALUES(sha256(convert_to(token,'UTF8')),f.tenant_id,conn,f.actor_id,f.connection_generation,version,expiry,'DOMAIN',cap_id);
  RETURN token;
END; $wso$
"""
