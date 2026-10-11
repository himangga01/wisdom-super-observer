"""Add separately owned shared transport, retained slots and viewer cleanup.

Historical media functions and their ACLs are deliberately left byte-for-byte
unchanged. A worker JSON receipt records a decision; it never proves OS custody.
The Python admission boundary must first authenticate the original custodian.
"""

from alembic import op

revision = "0016_tvt_device_media_epochs"
down_revision = "0015_tvt_local_media_capacity"
branch_labels = None
depends_on = None
OWNER = "wso_tvt_local_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = (
    "tvt_local_media_walls",
    "tvt_local_media_masters",
    "tvt_local_media_slots",
    "tvt_local_media_focus_refs",
    "tvt_local_media_mux_controls",
    "tvt_local_media_master_operations",
)
OPTIONS = "LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s'"
SCHEMA = """
CREATE TABLE wso_private.tvt_local_media_walls(
 id uuid PRIMARY KEY,tenant_id uuid NOT NULL,actor_id uuid NOT NULL,
 session_digest text NOT NULL,tenant_epoch bigint NOT NULL,
 state text NOT NULL CHECK(state IN ('ACTIVE','STOPPING','CLOSED')),
 issued_at timestamptz NOT NULL,heartbeat_at timestamptz NOT NULL,
 expires_at timestamptz NOT NULL,ttl_seconds integer NOT NULL CHECK(ttl_seconds BETWEEN 5 AND 30),
 CHECK(expires_at>heartbeat_at AND expires_at<=heartbeat_at+ttl_seconds*interval '1 second'));
CREATE UNIQUE INDEX local_media_wall_active ON wso_private.tvt_local_media_walls(tenant_id,actor_id,session_digest) WHERE state<>'CLOSED';
CREATE TABLE wso_private.tvt_local_media_masters(
 id uuid PRIMARY KEY,wall_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_walls(id),
 source_lease uuid NOT NULL REFERENCES wso_private.tvt_local_media_leases(id),
 authority_digest bytea NOT NULL UNIQUE CHECK(octet_length(authority_digest)=32),
 worker_epoch uuid NOT NULL,native_generation uuid NOT NULL UNIQUE,
 tenant_id uuid NOT NULL,tenant_epoch bigint NOT NULL,actor_id uuid NOT NULL,
 session_digest text NOT NULL,store_id uuid NOT NULL,device_id uuid NOT NULL,
 connection_id uuid NOT NULL,generation bigint NOT NULL,version_id uuid NOT NULL,
 inventory_revision bigint NOT NULL,inventory_session text NOT NULL,
 state text NOT NULL CHECK(state IN ('STARTING','ACTIVE','STOPPING','QUARANTINED','CLOSED')),
 login_claimed boolean NOT NULL DEFAULT false,login_proof jsonb,
 wire_generation bigint,wire_session bytea,
 issued_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 cleanup_confirmed boolean NOT NULL DEFAULT false,
 CHECK(wire_generation IS NULL OR wire_generation>0),
 CHECK(wire_session IS NULL OR octet_length(wire_session)=16),
 CHECK(expires_at>issued_at));
CREATE UNIQUE INDEX local_media_master_open ON wso_private.tvt_local_media_masters(connection_id) WHERE state<>'CLOSED';
CREATE TABLE wso_private.tvt_local_media_slots(
 id uuid PRIMARY KEY,master_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_masters(id),
 channel_id uuid NOT NULL,channel_guid bytea NOT NULL CHECK(octet_length(channel_guid)=16),
 task_id uuid NOT NULL UNIQUE,authority_digest bytea NOT NULL UNIQUE CHECK(octet_length(authority_digest)=32),
 stream text NOT NULL DEFAULT 'sub' CHECK(stream='sub'),
 state text NOT NULL CHECK(state IN ('RESERVED','ACTIVE','PARKED','TOMBSTONED','CLOSED')),
 permission_proof jsonb,issued_at timestamptz NOT NULL,retained_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 CHECK(expires_at>retained_at AND expires_at<=retained_at+interval '30 seconds'),
 UNIQUE(master_id,channel_id));
CREATE TABLE wso_private.tvt_local_media_focus_refs(
 id uuid PRIMARY KEY,wall_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_walls(id),
 source_lease uuid NOT NULL REFERENCES wso_private.tvt_local_media_leases(id),
 attached_viewer uuid REFERENCES wso_private.tvt_local_media_leases(id),active_expires_at timestamptz,
 master_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_masters(id),
 channel_id uuid NOT NULL,direction text NOT NULL CHECK(direction IN ('FORWARD','RETURN')),
 state text NOT NULL CHECK(state IN ('PENDING','MAIN_ACTIVE','ATTACHED','CANCELLED','FAILED','EXPIRED','CONSUMED')),
 ticket_digest bytea NOT NULL UNIQUE,authority_digest bytea UNIQUE,worker_epoch uuid,
 issued_at timestamptz NOT NULL,expires_at timestamptz NOT NULL,
 CHECK(expires_at>issued_at AND expires_at<=issued_at+interval '20 seconds'));
CREATE UNIQUE INDEX local_media_focus_lane ON wso_private.tvt_local_media_focus_refs(wall_id) WHERE state IN ('PENDING','MAIN_ACTIVE');
CREATE TABLE wso_private.tvt_local_media_mux_controls(
 digest bytea PRIMARY KEY,wall_id uuid NOT NULL REFERENCES wso_private.tvt_local_media_walls(id),
 focus_id uuid REFERENCES wso_private.tvt_local_media_focus_refs(id),
 purpose text NOT NULL CHECK(purpose IN ('WALL_STOP','WALL_HEARTBEAT','FOCUS_CANCELLED','FOCUS_FAILED')),
 consumed boolean NOT NULL DEFAULT false,expires_at timestamptz NOT NULL);
ALTER TABLE wso_private.tvt_local_media_leases
 ADD COLUMN mux_wall_id uuid REFERENCES wso_private.tvt_local_media_walls(id),
 ADD COLUMN mux_master_id uuid REFERENCES wso_private.tvt_local_media_masters(id),
 ADD COLUMN mux_slot_id uuid REFERENCES wso_private.tvt_local_media_slots(id),
 ADD COLUMN mux_focus_id uuid REFERENCES wso_private.tvt_local_media_focus_refs(id),
 ADD COLUMN mux_registration uuid,
 ADD COLUMN mux_cleanup_scope text CHECK(mux_cleanup_scope IN ('VIEWER','DEDICATED_NATIVE','LAST_VIEWER_AND_DEVICE_EPOCH')),
 ADD COLUMN mux_viewer_settled boolean NOT NULL DEFAULT false,
 ADD COLUMN mux_native_settled boolean NOT NULL DEFAULT false,
 ADD COLUMN mux_acquisition_started boolean NOT NULL DEFAULT false;
CREATE TABLE wso_private.tvt_local_media_master_operations(
 operation_digest bytea PRIMARY KEY CHECK(octet_length(operation_digest)=32),
 lease_id uuid NOT NULL UNIQUE REFERENCES wso_private.tvt_local_media_leases(id),
 viewer_authority_digest bytea NOT NULL,worker_epoch uuid NOT NULL,operation_native uuid NOT NULL,
 scope jsonb NOT NULL CHECK(jsonb_typeof(scope)='object'),
 outcome text NOT NULL CHECK(outcome IN ('ABSENT','RESERVED')),
 master_id uuid REFERENCES wso_private.tvt_local_media_masters(id),creator boolean,
 issued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((outcome='ABSENT' AND master_id IS NULL AND creator IS NULL) OR
       (outcome='RESERVED' AND master_id IS NOT NULL AND creator IS NOT NULL)));
"""

# All short mutation paths serialize with the existing issue capacity lock.
LOCK = "PERFORM pg_advisory_xact_lock(711300001);"
TOKEN = (
    "replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','')"
)
AUTH = "p_authority text,p_worker uuid,p_native uuid"
MASTER_AUTH = "p_master_authority text,p_worker uuid,p_master_native uuid"
MASTER_SELECT = """SELECT * INTO m FROM wso_private.tvt_local_media_masters x
 WHERE x.authority_digest=sha256(convert_to(p_master_authority,'UTF8'))
 AND x.worker_epoch=p_worker AND x.native_generation=p_master_native;"""
VIEWER_SELECT = """SELECT * INTO l FROM wso_private.tvt_local_media_leases x
 WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8'))
 AND x.worker_epoch=p_worker AND x.native_generation=p_native;"""

WALL_CURRENT = """
BEGIN
 RETURN current_setting('transaction_isolation')='read committed' AND w.id IS NOT NULL
 AND w.state='ACTIVE' AND w.expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM public.tenants t WHERE t.id=w.tenant_id AND t.job_generation=w.tenant_epoch)
 AND EXISTS(SELECT 1 FROM public.memberships x WHERE x.tenant_id=w.tenant_id AND x.user_id=w.actor_id AND x.role='OWNER')
 AND EXISTS(SELECT 1 FROM public.web_sessions x WHERE x.session_digest=w.session_digest AND x.user_id=w.actor_id AND x.revoked_at IS NULL AND x.expires_at>clock_timestamp());
END;
"""
MASTER_SCOPE = """
DECLARE l wso_private.tvt_local_media_leases; w wso_private.tvt_local_media_walls;
BEGIN
 IF m.id IS NULL OR m.state NOT IN ('STARTING','ACTIVE') OR m.expires_at<=clock_timestamp() THEN RETURN false; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=m.wall_id;
 IF NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN false; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=m.source_lease;
 IF NOT FOUND OR (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision)
 IS DISTINCT FROM (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.store_id,m.device_id,m.connection_id,m.generation,m.version_id,m.inventory_revision) THEN RETURN false; END IF;
 -- Current metadata is independently checked even when the source viewer closed.
 l.invalidated:=false;l.state:='CLAIMED';l.expires_at:=least(m.expires_at,w.expires_at);l.login_expires_at:=l.expires_at;
 RETURN wso_private.wso_tvt_local_media_live_read(l)
 AND EXISTS(SELECT 1 FROM wso_private.tvt_local_devices d WHERE d.id=m.device_id AND d.session_digest=m.inventory_session AND d.session_digest=m.session_digest);
END;
"""
SLOT_CURRENT = """
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=s.master_id;
 RETURN s.id IS NOT NULL AND s.state IN ('RESERVED','ACTIVE','PARKED') AND s.expires_at>clock_timestamp()
 AND wso_private.wso_tvt_local_media_master_scope(m)
 AND EXISTS(SELECT 1 FROM wso_private.tvt_local_channels c WHERE c.id=s.channel_id AND c.device_id=m.device_id AND c.tenant_id=m.tenant_id AND c.revision=m.inventory_revision AND c.active AND c.guid=s.channel_guid);
END;
"""
MASTER_CURRENT = """
BEGIN
 RETURN wso_private.wso_tvt_local_media_master_scope(m)
 AND NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_slots s WHERE s.master_id=m.id AND NOT wso_private.wso_tvt_local_media_slot_current(s))
 AND (EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases l WHERE l.mux_master_id=m.id AND wso_private.wso_tvt_local_media_live_read(l))
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_focus_refs f WHERE f.master_id=m.id AND wso_private.wso_tvt_local_media_focus_current(f)));
END;
"""
MASTER_VIEW = """
BEGIN
 RETURN jsonb_build_object('master_id',m.id,'native_generation',m.native_generation,
 'tenant_id',m.tenant_id,'tenant_epoch',m.tenant_epoch,'actor_user_id',m.actor_id,
 'session_digest',m.session_digest,'wall_id',m.wall_id,'store_id',m.store_id,
 'device_id',m.device_id,'connection_id',m.connection_id,'connection_generation',m.generation,
 'secret_version',m.version_id,'inventory_revision',m.inventory_revision,'worker_epoch',m.worker_epoch,
 'expires_at',m.expires_at,'state',m.state,'wire_generation',m.wire_generation,
 'wire_session',encode(m.wire_session,'hex'),
 'creator_channel', (SELECT encode(c.guid,'hex') FROM wso_private.tvt_local_channels c JOIN wso_private.tvt_local_media_leases l ON l.channel_id=c.id WHERE l.id=m.source_lease));
END;
"""
WALL_LOCK = """
BEGIN
 IF NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN false; END IF;
 PERFORM 1 FROM public.tenants WHERE id=w.tenant_id AND job_generation=w.tenant_epoch FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.memberships WHERE tenant_id=w.tenant_id AND user_id=w.actor_id AND role='OWNER' FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.web_sessions WHERE session_digest=w.session_digest AND user_id=w.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp() FOR SHARE;
 RETURN FOUND AND w.expires_at>clock_timestamp();
END;
"""
MASTER_LOCK = """
DECLARE l wso_private.tvt_local_media_leases; w wso_private.tvt_local_media_walls; s wso_private.tvt_local_media_slots;
BEGIN
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=m.wall_id FOR SHARE;
 IF NOT wso_private.wso_tvt_local_media_wall_lock(w) OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN false; END IF;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=m.source_lease FOR SHARE;
 l.invalidated:=false;l.state:='CLAIMED';l.expires_at:=least(m.expires_at,w.expires_at);l.login_expires_at:=l.expires_at;
 IF NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN false; END IF;
 FOR s IN SELECT * FROM wso_private.tvt_local_media_slots WHERE master_id=m.id FOR SHARE LOOP
   l.channel_id:=s.channel_id;
   IF NOT wso_private.wso_tvt_local_media_slot_current(s) OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN false; END IF;
 END LOOP;
 PERFORM 1 FROM wso_private.tvt_local_media_leases WHERE mux_master_id=m.id AND state<>'CLOSED' FOR SHARE;
 PERFORM 1 FROM wso_private.tvt_local_media_focus_refs WHERE master_id=m.id AND state IN ('PENDING','MAIN_ACTIVE') FOR SHARE;
 RETURN wso_private.wso_tvt_local_media_master_current(m);
END;
"""
FINALIZE_WALL = f"""
DECLARE w wso_private.tvt_local_media_walls;
BEGIN
 {LOCK}
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall FOR UPDATE;
 IF NOT FOUND OR w.state<>'STOPPING' THEN RETURN; END IF;
 -- Only existing durable settlement facts authorize closure. Expiry is not
 -- native quiescence, and a terminal viewer does not release a physical slot.
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_masters m WHERE m.wall_id=w.id AND (m.state<>'CLOSED' OR NOT m.cleanup_confirmed))
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_slots s JOIN wso_private.tvt_local_media_masters m ON m.id=s.master_id WHERE m.wall_id=w.id AND s.state<>'CLOSED')
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases l WHERE l.mux_wall_id=w.id AND
   (l.state<>'CLOSED' OR NOT l.cleanup_confirmed OR
    (l.worker_epoch IS NOT NULL AND (NOT l.mux_viewer_settled OR
     (l.mux_cleanup_scope IN ('DEDICATED_NATIVE','LAST_VIEWER_AND_DEVICE_EPOCH') AND NOT l.mux_native_settled)))))
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_focus_refs f WHERE f.wall_id=w.id AND f.state IN ('PENDING','MAIN_ACTIVE'))
 THEN RETURN; END IF;
 UPDATE wso_private.tvt_local_media_walls SET state='CLOSED' WHERE id=w.id AND state='STOPPING';
END;
"""
STOP_MASTER = """
BEGIN
 UPDATE wso_private.tvt_local_media_masters SET state='STOPPING' WHERE id=p_id AND state NOT IN ('CLOSED','QUARANTINED');
 UPDATE wso_private.tvt_local_media_slots SET state='TOMBSTONED' WHERE master_id=p_id AND state<>'CLOSED';
 UPDATE wso_private.tvt_local_media_focus_refs SET state='CANCELLED' WHERE master_id=p_id AND state IN ('PENDING','MAIN_ACTIVE');
 UPDATE wso_private.tvt_local_media_leases SET state='STOPPING',invalidated=true,mux_cleanup_scope='LAST_VIEWER_AND_DEVICE_EPOCH'
 WHERE mux_master_id=p_id AND state<>'CLOSED';
END;
"""
WALL_ISSUE = f"""
DECLARE w wso_private.tvt_local_media_walls;
BEGIN
 {LOCK}
 w.id:=gen_random_uuid();w.tenant_id:=public.wso_current_tenant_id();w.actor_id:=public.wso_connection_owner();
 w.session_digest:=p_session;w.state:='ACTIVE';w.issued_at:=clock_timestamp();w.heartbeat_at:=w.issued_at;
 w.ttl_seconds:=p_ttl;w.expires_at:=w.issued_at+p_ttl*interval '1 second';
 w.expires_at:=least(w.expires_at,(SELECT expires_at FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id AND revoked_at IS NULL));
 SELECT job_generation INTO w.tenant_epoch FROM public.tenants WHERE id=w.tenant_id;
 IF p_ttl IS NULL OR p_ttl NOT BETWEEN 5 AND 30 OR p_session IS NULL OR p_session!~'^[0-9a-f]{{64}}$' OR NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_walls x WHERE x.tenant_id=w.tenant_id AND x.actor_id=w.actor_id AND x.state<>'CLOSED') THEN RAISE EXCEPTION 'wall capacity' USING ERRCODE='53300'; END IF;
 INSERT INTO wso_private.tvt_local_media_walls SELECT w.*;
 RETURN jsonb_build_object('id',w.id,'state',w.state,'expires_at',w.expires_at);
END;
"""
WALL_READ = f"""
DECLARE w wso_private.tvt_local_media_walls; m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN NULL; END IF;
 FOR m IN SELECT * FROM wso_private.tvt_local_media_masters WHERE wall_id=w.id AND state<>'CLOSED' LOOP
   IF NOT wso_private.wso_tvt_local_media_master_current(m) THEN
     PERFORM wso_private.wso_tvt_local_media_stop_master(m.id);RETURN NULL;
   END IF;
 END LOOP;
 IF p_heartbeat THEN
   UPDATE wso_private.tvt_local_media_walls SET heartbeat_at=statement_timestamp(),expires_at=least(statement_timestamp()+ttl_seconds*interval '1 second',(SELECT expires_at FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id AND revoked_at IS NULL)) WHERE id=w.id AND expires_at>clock_timestamp() RETURNING * INTO w;
   IF NOT FOUND THEN RETURN NULL; END IF;
   UPDATE wso_private.tvt_local_media_masters SET expires_at=w.expires_at WHERE wall_id=w.id AND state IN ('STARTING','ACTIVE') AND expires_at>clock_timestamp();
   UPDATE wso_private.tvt_local_media_slots s SET retained_at=statement_timestamp(),expires_at=least(w.expires_at,statement_timestamp()+interval '30 seconds')
   WHERE s.master_id IN (SELECT id FROM wso_private.tvt_local_media_masters WHERE wall_id=w.id AND state='ACTIVE') AND s.expires_at>clock_timestamp() AND s.state IN ('RESERVED','ACTIVE','PARKED');
   UPDATE wso_private.tvt_local_media_focus_refs f SET active_expires_at=least(l.expires_at,w.expires_at,statement_timestamp()+interval '30 seconds') FROM wso_private.tvt_local_media_leases l
   WHERE f.wall_id=w.id AND f.attached_viewer=l.id AND f.state='MAIN_ACTIVE' AND f.active_expires_at>clock_timestamp() AND wso_private.wso_tvt_local_media_live_read(l);
 END IF;
 RETURN jsonb_build_object('id',w.id,'state',w.state,'expires_at',w.expires_at);
END;
"""
WALL_VIEW = """
DECLARE w wso_private.tvt_local_media_walls;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.tenants WHERE id=w.tenant_id AND job_generation=w.tenant_epoch)
 OR NOT EXISTS(SELECT 1 FROM public.memberships WHERE tenant_id=w.tenant_id AND user_id=w.actor_id AND role='OWNER')
 OR NOT EXISTS(SELECT 1 FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('id',w.id,'state',w.state,'expires_at',w.expires_at);
END;
"""
SHARED_ISSUE = f"""
DECLARE w wso_private.tvt_local_media_walls; f wso_private.tvt_local_media_focus_refs; token text;
BEGIN
 {LOCK}
 IF p_wall IS NULL THEN RETURN public.wso_tvt_local_media_issue(p_session,p_connection,p_store,p_device,p_channel,p_generation,p_revision,p_stream,p_ttl); END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN NULL; END IF;
 IF p_focus IS NOT NULL THEN
   SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=p_focus AND wall_id=p_wall AND channel_id=p_channel AND state='PENDING' AND expires_at>clock_timestamp();
   IF NOT FOUND OR (p_stream='main' AND f.direction<>'FORWARD') OR (p_stream='sub' AND f.direction<>'RETURN') THEN RETURN NULL; END IF;
   IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases WHERE mux_focus_id=f.id AND state<>'CLOSED') THEN RETURN NULL; END IF;
 ELSIF p_stream<>'sub' THEN RETURN NULL;
 END IF;
 token:=public.wso_tvt_local_media_issue(p_session,p_connection,p_store,p_device,p_channel,p_generation,p_revision,p_stream,p_ttl);
 IF token IS NULL THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases SET mux_wall_id=p_wall,mux_focus_id=p_focus,
 mux_cleanup_scope=CASE WHEN p_stream='main' THEN 'DEDICATED_NATIVE' ELSE 'VIEWER' END
 WHERE ticket_digest=sha256(convert_to(token,'UTF8'));
 RETURN token;
END;
"""
MASTER_RESERVE = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; w wso_private.tvt_local_media_walls; original boolean:=false; inv text;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream<>'sub' OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=l.mux_wall_id;
 SELECT session_digest INTO inv FROM wso_private.tvt_local_devices WHERE id=l.device_id;
 IF inv IS DISTINCT FROM l.session_digest OR NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN NULL; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE connection_id=l.connection_id AND state<>'CLOSED';
 IF FOUND THEN
   IF (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.wall_id,m.store_id,m.device_id,m.generation,m.version_id,m.inventory_revision,m.worker_epoch)
   IS DISTINCT FROM (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.mux_wall_id,l.store_id,l.device_id,l.generation,l.version_id,l.inventory_revision,p_worker)
   OR NOT wso_private.wso_tvt_local_media_master_scope(m) THEN RETURN NULL; END IF;
 ELSE
   IF p_master_authority IS NULL OR p_master_authority!~'^[0-9a-f]{{64}}$' OR p_master_native IS NULL THEN RETURN NULL; END IF;
   IF (SELECT count(*) FROM wso_private.tvt_local_media_masters WHERE state<>'CLOSED')>=2 THEN RAISE EXCEPTION 'master capacity' USING ERRCODE='53300'; END IF;
   INSERT INTO wso_private.tvt_local_media_masters(id,wall_id,source_lease,authority_digest,worker_epoch,native_generation,tenant_id,tenant_epoch,actor_id,session_digest,store_id,device_id,connection_id,generation,version_id,inventory_revision,inventory_session,state,issued_at,expires_at)
   VALUES(gen_random_uuid(),w.id,l.id,sha256(convert_to(p_master_authority,'UTF8')),p_worker,p_master_native,l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision,inv,'STARTING',clock_timestamp(),least(w.expires_at,l.expires_at)) RETURNING * INTO m;
   original:=true;
 END IF;
 UPDATE wso_private.tvt_local_media_leases SET mux_master_id=m.id WHERE id=l.id;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('creator',original);
END;
"""
LEASE_SCOPE = """
BEGIN
 RETURN jsonb_build_object('tenant_id',l.tenant_id,'tenant_epoch',l.tenant_epoch,'actor_user_id',l.actor_id,'session_digest',l.session_digest,'wall_id',l.mux_wall_id,'store_id',l.store_id,'device_id',l.device_id,'connection_id',l.connection_id,'connection_generation',l.generation,'secret_version',l.version_id,'inventory_revision',l.inventory_revision,'worker_epoch',l.worker_epoch);
END;
"""
ATTEMPT_SCOPE = f"""
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream<>'sub' THEN RETURN NULL; END IF;
 -- Stored immutable lease identity also serves expired/Stop cleanup. It grants
 -- no current authority; the reserve mutation independently checks LIVE.
 RETURN wso_private.wso_tvt_local_media_lease_scope(l);
END;
"""
OPERATION_VIEW = """
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 IF j.outcome='ABSENT' THEN RETURN j.scope||jsonb_build_object('outcome','ABSENT','operation_native',j.operation_native,'lease_id',j.lease_id); END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=j.master_id AND worker_epoch=j.worker_epoch;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('outcome','RESERVED','operation_native',j.operation_native,'lease_id',j.lease_id,'creator',j.creator);
END;
"""
JOURNAL_RESERVE = f"""
DECLARE l wso_private.tvt_local_media_leases; j wso_private.tvt_local_media_master_operations; expected jsonb; value jsonb; operation text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream<>'sub' THEN RETURN NULL; END IF;
 expected:=wso_private.wso_tvt_local_media_lease_scope(l);
 operation:=coalesce(p_operation,p_master_authority);
 IF operation IS NULL OR operation!~'^[0-9a-f]{{64}}$' OR p_master_native IS NULL OR (p_scope IS NOT NULL AND p_scope IS DISTINCT FROM expected) THEN RETURN NULL; END IF;
 SELECT * INTO j FROM wso_private.tvt_local_media_master_operations WHERE operation_digest=sha256(convert_to(operation,'UTF8'));
 IF FOUND THEN
   IF (j.lease_id,j.viewer_authority_digest,j.worker_epoch,j.operation_native,j.scope) IS DISTINCT FROM (l.id,l.authority_digest,p_worker,p_master_native,expected) OR j.outcome='ABSENT' THEN RETURN NULL; END IF;
   RETURN wso_private.wso_tvt_local_media_operation_view(j);
 END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_master_operations WHERE lease_id=l.id) THEN RETURN NULL; END IF;
 -- Permanent operation fences have a hard storage ceiling, never TTL eviction.
 IF (SELECT count(*) FROM wso_private.tvt_local_media_master_operations)>=65536 THEN RAISE EXCEPTION 'operation journal capacity' USING ERRCODE='53300'; END IF;
 value:=wso_private.wso_tvt_local_media_master_reserve_core(p_authority,p_worker,p_native,p_master_authority,p_master_native);
 INSERT INTO wso_private.tvt_local_media_master_operations(operation_digest,lease_id,viewer_authority_digest,worker_epoch,operation_native,scope,outcome,master_id,creator)
 VALUES(sha256(convert_to(operation,'UTF8')),l.id,l.authority_digest,p_worker,p_master_native,expected,CASE WHEN value IS NULL THEN 'ABSENT' ELSE 'RESERVED' END,(value->>'master_id')::uuid,(value->>'creator')::boolean) RETURNING * INTO j;
 IF value IS NULL THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_operation_view(j);
END;
"""
ATTEMPT_RESOLVE = f"""
DECLARE l wso_private.tvt_local_media_leases; j wso_private.tvt_local_media_master_operations; expected jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream<>'sub' OR p_operation IS NULL OR p_operation!~'^[0-9a-f]{{64}}$' OR p_operation_native IS NULL THEN RETURN NULL; END IF;
 expected:=wso_private.wso_tvt_local_media_lease_scope(l);
 IF p_scope IS DISTINCT FROM expected THEN RETURN NULL; END IF;
 SELECT * INTO j FROM wso_private.tvt_local_media_master_operations WHERE operation_digest=sha256(convert_to(p_operation,'UTF8'));
 IF NOT FOUND THEN
   IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_master_operations WHERE lease_id=l.id) OR l.mux_master_id IS NOT NULL THEN RETURN NULL; END IF;
   IF (SELECT count(*) FROM wso_private.tvt_local_media_master_operations)>=65536 THEN RAISE EXCEPTION 'operation journal capacity' USING ERRCODE='53300'; END IF;
   INSERT INTO wso_private.tvt_local_media_master_operations(operation_digest,lease_id,viewer_authority_digest,worker_epoch,operation_native,scope,outcome)
   VALUES(sha256(convert_to(p_operation,'UTF8')),l.id,l.authority_digest,p_worker,p_operation_native,expected,'ABSENT') RETURNING * INTO j;
 END IF;
 IF (j.lease_id,j.viewer_authority_digest,j.worker_epoch,j.operation_native,j.scope) IS DISTINCT FROM (l.id,l.authority_digest,p_worker,p_operation_native,expected) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_operation_view(j);
END;
"""
UNSTARTED_CLOSE = f"""
DECLARE m wso_private.tvt_local_media_masters; l wso_private.tvt_local_media_leases; ids jsonb;
BEGIN
 {LOCK}
 {MASTER_SELECT}
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM wso_private.tvt_local_media_leases WHERE mux_master_id=m.id FOR UPDATE;
 SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=m.source_lease;
 IF p_scope IS DISTINCT FROM wso_private.wso_tvt_local_media_lease_scope(l) OR p_scope IS DISTINCT FROM (wso_private.wso_tvt_local_media_master_view(m)-ARRAY['master_id','native_generation','expires_at','state','wire_generation','wire_session','creator_channel']) THEN RETURN NULL; END IF;
 IF m.login_claimed OR m.login_proof IS NOT NULL OR m.wire_generation IS NOT NULL OR m.wire_session IS NOT NULL OR m.state IN ('ACTIVE','QUARANTINED')
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_slots WHERE master_id=m.id)
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases x WHERE x.mux_master_id=m.id AND (x.mux_acquisition_started OR x.worker_epoch<>p_worker OR x.mux_slot_id IS NOT NULL OR x.mux_registration IS NOT NULL OR x.state IN ('CLAIMED','NEGOTIATING','PLAYING') OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_grants g WHERE g.lease_id=x.id)))
 THEN RETURN NULL; END IF;
 IF p_receipt->>'master_id' IS DISTINCT FROM m.id::text OR p_receipt->>'worker_epoch' IS DISTINCT FROM m.worker_epoch::text OR p_receipt->>'native_generation' IS DISTINCT FROM m.native_generation::text OR p_receipt->>'original_state' IS DISTINCT FROM 'NOT_CREATED'
 OR EXISTS(SELECT 1 FROM unnest(ARRAY['callback_settled','ipc_settled','job_settled']) k WHERE p_receipt->k IS DISTINCT FROM 'true'::jsonb) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_masters SET state='CLOSED',cleanup_confirmed=true WHERE id=m.id;
 UPDATE wso_private.tvt_local_media_leases SET state='CLOSED',invalidated=true,cleanup_confirmed=true,mux_viewer_settled=true,mux_native_settled=true,mux_cleanup_scope='LAST_VIEWER_AND_DEVICE_EPOCH' WHERE mux_master_id=m.id;
 SELECT coalesce(jsonb_agg(id ORDER BY id),'[]'::jsonb) INTO ids FROM wso_private.tvt_local_media_leases WHERE mux_master_id=m.id;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(m.wall_id);
 RETURN p_scope||jsonb_build_object('master_id',m.id,'native_generation',m.native_generation,'lease_ids',ids,'closed',true);
END;
"""
ABSENT_CLOSE = f"""
DECLARE l wso_private.tvt_local_media_leases; j wso_private.tvt_local_media_master_operations;
BEGIN
 {LOCK}
 {VIEWER_SELECT.replace(";", " FOR UPDATE;")}
 IF NOT FOUND OR p_scope IS DISTINCT FROM wso_private.wso_tvt_local_media_lease_scope(l) THEN RETURN NULL; END IF;
 SELECT * INTO j FROM wso_private.tvt_local_media_master_operations WHERE operation_digest=sha256(convert_to(p_operation,'UTF8')) AND lease_id=l.id AND worker_epoch=p_worker AND operation_native=p_operation_native AND viewer_authority_digest=l.authority_digest AND scope=p_scope AND outcome='ABSENT';
 IF NOT FOUND OR l.mux_acquisition_started OR l.mux_master_id IS NOT NULL OR l.mux_slot_id IS NOT NULL OR l.mux_registration IS NOT NULL OR l.state NOT IN ('LOGIN','STOPPING','CLOSED') OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_grants WHERE lease_id=l.id) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases SET invalidated=true,state='CLOSED',cleanup_confirmed=true,mux_viewer_settled=true,mux_cleanup_scope='VIEWER' WHERE id=l.id;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(l.mux_wall_id);
 RETURN p_scope||jsonb_build_object('master_id',NULL,'lease_id',l.id,'closed',true);
END;
"""
FOLLOWER_CLOSE = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 {VIEWER_SELECT.replace(";", " FOR UPDATE;")}
 IF NOT FOUND OR p_scope IS DISTINCT FROM wso_private.wso_tvt_local_media_lease_scope(l) THEN RETURN NULL; END IF;
 {MASTER_SELECT}
 IF NOT FOUND OR l.mux_acquisition_started OR p_scope IS DISTINCT FROM (wso_private.wso_tvt_local_media_master_view(m)-ARRAY['master_id','native_generation','expires_at','state','wire_generation','wire_session','creator_channel']) OR l.mux_master_id IS DISTINCT FROM m.id OR l.id=m.source_lease OR m.worker_epoch<>l.worker_epoch OR l.mux_slot_id IS NOT NULL OR l.mux_registration IS NOT NULL OR l.state NOT IN ('LOGIN','STOPPING','CLOSED') OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_grants WHERE lease_id=l.id)
 OR NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_master_operations WHERE operation_digest=sha256(convert_to(p_operation,'UTF8')) AND operation_native=p_operation_native AND viewer_authority_digest=l.authority_digest AND worker_epoch=p_worker AND lease_id=l.id AND master_id=m.id AND outcome='RESERVED' AND creator=false AND scope=p_scope) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases SET invalidated=true,state='CLOSED',cleanup_confirmed=true,mux_viewer_settled=true,mux_cleanup_scope='VIEWER' WHERE id=l.id;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(l.mux_wall_id);
 RETURN p_scope||jsonb_build_object('master_id',m.id,'lease_id',l.id,'closed',true);
END;
"""
MASTER_LOGIN = f"""
DECLARE m wso_private.tvt_local_media_masters; result jsonb;
BEGIN
 {LOCK}
 {MASTER_SELECT}
 IF NOT FOUND OR m.state<>'STARTING' OR m.login_claimed OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_masters SET login_claimed=true WHERE id=m.id;
 SELECT wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('nonce',encode(s.nonce,'hex'),'ciphertext',encode(s.ciphertext,'hex')) INTO result
 FROM wso_private.connection_secrets s WHERE s.tenant_id=m.tenant_id AND s.connection_id=m.connection_id AND s.version_id=m.version_id;
 RETURN result;
END;
"""
MASTER_ACTIVATE = f"""
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 {MASTER_SELECT}
 IF NOT FOUND OR m.state<>'STARTING' OR NOT m.login_claimed OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 IF jsonb_typeof(p_proof) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(p_proof))<>6
 OR EXISTS(SELECT 1 FROM unnest(ARRAY['login_accepted','same_original_session','serial_matched','device_matched','inventory_session_matched']) k WHERE p_proof->k IS DISTINCT FROM 'true'::jsonb)
 OR jsonb_typeof(p_proof->'peer_capability') IS DISTINCT FROM 'number' OR (p_proof->>'peer_capability')!~'^[0-9]+$' OR (p_proof->>'peer_capability')::integer NOT BETWEEN 1 AND 32767 THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_masters SET state='ACTIVE',login_proof=p_proof WHERE id=m.id RETURNING * INTO m;
 RETURN wso_private.wso_tvt_local_media_master_view(m);
END;
"""
MASTER_OBSERVE = f"""
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 {MASTER_SELECT}
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m);
END;
"""
SLOT_RESERVE = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; s wso_private.tvt_local_media_slots; guid bytea;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.stream<>'sub' OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
 {MASTER_SELECT}
 IF NOT FOUND OR m.id IS DISTINCT FROM l.mux_master_id OR m.state<>'ACTIVE' OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 IF p_wire_generation IS NULL OR p_wire_generation<1 OR p_wire_session IS NULL OR octet_length(p_wire_session)<>16 OR p_wire_session=decode(repeat('00',16),'hex') THEN RETURN NULL; END IF;
 IF m.wire_generation IS NOT NULL AND (m.wire_generation,m.wire_session) IS DISTINCT FROM (p_wire_generation,p_wire_session) THEN RETURN NULL; END IF;
 SELECT c.guid INTO guid FROM wso_private.tvt_local_channels c WHERE c.id=l.channel_id AND c.device_id=m.device_id AND c.active AND c.revision=m.inventory_revision;
 IF NOT FOUND OR guid IS DISTINCT FROM p_channel_guid THEN RETURN NULL; END IF;
 SELECT * INTO s FROM wso_private.tvt_local_media_slots WHERE master_id=m.id AND channel_id=l.channel_id;
 IF FOUND THEN
   IF NOT wso_private.wso_tvt_local_media_slot_current(s) THEN RETURN NULL; END IF;
 ELSE
   IF p_task IS NULL OR p_slot_authority IS NULL OR p_slot_authority!~'^[0-9a-f]{{64}}$' THEN RETURN NULL; END IF;
   IF (SELECT count(*) FROM wso_private.tvt_local_media_slots WHERE state<>'CLOSED')>=16 THEN RAISE EXCEPTION 'slot capacity' USING ERRCODE='53300'; END IF;
   INSERT INTO wso_private.tvt_local_media_slots(id,master_id,channel_id,channel_guid,task_id,authority_digest,state,issued_at,retained_at,expires_at)
   VALUES(gen_random_uuid(),m.id,l.channel_id,guid,p_task,sha256(convert_to(p_slot_authority,'UTF8')),'RESERVED',clock_timestamp(),statement_timestamp(),least(m.expires_at,statement_timestamp()+interval '30 seconds')) RETURNING * INTO s;
 END IF;
 UPDATE wso_private.tvt_local_media_masters SET wire_generation=p_wire_generation,wire_session=p_wire_session WHERE id=m.id;
 UPDATE wso_private.tvt_local_media_leases SET mux_slot_id=s.id WHERE id=l.id;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('slot_id',s.id,'channel_guid',encode(s.channel_guid,'hex'),'task_id',s.task_id,'expires_at',least(s.expires_at,m.expires_at),'wire_generation',p_wire_generation,'wire_session',encode(p_wire_session,'hex'));
END;
"""
SLOT_OBSERVE = """
DECLARE s wso_private.tvt_local_media_slots; m wso_private.tvt_local_media_masters;
BEGIN
 SELECT x.* INTO s FROM wso_private.tvt_local_media_slots x JOIN wso_private.tvt_local_media_masters y ON y.id=x.master_id WHERE x.authority_digest=sha256(convert_to(p_slot_authority,'UTF8')) AND y.worker_epoch=p_worker AND y.native_generation=p_master_native;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_slot_current(s) THEN RETURN NULL; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=s.master_id;
 IF NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('slot_id',s.id,'task_id',s.task_id,'channel_guid',encode(s.channel_guid,'hex'),'expires_at',least(m.expires_at,s.expires_at));
END;
"""
VIEWER_SELECTION = f"""
DECLARE l wso_private.tvt_local_media_leases; w wso_private.tvt_local_media_walls;
 m wso_private.tvt_local_media_masters; f wso_private.tvt_local_media_focus_refs; c wso_private.tvt_local_channels;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream NOT IN ('sub','main') OR
 NOT (l.state='LOGIN' OR (l.stream='main' AND l.state='CLAIMED' AND l.mux_registration IS NOT NULL))
 OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=l.mux_wall_id;
 IF NOT FOUND OR (w.tenant_id,w.tenant_epoch,w.actor_id,w.session_digest) IS DISTINCT FROM (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest)
 OR NOT wso_private.wso_tvt_local_media_wall_lock(w) THEN RETURN NULL; END IF;
 IF l.stream='main' THEN
   SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=l.mux_focus_id AND wall_id=w.id AND channel_id=l.channel_id AND direction='FORWARD' AND state='PENDING' AND worker_epoch=p_worker AND expires_at>clock_timestamp();
   IF NOT FOUND THEN RETURN NULL; END IF;
   SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker;
   IF NOT FOUND OR (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision)
   IS DISTINCT FROM (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.store_id,m.device_id,m.connection_id,m.generation,m.version_id,m.inventory_revision)
   OR NOT wso_private.wso_tvt_local_media_master_lock(m) THEN RETURN NULL; END IF;
 END IF;
 SELECT * INTO c FROM wso_private.tvt_local_channels WHERE id=l.channel_id AND tenant_id=l.tenant_id AND device_id=l.device_id AND active AND revision=l.inventory_revision;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('guid',encode(c.guid,'hex'),'raw_index',c.raw_index,'window_index',c.window_index,'ordinal',c.ordinal,'kind',c.kind,'stream',l.stream);
END;
"""
VIEWER_ADMIT = f"""
DECLARE l wso_private.tvt_local_media_leases; s wso_private.tvt_local_media_slots; m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.state<>'LOGIN' OR l.mux_registration IS NOT NULL OR p_registration IS NULL OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
 SELECT * INTO s FROM wso_private.tvt_local_media_slots WHERE id=l.mux_slot_id AND authority_digest=sha256(convert_to(p_slot_authority,'UTF8'));
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=l.mux_master_id;
 IF s.id IS NULL OR s.master_id IS DISTINCT FROM m.id OR NOT wso_private.wso_tvt_local_media_slot_current(s) OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases x WHERE x.mux_slot_id=s.id AND x.id<>l.id AND x.state<>'CLOSED') THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_leases SET mux_registration=p_registration,state='CLAIMED' WHERE id=l.id RETURNING * INTO l;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('lease_id',l.id,'registration',p_registration,'slot_id',s.id,'expires_at',least(l.expires_at,s.expires_at,m.expires_at));
END;
"""
VIEWER_OBSERVE = f"""
DECLARE l wso_private.tvt_local_media_leases; s wso_private.tvt_local_media_slots; m wso_private.tvt_local_media_masters;
BEGIN
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_registration IS DISTINCT FROM p_registration OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
 SELECT * INTO s FROM wso_private.tvt_local_media_slots WHERE id=l.mux_slot_id;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=l.mux_master_id;
 IF NOT wso_private.wso_tvt_local_media_slot_current(s) OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||wso_private.wso_tvt_local_media_view(l)||jsonb_build_object('expires_at',least(l.expires_at,s.expires_at,m.expires_at));
END;
"""
VIEWER_ACTIVATE = f"""
DECLARE l wso_private.tvt_local_media_leases; value jsonb;
BEGIN
 {LOCK}
 IF public.wso_tvt_local_media_viewer_observe(p_authority,p_worker,p_native,p_registration) IS NULL THEN RETURN NULL; END IF;
 IF NOT wso_private.wso_tvt_local_media_proof(p_proof,false) THEN RETURN NULL; END IF;
 value:=public.wso_tvt_local_media_activate(p_authority,p_worker,p_native,p_proof);
 IF value IS NULL THEN RETURN NULL; END IF;
 {VIEWER_SELECT}
 UPDATE wso_private.tvt_local_media_slots SET state='ACTIVE',permission_proof=p_proof WHERE id=l.mux_slot_id;
 RETURN value;
END;
"""
VIEWER_CLOSE = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; keep boolean;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_registration IS DISTINCT FROM p_registration OR l.mux_wall_id IS NULL THEN RETURN; END IF;
 IF l.state='CLOSED' THEN PERFORM wso_private.wso_tvt_local_media_finalize_wall(l.mux_wall_id);RETURN; END IF;
 IF p_scope NOT IN ('VIEWER','DEDICATED_NATIVE','LAST_VIEWER_AND_DEVICE_EPOCH') OR p_receipt->>'lease_id' IS DISTINCT FROM l.id::text OR p_receipt->>'registration_id' IS DISTINCT FROM p_registration::text
 OR EXISTS(SELECT 1 FROM unnest(ARRAY['decoder_settled','peer_settled','media_cleared']) k WHERE p_receipt->k IS DISTINCT FROM 'true'::jsonb) THEN RAISE EXCEPTION 'viewer receipt denied' USING ERRCODE='22023'; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=l.mux_master_id;
 keep:=m.state='ACTIVE' AND (EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases x WHERE x.mux_master_id=m.id AND x.id<>l.id AND wso_private.wso_tvt_local_media_live_read(x))
 OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_focus_refs f WHERE f.master_id=m.id AND wso_private.wso_tvt_local_media_focus_current(f)));
 UPDATE wso_private.tvt_local_media_leases SET invalidated=true,mux_viewer_settled=true,
 mux_cleanup_scope=CASE WHEN l.stream='main' THEN 'DEDICATED_NATIVE' WHEN keep AND p_scope='VIEWER' THEN 'VIEWER' ELSE 'LAST_VIEWER_AND_DEVICE_EPOCH' END,
 state=CASE WHEN (keep AND p_scope='VIEWER' AND l.stream='sub') OR l.mux_native_settled THEN 'CLOSED' ELSE 'STOPPING' END,
 cleanup_confirmed=coalesce((keep AND p_scope='VIEWER' AND l.stream='sub') OR l.mux_native_settled,false) WHERE id=l.id;
 UPDATE wso_private.tvt_local_media_grants SET invalidated=true WHERE lease_id=l.id;
 UPDATE wso_private.tvt_local_media_slots SET state='PARKED' WHERE id=l.mux_slot_id AND state IN ('RESERVED','ACTIVE');
 IF NOT coalesce(keep,false) OR p_scope='LAST_VIEWER_AND_DEVICE_EPOCH' THEN PERFORM wso_private.wso_tvt_local_media_stop_master(m.id); END IF;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(l.mux_wall_id);
END;
"""
EPOCH_CLOSE = f"""
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 {MASTER_SELECT}
 IF NOT FOUND THEN RETURN; END IF;
 IF m.state='CLOSED' THEN PERFORM wso_private.wso_tvt_local_media_finalize_wall(m.wall_id);RETURN; END IF;
 IF p_receipt->>'master_id' IS DISTINCT FROM m.id::text OR p_receipt->>'worker_epoch' IS DISTINCT FROM m.worker_epoch::text OR p_receipt->>'native_generation' IS DISTINCT FROM m.native_generation::text
 OR p_receipt->>'original_state' NOT IN ('NOT_CREATED','REAPED') OR p_receipt->>'original_state' IS NULL
 OR EXISTS(SELECT 1 FROM unnest(ARRAY['callback_settled','ipc_settled','job_settled']) k WHERE p_receipt->k IS DISTINCT FROM 'true'::jsonb) THEN RAISE EXCEPTION 'epoch receipt denied' USING ERRCODE='22023'; END IF;
 IF p_receipt->>'original_state'='NOT_CREATED' AND (m.state='ACTIVE' OR m.login_proof IS NOT NULL) THEN RAISE EXCEPTION 'started epoch' USING ERRCODE='22023'; END IF;
 PERFORM wso_private.wso_tvt_local_media_stop_master(m.id);
 UPDATE wso_private.tvt_local_media_masters SET state='CLOSED',cleanup_confirmed=true WHERE id=m.id;
 UPDATE wso_private.tvt_local_media_slots SET state='CLOSED' WHERE master_id=m.id;
 UPDATE wso_private.tvt_local_media_leases SET mux_native_settled=true,
 state=CASE WHEN mux_viewer_settled THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=mux_viewer_settled WHERE mux_master_id=m.id AND state<>'CLOSED';
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(m.wall_id);
END;
"""

FOCUS_ISSUE = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; f wso_private.tvt_local_media_focus_refs; old wso_private.tvt_local_media_focus_refs; token text;
BEGIN
 {LOCK}
 SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=p_id AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR l.mux_wall_id IS NULL OR NOT wso_private.wso_tvt_local_media_live_read(l) OR p_direction IS NULL OR p_direction NOT IN ('FORWARD','RETURN') OR p_deadline_at IS NULL OR p_deadline_at<=clock_timestamp() THEN RETURN NULL; END IF;
 IF p_direction='FORWARD' THEN
   IF l.stream<>'sub' OR l.mux_master_id IS NULL OR l.mux_slot_id IS NULL THEN RETURN NULL; END IF;
   SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=l.mux_master_id;
 ELSE
   IF l.stream<>'main' THEN RETURN NULL; END IF;
   SELECT * INTO old FROM wso_private.tvt_local_media_focus_refs x WHERE x.attached_viewer=l.id AND x.state='MAIN_ACTIVE' AND wso_private.wso_tvt_local_media_focus_current(x);
   IF NOT FOUND THEN RETURN NULL; END IF;
   SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=old.master_id;
 END IF;
 IF NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_focus_refs x SET state='EXPIRED' WHERE x.wall_id=l.mux_wall_id AND x.state IN ('PENDING','MAIN_ACTIVE') AND NOT wso_private.wso_tvt_local_media_focus_current(x);
 IF p_direction='RETURN' THEN
   UPDATE wso_private.tvt_local_media_focus_refs SET state='CONSUMED' WHERE id=old.id AND state='MAIN_ACTIVE';
   IF NOT FOUND THEN RETURN NULL; END IF;
 END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_focus_refs WHERE wall_id=l.mux_wall_id AND state IN ('PENDING','MAIN_ACTIVE')) THEN RAISE EXCEPTION 'focus capacity' USING ERRCODE='53300'; END IF;
 token:={TOKEN};
 INSERT INTO wso_private.tvt_local_media_focus_refs(id,wall_id,source_lease,master_id,channel_id,direction,state,ticket_digest,issued_at,expires_at)
 VALUES(gen_random_uuid(),l.mux_wall_id,l.id,m.id,l.channel_id,p_direction,'PENDING',sha256(convert_to(token,'UTF8')),clock_timestamp(),least(clock_timestamp()+interval '20 seconds',p_deadline_at,l.expires_at,m.expires_at)) RETURNING * INTO f;
 RETURN token;
END;
"""
FOCUS_CURRENT = """
BEGIN
 IF f.id IS NULL THEN RETURN false; END IF;
 IF f.state='PENDING' THEN RETURN f.expires_at>clock_timestamp(); END IF;
 RETURN f.state='MAIN_ACTIVE' AND f.active_expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases l WHERE l.id=f.attached_viewer AND l.stream='main' AND l.mux_focus_id=f.id AND wso_private.wso_tvt_local_media_live_read(l));
END;
"""
DEDICATED_CLOSE = f"""
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.mux_wall_id IS NULL OR l.stream<>'main' OR l.mux_cleanup_scope<>'DEDICATED_NATIVE' OR l.mux_registration IS DISTINCT FROM p_registration THEN RETURN; END IF;
 IF p_receipt->>'master_id' IS DISTINCT FROM l.id::text OR p_receipt->>'worker_epoch' IS DISTINCT FROM l.worker_epoch::text OR p_receipt->>'native_generation' IS DISTINCT FROM l.native_generation::text
 OR p_receipt->>'original_state' IS NULL OR p_receipt->>'original_state' NOT IN ('NOT_CREATED','REAPED')
 OR EXISTS(SELECT 1 FROM unnest(ARRAY['callback_settled','ipc_settled','job_settled']) k WHERE p_receipt->k IS DISTINCT FROM 'true'::jsonb) THEN RAISE EXCEPTION 'dedicated receipt denied' USING ERRCODE='22023'; END IF;
 IF p_receipt->>'original_state'='NOT_CREATED' AND EXISTS(SELECT 1 FROM wso_private.tvt_local_media_grants WHERE lease_id=l.id) THEN RAISE EXCEPTION 'started dedicated original' USING ERRCODE='22023'; END IF;
 UPDATE wso_private.tvt_local_media_leases SET invalidated=true,mux_native_settled=true,
 state=CASE WHEN mux_viewer_settled THEN 'CLOSED' ELSE 'STOPPING' END,cleanup_confirmed=mux_viewer_settled WHERE id=l.id;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(l.mux_wall_id);
END;
"""
DEDICATED_REGISTER = f"""
DECLARE l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; f wso_private.tvt_local_media_focus_refs;
BEGIN
 {LOCK}
 {VIEWER_SELECT}
 IF NOT FOUND OR l.stream<>'main' OR l.mux_focus_id IS NULL OR l.mux_registration IS NOT NULL OR p_registration IS NULL OR NOT wso_private.wso_tvt_local_media_live(l) THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=l.mux_focus_id AND state='PENDING' AND direction='FORWARD' AND expires_at>clock_timestamp() AND channel_id=l.channel_id AND wall_id=l.mux_wall_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases WHERE id=f.source_lease AND state='CLOSED' AND cleanup_confirmed) THEN RETURN NULL; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) OR
 (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision)
 IS DISTINCT FROM (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.store_id,m.device_id,m.connection_id,m.generation,m.version_id,m.inventory_revision) THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases WHERE stream='main' AND mux_registration IS NOT NULL AND state<>'CLOSED') THEN RAISE EXCEPTION 'dedicated capacity' USING ERRCODE='53300'; END IF;
 UPDATE wso_private.tvt_local_media_leases SET mux_registration=p_registration,mux_cleanup_scope='DEDICATED_NATIVE' WHERE id=l.id;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('lease_id',l.id,'registration',p_registration,'dedicated_native_generation',l.native_generation);
END;
"""
FOCUS_REDEEM = f"""
DECLARE f wso_private.tvt_local_media_focus_refs; m wso_private.tvt_local_media_masters; token text;
BEGIN
 {LOCK}
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE ticket_digest=sha256(convert_to(p_ticket,'UTF8')) AND authority_digest IS NULL AND state='PENDING' AND expires_at>clock_timestamp();
 IF NOT FOUND OR p_worker IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 token:={TOKEN};
 UPDATE wso_private.tvt_local_media_focus_refs SET authority_digest=sha256(convert_to(token,'UTF8')),worker_epoch=p_worker WHERE id=f.id;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('focus_id',f.id,'lease_id',f.source_lease,'direction',f.direction,'authority',token,'issued_at',f.issued_at,'expires_at',f.expires_at);
END;
"""
FOCUS_OBSERVE = """
DECLARE f wso_private.tvt_local_media_focus_refs; m wso_private.tvt_local_media_masters;
BEGIN
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE authority_digest=sha256(convert_to(p_focus_authority,'UTF8')) AND worker_epoch=p_worker AND state='PENDING' AND expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id;
 IF NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('focus_id',f.id,'lease_id',f.source_lease,'direction',f.direction,'expires_at',f.expires_at);
END;
"""
FOCUS_SETTLEMENT_VIEW = """
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=f.worker_epoch;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_master_view(m)||jsonb_build_object('focus_id',f.id,'wall_id',f.wall_id,'lease_id',f.source_lease,'direction',f.direction,'state',f.state,'attached_viewer',f.attached_viewer);
END;
"""
FOCUS_SETTLEMENT_OBSERVE = """
DECLARE f wso_private.tvt_local_media_focus_refs; latest wso_private.tvt_local_media_focus_refs;
 m wso_private.tvt_local_media_masters; l wso_private.tvt_local_media_leases;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE authority_digest=sha256(convert_to(p_focus_authority,'UTF8')) AND worker_epoch=p_worker;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF f.state IN ('MAIN_ACTIVE','ATTACHED') THEN
   SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker;
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
   SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=f.attached_viewer AND mux_focus_id=f.id AND mux_wall_id=f.wall_id AND channel_id=f.channel_id AND worker_epoch=p_worker AND state IN ('NEGOTIATING','PLAYING');
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live_read(l)
   OR (f.state='MAIN_ACTIVE' AND (f.direction<>'FORWARD' OR l.stream<>'main' OR f.active_expires_at<=clock_timestamp()))
   OR (f.state='ATTACHED' AND (f.direction<>'RETURN' OR l.stream<>'sub')) THEN RETURN NULL; END IF;
 END IF;
 -- Re-read after current predicates so a committed RETURN/Stop during them
 -- cannot be hidden by the first statement's snapshot.
 SELECT * INTO latest FROM wso_private.tvt_local_media_focus_refs x WHERE x.id=f.id AND x.worker_epoch=p_worker AND x.state=f.state AND x.attached_viewer IS NOT DISTINCT FROM f.attached_viewer;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_focus_settlement_view(latest);
END;
"""
FOCUS_SETTLE = f"""
DECLARE f wso_private.tvt_local_media_focus_refs; l wso_private.tvt_local_media_leases; m wso_private.tvt_local_media_masters; wanted text;
BEGIN
 {LOCK}
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE authority_digest=sha256(convert_to(p_focus_authority,'UTF8')) AND worker_epoch=p_worker;
 IF NOT FOUND OR p_transition IS NULL OR p_transition NOT IN ('ATTACHED','CANCELLED','FAILED','EXPIRED') THEN RETURN NULL; END IF;
 IF p_transition='ATTACHED' THEN
   wanted:=CASE WHEN f.direction='FORWARD' THEN 'MAIN_ACTIVE' ELSE 'ATTACHED' END;
   IF f.state=wanted AND f.attached_viewer=p_viewer THEN RETURN public.wso_tvt_local_media_focus_settlement_observe(p_focus_authority,p_worker); END IF;
   IF f.state<>'PENDING' OR f.expires_at<=clock_timestamp() OR public.wso_tvt_local_media_focus_observe(p_focus_authority,p_worker) IS NULL THEN RETURN NULL; END IF;
   SELECT * INTO l FROM wso_private.tvt_local_media_leases WHERE id=p_viewer AND mux_focus_id=f.id AND mux_wall_id=f.wall_id AND channel_id=f.channel_id AND worker_epoch=p_worker AND state IN ('NEGOTIATING','PLAYING');
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live_read(l) OR (f.direction='FORWARD' AND l.stream<>'main') OR (f.direction='RETURN' AND l.stream<>'sub') THEN RETURN NULL; END IF;
   IF NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases WHERE id=f.source_lease AND state='CLOSED' AND cleanup_confirmed) THEN RETURN NULL; END IF;
   SELECT * INTO m FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker;
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
   UPDATE wso_private.tvt_local_media_focus_refs x SET state=wanted,attached_viewer=l.id,active_expires_at=least(l.expires_at,m.expires_at,clock_timestamp()+interval '30 seconds') WHERE x.id=f.id AND x.state='PENDING' AND x.expires_at>clock_timestamp() RETURNING * INTO f;
   IF NOT FOUND THEN RETURN NULL; END IF;
 ELSE
   IF p_viewer IS NOT NULL AND f.attached_viewer IS NOT NULL AND f.attached_viewer<>p_viewer THEN RETURN NULL; END IF;
   IF p_viewer IS NOT NULL AND f.attached_viewer IS NULL AND NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases WHERE id=p_viewer AND mux_focus_id=f.id AND mux_wall_id=f.wall_id AND channel_id=f.channel_id AND worker_epoch=p_worker) THEN RETURN NULL; END IF;
   IF f.state IN ('CANCELLED','FAILED','EXPIRED','CONSUMED') THEN
     PERFORM wso_private.wso_tvt_local_media_finalize_wall(f.wall_id);
     RETURN wso_private.wso_tvt_local_media_focus_settlement_view(f);
   END IF;
   IF p_transition='EXPIRED' AND f.expires_at>clock_timestamp() THEN RETURN NULL; END IF;
   UPDATE wso_private.tvt_local_media_focus_refs x SET state=p_transition WHERE x.id=f.id RETURNING * INTO f;
   -- Late local rejection revokes delivery, never attests redeemed cleanup.
   UPDATE wso_private.tvt_local_media_leases SET invalidated=true,
     state=CASE WHEN worker_epoch IS NULL THEN 'CLOSED' ELSE 'STOPPING' END,
     cleanup_confirmed=(worker_epoch IS NULL)
   WHERE mux_focus_id=f.id AND mux_wall_id=f.wall_id AND channel_id=f.channel_id AND state<>'CLOSED';
 END IF;
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(f.wall_id);
 RETURN wso_private.wso_tvt_local_media_focus_settlement_view(f);
END;
"""
WALL_CONTROL_ISSUE = f"""
DECLARE w wso_private.tvt_local_media_walls; token text; m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR w.state='CLOSED' OR p_purpose IS NULL OR p_purpose NOT IN ('WALL_STOP','WALL_HEARTBEAT') THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN RETURN NULL; END IF;
 IF p_purpose='WALL_HEARTBEAT' THEN
   IF public.wso_tvt_local_media_wall_read(p_session,p_wall,true) IS NULL THEN RETURN NULL; END IF;
   SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=p_wall;
   token:={TOKEN};
   INSERT INTO wso_private.tvt_local_media_mux_controls(digest,wall_id,purpose,expires_at)
   VALUES(sha256(convert_to(token,'UTF8')),w.id,'WALL_HEARTBEAT',least(clock_timestamp()+interval '20 seconds',w.expires_at,(SELECT expires_at FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id)));
   RETURN token;
 END IF;
 UPDATE wso_private.tvt_local_media_walls SET state='STOPPING' WHERE id=w.id;
 FOR m IN SELECT * FROM wso_private.tvt_local_media_masters WHERE wall_id=w.id AND state<>'CLOSED' LOOP
   PERFORM wso_private.wso_tvt_local_media_stop_master(m.id);
 END LOOP;
 UPDATE wso_private.tvt_local_media_focus_refs SET state='CANCELLED' WHERE wall_id=w.id AND state IN ('PENDING','MAIN_ACTIVE');
 UPDATE wso_private.tvt_local_media_leases SET state=CASE WHEN worker_epoch IS NULL THEN 'CLOSED' ELSE 'STOPPING' END,invalidated=true,cleanup_confirmed=(worker_epoch IS NULL) WHERE mux_wall_id=w.id AND state<>'CLOSED';
 token:={TOKEN};
 INSERT INTO wso_private.tvt_local_media_mux_controls(digest,wall_id,purpose,expires_at) VALUES(sha256(convert_to(token,'UTF8')),w.id,'WALL_STOP',clock_timestamp()+interval '20 seconds');
 PERFORM wso_private.wso_tvt_local_media_finalize_wall(w.id);
 RETURN token;
END;
"""
WALL_CONTROL_REDEEM = f"""
DECLARE c wso_private.tvt_local_media_mux_controls;
BEGIN
 {LOCK}
 SELECT * INTO c FROM wso_private.tvt_local_media_mux_controls WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND NOT consumed AND expires_at>clock_timestamp() AND purpose='WALL_STOP';
 IF NOT FOUND OR p_worker IS NULL OR EXISTS(SELECT 1 FROM wso_private.tvt_local_media_masters WHERE wall_id=c.wall_id AND state<>'CLOSED' AND worker_epoch<>p_worker) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_mux_controls SET consumed=true WHERE digest=c.digest;
 RETURN jsonb_build_object('wall_id',c.wall_id,'purpose',c.purpose);
END;
"""
WALL_HEARTBEAT_REDEEM = f"""
DECLARE c wso_private.tvt_local_media_mux_controls; w wso_private.tvt_local_media_walls; m wso_private.tvt_local_media_masters;
BEGIN
 {LOCK}
 SELECT * INTO c FROM wso_private.tvt_local_media_mux_controls WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND NOT consumed AND expires_at>clock_timestamp() AND purpose='WALL_HEARTBEAT';
 IF NOT FOUND OR p_worker IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=c.wall_id;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_wall_lock(w) THEN RETURN NULL; END IF;
 FOR m IN SELECT * FROM wso_private.tvt_local_media_masters WHERE wall_id=w.id AND state<>'CLOSED' LOOP
   IF m.worker_epoch<>p_worker OR NOT wso_private.wso_tvt_local_media_master_lock(m) THEN RETURN NULL; END IF;
 END LOOP;
 UPDATE wso_private.tvt_local_media_mux_controls SET consumed=true WHERE digest=c.digest;
 RETURN jsonb_build_object('wall_id',w.id,'purpose','WALL_HEARTBEAT');
END;
"""
FOCUS_READ = """
DECLARE f wso_private.tvt_local_media_focus_refs; w wso_private.tvt_local_media_walls;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=p_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=f.wall_id AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.tenants WHERE id=w.tenant_id AND job_generation=w.tenant_epoch)
 OR NOT EXISTS(SELECT 1 FROM public.web_sessions WHERE session_digest=p_session AND user_id=w.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp()) THEN RETURN NULL; END IF;
 RETURN jsonb_build_object('id',f.id,'wall_id',f.wall_id,'lease_id',f.source_lease,'direction',f.direction,'state',f.state,
 'expires_at',CASE WHEN f.state='MAIN_ACTIVE' THEN f.active_expires_at ELSE f.expires_at END);
END;
"""
FOCUS_SETTLE_ISSUE = f"""
DECLARE f wso_private.tvt_local_media_focus_refs; w wso_private.tvt_local_media_walls; token text;
BEGIN
 {LOCK}
 IF p_transition IS NULL OR p_transition NOT IN ('CANCELLED','FAILED') THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=p_focus AND state='PENDING' AND expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO w FROM wso_private.tvt_local_media_walls WHERE id=f.wall_id AND tenant_id=public.wso_current_tenant_id() AND actor_id=public.wso_connection_owner() AND session_digest=p_session;
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_wall_current(w) THEN RETURN NULL; END IF;
 token:={TOKEN};
 INSERT INTO wso_private.tvt_local_media_mux_controls(digest,wall_id,focus_id,purpose,expires_at) VALUES(sha256(convert_to(token,'UTF8')),w.id,f.id,'FOCUS_'||p_transition,least(f.expires_at,clock_timestamp()+interval '20 seconds'));
 RETURN token;
END;
"""
FOCUS_SETTLE_REDEEM = f"""
DECLARE c wso_private.tvt_local_media_mux_controls; f wso_private.tvt_local_media_focus_refs;
BEGIN
 {LOCK}
 SELECT * INTO c FROM wso_private.tvt_local_media_mux_controls WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND NOT consumed AND expires_at>clock_timestamp() AND purpose IN ('FOCUS_CANCELLED','FOCUS_FAILED');
 IF NOT FOUND OR p_worker IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs WHERE id=c.focus_id AND state='PENDING' AND (worker_epoch=p_worker OR worker_epoch IS NULL);
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_masters WHERE id=f.master_id AND worker_epoch=p_worker) THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_local_media_mux_controls SET consumed=true WHERE digest=c.digest;
 RETURN jsonb_build_object('focus_id',f.id,'wall_id',c.wall_id,'transition',substring(c.purpose from 7));
END;
"""

# New lifecycle triggers read every retained slot, including parked ones whose
# original viewer is CLOSED. Legacy trigger semantics remain untouched.
REVOKE = """
DECLARE m wso_private.tvt_local_media_masters;
BEGIN
 FOR m IN SELECT * FROM wso_private.tvt_local_media_masters WHERE state IN ('STARTING','ACTIVE') LOOP
   IF NOT wso_private.wso_tvt_local_media_master_current(m) THEN PERFORM wso_private.wso_tvt_local_media_stop_master(m.id); END IF;
 END LOOP;
 RETURN NULL;
END;
"""
CLEANUP_GUARD = """
BEGIN
 IF OLD.mux_wall_id IS NOT NULL OR NEW.mux_wall_id IS NOT NULL THEN
   -- Legacy media_use records acquisition as LOGIN -> CLAIMED. Preserve that
   -- evidence before the claim can return, even if Stop later overwrites state.
   NEW.mux_acquisition_started:=OLD.mux_acquisition_started OR NEW.mux_acquisition_started
     OR NEW.state IN ('CLAIMED','NEGOTIATING','PLAYING')
     OR NEW.mux_slot_id IS NOT NULL OR NEW.mux_registration IS NOT NULL;
 END IF;
 IF OLD.mux_wall_id IS NULL OR OLD.worker_epoch IS NULL THEN RETURN NEW; END IF;
 IF NEW.state='CLOSED' AND (NOT NEW.mux_viewer_settled OR
 (NEW.mux_cleanup_scope IN ('LAST_VIEWER_AND_DEVICE_EPOCH','DEDICATED_NATIVE') AND NOT NEW.mux_native_settled)) THEN
   RAISE EXCEPTION 'shared cleanup custody required' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END;
"""
LIFECYCLE = (
    ("public.memberships", "UPDATE OR DELETE"),
    ("public.store_connections", "DELETE"),
    ("public.stores", "UPDATE"),
    ("public.connections", "UPDATE OR DELETE"),
    ("public.tenants", "UPDATE"),
    ("public.web_sessions", "UPDATE OR DELETE"),
    ("wso_private.connection_secrets", "UPDATE OR DELETE"),
    ("wso_private.tvt_local_devices", "UPDATE OR DELETE"),
    ("wso_private.tvt_local_channels", "UPDATE OR DELETE"),
)


def _private(name: str, args: str, returns: str, body: str) -> tuple[str, ...]:
    return (f"wso_private.wso_tvt_local_media_{name}", args, returns, body, "")


def _public(
    name: str, args: str, returns: str, body: str, role: str = "wso_connection_worker"
) -> tuple[str, ...]:
    if name not in {
        "master_observe",
        "slot_observe",
        "viewer_observe",
        "focus_observe",
        "focus_settlement_observe",
    }:
        body = (
            body.replace(
                "wso_tvt_local_media_master_current(m)",
                "wso_tvt_local_media_master_lock(m)",
            )
            .replace(
                "wso_tvt_local_media_master_scope(m)",
                "wso_tvt_local_media_master_lock(m)",
            )
            .replace(
                "wso_tvt_local_media_wall_current(w)",
                "wso_tvt_local_media_wall_lock(w)",
            )
            .replace("wso_tvt_local_media_live_read(l)", "wso_tvt_local_media_live(l)")
        )
    return (f"public.wso_tvt_local_media_{name}", args, returns, body, role)


FUNCTIONS = (
    _private(
        "wall_current", "w wso_private.tvt_local_media_walls", "boolean", WALL_CURRENT
    ),
    _private(
        "master_scope", "m wso_private.tvt_local_media_masters", "boolean", MASTER_SCOPE
    ),
    _private(
        "slot_current", "s wso_private.tvt_local_media_slots", "boolean", SLOT_CURRENT
    ),
    _private(
        "focus_current",
        "f wso_private.tvt_local_media_focus_refs",
        "boolean",
        FOCUS_CURRENT,
    ),
    _private(
        "master_current",
        "m wso_private.tvt_local_media_masters",
        "boolean",
        MASTER_CURRENT,
    ),
    _private(
        "master_view", "m wso_private.tvt_local_media_masters", "jsonb", MASTER_VIEW
    ),
    _private("wall_lock", "w wso_private.tvt_local_media_walls", "boolean", WALL_LOCK),
    _private(
        "master_lock", "m wso_private.tvt_local_media_masters", "boolean", MASTER_LOCK
    ),
    _private("stop_master", "p_id uuid", "void", STOP_MASTER),
    _private("finalize_wall", "p_wall uuid", "void", FINALIZE_WALL),
    _private(
        "lease_scope", "l wso_private.tvt_local_media_leases", "jsonb", LEASE_SCOPE
    ),
    _private(
        "operation_view",
        "j wso_private.tvt_local_media_master_operations",
        "jsonb",
        OPERATION_VIEW,
    ),
    _private(
        "master_reserve_core",
        AUTH + ",p_master_authority text,p_master_native uuid",
        "jsonb",
        MASTER_RESERVE.replace(
            "wso_tvt_local_media_live_read(l)", "wso_tvt_local_media_live(l)"
        )
        .replace(
            "wso_tvt_local_media_master_scope(m)", "wso_tvt_local_media_master_lock(m)"
        )
        .replace(
            "wso_tvt_local_media_wall_current(w)", "wso_tvt_local_media_wall_lock(w)"
        ),
    ),
    _public("master_attempt_scope", AUTH, "jsonb", ATTEMPT_SCOPE),
    _public(
        "master_attempt_resolve",
        AUTH + ",p_operation text,p_operation_native uuid,p_scope jsonb",
        "jsonb",
        ATTEMPT_RESOLVE,
    ),
    _public(
        "unstarted_master_close",
        MASTER_AUTH + ",p_scope jsonb,p_receipt jsonb",
        "jsonb",
        UNSTARTED_CLOSE,
    ),
    _public(
        "absent_attempt_close",
        AUTH + ",p_operation text,p_operation_native uuid,p_scope jsonb",
        "jsonb",
        ABSENT_CLOSE,
    ),
    _public(
        "unadopted_follower_close",
        AUTH
        + ",p_master_authority text,p_master_native uuid,p_scope jsonb,p_operation text,p_operation_native uuid",
        "jsonb",
        FOLLOWER_CLOSE,
    ),
    _private(
        "focus_settlement_view",
        "f wso_private.tvt_local_media_focus_refs",
        "jsonb",
        FOCUS_SETTLEMENT_VIEW,
    ),
    _public(
        "wall_issue", "p_session text,p_ttl integer", "jsonb", WALL_ISSUE, "wso_app"
    ),
    _public(
        "wall_read",
        "p_session text,p_wall uuid,p_heartbeat boolean",
        "jsonb",
        WALL_READ,
        "wso_app",
    ),
    _public(
        "shared_issue",
        "p_session text,p_connection uuid,p_store uuid,p_device uuid,p_channel uuid,p_generation bigint,p_revision bigint,p_stream text,p_ttl integer,p_wall uuid,p_focus uuid DEFAULT NULL",
        "text",
        SHARED_ISSUE,
        "wso_app",
    ),
    _public("wall_view", "p_session text,p_wall uuid", "jsonb", WALL_VIEW, "wso_app"),
    _public(
        "master_reserve",
        AUTH
        + ",p_master_authority text,p_master_native uuid,p_operation text DEFAULT NULL,p_scope jsonb DEFAULT NULL",
        "jsonb",
        JOURNAL_RESERVE,
    ),
    _public("master_login", MASTER_AUTH, "jsonb", MASTER_LOGIN),
    _public(
        "master_activate", MASTER_AUTH + ",p_proof jsonb", "jsonb", MASTER_ACTIVATE
    ),
    _public("master_observe", MASTER_AUTH, "jsonb", MASTER_OBSERVE),
    _public(
        "slot_reserve",
        AUTH
        + ",p_master_authority text,p_master_native uuid,p_slot_authority text,p_task uuid,p_wire_generation bigint,p_wire_session bytea,p_channel_guid bytea",
        "jsonb",
        SLOT_RESERVE,
    ),
    _public(
        "slot_observe",
        "p_slot_authority text,p_worker uuid,p_master_native uuid",
        "jsonb",
        SLOT_OBSERVE,
    ),
    _public(
        "viewer_admit",
        AUTH + ",p_registration uuid,p_slot_authority text",
        "jsonb",
        VIEWER_ADMIT,
    ),
    _public("viewer_selection", AUTH, "jsonb", VIEWER_SELECTION),
    _public("viewer_observe", AUTH + ",p_registration uuid", "jsonb", VIEWER_OBSERVE),
    _public(
        "viewer_activate",
        AUTH + ",p_registration uuid,p_proof jsonb",
        "jsonb",
        VIEWER_ACTIVATE,
    ),
    _public(
        "viewer_close",
        AUTH + ",p_registration uuid,p_scope text,p_receipt jsonb",
        "void",
        VIEWER_CLOSE,
    ),
    _public("epoch_close", MASTER_AUTH + ",p_receipt jsonb", "void", EPOCH_CLOSE),
    _public(
        "dedicated_close",
        AUTH + ",p_registration uuid,p_receipt jsonb",
        "void",
        DEDICATED_CLOSE,
    ),
    _public(
        "dedicated_register", AUTH + ",p_registration uuid", "jsonb", DEDICATED_REGISTER
    ),
    _public(
        "focus_issue",
        "p_session text,p_id uuid,p_direction text,p_deadline_at timestamptz",
        "text",
        FOCUS_ISSUE,
        "wso_app",
    ),
    _public("focus_redeem", "p_ticket text,p_worker uuid", "jsonb", FOCUS_REDEEM),
    _public(
        "focus_observe", "p_focus_authority text,p_worker uuid", "jsonb", FOCUS_OBSERVE
    ),
    _public(
        "focus_settle",
        "p_focus_authority text,p_worker uuid,p_transition text,p_viewer uuid DEFAULT NULL",
        "jsonb",
        FOCUS_SETTLE,
    ),
    _public(
        "focus_settlement_observe",
        "p_focus_authority text,p_worker uuid",
        "jsonb",
        FOCUS_SETTLEMENT_OBSERVE,
    ),
    _public(
        "wall_control_issue",
        "p_session text,p_wall uuid,p_purpose text",
        "text",
        WALL_CONTROL_ISSUE,
        "wso_app",
    ),
    _public(
        "wall_stop_issue",
        "p_session text,p_wall uuid",
        "text",
        "BEGIN RETURN public.wso_tvt_local_media_wall_control_issue(p_session,p_wall,'WALL_STOP');END;",
        "wso_app",
    ),
    _public(
        "wall_control_redeem",
        "p_ticket text,p_worker uuid",
        "jsonb",
        WALL_CONTROL_REDEEM,
    ),
    _public(
        "wall_heartbeat_redeem",
        "p_ticket text,p_worker uuid",
        "jsonb",
        WALL_HEARTBEAT_REDEEM,
    ),
    _public("focus_read", "p_session text,p_id uuid", "jsonb", FOCUS_READ, "wso_app"),
    _public(
        "focus_settle_issue",
        "p_session text,p_focus uuid,p_transition text",
        "text",
        FOCUS_SETTLE_ISSUE,
        "wso_app",
    ),
    _public(
        "focus_settle_redeem",
        "p_ticket text,p_worker uuid",
        "jsonb",
        FOCUS_SETTLE_REDEEM,
    ),
    _private("mux_revoke", "", "trigger", REVOKE),
    _private("mux_cleanup_guard", "", "trigger", CLEANUP_GUARD),
)


def upgrade() -> None:
    op.execute(SCHEMA)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} OWNER TO {OWNER};
ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
GRANT ALL ON wso_private.{table} TO wso_migrator;
CREATE POLICY mux_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
CREATE POLICY mux_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);""")
    for name, args, returns, body, role in FUNCTIONS:
        signature = f"{name}({args})"
        op.execute(
            f"CREATE FUNCTION {signature} RETURNS {returns} {OPTIONS} AS $mux$ {body} $mux$"
        )
        identity = signature.replace(" DEFAULT NULL", "")
        op.execute(f"ALTER FUNCTION {identity} OWNER TO {OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION {identity} FROM {RUNTIME}")
        if role:
            op.execute(f"GRANT EXECUTE ON FUNCTION {identity} TO {role}")
    for table, event in LIFECYCLE:
        op.execute(
            f"CREATE TRIGGER mux_revoke AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION wso_private.wso_tvt_local_media_mux_revoke()"
        )
    op.execute(
        "CREATE TRIGGER mux_cleanup_guard BEFORE UPDATE ON wso_private.tvt_local_media_leases FOR EACH ROW EXECUTE FUNCTION wso_private.wso_tvt_local_media_mux_cleanup_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER mux_cleanup_guard ON wso_private.tvt_local_media_leases")
    for table, _ in LIFECYCLE:
        op.execute(f"DROP TRIGGER mux_revoke ON {table}")
    for name, args, *_ in reversed(FUNCTIONS):
        # DEFAULT belongs to CREATE only, never identity/ALTER/DROP signatures.
        args = args.replace(" DEFAULT NULL", "")
        op.execute(f"DROP FUNCTION {name}({args})")
    for column in (
        "mux_acquisition_started",
        "mux_native_settled",
        "mux_viewer_settled",
        "mux_cleanup_scope",
        "mux_registration",
        "mux_focus_id",
        "mux_slot_id",
        "mux_master_id",
        "mux_wall_id",
    ):
        op.execute(
            f"ALTER TABLE wso_private.tvt_local_media_leases DROP COLUMN {column}"
        )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE wso_private.{table}")
