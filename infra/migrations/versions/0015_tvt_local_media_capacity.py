"""Raise local media admission caps; preserve all authority and custody rules."""

from alembic import op

revision = "0015_tvt_local_media_capacity"
down_revision = "0014_tvt_local_media_hot_auth"
branch_labels = None
depends_on = None

ORIGINAL_ISSUE = """
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
ISSUE = ORIGINAL_ISSUE.replace(">=32\n", ">=64\n").replace(">=4 THEN", ">=16 THEN")
SIGNATURE = "public.wso_tvt_local_media_issue(p_session text,p_connection uuid,p_store uuid,p_device uuid,p_channel uuid,p_generation bigint,p_revision bigint,p_stream text,p_ttl integer)"
OPTIONS = "LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s'"


def upgrade() -> None:
    # CREATE OR REPLACE retains 0013's owner and exact function grants.
    op.execute(
        f"CREATE OR REPLACE FUNCTION {SIGNATURE} RETURNS text {OPTIONS} AS $media$ {ISSUE} $media$"
    )


def downgrade() -> None:
    op.execute(
        f"CREATE OR REPLACE FUNCTION {SIGNATURE} RETURNS text {OPTIONS} AS $media$ {ORIGINAL_ISSUE} $media$"
    )
