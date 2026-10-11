"""Independent OWNER local media leases, native permission grants and tombstones."""

from alembic import op

revision = "0013_tvt_local_media_leases"
down_revision = "0012_tvt_local_devices"
branch_labels = None
depends_on = None
OWNER = "wso_tvt_local_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = (
    "tvt_local_media_leases",
    "tvt_local_media_grants",
    "tvt_local_media_controls",
)


def upgrade():
    op.execute("""
    CREATE TABLE wso_private.tvt_local_media_leases(
      id uuid PRIMARY KEY, ticket_digest bytea NOT NULL UNIQUE CHECK(octet_length(ticket_digest)=32),
      authority_digest bytea UNIQUE CHECK(octet_length(authority_digest)=32),
      tenant_id uuid NOT NULL,actor_id uuid NOT NULL,session_digest text NOT NULL,
      tenant_epoch bigint NOT NULL,connection_id uuid NOT NULL,generation bigint NOT NULL,
      version_id uuid NOT NULL,store_id uuid NOT NULL,device_id uuid NOT NULL,channel_id uuid NOT NULL,
      inventory_revision bigint NOT NULL CHECK(inventory_revision BETWEEN 1 AND 9007199254740991),
      grant_revision bigint NOT NULL DEFAULT 1 CHECK(grant_revision BETWEEN 1 AND 9007199254740991),
      worker_epoch uuid,native_generation uuid, stream text NOT NULL CHECK(stream IN ('main','sub')),
      state text NOT NULL CHECK(state IN ('REQUESTED','LOGIN','CLAIMED','NEGOTIATING','PLAYING','STOPPING','CLOSED')),
      invalidated boolean NOT NULL DEFAULT false, cleanup_confirmed boolean NOT NULL DEFAULT false,
      issued_at timestamptz NOT NULL,login_expires_at timestamptz NOT NULL,
      heartbeat_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
      ttl_seconds integer NOT NULL CHECK(ttl_seconds BETWEEN 5 AND 30),
      CHECK(login_expires_at>issued_at AND login_expires_at<=issued_at+interval '30 seconds'),
      CHECK(expires_at>=heartbeat_at AND expires_at<=heartbeat_at+ttl_seconds*interval '1 second'));
    CREATE INDEX local_media_expiry ON wso_private.tvt_local_media_leases(expires_at);
    CREATE UNIQUE INDEX local_media_active ON wso_private.tvt_local_media_leases(connection_id,channel_id)
      WHERE state NOT IN ('STOPPING','CLOSED');
    CREATE INDEX local_media_open ON wso_private.tvt_local_media_leases(tenant_id) WHERE state<>'CLOSED';
    CREATE TABLE wso_private.tvt_local_media_grants(
      id uuid PRIMARY KEY,lease_id uuid NOT NULL UNIQUE REFERENCES wso_private.tvt_local_media_leases(id) ON DELETE CASCADE,
      revision bigint NOT NULL CHECK(revision BETWEEN 1 AND 9007199254740991),
      native_generation uuid NOT NULL,permission_proof jsonb NOT NULL,invalidated boolean NOT NULL DEFAULT false);
    CREATE TABLE wso_private.tvt_local_media_controls(
      digest bytea PRIMARY KEY CHECK(octet_length(digest)=32),
      lease_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_leases(id) ON DELETE CASCADE,
      purpose text NOT NULL CHECK(purpose IN ('offer','stop','playing')), consumed boolean NOT NULL DEFAULT false,
      issued_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
      CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '20 seconds'));
    """)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} OWNER TO {OWNER};
        ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
        GRANT ALL ON wso_private.{table} TO wso_migrator;
        CREATE POLICY local_media_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
        CREATE POLICY local_media_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);""")
    for name, args, returns, body, grantee in FUNCTIONS:
        signature = f"{name}({args})"
        op.execute(
            f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $media$ {body} $media$"
        )
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME}")
        if grantee:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {grantee}")
    for table, event in LIFECYCLE:
        op.execute(
            f"CREATE TRIGGER local_media_revoke AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION wso_private.wso_tvt_local_media_revoke()"
        )


LIVE = """
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR l.id IS NULL OR l.invalidated OR l.expires_at<=clock_timestamp() OR l.state NOT IN ('REQUESTED','LOGIN','CLAIMED','NEGOTIATING','PLAYING') THEN RETURN false; END IF;
 IF l.state IN ('REQUESTED','LOGIN','CLAIMED') AND l.login_expires_at<=clock_timestamp() THEN RETURN false; END IF;
 PERFORM 1 FROM public.tenants x WHERE x.id=l.tenant_id AND x.job_generation=l.tenant_epoch FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.memberships x WHERE x.tenant_id=l.tenant_id AND x.user_id=l.actor_id AND x.role='OWNER' FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.connections x WHERE x.tenant_id=l.tenant_id AND x.id=l.connection_id AND x.kind='TVT_DEVICE' AND x.status='NOT_VERIFIED' AND x.generation=l.generation FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.stores x WHERE x.tenant_id=l.tenant_id AND x.id=l.store_id AND x.active FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.store_connections x WHERE x.tenant_id=l.tenant_id AND x.connection_id=l.connection_id AND x.store_id=l.store_id FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.web_sessions x WHERE x.session_digest=l.session_digest AND x.user_id=l.actor_id AND x.revoked_at IS NULL AND x.expires_at>clock_timestamp() FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.connection_secrets x WHERE x.tenant_id=l.tenant_id AND x.connection_id=l.connection_id AND x.version_id=l.version_id FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_local_devices d JOIN public.web_sessions s ON s.session_digest=d.session_digest AND s.user_id=d.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 WHERE d.id=l.device_id AND d.tenant_id=l.tenant_id AND d.connection_id=l.connection_id AND d.store_id=l.store_id AND d.actor_id=l.actor_id AND d.generation=l.generation AND d.tenant_epoch=l.tenant_epoch AND d.revision=l.inventory_revision AND NOT d.invalidated FOR SHARE OF d,s;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_local_channels x WHERE x.id=l.channel_id AND x.tenant_id=l.tenant_id AND x.device_id=l.device_id AND x.revision=l.inventory_revision AND x.active FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF l.state IN ('NEGOTIATING','PLAYING') THEN
   PERFORM 1 FROM wso_private.tvt_local_media_grants g WHERE g.lease_id=l.id AND g.revision=l.grant_revision AND g.native_generation=l.native_generation AND NOT g.invalidated FOR SHARE;
   IF NOT FOUND THEN RETURN false; END IF;
 END IF;
 RETURN l.expires_at>clock_timestamp();
END;
"""
VIEW = """
BEGIN
 RETURN jsonb_build_object('id',l.id,'owner',jsonb_build_object('tenant_id',l.tenant_id,'actor_user_id',l.actor_id,'connection_id',l.connection_id,'store_id',l.store_id),
 'device',jsonb_build_object('tenant_id',l.tenant_id,'actor_user_id',l.actor_id,'connection_id',l.connection_id,'store_id',l.store_id,'device_id',l.device_id,'channel_id',l.channel_id),
 'channel',l.channel_id,'kind','live','state',CASE WHEN l.invalidated OR l.expires_at<=clock_timestamp() THEN CASE WHEN l.cleanup_confirmed THEN 'CLOSED' ELSE 'STOPPING' END ELSE l.state END,
 'expires_at',l.expires_at,'heartbeat_at',l.heartbeat_at,'connection_generation',l.generation,'inventory_revision',l.inventory_revision,'grant_revision',l.grant_revision);
END;
"""
ISSUE = """
DECLARE l wso_private.tvt_local_media_leases; token text; actual bigint;
BEGIN
 l.tenant_id:=public.wso_current_tenant_id(); l.actor_id:=public.wso_connection_owner();
 IF l.tenant_id IS NULL OR l.actor_id IS NULL OR p_session IS NULL OR p_session!~'^[0-9a-f]{64}$' OR p_generation IS NULL OR p_generation NOT BETWEEN 1 AND 9007199254740991 OR p_revision IS NULL OR p_revision NOT BETWEEN 1 AND 9007199254740991 OR p_ttl IS NULL OR p_ttl NOT BETWEEN 5 AND 30 OR p_stream IS NULL OR p_stream NOT IN ('main','sub') THEN RETURN NULL; END IF;
 SELECT c.generation INTO actual FROM public.connections c WHERE c.tenant_id=l.tenant_id AND c.id=p_connection AND c.kind='TVT_DEVICE';
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF actual<>p_generation THEN RAISE EXCEPTION 'local media generation conflict' USING ERRCODE='40001'; END IF;
 SELECT x.job_generation INTO l.tenant_epoch FROM public.tenants x WHERE x.id=l.tenant_id;
 SELECT x.version_id INTO l.version_id FROM wso_private.connection_secrets x WHERE x.tenant_id=l.tenant_id AND x.connection_id=p_connection;
 IF NOT FOUND THEN RETURN NULL; END IF;
 l.id:=gen_random_uuid();l.session_digest:=p_session;l.connection_id:=p_connection;l.generation:=p_generation;l.store_id:=p_store;l.device_id:=p_device;l.channel_id:=p_channel;l.inventory_revision:=p_revision;l.grant_revision:=1;l.stream:=p_stream;l.state:='REQUESTED';l.invalidated:=false;l.ttl_seconds:=p_ttl;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');l.ticket_digest:=sha256(convert_to(token,'UTF8'));
 l.issued_at:=clock_timestamp();l.login_expires_at:=l.issued_at+interval '20 seconds';l.heartbeat_at:=l.issued_at;l.expires_at:=l.issued_at+p_ttl*interval '1 second';
 IF NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 PERFORM pg_advisory_xact_lock(711300001);
 UPDATE wso_private.tvt_local_media_leases x SET invalidated=true,state=CASE WHEN x.worker_epoch IS NULL THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=(x.worker_epoch IS NULL) WHERE x.state<>'CLOSED' AND x.expires_at<=clock_timestamp();
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases x WHERE x.connection_id=p_connection AND x.channel_id=p_channel AND x.state<>'CLOSED')
 OR (SELECT count(*) FROM wso_private.tvt_local_media_leases x WHERE x.state<>'CLOSED')>=32
 OR (SELECT count(*) FROM wso_private.tvt_local_media_leases x WHERE x.tenant_id=l.tenant_id AND x.actor_id=l.actor_id AND x.state<>'CLOSED')>=4 THEN RAISE EXCEPTION 'local media capacity' USING ERRCODE='53300'; END IF;
 IF NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 INSERT INTO wso_private.tvt_local_media_leases(id,ticket_digest,tenant_id,actor_id,session_digest,tenant_epoch,connection_id,generation,version_id,store_id,device_id,channel_id,inventory_revision,grant_revision,stream,state,issued_at,login_expires_at,heartbeat_at,expires_at,ttl_seconds)
 VALUES(l.id,l.ticket_digest,l.tenant_id,l.actor_id,l.session_digest,l.tenant_epoch,l.connection_id,l.generation,l.version_id,l.store_id,l.device_id,l.channel_id,l.inventory_revision,l.grant_revision,l.stream,l.state,l.issued_at,l.login_expires_at,l.heartbeat_at,l.expires_at,l.ttl_seconds);
 RETURN token;
END;
"""
REDEEM = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 IF p_ticket IS NULL OR p_ticket!~'^[0-9a-f]{64}$' OR p_authority IS NULL OR p_authority!~'^[0-9a-f]{64}$' OR p_worker IS NULL OR p_native IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.ticket_digest=sha256(convert_to(p_ticket,'UTF8')) AND x.state='REQUESTED';
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases x SET authority_digest=sha256(convert_to(p_authority,'UTF8')),worker_epoch=p_worker,native_generation=p_native,state='LOGIN' WHERE x.id=l.id AND x.state='REQUESTED' AND NOT x.invalidated AND x.expires_at>clock_timestamp() AND x.login_expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN l.id;
END;
"""
USE = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native AND x.state='LOGIN';
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN; END IF;
 UPDATE wso_private.tvt_local_media_leases x SET state='CLAIMED' WHERE x.id=l.id AND x.state='LOGIN' AND NOT x.invalidated AND x.login_expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN; END IF;
 RETURN QUERY SELECT l.tenant_id,l.connection_id,l.version_id,s.nonce,s.ciphertext,c.guid,c.raw_index,c.window_index,c.ordinal,c.kind,l.stream FROM wso_private.connection_secrets s JOIN wso_private.tvt_local_channels c ON c.tenant_id=l.tenant_id AND c.id=l.channel_id AND c.device_id=l.device_id AND c.active AND c.revision=l.inventory_revision WHERE s.tenant_id=l.tenant_id AND s.connection_id=l.connection_id AND s.version_id=l.version_id;
END;
"""
CURRENT = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native;
 RETURN FOUND AND wso_private.wso_tvt_local_media_live(l);
END;
"""
PROOF = """
BEGIN
 IF jsonb_typeof(p_proof) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(p_proof))<>9 OR (p_proof - ARRAY['login_accepted','same_original_session','serial_matched','channel_matched','live_permission','codec_supported','framing_verified','timing_verified','codec']::text[])<>'{}'::jsonb THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM unnest(ARRAY['login_accepted','same_original_session','serial_matched','channel_matched','live_permission']) k WHERE p_proof->k IS DISTINCT FROM 'true'::jsonb) THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM unnest(ARRAY['codec_supported','framing_verified','timing_verified']) k WHERE jsonb_typeof(p_proof->k) IS DISTINCT FROM 'boolean') THEN RETURN false; END IF;
 IF p_proof->'codec' IS DISTINCT FROM 'null'::jsonb AND p_proof->>'codec' NOT IN ('h264','hevc') THEN RETURN false; END IF;
 IF p_delivery AND (p_proof->'codec_supported' IS DISTINCT FROM 'true'::jsonb OR p_proof->'framing_verified' IS DISTINCT FROM 'true'::jsonb OR p_proof->'timing_verified' IS DISTINCT FROM 'true'::jsonb OR p_proof->>'codec' IS NULL) THEN RETURN false; END IF;
 RETURN true;
END;
"""
ACTIVATE = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native AND x.state='CLAIMED';
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 IF NOT wso_private.wso_tvt_local_media_proof(p_proof,false) THEN RAISE EXCEPTION 'local live proof denied' USING ERRCODE='22023'; END IF;
 INSERT INTO wso_private.tvt_local_media_grants(id,lease_id,revision,native_generation,permission_proof) VALUES(gen_random_uuid(),l.id,l.grant_revision,l.native_generation,p_proof);
 UPDATE wso_private.tvt_local_media_leases x SET state='NEGOTIATING',heartbeat_at=statement_timestamp(),expires_at=statement_timestamp()+x.ttl_seconds*interval '1 second' WHERE x.id=l.id AND x.state='CLAIMED' AND NOT x.invalidated AND x.expires_at>clock_timestamp() AND x.login_expires_at>clock_timestamp() RETURNING * INTO l;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RAISE EXCEPTION 'local live activation revoked' USING ERRCODE='42501'; END IF;
 RETURN wso_private.wso_tvt_local_media_view(l);
END;
"""
WORKER_VIEW = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_view(l);
END;
"""
PLAYING = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 IF NOT wso_private.wso_tvt_local_media_proof(p_proof,true) THEN RAISE EXCEPTION 'local delivery proof denied' USING ERRCODE='22023'; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native AND x.state IN ('NEGOTIATING','PLAYING');
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases x SET state='PLAYING' WHERE x.id=l.id AND x.state IN ('NEGOTIATING','PLAYING') AND NOT x.invalidated AND x.expires_at>clock_timestamp() RETURNING * INTO l;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_view(l);
END;
"""
API = """
DECLARE l wso_private.tvt_local_media_leases; tenant uuid; actor uuid;
BEGIN
 tenant:=public.wso_current_tenant_id();actor:=public.wso_connection_owner();
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.id=p_id AND x.tenant_id=tenant AND x.actor_id=actor AND x.session_digest=p_session;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM public.connections x WHERE x.tenant_id=tenant AND x.id=l.connection_id AND x.kind='TVT_DEVICE' AND x.generation=l.generation FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM public.stores x WHERE x.tenant_id=tenant AND x.id=l.store_id AND x.active FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM public.store_connections x WHERE x.tenant_id=tenant AND x.connection_id=l.connection_id AND x.store_id=l.store_id FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM public.web_sessions x WHERE x.session_digest=p_session AND x.user_id=actor AND x.revoked_at IS NULL AND x.expires_at>clock_timestamp() FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF p_heartbeat THEN
   IF l.state NOT IN ('NEGOTIATING','PLAYING') OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
   UPDATE wso_private.tvt_local_media_leases x SET heartbeat_at=statement_timestamp(),expires_at=statement_timestamp()+x.ttl_seconds*interval '1 second' WHERE x.id=l.id AND NOT x.invalidated AND x.expires_at>clock_timestamp() AND x.state IN ('NEGOTIATING','PLAYING') RETURNING * INTO l;
   IF NOT FOUND THEN RETURN NULL; END IF;
 ELSIF l.state NOT IN ('STOPPING','CLOSED') AND NOT wso_private.wso_tvt_local_media_live(l) THEN
   UPDATE wso_private.tvt_local_media_leases x SET invalidated=true,state=CASE WHEN x.worker_epoch IS NULL THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=(x.cleanup_confirmed OR x.worker_epoch IS NULL) WHERE x.id=l.id AND x.state<>'CLOSED' RETURNING * INTO l;
   IF NOT FOUND THEN
     SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.id=p_id AND x.tenant_id=tenant AND x.actor_id=actor AND x.session_digest=p_session;
     IF NOT FOUND THEN RETURN NULL; END IF;
   END IF;
 END IF;
 RETURN wso_private.wso_tvt_local_media_view(l);
END;
"""
CONTROL_ISSUE = """
DECLARE l wso_private.tvt_local_media_leases; token text; now_at timestamptz;
BEGIN
 IF p_purpose IS NULL OR p_purpose NOT IN ('offer','stop','playing') THEN RETURN NULL; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.id=p_id AND x.tenant_id=public.wso_current_tenant_id() AND x.actor_id=public.wso_connection_owner() AND x.session_digest=p_session;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live(l) OR l.state NOT IN ('NEGOTIATING','PLAYING') THEN RETURN NULL; END IF;
 PERFORM pg_advisory_xact_lock(711300002);
 DELETE FROM wso_private.tvt_local_media_controls WHERE expires_at<=clock_timestamp() OR consumed;
 IF (SELECT count(*) FROM wso_private.tvt_local_media_controls x WHERE x.lease_id=l.id)>=4 THEN RAISE EXCEPTION 'local control capacity' USING ERRCODE='53300'; END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');now_at:=clock_timestamp();
 INSERT INTO wso_private.tvt_local_media_controls(digest,lease_id,purpose,issued_at,expires_at) VALUES(sha256(convert_to(token,'UTF8')),l.id,p_purpose,now_at,least(now_at+interval '20 seconds',l.expires_at));
 IF p_purpose='stop' THEN UPDATE wso_private.tvt_local_media_leases x SET state='STOPPING' WHERE x.id=l.id AND x.state<>'CLOSED'; END IF;
 RETURN token;
END;
"""
CONTROL_REDEEM = """
DECLARE c wso_private.tvt_local_media_controls; l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO c FROM wso_private.tvt_local_media_controls x WHERE x.digest=sha256(convert_to(p_ticket,'UTF8')) AND x.purpose=p_purpose AND NOT x.consumed AND x.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.id=c.lease_id AND x.worker_epoch=p_worker;
 IF NOT FOUND OR (p_purpose IN ('offer','playing') AND NOT wso_private.wso_tvt_local_media_live(l)) OR (p_purpose='stop' AND l.state NOT IN ('STOPPING','CLOSED')) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_controls x SET consumed=true WHERE x.digest=c.digest AND NOT x.consumed AND x.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN l.id;
END;
"""
CLOSE = """
BEGIN
 UPDATE wso_private.tvt_local_media_leases x SET invalidated=true,state=CASE WHEN p_cleanup THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=p_cleanup
 WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native AND x.state<>'CLOSED';
 UPDATE wso_private.tvt_local_media_grants g SET invalidated=true WHERE g.lease_id IN (SELECT x.id FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native);
END;
"""
REVOKE = """
DECLARE tenant uuid; actor uuid; connection uuid; store uuid; web text; device uuid; channel uuid;
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
 ELSIF TG_TABLE_NAME='connection_secrets' THEN tenant:=OLD.tenant_id;connection:=OLD.connection_id;
 ELSIF TG_TABLE_NAME='tvt_local_devices' THEN
   IF TG_OP='UPDATE' AND NEW.revision=OLD.revision AND NEW.generation=OLD.generation AND NEW.invalidated=OLD.invalidated THEN RETURN NULL; END IF;
   tenant:=OLD.tenant_id;device:=OLD.id;
 ELSIF TG_TABLE_NAME='tvt_local_channels' THEN
   IF TG_OP='UPDATE' AND NEW.revision=OLD.revision AND NEW.active=OLD.active AND NEW.guid=OLD.guid AND NEW.raw_index=OLD.raw_index AND NEW.window_index=OLD.window_index THEN RETURN NULL; END IF;
   tenant:=OLD.tenant_id;channel:=OLD.id;
 END IF;
 WITH revoked AS (UPDATE wso_private.tvt_local_media_leases l SET invalidated=true,state=CASE WHEN l.worker_epoch IS NULL THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=(l.cleanup_confirmed OR l.worker_epoch IS NULL) WHERE l.state<>'CLOSED' AND NOT (l.invalidated AND l.state='STOPPING' AND l.worker_epoch IS NOT NULL) AND (tenant IS NULL OR l.tenant_id=tenant) AND (actor IS NULL OR l.actor_id=actor) AND (connection IS NULL OR l.connection_id=connection) AND (store IS NULL OR l.store_id=store) AND (web IS NULL OR l.session_digest=web OR l.device_id IN (SELECT d.id FROM wso_private.tvt_local_devices d WHERE d.session_digest=web)) AND (device IS NULL OR l.device_id=device) AND (channel IS NULL OR l.channel_id=channel) RETURNING l.id)
 UPDATE wso_private.tvt_local_media_grants g SET invalidated=true WHERE g.lease_id IN (SELECT r.id FROM revoked r) AND NOT g.invalidated;
 RETURN NULL;
END;
"""
AUTH = "p_authority text,p_worker uuid,p_native uuid"
FUNCTIONS = (
    (
        "wso_private.wso_tvt_local_media_live",
        "l wso_private.tvt_local_media_leases",
        "boolean",
        LIVE,
        "",
    ),
    (
        "wso_private.wso_tvt_local_media_view",
        "l wso_private.tvt_local_media_leases",
        "jsonb",
        VIEW,
        "",
    ),
    (
        "wso_private.wso_tvt_local_media_proof",
        "p_proof jsonb,p_delivery boolean",
        "boolean",
        PROOF,
        "",
    ),
    (
        "public.wso_tvt_local_media_issue",
        "p_session text,p_connection uuid,p_store uuid,p_device uuid,p_channel uuid,p_generation bigint,p_revision bigint,p_stream text,p_ttl integer",
        "text",
        ISSUE,
        "wso_app",
    ),
    (
        "public.wso_tvt_local_media_redeem",
        "p_ticket text,p_authority text,p_worker uuid,p_native uuid",
        "uuid",
        REDEEM,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_use",
        AUTH,
        "TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea,guid bytea,raw_index integer,window_index integer,ordinal integer,kind text,stream text)",
        USE,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_current",
        AUTH,
        "boolean",
        CURRENT,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_activate",
        AUTH + ",p_proof jsonb",
        "jsonb",
        ACTIVATE,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_worker_view",
        AUTH,
        "jsonb",
        WORKER_VIEW,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_playing",
        AUTH + ",p_proof jsonb",
        "jsonb",
        PLAYING,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_read",
        "p_session text,p_id uuid,p_heartbeat boolean",
        "jsonb",
        API,
        "wso_app",
    ),
    (
        "public.wso_tvt_local_media_control_issue",
        "p_session text,p_id uuid,p_purpose text",
        "text",
        CONTROL_ISSUE,
        "wso_app",
    ),
    (
        "public.wso_tvt_local_media_control_redeem",
        "p_ticket text,p_purpose text,p_worker uuid",
        "uuid",
        CONTROL_REDEEM,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_local_media_close",
        AUTH + ",p_cleanup boolean",
        "void",
        CLOSE,
        "wso_connection_worker",
    ),
    ("wso_private.wso_tvt_local_media_revoke", "", "trigger", REVOKE, ""),
)
LIFECYCLE = (
    ("public.memberships", "UPDATE OR DELETE"),
    ("public.store_connections", "UPDATE OR DELETE"),
    ("public.stores", "UPDATE OF active,tenant_id,id"),
    ("public.connections", "UPDATE OF generation,status,kind OR DELETE"),
    ("public.tenants", "UPDATE OF job_generation"),
    ("public.web_sessions", "UPDATE OR DELETE"),
    ("wso_private.connection_secrets", "UPDATE OR DELETE"),
    ("wso_private.tvt_local_devices", "UPDATE OR DELETE"),
    ("wso_private.tvt_local_channels", "UPDATE OR DELETE"),
)


def downgrade():
    for table, _ in LIFECYCLE:
        op.execute(f"DROP TRIGGER local_media_revoke ON {table}")
    for name, args, *_ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {name}({args})")
    op.execute("DROP INDEX wso_private.local_media_open")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE wso_private.{table}")
