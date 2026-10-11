"""Observe original MAIN retention across an exact bounded pending RETURN."""

from alembic import op

revision = "0017_tvt_main_return_retention"
down_revision = "0016_tvt_device_media_epochs"
branch_labels = None
depends_on = None

BODY = """
DECLARE f wso_private.tvt_local_media_focus_refs;
 latest wso_private.tvt_local_media_focus_refs;
 r wso_private.tvt_local_media_focus_refs;
 m wso_private.tvt_local_media_masters;
 l wso_private.tvt_local_media_leases;
 first_m wso_private.tvt_local_media_masters;
 first_l wso_private.tvt_local_media_leases;
 mode text; expiry timestamptz; valid boolean; pending_count integer;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RETURN NULL; END IF;
 FOR probe IN 1..2 LOOP
   SELECT * INTO f FROM wso_private.tvt_local_media_focus_refs
   WHERE authority_digest=sha256(convert_to(p_focus_authority,'UTF8'))
   AND worker_epoch=p_worker AND direction='FORWARD' AND attached_viewer=p_main;
   IF NOT FOUND THEN RETURN NULL; END IF;
   SELECT * INTO m FROM wso_private.tvt_local_media_masters
   WHERE id=f.master_id AND worker_epoch=p_worker AND wall_id=f.wall_id;
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_master_current(m) THEN RETURN NULL; END IF;
   SELECT * INTO l FROM wso_private.tvt_local_media_leases
   WHERE id=p_main AND mux_focus_id=f.id AND mux_wall_id=f.wall_id
   AND channel_id=f.channel_id AND worker_epoch=p_worker AND stream='main'
   AND state IN ('NEGOTIATING','PLAYING');
   IF NOT FOUND OR NOT wso_private.wso_tvt_local_media_live_read(l)
   OR (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision)
   IS DISTINCT FROM (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.store_id,m.device_id,m.connection_id,m.generation,m.version_id,m.inventory_revision)
   THEN RETURN NULL; END IF;
   first_m:=m; first_l:=l;
   -- Classify after original MAIN/master/rights observation. A RETURN committed
   -- during those calls legitimately replaces the initial MAIN_ACTIVE branch.
   SELECT * INTO latest FROM wso_private.tvt_local_media_focus_refs
   WHERE id=f.id AND authority_digest=f.authority_digest AND worker_epoch=p_worker;
   IF NOT FOUND OR (latest.master_id,latest.wall_id,latest.channel_id,latest.source_lease,latest.direction,latest.attached_viewer)
   IS DISTINCT FROM (f.master_id,f.wall_id,f.channel_id,f.source_lease,f.direction,f.attached_viewer)
   THEN RETURN NULL; END IF;
   f:=latest; valid:=false; r:=NULL;
   IF f.state='MAIN_ACTIVE' THEN
     mode:='MAIN_ACTIVE'; expiry:=least(f.active_expires_at,l.expires_at,m.expires_at);
     valid:=f.active_expires_at>clock_timestamp();
   ELSIF f.state='CONSUMED' THEN
     SELECT count(*) INTO pending_count FROM wso_private.tvt_local_media_focus_refs
     WHERE wall_id=f.wall_id AND state='PENDING' AND expires_at>clock_timestamp();
     SELECT * INTO r FROM wso_private.tvt_local_media_focus_refs
     WHERE wall_id=f.wall_id AND master_id=f.master_id AND channel_id=f.channel_id
     AND source_lease=p_main AND direction='RETURN' AND state='PENDING'
     AND expires_at>clock_timestamp() AND expires_at<=issued_at+interval '20 seconds'
     AND ((worker_epoch IS NULL AND authority_digest IS NULL)
       OR (worker_epoch=p_worker AND authority_digest IS NOT NULL));
     valid:=FOUND AND pending_count=1;
     mode:='RETURN_PENDING'; expiry:=least(r.expires_at,l.expires_at,m.expires_at);
   ELSE RETURN NULL;
   END IF;
   -- Reload original MAIN/master before final validation; stale PLAYING
   -- composites cannot authorize a MAIN already committed to STOPPING.
   SELECT * INTO m FROM wso_private.tvt_local_media_masters
   WHERE id=first_m.id AND worker_epoch=p_worker AND native_generation=first_m.native_generation
   AND wall_id=f.wall_id;
   IF NOT FOUND OR m.state NOT IN ('STARTING','ACTIVE') THEN RETURN NULL; END IF;
   SELECT * INTO l FROM wso_private.tvt_local_media_leases
   WHERE id=p_main AND native_generation=first_l.native_generation AND worker_epoch=p_worker
   AND mux_focus_id=f.id AND mux_wall_id=f.wall_id AND channel_id=f.channel_id
   AND stream='main' AND state IN ('NEGOTIATING','PLAYING');
   IF NOT FOUND
   OR (l.tenant_id,l.tenant_epoch,l.actor_id,l.session_digest,l.store_id,l.device_id,l.connection_id,l.generation,l.version_id,l.inventory_revision)
   IS DISTINCT FROM (m.tenant_id,m.tenant_epoch,m.actor_id,m.session_digest,m.store_id,m.device_id,m.connection_id,m.generation,m.version_id,m.inventory_revision)
   THEN RETURN NULL; END IF;
   expiry:=least(expiry,l.expires_at,m.expires_at);
   IF NOT wso_private.wso_tvt_local_media_master_current(m)
   OR NOT wso_private.wso_tvt_local_media_live_read(l) THEN RETURN NULL; END IF;
   SELECT * INTO latest FROM wso_private.tvt_local_media_focus_refs
   WHERE id=f.id AND worker_epoch=p_worker AND authority_digest=f.authority_digest
   AND (master_id,wall_id,channel_id,source_lease,direction,attached_viewer)
   IS NOT DISTINCT FROM (f.master_id,f.wall_id,f.channel_id,f.source_lease,f.direction,f.attached_viewer);
   IF NOT FOUND THEN RETURN NULL; END IF;
   IF latest.state IS DISTINCT FROM f.state THEN CONTINUE; END IF;
   IF NOT valid OR expiry<=clock_timestamp() THEN RETURN NULL; END IF;
   IF NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_leases x
     WHERE x.id=l.id AND x.worker_epoch=p_worker AND x.native_generation=l.native_generation
     AND x.mux_focus_id=f.id AND x.mux_wall_id=f.wall_id AND x.channel_id=f.channel_id
     AND x.stream='main' AND x.state IN ('NEGOTIATING','PLAYING') AND NOT x.invalidated
     AND x.expires_at>clock_timestamp())
   OR NOT EXISTS(SELECT 1 FROM wso_private.tvt_local_media_masters x
     WHERE x.id=m.id AND x.worker_epoch=p_worker AND x.native_generation=m.native_generation
     AND x.wall_id=f.wall_id AND x.state IN ('STARTING','ACTIVE') AND x.expires_at>clock_timestamp())
   THEN RETURN NULL; END IF;
   IF mode='RETURN_PENDING' AND NOT EXISTS(
     SELECT 1 FROM wso_private.tvt_local_media_focus_refs x
     WHERE x.id=r.id AND x.wall_id=f.wall_id AND x.master_id=f.master_id
     AND x.channel_id=f.channel_id AND x.source_lease=p_main
     AND x.direction='RETURN' AND x.state='PENDING' AND x.expires_at>clock_timestamp()
     AND x.expires_at=r.expires_at AND x.issued_at=r.issued_at
     AND ((x.worker_epoch IS NULL AND x.authority_digest IS NULL)
       OR (x.worker_epoch=p_worker AND x.authority_digest IS NOT NULL)))
   THEN RETURN NULL; END IF;
   RETURN wso_private.wso_tvt_local_media_focus_settlement_view(latest)
     ||jsonb_build_object('main_id',l.id,'dedicated_native_generation',l.native_generation,
       'retention_state',mode,'return_focus_id',r.id,'expires_at',expiry);
 END LOOP;
 RETURN NULL;
END;
"""

SIGNATURE = "public.wso_tvt_local_media_main_retention_observe(text,uuid,uuid)"


def upgrade() -> None:
    op.execute(
        "CREATE FUNCTION public.wso_tvt_local_media_main_retention_observe("
        "p_focus_authority text,p_worker uuid,p_main uuid) RETURNS jsonb "
        "LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog "
        "SET lock_timeout='3s' AS $main_return$ " + BODY + " $main_return$"
    )
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO wso_tvt_local_owner")
    op.execute(
        f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC,wso_app,"
        "wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,"
        "wso_dispatcher,wso_asset_maintenance"
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO wso_connection_worker")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {SIGNATURE}")
