"""Non-locking hot-path media authority read (R120/R121); 0013 stays the locking path.

``observe`` answers the worker's per-frame authority cache. It is 0013's worker
view on ``live_read``: 0013's LIVE predicate with every FOR SHARE removed, so it
assigns no transaction ID and writes no row-lock WAL. A volatile plpgsql
function in READ COMMITTED takes a fresh snapshot per statement, so it sees any
revoke committed before the check began. State transitions, startup open and
API paths keep the locking LIVE.
"""

from alembic import op

# alembic_version.version_num is varchar(32); the file stem would not fit.
revision = "0014_tvt_local_media_hot_auth"
down_revision = "0013_tvt_local_media_leases"
branch_labels = None
depends_on = None
OWNER = "wso_tvt_local_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
# The function options of every 0013 media function.
OPTIONS = "LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s'"

LIVE_READ = """
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR l.id IS NULL OR l.invalidated OR l.expires_at<=clock_timestamp() OR l.state NOT IN ('REQUESTED','LOGIN','CLAIMED','NEGOTIATING','PLAYING') THEN RETURN false; END IF;
 IF l.state IN ('REQUESTED','LOGIN','CLAIMED') AND l.login_expires_at<=clock_timestamp() THEN RETURN false; END IF;
 PERFORM 1 FROM public.tenants x WHERE x.id=l.tenant_id AND x.job_generation=l.tenant_epoch;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.memberships x WHERE x.tenant_id=l.tenant_id AND x.user_id=l.actor_id AND x.role='OWNER';
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.connections x WHERE x.tenant_id=l.tenant_id AND x.id=l.connection_id AND x.kind='TVT_DEVICE' AND x.status='NOT_VERIFIED' AND x.generation=l.generation;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.stores x WHERE x.tenant_id=l.tenant_id AND x.id=l.store_id AND x.active;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.store_connections x WHERE x.tenant_id=l.tenant_id AND x.connection_id=l.connection_id AND x.store_id=l.store_id;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.web_sessions x WHERE x.session_digest=l.session_digest AND x.user_id=l.actor_id AND x.revoked_at IS NULL AND x.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.connection_secrets x WHERE x.tenant_id=l.tenant_id AND x.connection_id=l.connection_id AND x.version_id=l.version_id;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_local_devices d JOIN public.web_sessions s ON s.session_digest=d.session_digest AND s.user_id=d.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp()
 WHERE d.id=l.device_id AND d.tenant_id=l.tenant_id AND d.connection_id=l.connection_id AND d.store_id=l.store_id AND d.actor_id=l.actor_id AND d.generation=l.generation AND d.tenant_epoch=l.tenant_epoch AND d.revision=l.inventory_revision AND NOT d.invalidated;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_local_channels x WHERE x.id=l.channel_id AND x.tenant_id=l.tenant_id AND x.device_id=l.device_id AND x.revision=l.inventory_revision AND x.active;
 IF NOT FOUND THEN RETURN false; END IF;
 IF l.state IN ('NEGOTIATING','PLAYING') THEN
   PERFORM 1 FROM wso_private.tvt_local_media_grants g WHERE g.lease_id=l.id AND g.revision=l.grant_revision AND g.native_generation=l.native_generation AND NOT g.invalidated;
   IF NOT FOUND THEN RETURN false; END IF;
 END IF;
 RETURN l.expires_at>clock_timestamp();
END;
"""
OBSERVE = """
DECLARE l wso_private.tvt_local_media_leases;
BEGIN
 SELECT * INTO l FROM wso_private.tvt_local_media_leases x WHERE x.authority_digest=sha256(convert_to(p_authority,'UTF8')) AND x.worker_epoch=p_worker AND x.native_generation=p_native AND x.state IN ('NEGOTIATING','PLAYING');
 IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
 RETURN wso_private.wso_tvt_local_media_view(l);
END;
"""
FUNCTIONS = (
    (
        "wso_private.wso_tvt_local_media_live_read",
        "l wso_private.tvt_local_media_leases",
        "boolean",
        LIVE_READ,
        "",
    ),
    (
        "public.wso_tvt_local_media_observe",
        "p_authority text,p_worker uuid,p_native uuid",
        "jsonb",
        OBSERVE,
        "wso_connection_worker",
    ),
)


def upgrade() -> None:
    for name, args, returns, body, grantee in FUNCTIONS:
        signature = f"{name}({args})"
        op.execute(
            f"CREATE FUNCTION {signature} RETURNS {returns} {OPTIONS} AS $media$ {body} $media$"
        )
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {OWNER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM {RUNTIME}")
        if grantee:
            op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {grantee}")


def downgrade() -> None:
    for name, args, *_ in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {name}({args})")
