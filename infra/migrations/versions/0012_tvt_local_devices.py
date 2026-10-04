"""OWNER/store-scoped local tickets and inventory; no cloud/media authority."""

from alembic import op

revision = "0012_tvt_local_devices"
down_revision = "0011_tvt_directory_read_tickets"
branch_labels = None
depends_on = None
OWNER = "wso_tvt_local_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = ("tvt_local_device_tickets", "tvt_local_devices", "tvt_local_channels")
METADATA = {
    "public.tenants": "id,job_generation",
    "public.memberships": "tenant_id,user_id,role",
    "public.stores": "tenant_id,id,active",
    "public.store_connections": "tenant_id,connection_id,store_id",
    "public.connections": "tenant_id,id,kind,status,generation",
    "public.web_sessions": "session_digest,user_id,expires_at,revoked_at",
    "wso_private.connection_secrets": "tenant_id,connection_id,version_id,nonce,ciphertext",
}


def upgrade():
    op.execute(f"""
      DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{OWNER}') THEN
      CREATE ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS; END IF; END $$;
      ALTER ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_auth_members WHERE member='{OWNER}'::regrole OR roleid='{OWNER}'::regrole) THEN RAISE EXCEPTION 'local role membership forbidden'; END IF; END $$;
      GRANT USAGE ON SCHEMA public,wso_private TO {OWNER};
      GRANT EXECUTE ON FUNCTION public.wso_current_tenant_id(),public.wso_connection_owner() TO {OWNER};
      CREATE TABLE wso_private.tvt_local_device_tickets(
        digest bytea PRIMARY KEY CHECK(octet_length(digest)=32), lease_digest bytea UNIQUE,
        tenant_id uuid NOT NULL,actor_id uuid NOT NULL,session_digest text NOT NULL,
        tenant_epoch bigint NOT NULL,connection_id uuid NOT NULL,generation bigint NOT NULL,
        version_id uuid NOT NULL,store_id uuid NOT NULL,
        state text NOT NULL DEFAULT 'ISSUED' CHECK(state IN ('ISSUED','REDEEMED','CLAIMED','PUBLISHED','CLOSED')),
        issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),expires_at timestamptz NOT NULL,
        CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '30 seconds'));
      CREATE UNIQUE INDEX local_verify_active ON wso_private.tvt_local_device_tickets(connection_id,generation)
        WHERE state IN ('ISSUED','REDEEMED','CLAIMED');
      CREATE INDEX local_verify_expiry ON wso_private.tvt_local_device_tickets(expires_at);
      CREATE TABLE wso_private.tvt_local_devices(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,connection_id uuid NOT NULL,
        connection_kind text NOT NULL DEFAULT 'TVT_DEVICE' CHECK(connection_kind='TVT_DEVICE'),
        store_id uuid NOT NULL,actor_id uuid NOT NULL,session_digest text NOT NULL,
        generation bigint NOT NULL CHECK(generation>0),tenant_epoch bigint NOT NULL,
        revision bigint NOT NULL CHECK(revision>0),observed_at timestamptz NOT NULL,
        invalidated boolean NOT NULL DEFAULT false,
        UNIQUE(tenant_id,id),UNIQUE(tenant_id,connection_id),
        FOREIGN KEY(tenant_id,connection_id,connection_kind) REFERENCES public.connections(tenant_id,id,kind) ON DELETE CASCADE);
      CREATE TABLE wso_private.tvt_local_channels(
        id uuid PRIMARY KEY,tenant_id uuid NOT NULL,device_id uuid NOT NULL,
        guid bytea NOT NULL CHECK(octet_length(guid)=16 AND guid<>decode(repeat('00',16),'hex')),
        raw_index integer NOT NULL CHECK(raw_index BETWEEN -128 AND 65535),
        window_index integer NOT NULL CHECK(window_index BETWEEN -128 AND 65535),
        ordinal integer NOT NULL CHECK(ordinal BETWEEN 1 AND 256),
        kind text NOT NULL CHECK(kind IN ('analog','digital','recorder')),
        revision bigint NOT NULL CHECK(revision>0),active boolean NOT NULL DEFAULT true,
        UNIQUE(tenant_id,device_id,guid),
        FOREIGN KEY(tenant_id,device_id) REFERENCES wso_private.tvt_local_devices(tenant_id,id) ON DELETE CASCADE);
      CREATE UNIQUE INDEX local_channel_ordinal ON wso_private.tvt_local_channels(device_id,ordinal) WHERE active;
    """)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} OWNER TO {OWNER};
          ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
          GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY local_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY local_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);""")
    for table, columns in METADATA.items():
        op.execute(f"GRANT SELECT({columns}) ON {table} TO {OWNER}")
        # SELECT FOR SHARE also needs UPDATE visibility. WITH CHECK(false)
        # permits row locking but prevents an actual foundation-row write.
        column = columns.split(",")[0]
        op.execute(f"GRANT UPDATE({column}) ON {table} TO {OWNER}")
        op.execute(
            f"CREATE POLICY local_metadata_read ON {table} FOR SELECT TO {OWNER} USING(true)"
        )
        op.execute(
            f"CREATE POLICY local_metadata_lock ON {table} FOR UPDATE TO {OWNER} USING(true) WITH CHECK(false)"
        )
    for name, args, returns, body, grantee in FUNCTIONS:
        signature = f"{name}({args})"
        op.execute(
            f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $local$ {body} $local$"
        )
        # Exact function identity, without accidental sibling overload changes.
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME}")
        if grantee:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {grantee}")
    for table, event in LIFECYCLE:
        op.execute(
            f"CREATE TRIGGER local_device_revoke AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION wso_private.wso_tvt_local_revoke()"
        )


LIVE = """
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR t.digest IS NULL OR t.expires_at<=clock_timestamp() OR t.state NOT IN ('ISSUED','REDEEMED','CLAIMED') THEN RETURN false; END IF;
 PERFORM 1 FROM public.tenants x WHERE x.id=t.tenant_id AND x.job_generation=t.tenant_epoch FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.memberships m WHERE m.tenant_id=t.tenant_id AND m.user_id=t.actor_id AND m.role='OWNER' FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.connections c WHERE c.tenant_id=t.tenant_id AND c.id=t.connection_id AND c.kind='TVT_DEVICE' AND c.status='NOT_VERIFIED' AND c.generation=t.generation FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.stores s WHERE s.tenant_id=t.tenant_id AND s.id=t.store_id AND s.active FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.store_connections l WHERE l.tenant_id=t.tenant_id AND l.connection_id=t.connection_id AND l.store_id=t.store_id FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.web_sessions s WHERE s.session_digest=t.session_digest AND s.user_id=t.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp() FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.connection_secrets s WHERE s.tenant_id=t.tenant_id AND s.connection_id=t.connection_id AND s.version_id=t.version_id FOR SHARE;
 RETURN FOUND AND t.expires_at>clock_timestamp();
END;
"""
ISSUE = """
DECLARE t wso_private.tvt_local_device_tickets; token text; actual bigint;
BEGIN
 t.tenant_id:=public.wso_current_tenant_id(); t.actor_id:=public.wso_connection_owner();
 IF t.tenant_id IS NULL OR t.actor_id IS NULL OR p_session IS NULL OR p_session!~'^[0-9a-f]{64}$' OR p_generation IS NULL OR p_generation NOT BETWEEN 1 AND 9007199254740991 THEN RETURN NULL; END IF;
 SELECT c.generation INTO actual FROM public.connections c WHERE c.tenant_id=t.tenant_id AND c.id=p_connection AND c.kind='TVT_DEVICE';
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF actual<>p_generation THEN RAISE EXCEPTION 'local generation conflict' USING ERRCODE='40001'; END IF;
 SELECT x.job_generation INTO t.tenant_epoch FROM public.tenants x WHERE x.id=t.tenant_id;
 SELECT s.version_id INTO t.version_id FROM wso_private.connection_secrets s WHERE s.tenant_id=t.tenant_id AND s.connection_id=p_connection;
 IF NOT FOUND THEN RETURN NULL; END IF;
 t.connection_id:=p_connection; t.generation:=p_generation; t.store_id:=p_store; t.session_digest:=p_session; t.state:='ISSUED';
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 t.digest:=sha256(convert_to(token,'UTF8')); t.issued_at:=clock_timestamp(); t.expires_at:=t.issued_at+interval '30 seconds';
 IF NOT wso_private.wso_tvt_local_live(t) THEN RETURN NULL; END IF;
 PERFORM pg_advisory_xact_lock(711200001);
 DELETE FROM wso_private.tvt_local_device_tickets WHERE expires_at<=clock_timestamp() OR state='CLOSED';
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_device_tickets x WHERE x.connection_id=p_connection AND x.generation=p_generation AND x.state IN ('ISSUED','REDEEMED','CLAIMED'))
 OR (SELECT count(*) FROM wso_private.tvt_local_device_tickets WHERE state IN ('ISSUED','REDEEMED','CLAIMED'))>=128
 OR (SELECT count(*) FROM wso_private.tvt_local_device_tickets x WHERE x.tenant_id=t.tenant_id AND x.actor_id=t.actor_id AND x.state IN ('ISSUED','REDEEMED','CLAIMED'))>=4 THEN RAISE EXCEPTION 'local capacity' USING ERRCODE='53300'; END IF;
 IF NOT wso_private.wso_tvt_local_live(t) THEN RETURN NULL; END IF;
 INSERT INTO wso_private.tvt_local_device_tickets(digest,tenant_id,actor_id,session_digest,tenant_epoch,connection_id,generation,version_id,store_id,state,issued_at,expires_at) VALUES(t.digest,t.tenant_id,t.actor_id,t.session_digest,t.tenant_epoch,t.connection_id,t.generation,t.version_id,t.store_id,t.state,t.issued_at,t.expires_at);
 RETURN token;
END;
"""
REDEEM = """
DECLARE t wso_private.tvt_local_device_tickets;
BEGIN
 IF p_ticket IS NULL OR p_ticket!~'^[0-9a-f]{64}$' OR p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN false; END IF;
 SELECT * INTO t FROM wso_private.tvt_local_device_tickets x WHERE x.digest=sha256(convert_to(p_ticket,'UTF8')) AND x.state='ISSUED';
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_live(t) THEN RETURN false; END IF;
 UPDATE wso_private.tvt_local_device_tickets SET lease_digest=sha256(convert_to(p_lease,'UTF8')),state='REDEEMED' WHERE digest=t.digest AND state='ISSUED' AND expires_at>clock_timestamp();
 RETURN FOUND;
END;
"""
USE = """
DECLARE t wso_private.tvt_local_device_tickets;
BEGIN
 IF p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN; END IF;
 SELECT * INTO t FROM wso_private.tvt_local_device_tickets x WHERE x.lease_digest=sha256(convert_to(p_lease,'UTF8')) AND x.state='REDEEMED';
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_live(t) THEN RETURN; END IF;
 UPDATE wso_private.tvt_local_device_tickets AS x SET state='CLAIMED' WHERE x.digest=t.digest AND x.state='REDEEMED' AND x.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN; END IF;
 RETURN QUERY SELECT t.tenant_id,t.actor_id,t.connection_id,t.store_id,t.generation,s.version_id,s.nonce,s.ciphertext,t.expires_at FROM wso_private.connection_secrets s WHERE s.tenant_id=t.tenant_id AND s.connection_id=t.connection_id AND s.version_id=t.version_id;
END;
"""
CURRENT = """
DECLARE t wso_private.tvt_local_device_tickets;
BEGIN
 IF p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN false; END IF;
 SELECT * INTO t FROM wso_private.tvt_local_device_tickets x WHERE x.lease_digest=sha256(convert_to(p_lease,'UTF8')) AND x.state='CLAIMED';
 RETURN FOUND AND wso_private.wso_tvt_local_live(t);
END;
"""
VIEW = """
DECLARE d wso_private.tvt_local_devices; current_gen bigint; safe boolean;
BEGIN
 SELECT generation INTO current_gen FROM public.connections c WHERE c.tenant_id=p_tenant AND c.id=p_connection AND c.kind='TVT_DEVICE';
 SELECT * INTO d FROM wso_private.tvt_local_devices x WHERE x.tenant_id=p_tenant AND x.connection_id=p_connection;
 safe:=d.id IS NOT NULL AND NOT d.invalidated AND d.generation=current_gen AND d.store_id=p_store
   AND EXISTS(SELECT 1 FROM public.tenants x WHERE x.id=p_tenant AND x.job_generation=d.tenant_epoch);
 RETURN jsonb_build_object('connection_id',p_connection,'device_id',d.id,'store_id',p_store,
   'connection_generation',current_gen,'inventory_revision',coalesce(d.revision,0),
   'inventory_state',CASE WHEN d.id IS NULL THEN 'UNAVAILABLE' WHEN safe THEN 'AVAILABLE' ELSE 'STALE' END,
   'observed_at',d.observed_at,'request_id','local-device',
   'channels',CASE WHEN safe THEN coalesce((SELECT jsonb_agg(jsonb_build_object('id',c.id,'ordinal',c.ordinal,'label','Channel '||c.ordinal::text) ORDER BY c.ordinal) FROM wso_private.tvt_local_channels c WHERE c.tenant_id=p_tenant AND c.device_id=d.id AND c.active AND c.revision=d.revision),'[]'::jsonb) ELSE '[]'::jsonb END);
END;
"""
PUBLISH = """
DECLARE t wso_private.tvt_local_device_tickets; d wso_private.tvt_local_devices; item jsonb; keys text[]; next_revision bigint;
BEGIN
 IF NOT public.wso_tvt_local_current(p_lease) THEN RETURN NULL; END IF;
 SELECT * INTO t FROM wso_private.tvt_local_device_tickets x WHERE x.lease_digest=sha256(convert_to(p_lease,'UTF8')) AND x.state='CLAIMED' FOR UPDATE;
 keys:=ARRAY['login_accepted','same_original_session','serial_matched','channels_complete','cleanup_confirmed','channels','group_provenance','metadata_branch_complete','permissions_complete','proof_verified'];
 IF p_observation IS NULL OR jsonb_typeof(p_observation)<>'object' OR octet_length(p_observation::text)>65536 OR NOT p_observation ?& keys OR p_observation-keys<>'{}'::jsonb THEN RAISE EXCEPTION 'invalid local observation' USING ERRCODE='22023'; END IF;
 FOREACH item IN ARRAY ARRAY[p_observation->'login_accepted',p_observation->'same_original_session',p_observation->'serial_matched',p_observation->'channels_complete',p_observation->'cleanup_confirmed'] LOOP
   IF item IS DISTINCT FROM 'true'::jsonb THEN RAISE EXCEPTION 'incomplete local observation' USING ERRCODE='22023'; END IF;
 END LOOP;
 FOREACH item IN ARRAY ARRAY[p_observation->'metadata_branch_complete',p_observation->'permissions_complete',p_observation->'proof_verified'] LOOP
   IF jsonb_typeof(item) IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'invalid local flags' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF jsonb_typeof(p_observation->'group_provenance') IS DISTINCT FROM 'string' OR (p_observation->>'group_provenance') NOT IN ('unavailable','missing','empty','value') OR (p_observation->>'group_provenance'<>'value' AND p_observation->'permissions_complete'<>'false'::jsonb) OR jsonb_typeof(p_observation->'channels') IS DISTINCT FROM 'array' OR jsonb_array_length(p_observation->'channels')>256 THEN RAISE EXCEPTION 'invalid local roster' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT value FROM jsonb_array_elements(p_observation->'channels') LOOP
   keys:=ARRAY['guid','raw_index','window_index','ordinal','kind'];
   IF jsonb_typeof(item) IS DISTINCT FROM 'object' OR NOT item ?& keys OR item-keys<>'{}'::jsonb OR jsonb_typeof(item->'guid') IS DISTINCT FROM 'string' OR (item->>'guid')!~'^[0-9a-f]{32}$' OR item->>'guid'=repeat('0',32) OR jsonb_typeof(item->'kind') IS DISTINCT FROM 'string' OR item->>'kind' NOT IN ('analog','digital','recorder') THEN RAISE EXCEPTION 'invalid local channel' USING ERRCODE='22023'; END IF;
   IF jsonb_typeof(item->'raw_index') IS DISTINCT FROM 'number' OR jsonb_typeof(item->'window_index') IS DISTINCT FROM 'number' OR jsonb_typeof(item->'ordinal') IS DISTINCT FROM 'number' OR (item->>'raw_index')::numeric<>trunc((item->>'raw_index')::numeric) OR (item->>'window_index')::numeric<>trunc((item->>'window_index')::numeric) OR (item->>'ordinal')::numeric<>trunc((item->>'ordinal')::numeric) OR (item->>'raw_index')::numeric NOT BETWEEN -128 AND 65535 OR (item->>'window_index')::numeric NOT BETWEEN -128 AND 65535 OR (item->>'ordinal')::numeric NOT BETWEEN 1 AND 256 THEN RAISE EXCEPTION 'invalid local index' USING ERRCODE='22023'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_observation->'channels') x GROUP BY x->>'guid' HAVING count(*)>1) OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_observation->'channels') x GROUP BY (x->>'ordinal')::integer HAVING count(*)>1) THEN RAISE EXCEPTION 'duplicate local channel' USING ERRCODE='22023'; END IF;
 SELECT * INTO d FROM wso_private.tvt_local_devices x WHERE x.tenant_id=t.tenant_id AND x.connection_id=t.connection_id FOR UPDATE;
 next_revision:=coalesce(d.revision,0)+1;
 IF next_revision>9007199254740991 THEN RAISE EXCEPTION 'local revision exhausted' USING ERRCODE='40001'; END IF;
 IF d.id IS NULL THEN d.id:=gen_random_uuid();
 ELSIF d.generation<>t.generation THEN DELETE FROM wso_private.tvt_local_channels WHERE device_id=d.id; END IF;
 INSERT INTO wso_private.tvt_local_devices(id,tenant_id,connection_id,store_id,actor_id,session_digest,generation,tenant_epoch,revision,observed_at)
 VALUES(d.id,t.tenant_id,t.connection_id,t.store_id,t.actor_id,t.session_digest,t.generation,t.tenant_epoch,next_revision,clock_timestamp())
 ON CONFLICT(tenant_id,connection_id) DO UPDATE SET store_id=EXCLUDED.store_id,actor_id=EXCLUDED.actor_id,session_digest=EXCLUDED.session_digest,generation=EXCLUDED.generation,tenant_epoch=EXCLUDED.tenant_epoch,revision=EXCLUDED.revision,observed_at=EXCLUDED.observed_at,invalidated=false;
 UPDATE wso_private.tvt_local_channels SET active=false WHERE device_id=d.id;
 FOR item IN SELECT value FROM jsonb_array_elements(p_observation->'channels') LOOP
   INSERT INTO wso_private.tvt_local_channels(id,tenant_id,device_id,guid,raw_index,window_index,ordinal,kind,revision)
   VALUES(gen_random_uuid(),t.tenant_id,d.id,decode(item->>'guid','hex'),(item->>'raw_index')::integer,(item->>'window_index')::integer,(item->>'ordinal')::integer,item->>'kind',next_revision)
   ON CONFLICT(tenant_id,device_id,guid) DO UPDATE SET raw_index=EXCLUDED.raw_index,window_index=EXCLUDED.window_index,ordinal=EXCLUDED.ordinal,kind=EXCLUDED.kind,revision=EXCLUDED.revision,active=true;
 END LOOP;
 IF NOT public.wso_tvt_local_current(p_lease) THEN RAISE EXCEPTION 'local publication revoked' USING ERRCODE='42501'; END IF;
 UPDATE wso_private.tvt_local_device_tickets SET state='PUBLISHED' WHERE digest=t.digest;
 RETURN wso_private.wso_tvt_local_view(t.tenant_id,t.connection_id,t.store_id);
END;
"""
READ = """
DECLARE tenant uuid; actor uuid; item uuid;
BEGIN
 tenant:=public.wso_current_tenant_id(); actor:=public.wso_connection_owner();
 IF tenant IS NULL OR actor IS NULL THEN RAISE EXCEPTION 'local inventory denied' USING ERRCODE='42501'; END IF;
 PERFORM 1 FROM public.stores s WHERE s.tenant_id=tenant AND s.id=p_store AND s.active FOR SHARE;
 IF NOT FOUND THEN RAISE EXCEPTION 'local inventory store denied' USING ERRCODE='42501'; END IF;
 FOR item IN SELECT c.id FROM public.connections c JOIN public.store_connections l ON l.tenant_id=c.tenant_id AND l.connection_id=c.id AND l.store_id=p_store WHERE c.tenant_id=tenant AND c.kind='TVT_DEVICE' AND (p_connection IS NULL OR c.id=p_connection) ORDER BY c.id LOOP
   RETURN NEXT wso_private.wso_tvt_local_view(tenant,item,p_store);
 END LOOP;
END;
"""
REVOKE = """
DECLARE tenant uuid; actor uuid; connection uuid; store uuid; web text;
BEGIN
 IF TG_TABLE_NAME='memberships' THEN
   IF TG_OP='UPDATE' AND NEW.role=OLD.role AND NEW.user_id=OLD.user_id AND NEW.tenant_id=OLD.tenant_id THEN RETURN NULL; END IF;
   tenant:=OLD.tenant_id;actor:=OLD.user_id;
 ELSIF TG_TABLE_NAME='store_connections' THEN tenant:=OLD.tenant_id;connection:=OLD.connection_id;store:=OLD.store_id;
 ELSIF TG_TABLE_NAME='stores' THEN
   IF NEW.active AND NEW.tenant_id=OLD.tenant_id AND NEW.id=OLD.id THEN RETURN NULL; END IF;
   tenant:=OLD.tenant_id;store:=OLD.id;
 ELSIF TG_TABLE_NAME='connections' THEN
   IF TG_OP='UPDATE' AND NEW.generation=OLD.generation AND NEW.status=OLD.status AND NEW.kind=OLD.kind THEN RETURN NULL; END IF;
   tenant:=OLD.tenant_id;connection:=OLD.id;
 ELSIF TG_TABLE_NAME='tenants' THEN
   IF NEW.job_generation=OLD.job_generation THEN RETURN NULL; END IF;
   tenant:=OLD.id;
 ELSIF TG_TABLE_NAME='web_sessions' THEN
   IF TG_OP='UPDATE' AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at AND NEW.user_id=OLD.user_id AND NEW.expires_at=OLD.expires_at THEN RETURN NULL; END IF;
   web:=OLD.session_digest;
 END IF;
 UPDATE wso_private.tvt_local_device_tickets t SET state='CLOSED' WHERE (tenant IS NULL OR t.tenant_id=tenant) AND (actor IS NULL OR t.actor_id=actor) AND (connection IS NULL OR t.connection_id=connection) AND (store IS NULL OR t.store_id=store) AND (web IS NULL OR t.session_digest=web);
 UPDATE wso_private.tvt_local_devices d SET invalidated=true WHERE (tenant IS NULL OR d.tenant_id=tenant) AND (actor IS NULL OR d.actor_id=actor) AND (connection IS NULL OR d.connection_id=connection) AND (store IS NULL OR d.store_id=store) AND (web IS NULL OR d.session_digest=web);
 RETURN NULL;
END;
"""
LIFECYCLE = (
    ("public.memberships", "UPDATE OR DELETE"),
    ("public.store_connections", "UPDATE OR DELETE"),
    ("public.stores", "UPDATE OF active,tenant_id,id"),
    ("public.connections", "UPDATE OF generation,status,kind OR DELETE"),
    ("public.tenants", "UPDATE OF job_generation"),
    ("public.web_sessions", "UPDATE OR DELETE"),
)
FUNCTIONS = (
    (
        "wso_private.wso_tvt_local_live",
        "t wso_private.tvt_local_device_tickets",
        "boolean",
        LIVE,
        "",
    ),
    (
        "public.wso_tvt_local_issue",
        "p_session text,p_connection uuid,p_store uuid,p_generation bigint",
        "text",
        ISSUE,
        "wso_app",
    ),
    (
        "public.wso_tvt_local_redeem",
        "p_ticket text,p_lease text",
        "boolean",
        REDEEM,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_use",
        "p_lease text",
        "TABLE(tenant_id uuid,actor_id uuid,connection_id uuid,store_id uuid,generation bigint,version_id uuid,nonce bytea,ciphertext bytea,expires_at timestamptz)",
        USE,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_current",
        "p_lease text",
        "boolean",
        CURRENT,
        "wso_connection_worker",
    ),
    (
        "wso_private.wso_tvt_local_view",
        "p_tenant uuid,p_connection uuid,p_store uuid",
        "jsonb",
        VIEW,
        "",
    ),
    (
        "public.wso_tvt_local_publish",
        "p_lease text,p_observation jsonb",
        "jsonb",
        PUBLISH,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_close",
        "p_lease text",
        "void",
        "BEGIN DELETE FROM wso_private.tvt_local_device_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8')); END;",
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_inventory",
        "p_connection uuid,p_store uuid",
        "SETOF jsonb",
        READ,
        "wso_app",
    ),
    ("wso_private.wso_tvt_local_revoke", "", "trigger", REVOKE, ""),
)


def downgrade():
    for table, _ in LIFECYCLE:
        op.execute(f"DROP TRIGGER local_device_revoke ON {table}")
    for name, args, *_ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {name}({args})")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE wso_private.{table}")
    for table, columns in METADATA.items():
        op.execute(f"DROP POLICY local_metadata_read ON {table}")
        op.execute(f"DROP POLICY local_metadata_lock ON {table}")
        op.execute(
            f"REVOKE SELECT({columns}),UPDATE({columns.split(',')[0]}) ON {table} FROM {OWNER}"
        )
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION public.wso_current_tenant_id(),public.wso_connection_owner() FROM {OWNER}; REVOKE USAGE ON SCHEMA public,wso_private FROM {OWNER}"
    )
