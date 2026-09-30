"""Private image metadata and narrowly authorized lifecycle capabilities."""

from alembic import op

revision = "0003a_assets"
down_revision = "0003_jobs"
branch_labels = None
depends_on = None

POLICY = {
    "version": (1, 2147483647),
    "max_bytes": (20971520, 20971520),
    "max_pixels": (25000000, 25000000),
    "max_dimension": (10000, 10000),
    "max_frames": (1, 1),
    "chunk_bytes": (262144, 262144),
    "multipart_part_bytes": (5242880, 5242880),
    "upload_seconds": (120, 120),
    "verification_seconds": (30, 30),
    "download_seconds": (30, 30),
    "job_read_seconds": (10, 10),
    "decoder_seconds": (10, 10),
    "decoder_memory_bytes": (536870912, 536870912),
}
PRIVATE_PRIVILEGES = {
    "asset_settings": "SELECT,UPDATE",
    "asset_uploads": "SELECT,INSERT,UPDATE",
    "asset_tickets": "SELECT,INSERT,UPDATE,DELETE",
    "asset_read_leases": "SELECT,INSERT,UPDATE",
    "asset_cleanup": "SELECT,INSERT,UPDATE",
    "asset_job_kinds": "SELECT",
}
ASSET_COLUMNS = "id uuid,tenant_id uuid,store_id uuid,purpose text,parent_asset_id uuid,state text,checksum_sha256 text,byte_size bigint,content_type text,expires_at timestamptz,created_at timestamptz"
ASSET_SELECT = "a.id,a.tenant_id,a.store_id,a.purpose,a.parent_asset_id,a.state,a.checksum_sha256,a.byte_size,a.content_type,a.expires_at,a.created_at"
MANIFEST_COLUMNS = "installation_id uuid,tenant_id uuid,asset_id uuid,attempt_id uuid,store_id uuid,parent_asset_id uuid,purpose text,byte_size bigint,content_type text,checksum_sha256 text,object_key text,key_id text,wrapped_dek bytea,wrap_nonce bytea,object_nonce bytea,lease_id uuid,lease_generation bigint,lease_expires_at timestamptz,lease_remaining_ms integer,lease_token text,access_generation bigint,parent_access_generation bigint,policy_version integer"
TABLES = (
    "public.assets",
    "public.job_assets",
    "wso_private.asset_settings",
    "wso_private.asset_uploads",
    "wso_private.asset_tickets",
    "wso_private.asset_read_leases",
    "wso_private.asset_cleanup",
    "wso_private.asset_job_kinds",
)


def fn(signature, declaration, body, grantee="", *, language="plpgsql"):
    # Named TABLE output variables share column names. SQL references resolve to
    # columns; input parameters and local records always use explicit p_/record names.
    if language == "plpgsql":
        body = "#variable_conflict use_column\n" + body
    op.execute(
        f"CREATE OR REPLACE FUNCTION public.{declaration} LANGUAGE {language} SECURITY DEFINER SET search_path=pg_catalog AS $asset$ {body} $asset$"
    )
    op.execute(f"ALTER FUNCTION public.{signature} OWNER TO wso_asset_owner")
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    if grantee:
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {grantee}")


def upgrade():
    for role, login in (
        ("wso_asset_owner", "NOLOGIN"),
        ("wso_asset_maintenance", "LOGIN"),
    ):
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role}; END IF; END $$"
        )
        op.execute(
            f"ALTER ROLE {role} {login} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT FROM pg_auth_members WHERE member='{role}'::regrole OR roleid='{role}'::regrole) THEN RAISE EXCEPTION 'asset role membership is forbidden'; END IF; END $$"
        )
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute("GRANT USAGE ON SCHEMA wso_private TO wso_asset_owner")
    policy_columns = ",".join(
        f"{name} integer NOT NULL DEFAULT {default} CHECK({name} BETWEEN {default if name in ('max_frames', 'multipart_part_bytes') else 1} AND {maximum})"
        for name, (default, maximum) in POLICY.items()
    )
    op.execute(f"""
      CREATE TABLE wso_private.asset_settings(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
        installation_id uuid,bucket text CHECK(length(bucket) BETWEEN 3 AND 63 AND bucket ~ '^[a-z0-9][a-z0-9.-]{{1,61}}[a-z0-9]$' AND position('..' in bucket)=0),
        CHECK((installation_id IS NULL)=(bucket IS NULL)),{policy_columns},
        session_seconds integer NOT NULL DEFAULT 900 CHECK(session_seconds BETWEEN 1 AND 900),
        retention_seconds integer NOT NULL DEFAULT 604800 CHECK(retention_seconds BETWEEN 1 AND 604800),
        pending_limit integer NOT NULL DEFAULT 20 CHECK(pending_limit BETWEEN 1 AND 20),
        tenant_byte_limit bigint NOT NULL DEFAULT 1073741824 CHECK(tenant_byte_limit BETWEEN 1 AND 1073741824),
        crop_limit integer NOT NULL DEFAULT 100 CHECK(crop_limit BETWEEN 1 AND 100),
        cleanup_seconds integer NOT NULL DEFAULT 30 CHECK(cleanup_seconds BETWEEN 1 AND 30),
        grace_seconds integer NOT NULL DEFAULT 10 CHECK(grace_seconds BETWEEN 1 AND 10));
      INSERT INTO wso_private.asset_settings(singleton) VALUES(true);
      CREATE TABLE public.assets(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(id),store_id uuid,
        purpose text NOT NULL CHECK(purpose IN ('IMPORT_PHOTO','IMPORT_CROP','EVIDENCE')),parent_asset_id uuid,
        creator_id uuid NOT NULL REFERENCES public.users(id),state text NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','READY','DELETING','DELETED','REJECTED')),
        checksum_sha256 text NOT NULL CHECK(checksum_sha256 ~ '^[0-9a-f]{{64}}$'),byte_size bigint NOT NULL CHECK(byte_size BETWEEN 1 AND 20971520),
        content_type text NOT NULL CHECK(content_type IN ('image/png','image/jpeg')),created_at timestamptz NOT NULL DEFAULT clock_timestamp(),expires_at timestamptz NOT NULL,
        access_generation bigint NOT NULL DEFAULT 1 CHECK(access_generation>0),policy_version integer NOT NULL CHECK(policy_version>0),
        width integer,height integer,oriented_width integer,oriented_height integer,frame_count integer,
        tombstoned_at timestamptz,deleted_at timestamptz,
        CONSTRAINT asset_tenant_identity UNIQUE(tenant_id,id),CONSTRAINT asset_store_fk FOREIGN KEY(tenant_id,store_id) REFERENCES public.stores(tenant_id,id),
        CONSTRAINT asset_parent_fk FOREIGN KEY(tenant_id,parent_asset_id) REFERENCES public.assets(tenant_id,id),
        CONSTRAINT asset_parent_shape CHECK((purpose='IMPORT_CROP')=(parent_asset_id IS NOT NULL)),
        CONSTRAINT asset_evidence_store CHECK(purpose<>'EVIDENCE' OR store_id IS NOT NULL),CHECK(expires_at>created_at));
      CREATE INDEX ix_assets_expiry ON public.assets(state,expires_at);
      CREATE INDEX ix_assets_parent ON public.assets(tenant_id,parent_asset_id,id);
      CREATE TABLE wso_private.asset_uploads(asset_id uuid PRIMARY KEY,tenant_id uuid NOT NULL,id uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
        creator_id uuid NOT NULL,session_digest text NOT NULL CHECK(session_digest ~ '^[0-9a-f]{{64}}$'),expires_at timestamptz NOT NULL,
        status text NOT NULL DEFAULT 'ALLOCATED' CHECK(status IN ('ALLOCATED','WRITING','SEALED','VERIFYING','FINISHED')),
        generation bigint NOT NULL DEFAULT 0 CHECK(generation>=0),lease_id uuid,lease_digest bytea,lease_expires_at timestamptz,
        object_key text,key_id text,wrapped_dek bytea,wrap_nonce bytea,object_nonce bytea,multipart_id text,
        completion_dispatched boolean NOT NULL DEFAULT false,remote_uncertain boolean NOT NULL DEFAULT false,remote_observed boolean NOT NULL DEFAULT false,failure_code text,
        FOREIGN KEY(tenant_id,asset_id) REFERENCES public.assets(tenant_id,id),
        CHECK(wrapped_dek IS NULL OR octet_length(wrapped_dek)=48),CHECK(wrap_nonce IS NULL OR octet_length(wrap_nonce)=12),CHECK(object_nonce IS NULL OR octet_length(object_nonce)=12),
        CHECK(multipart_id IS NULL OR length(multipart_id) BETWEEN 1 AND 1024));
      CREATE TABLE wso_private.asset_tickets(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,asset_id uuid NOT NULL,
        token_digest bytea NOT NULL UNIQUE,actor_id uuid NOT NULL,session_digest text NOT NULL,access_generation bigint NOT NULL,parent_access_generation bigint,
        expires_at timestamptz NOT NULL,redeemed_at timestamptz,FOREIGN KEY(tenant_id,asset_id) REFERENCES public.assets(tenant_id,id));
      CREATE TABLE wso_private.asset_read_leases(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,asset_id uuid NOT NULL,
        access_generation bigint NOT NULL,parent_access_generation bigint,reader_kind text NOT NULL CHECK(reader_kind IN ('DOWNLOAD','JOB')),
        actor_id uuid NOT NULL,session_digest text,job_id uuid,job_generation bigint,expires_at timestamptz NOT NULL,closed_at timestamptz,
        FOREIGN KEY(tenant_id,asset_id) REFERENCES public.assets(tenant_id,id));
      CREATE INDEX ix_asset_read_deadline ON wso_private.asset_read_leases(asset_id,expires_at) WHERE closed_at IS NULL;
      CREATE TABLE wso_private.asset_cleanup(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,asset_id uuid NOT NULL,attempt_id uuid NOT NULL,
        operation text NOT NULL CHECK(operation IN ('DELETE_OBJECT','ABORT_MULTIPART')),multipart_id text,
        status text NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','LEASED','DONE')),due_at timestamptz NOT NULL,
        generation bigint NOT NULL DEFAULT 0,lease_id uuid,lease_digest bytea,lease_expires_at timestamptz,worker_id text,attempts integer NOT NULL DEFAULT 0,error_code text,
        CONSTRAINT asset_cleanup_target UNIQUE NULLS NOT DISTINCT(asset_id,attempt_id,operation,multipart_id));
      CREATE INDEX ix_asset_cleanup_due ON wso_private.asset_cleanup(status,due_at,lease_expires_at);
      CREATE TABLE public.job_assets(tenant_id uuid NOT NULL,job_id uuid NOT NULL,asset_id uuid NOT NULL,access_generation bigint NOT NULL,
        PRIMARY KEY(tenant_id,job_id,asset_id),FOREIGN KEY(tenant_id,job_id) REFERENCES public.jobs(tenant_id,id),FOREIGN KEY(tenant_id,asset_id) REFERENCES public.assets(tenant_id,id));
      CREATE TABLE wso_private.asset_job_kinds(kind text NOT NULL,purpose text NOT NULL CHECK(purpose IN ('IMPORT_PHOTO','IMPORT_CROP','EVIDENCE')),operation text NOT NULL CHECK(operation='READ'),PRIMARY KEY(kind,purpose,operation));
    """)
    for table in TABLES:
        owner = (
            "wso_migrator" if table.startswith("wso_private.") else "wso_asset_owner"
        )
        op.execute(f"ALTER TABLE {table} OWNER TO {owner}")
        if table.startswith("wso_private."):
            op.execute(
                f"GRANT {PRIVATE_PRIVILEGES[table.split('.')[1]]} ON {table} TO wso_asset_owner"
            )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"REVOKE ALL ON {table} FROM PUBLIC,wso_app,wso_job_worker,wso_asset_maintenance,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_dispatcher"
        )
        op.execute(
            f"CREATE POLICY asset_owner ON {table} TO wso_asset_owner USING(true) WITH CHECK(true)"
        )
        op.execute(
            f"CREATE POLICY asset_migrator ON {table} TO wso_migrator USING(true) WITH CHECK(true)"
        )
        op.execute(f"GRANT ALL ON {table} TO wso_migrator")
    columns = {
        "public.memberships": "tenant_id,user_id,role",
        "public.tenants": "id,job_generation",
        "public.stores": "id,tenant_id,active",
        "wso_private.tenant_contexts": "backend_pid,transaction_id,tenant_id,user_id,role",
        "public.web_sessions": "session_digest,user_id,expires_at,revoked_at",
        "public.jobs": "id,tenant_id,scope_kind,store_id,actor_user_id,kind,state,lease_generation,lease_expires_at,cancel_requested_at",
        "wso_private.job_contexts": "backend_pid,transaction_id,job_id,tenant_id,actor_id,lease_generation,expires_at",
    }
    for table, cols in columns.items():
        op.execute(f"GRANT SELECT({cols}) ON {table} TO wso_asset_owner")
        op.execute(
            f"CREATE POLICY asset_authority_read ON {table} TO wso_asset_owner USING(true)"
        )
    # PostgreSQL row-lock statements require UPDATE on at least one column.
    for table, col in (
        ("memberships", "role"),
        ("tenants", "job_generation"),
        ("stores", "active"),
        ("jobs", "id"),
    ):
        op.execute(f"GRANT UPDATE({col}) ON public.{table} TO wso_asset_owner")
    op.execute("GRANT INSERT ON public.audit_events TO wso_asset_owner")
    op.execute(
        "CREATE POLICY asset_audit ON public.audit_events FOR INSERT TO wso_asset_owner WITH CHECK(true)"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_current_job_id(),public.wso_job_authorized(uuid) TO wso_asset_owner"
    )
    _configuration()
    _audit_outbox()
    _authority()
    _allocation()
    _tombstone()
    _completion_fence()
    _write_controls()
    _read_controls()
    _maintenance()
    _job_reads()
    _reconciliation()
    _guards()


def _configuration():
    names = ",".join(POLICY)
    fn(
        "wso_asset_runtime_configuration()",
        "wso_asset_runtime_configuration() RETURNS TABLE(installation_id uuid,bucket text,"
        + ",".join(f"{n} integer" for n in POLICY)
        + ")",
        f"SELECT installation_id,bucket,{names} FROM wso_private.asset_settings WHERE singleton FOR SHARE",
        "wso_app,wso_job_worker,wso_asset_maintenance,wso_migrator",
        language="sql",
    )
    fn(
        "wso_asset_settings_guard()",
        "wso_asset_settings_guard() RETURNS trigger",
        """
      BEGIN
        IF OLD.installation_id IS NOT NULL AND (NEW.installation_id IS DISTINCT FROM OLD.installation_id OR NEW.bucket IS DISTINCT FROM OLD.bucket) THEN RAISE EXCEPTION 'asset namespace immutable' USING ERRCODE='40001'; END IF;
        IF (to_jsonb(NEW)-ARRAY['installation_id','bucket','version']) IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['installation_id','bucket','version']) AND NEW.version<=OLD.version THEN RAISE EXCEPTION 'asset policy version required' USING ERRCODE='22023'; END IF;
        IF NEW.version<OLD.version THEN RAISE EXCEPTION 'asset policy version required' USING ERRCODE='22023'; END IF;
        RETURN NEW;
      END;""",
    )
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='wso_private.asset_settings'::regclass AND tgname='asset_settings_guard') THEN CREATE TRIGGER asset_settings_guard BEFORE UPDATE ON wso_private.asset_settings FOR EACH ROW EXECUTE FUNCTION public.wso_asset_settings_guard(); END IF; END $$"
    )
    fn(
        "wso_install_asset_runtime_configuration(uuid,text)",
        "wso_install_asset_runtime_configuration(p_installation_id uuid,p_bucket text) RETURNS void",
        """
      DECLARE s wso_private.asset_settings%ROWTYPE;
      BEGIN
        IF p_installation_id IS NULL OR p_bucket IS NULL OR length(p_bucket) NOT BETWEEN 3 AND 63 OR p_bucket !~ '^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$' OR position('..' in p_bucket)>0 THEN RAISE EXCEPTION 'asset configuration invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO s FROM wso_private.asset_settings WHERE singleton FOR UPDATE;
        IF NOT FOUND THEN RAISE EXCEPTION 'asset configuration unavailable' USING ERRCODE='55000'; END IF;
        IF s.installation_id IS NOT NULL THEN
          IF s.installation_id<>p_installation_id OR s.bucket<>p_bucket THEN RAISE EXCEPTION 'asset namespace immutable' USING ERRCODE='40001'; END IF; RETURN;
        END IF;
        UPDATE wso_private.asset_settings SET installation_id=p_installation_id,bucket=p_bucket WHERE singleton;
      END;""",
        "wso_migrator",
    )


def _authority():
    fn(
        "wso_asset_actor(text,uuid,boolean)",
        "wso_asset_actor(p_session text,p_store uuid,p_lock boolean) RETURNS uuid",
        """
      DECLARE c record; r text;
      BEGIN
        SELECT tenant_id,user_id,role INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
        IF NOT FOUND OR c.role<>'OWNER' THEN RAISE EXCEPTION 'asset denied' USING ERRCODE='42501'; END IF;
        IF p_lock THEN
          SELECT role INTO r FROM public.memberships WHERE tenant_id=c.tenant_id AND user_id=c.user_id FOR SHARE;
          IF r IS DISTINCT FROM 'OWNER' THEN RAISE EXCEPTION 'asset denied' USING ERRCODE='42501'; END IF;
          PERFORM 1 FROM public.tenants WHERE id=c.tenant_id FOR UPDATE;
          IF p_store IS NOT NULL THEN
            PERFORM 1 FROM public.stores WHERE id=p_store AND tenant_id=c.tenant_id AND active FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
          END IF;
        END IF;
        IF NOT EXISTS(SELECT 1 FROM public.memberships WHERE tenant_id=c.tenant_id AND user_id=c.user_id AND role='OWNER')
          OR (p_store IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.stores WHERE id=p_store AND tenant_id=c.tenant_id AND active))
          OR p_session IS NULL OR p_session !~ '^[0-9a-f]{64}$'
          OR NOT EXISTS(SELECT 1 FROM public.web_sessions WHERE session_digest=p_session AND user_id=c.user_id AND revoked_at IS NULL AND expires_at>clock_timestamp())
          THEN RAISE EXCEPTION 'asset denied' USING ERRCODE='42501'; END IF;
        RETURN c.user_id;
      END;""",
    )
    fn(
        "wso_asset_visible(uuid,uuid)",
        "wso_asset_visible(p_tenant uuid,p_store uuid) RETURNS boolean",
        """
      SELECT EXISTS(SELECT 1 FROM wso_private.tenant_contexts c JOIN public.memberships m ON m.tenant_id=c.tenant_id AND m.user_id=c.user_id
        WHERE c.backend_pid=pg_backend_pid() AND c.transaction_id=txid_current() AND c.tenant_id=p_tenant AND c.role='OWNER' AND m.role='OWNER')
        AND (p_store IS NULL OR EXISTS(SELECT 1 FROM public.stores WHERE id=p_store AND tenant_id=p_tenant AND active))
      """,
        "wso_app",
        language="sql",
    )
    op.execute("GRANT SELECT ON public.assets TO wso_app")
    op.execute(
        "CREATE POLICY asset_app ON public.assets TO wso_app USING(public.wso_asset_visible(tenant_id,store_id))"
    )
    fn(
        "wso_asset_lock(uuid,text,boolean)",
        "wso_asset_lock(p_id uuid,p_session text,p_live boolean) RETURNS public.assets",
        """
      DECLARE a public.assets%ROWTYPE; parent public.assets%ROWTYPE; tenant uuid;
      BEGIN
        SELECT tenant_id INTO tenant FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
        SELECT * INTO a FROM public.assets WHERE id=p_id AND tenant_id=tenant;
        IF NOT FOUND THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        PERFORM public.wso_asset_actor(p_session,a.store_id,true);
        IF a.parent_asset_id IS NOT NULL THEN SELECT * INTO parent FROM public.assets WHERE id=a.parent_asset_id AND tenant_id=tenant FOR UPDATE; END IF;
        SELECT * INTO a FROM public.assets WHERE id=p_id AND tenant_id=tenant FOR UPDATE;
        PERFORM public.wso_asset_actor(p_session,a.store_id,false);
        IF p_live AND (a.expires_at<=clock_timestamp() OR (a.parent_asset_id IS NOT NULL AND (parent.state<>'READY' OR parent.expires_at<=clock_timestamp()))) THEN RAISE EXCEPTION 'asset unavailable' USING ERRCODE='55000'; END IF;
        RETURN a;
      END;""",
    )
    _audit()


def _audit_outbox():
    op.execute("""
      CREATE TABLE wso_private.asset_audit_outbox(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL,asset_id uuid NOT NULL,
        action text NOT NULL CHECK(action IN ('ASSET_EXPIRED','ASSET_CLEANUP_SUCCESS','ASSET_CLEANUP_RETRY','ASSET_CLEANUP_ATTENTION')),
        occurred_at timestamptz NOT NULL DEFAULT clock_timestamp());
      ALTER TABLE wso_private.asset_audit_outbox OWNER TO wso_migrator;
      ALTER TABLE wso_private.asset_audit_outbox ENABLE ROW LEVEL SECURITY;
      ALTER TABLE wso_private.asset_audit_outbox FORCE ROW LEVEL SECURITY;
      REVOKE ALL ON wso_private.asset_audit_outbox FROM PUBLIC;
      GRANT SELECT,INSERT,DELETE ON wso_private.asset_audit_outbox TO wso_asset_owner;
      GRANT UPDATE(id) ON wso_private.asset_audit_outbox TO wso_asset_owner;
      CREATE POLICY audit_outbox_owner ON wso_private.asset_audit_outbox TO wso_asset_owner USING(true) WITH CHECK(true);
      CREATE POLICY audit_outbox_migrator ON wso_private.asset_audit_outbox TO wso_migrator USING(true) WITH CHECK(true);
    """)


def _audit():
    fn(
        "wso_asset_audit(uuid,uuid,text,uuid)",
        "wso_asset_audit(p_tenant uuid,p_asset uuid,p_action text,p_actor uuid) RETURNS void",
        """
      BEGIN
        IF p_actor IS NULL THEN
          -- No upstream foreign key or business lock in asset-held maintenance.
          INSERT INTO wso_private.asset_audit_outbox(tenant_id,asset_id,action) VALUES(p_tenant,p_asset,p_action);
        ELSE
          INSERT INTO public.audit_events(id,tenant_id,actor_user_id,action,entity_type,entity_id,correlation_id,result)
          VALUES(gen_random_uuid(),p_tenant,p_actor,p_action,'asset',p_asset,
            CASE WHEN current_setting('wso.asset_request_id',true) ~ '^[A-Za-z0-9_.:-]{1,100}$' THEN current_setting('wso.asset_request_id',true) ELSE null END,'OK');
        END IF;
      END;
      """,
    )
    fn(
        "wso_flush_asset_audits(integer)",
        "wso_flush_asset_audits(p_limit integer) RETURNS integer",
        """
      DECLARE candidate record; staged wso_private.asset_audit_outbox%ROWTYPE; count integer:=0;
      BEGIN
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'asset audit limit invalid' USING ERRCODE='22023'; END IF;
        FOR candidate IN SELECT o.id,o.tenant_id FROM wso_private.asset_audit_outbox o WHERE EXISTS(SELECT 1 FROM public.tenants t WHERE t.id=o.tenant_id) ORDER BY o.tenant_id,o.id LIMIT p_limit LOOP
          -- This separate transaction holds no asset/job/cleanup lock. Missing
          -- tenants retain their durable record for operator reconciliation.
          PERFORM 1 FROM public.tenants WHERE id=candidate.tenant_id FOR KEY SHARE;
          IF NOT FOUND THEN CONTINUE; END IF;
          SELECT * INTO staged FROM wso_private.asset_audit_outbox WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
          IF NOT FOUND THEN CONTINUE; END IF;
          INSERT INTO public.audit_events(id,tenant_id,actor_user_id,action,entity_type,entity_id,correlation_id,result,occurred_at)
            VALUES(staged.id,staged.tenant_id,null,staged.action,'asset',staged.asset_id,null,'OK',staged.occurred_at)
            ON CONFLICT DO NOTHING;
          DELETE FROM wso_private.asset_audit_outbox WHERE id=staged.id;
          count:=count+1;
        END LOOP;
        RETURN count;
      END;
      """,
        "wso_asset_maintenance",
    )


def _allocation():
    fn(
        "wso_begin_asset_upload(jsonb,text)",
        "wso_begin_asset_upload(p_request jsonb,p_session text) RETURNS TABLE(id uuid,asset_id uuid,upload_path text,expires_at timestamptz,max_bytes bigint)",
        """
      DECLARE actor uuid; tenant uuid; store uuid; parent public.assets%ROWTYPE; s wso_private.asset_settings%ROWTYPE; aid uuid:=gen_random_uuid(); sid uuid:=gen_random_uuid(); ending timestamptz; expiration timestamptz; purpose text; size bigint;
      BEGIN
        IF p_request IS NULL OR jsonb_typeof(p_request)<>'object' OR p_request-ARRAY['scope','purpose','content_type','byte_size','checksum','parent_asset_id']<>'{}'::jsonb
          OR jsonb_typeof(p_request->'scope') IS DISTINCT FROM 'object' OR (p_request->'scope')-ARRAY['scope_kind','tenant_id','store_id']<>'{}'::jsonb
          OR jsonb_typeof(p_request->'checksum') IS DISTINCT FROM 'object' OR (p_request->'checksum')-ARRAY['algorithm','value']<>'{}'::jsonb
          OR p_request->'checksum'->>'algorithm' IS DISTINCT FROM 'SHA256' OR coalesce(p_request->'checksum'->>'value','') !~ '^[0-9a-f]{64}$'
          OR jsonb_typeof(p_request->'byte_size') IS DISTINCT FROM 'number' OR coalesce(p_request->>'byte_size','') !~ '^[0-9]{1,8}$'
          OR coalesce(p_request->>'content_type','') NOT IN ('image/png','image/jpeg') THEN RAISE EXCEPTION 'asset request invalid' USING ERRCODE='22023'; END IF;
        tenant:=(p_request->'scope'->>'tenant_id')::uuid; store:=(p_request->'scope'->>'store_id')::uuid; purpose:=p_request->>'purpose'; size:=(p_request->>'byte_size')::bigint;
        actor:=public.wso_asset_actor(p_session,store,true);
        IF NOT EXISTS(SELECT 1 FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current() AND tenant_id=tenant) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        IF purpose='EVIDENCE' THEN RAISE EXCEPTION 'asset capability unsupported' USING ERRCODE='0A000'; END IF;
        IF purpose IS NULL OR purpose NOT IN ('IMPORT_PHOTO','IMPORT_CROP') OR (purpose='IMPORT_CROP') IS DISTINCT FROM (p_request->>'parent_asset_id' IS NOT NULL)
          OR coalesce(p_request->'scope'->>'scope_kind','') NOT IN ('TENANT','STORE') OR ((p_request->'scope'->>'scope_kind')='STORE') IS DISTINCT FROM (store IS NOT NULL) THEN RAISE EXCEPTION 'asset request invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO s FROM wso_private.asset_settings WHERE singleton;
        IF s.installation_id IS NULL THEN RAISE EXCEPTION 'asset configuration unavailable' USING ERRCODE='55000'; END IF;
        IF size NOT BETWEEN 1 AND s.max_bytes THEN RAISE EXCEPTION 'asset limit' USING ERRCODE='54000'; END IF;
        ending:=clock_timestamp()+make_interval(secs=>s.retention_seconds);
        IF purpose='IMPORT_CROP' THEN
          SELECT * INTO parent FROM public.assets WHERE id=(p_request->>'parent_asset_id')::uuid AND tenant_id=tenant FOR UPDATE;
          IF NOT FOUND OR parent.purpose<>'IMPORT_PHOTO' OR parent.state<>'READY' OR parent.expires_at<=clock_timestamp() OR parent.store_id IS DISTINCT FROM store THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
          IF (SELECT count(*) FROM public.assets WHERE parent_asset_id=parent.id AND state<>'DELETED')>=s.crop_limit THEN RAISE EXCEPTION 'asset quota' USING ERRCODE='54000'; END IF;
          ending:=least(ending,parent.expires_at);
        END IF;
        IF (SELECT count(*) FROM public.assets WHERE tenant_id=tenant AND state='PENDING')>=s.pending_limit
          OR (SELECT coalesce(sum(byte_size),0) FROM public.assets WHERE tenant_id=tenant AND state<>'DELETED')+size>s.tenant_byte_limit THEN RAISE EXCEPTION 'asset quota' USING ERRCODE='54000'; END IF;
        PERFORM public.wso_asset_actor(p_session,store,false);
        expiration:=least(ending,clock_timestamp()+make_interval(secs=>s.session_seconds));
        INSERT INTO public.assets(id,tenant_id,store_id,purpose,parent_asset_id,creator_id,checksum_sha256,byte_size,content_type,expires_at,policy_version)
          VALUES(aid,tenant,store,purpose,parent.id,actor,p_request->'checksum'->>'value',size,p_request->>'content_type',ending,s.version);
        INSERT INTO wso_private.asset_uploads(asset_id,tenant_id,id,creator_id,session_digest,expires_at) VALUES(aid,tenant,sid,actor,p_session,expiration);
        PERFORM public.wso_asset_audit(tenant,aid,'ASSET_UPLOAD_BEGIN',actor);
        RETURN QUERY SELECT sid,aid,'/api/v1/assets/'||aid||'/content?tenant_id='||tenant,expiration,size;
      END;""",
        "wso_app",
    )


def _tombstone():
    fn(
        "wso_asset_schedule_delete(uuid)",
        "wso_asset_schedule_delete(p_id uuid) RETURNS void",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE; deadline timestamptz;
      BEGIN
        SELECT * INTO a FROM public.assets WHERE id=p_id FOR UPDATE;
        IF NOT FOUND OR a.state='DELETED' THEN RETURN; END IF;
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=a.id FOR UPDATE;
        deadline:=greatest(clock_timestamp(),coalesce(u.lease_expires_at,clock_timestamp())+(SELECT make_interval(secs=>grace_seconds) FROM wso_private.asset_settings WHERE singleton),
          (SELECT max(expires_at) FROM wso_private.asset_read_leases WHERE asset_id=a.id AND closed_at IS NULL));
        IF a.state<>'DELETING' THEN UPDATE public.assets SET state='DELETING',access_generation=access_generation+1,tombstoned_at=clock_timestamp() WHERE id=a.id; END IF;
        DELETE FROM wso_private.asset_tickets WHERE asset_id=a.id;
        INSERT INTO wso_private.asset_cleanup(tenant_id,asset_id,attempt_id,operation,due_at) VALUES(a.tenant_id,a.id,u.id,'DELETE_OBJECT',deadline) ON CONFLICT(asset_id,attempt_id,operation,multipart_id) DO NOTHING;
      END;""",
    )
    fn(
        "wso_tombstone_asset(uuid,text)",
        f"wso_tombstone_asset(p_id uuid,p_session text) RETURNS TABLE({ASSET_COLUMNS})",
        f"""
      DECLARE target public.assets%ROWTYPE; child record;
      BEGIN
        target:=public.wso_asset_lock(p_id,p_session,false);
        FOR child IN SELECT a.id FROM public.assets a WHERE a.parent_asset_id=target.id ORDER BY a.id FOR UPDATE LOOP NULL; END LOOP;
        PERFORM public.wso_asset_actor(p_session,target.store_id,false);
        IF target.state NOT IN ('DELETING','DELETED') THEN
          PERFORM public.wso_asset_schedule_delete(target.id);
          FOR child IN SELECT a.id FROM public.assets a WHERE a.parent_asset_id=target.id ORDER BY a.id LOOP PERFORM public.wso_asset_schedule_delete(child.id); END LOOP;
          PERFORM public.wso_asset_audit(target.tenant_id,target.id,'ASSET_DELETE',public.wso_asset_actor(p_session,target.store_id,false));
        END IF;
        RETURN QUERY SELECT {ASSET_SELECT} FROM public.assets a WHERE a.id=p_id;
      END;""",
        "wso_app",
    )


def _completion_fence():
    # Existing attempts cannot prove non-dispatch; never backfill them false.
    op.execute(
        "ALTER TABLE wso_private.asset_uploads ADD COLUMN IF NOT EXISTS completion_dispatched boolean NOT NULL DEFAULT true"
    )
    op.execute(
        "ALTER TABLE wso_private.asset_uploads ALTER COLUMN completion_dispatched SET DEFAULT false"
    )
    fn(
        "wso_asset_completion_monotonic()",
        "wso_asset_completion_monotonic() RETURNS trigger",
        """BEGIN
          IF OLD.completion_dispatched AND NOT NEW.completion_dispatched THEN
            RAISE EXCEPTION 'asset completion fence is monotonic' USING ERRCODE='22023';
          END IF;
          RETURN NEW;
        END;""",
    )
    op.execute(
        "CREATE TRIGGER asset_completion_monotonic BEFORE UPDATE ON wso_private.asset_uploads FOR EACH ROW EXECUTE FUNCTION public.wso_asset_completion_monotonic()"
    )


def _write_controls():
    fn(
        "wso_asset_manifest(uuid,text,uuid,text)",
        f"wso_asset_manifest(p_id uuid,p_use text,p_lease uuid,p_token text) RETURNS TABLE({MANIFEST_COLUMNS})",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE; l wso_private.asset_read_leases%ROWTYPE; ending timestamptz; gen bigint;
      BEGIN
        SELECT * INTO a FROM public.assets WHERE id=p_id;
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=p_id;
        IF p_use IN ('WRITE','VALIDATE') THEN ending:=u.lease_expires_at; gen:=u.generation;
        ELSE SELECT * INTO l FROM wso_private.asset_read_leases WHERE id=p_lease AND asset_id=p_id; ending:=l.expires_at; gen:=l.access_generation; END IF;
        IF ending IS NULL OR ending<=clock_timestamp() THEN RAISE EXCEPTION 'asset lease expired' USING ERRCODE='55000'; END IF;
        RETURN QUERY SELECT s.installation_id,a.tenant_id,a.id,u.id,a.store_id,a.parent_asset_id,a.purpose,a.byte_size,a.content_type,a.checksum_sha256,
          u.object_key,u.key_id,u.wrapped_dek,u.wrap_nonce,u.object_nonce,p_lease,gen,ending,greatest(1,floor(extract(epoch FROM ending-clock_timestamp())*1000)::integer),p_token,
          a.access_generation,(SELECT p.access_generation FROM public.assets p WHERE p.id=a.parent_asset_id),s.version FROM wso_private.asset_settings s WHERE s.singleton;
      END;""",
    )
    fn(
        "wso_prepare_asset_write(uuid,uuid,text)",
        "wso_prepare_asset_write(p_id uuid,p_upload uuid,p_session text) RETURNS TABLE(tenant_id uuid,asset_id uuid,attempt_id uuid,store_id uuid,parent_asset_id uuid,purpose text,byte_size bigint,content_type text,checksum_sha256 text,upload_session_id uuid,session_expires_at timestamptz,policy_version integer)",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_uploads.asset_id=p_id FOR UPDATE;
        IF a.state<>'PENDING' OR u.status<>'ALLOCATED' THEN RAISE EXCEPTION 'asset state conflict' USING ERRCODE='55000'; END IF;
        IF u.id IS DISTINCT FROM p_upload OR u.session_digest IS DISTINCT FROM p_session OR u.creator_id<>public.wso_asset_actor(p_session,a.store_id,false) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        IF u.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset upload expired' USING ERRCODE='WA410'; END IF;
        IF a.policy_version<>(SELECT version FROM wso_private.asset_settings WHERE singleton) THEN RAISE EXCEPTION 'asset configuration unavailable' USING ERRCODE='WA503'; END IF;
        RETURN QUERY SELECT a.tenant_id,a.id,u.id,a.store_id,a.parent_asset_id,a.purpose,a.byte_size,a.content_type,a.checksum_sha256,u.id,u.expires_at,a.policy_version;
      END;""",
        "wso_app",
    )
    fn(
        "wso_begin_asset_write(uuid,uuid,text,jsonb)",
        f"wso_begin_asset_write(p_id uuid,p_upload uuid,p_session text,p_envelope jsonb) RETURNS TABLE({MANIFEST_COLUMNS},upload_session_id uuid)",
        """
      DECLARE preparation record; token text:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-',''); lid uuid:=gen_random_uuid(); expiration timestamptz; configured record;
      BEGIN
        SELECT * INTO preparation FROM public.wso_prepare_asset_write(p_id,p_upload,p_session);
        IF p_envelope IS NULL OR jsonb_typeof(p_envelope)<>'object' OR p_envelope-ARRAY['key_id','wrapped_dek','wrap_nonce','object_nonce']<>'{}'::jsonb
          OR coalesce(p_envelope->>'key_id','') !~ '^[A-Za-z0-9_-]{1,64}$' OR coalesce(p_envelope->>'wrapped_dek','') !~ '^[0-9a-f]{96}$'
          OR coalesce(p_envelope->>'wrap_nonce','') !~ '^[0-9a-f]{24}$' OR coalesce(p_envelope->>'object_nonce','') !~ '^[0-9a-f]{24}$' THEN RAISE EXCEPTION 'asset envelope invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO configured FROM wso_private.asset_settings WHERE singleton;
        PERFORM public.wso_asset_actor(p_session,preparation.store_id,false);
        expiration:=least(preparation.session_expires_at,clock_timestamp()+make_interval(secs=>configured.upload_seconds),(SELECT s.expires_at FROM public.web_sessions s WHERE s.session_digest=p_session));
        IF expiration<=clock_timestamp() THEN RAISE EXCEPTION 'asset upload expired' USING ERRCODE='WA410'; END IF;
        UPDATE wso_private.asset_uploads SET status='WRITING',generation=generation+1,lease_id=lid,lease_digest=sha256(convert_to(token,'UTF8')),lease_expires_at=expiration,
          object_key='wso-assets/v1/'||replace(configured.installation_id::text,'-','')||'/objects/'||replace(preparation.tenant_id::text,'-','')||'/'||replace(p_id::text,'-','')||'/'||replace(p_upload::text,'-','')||'.wso',
          key_id=p_envelope->>'key_id',wrapped_dek=decode(p_envelope->>'wrapped_dek','hex'),wrap_nonce=decode(p_envelope->>'wrap_nonce','hex'),object_nonce=decode(p_envelope->>'object_nonce','hex'),remote_uncertain=true WHERE asset_uploads.asset_id=p_id;
        RETURN QUERY SELECT m.*,p_upload FROM public.wso_asset_manifest(p_id,'WRITE',lid,token) m;
      END;""",
        "wso_app",
    )
    fn(
        "wso_asset_upload_lease(uuid,bigint,text,text,text)",
        "wso_asset_upload_lease(p_id uuid,p_generation bigint,p_token text,p_session text,p_status text) RETURNS public.assets",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=p_id FOR UPDATE;
        IF a.state<>'PENDING' OR u.status<>p_status OR u.generation IS DISTINCT FROM p_generation OR u.lease_digest IS DISTINCT FROM sha256(convert_to(p_token,'UTF8'))
          OR u.lease_expires_at<=clock_timestamp() OR u.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset lease conflict' USING ERRCODE='55000'; END IF;
        IF u.session_digest IS DISTINCT FROM p_session OR u.creator_id<>public.wso_asset_actor(p_session,a.store_id,false) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        IF a.policy_version<>(SELECT version FROM wso_private.asset_settings WHERE singleton) THEN RAISE EXCEPTION 'asset configuration unavailable' USING ERRCODE='WA503'; END IF;
        RETURN a;
      END;""",
    )
    fn(
        "wso_record_asset_multipart(uuid,bigint,text,text,text)",
        "wso_record_asset_multipart(p_id uuid,p_generation bigint,p_token text,p_multipart text,p_session text) RETURNS void",
        """
      BEGIN
        PERFORM public.wso_asset_upload_lease(p_id,p_generation,p_token,p_session,'WRITING');
        IF p_multipart IS NULL OR length(p_multipart) NOT BETWEEN 1 AND 1024 THEN RAISE EXCEPTION 'asset multipart invalid' USING ERRCODE='22023'; END IF;
        IF EXISTS(SELECT 1 FROM wso_private.asset_uploads WHERE asset_id=p_id AND multipart_id IS NOT NULL AND multipart_id<>p_multipart) THEN RAISE EXCEPTION 'asset lease conflict' USING ERRCODE='55000'; END IF;
        UPDATE wso_private.asset_uploads SET multipart_id=p_multipart WHERE asset_id=p_id;
      END;""",
        "wso_app",
    )
    fn(
        "wso_begin_asset_completion(uuid,bigint,text,text)",
        "wso_begin_asset_completion(p_id uuid,p_generation bigint,p_token text,p_session text) RETURNS void",
        """
      BEGIN
        PERFORM public.wso_asset_upload_lease(p_id,p_generation,p_token,p_session,'WRITING');
        IF NOT EXISTS(SELECT 1 FROM wso_private.asset_uploads WHERE asset_id=p_id AND multipart_id IS NOT NULL) THEN
          RAISE EXCEPTION 'asset completion not prepared' USING ERRCODE='55000';
        END IF;
        UPDATE wso_private.asset_uploads SET completion_dispatched=true WHERE asset_id=p_id;
      END;""",
        "wso_app",
    )
    fn(
        "wso_seal_asset_upload(uuid,bigint,text,text)",
        "wso_seal_asset_upload(p_id uuid,p_generation bigint,p_token text,p_session text) RETURNS void",
        """
      BEGIN
        PERFORM public.wso_asset_upload_lease(p_id,p_generation,p_token,p_session,'WRITING');
        IF NOT EXISTS(SELECT 1 FROM wso_private.asset_uploads WHERE asset_id=p_id AND completion_dispatched) THEN RAISE EXCEPTION 'asset completion not dispatched' USING ERRCODE='55000'; END IF;
        UPDATE wso_private.asset_uploads SET status='SEALED',lease_digest=null,lease_expires_at=null,remote_uncertain=false,remote_observed=true WHERE asset_id=p_id;
      END;""",
        "wso_app",
    )
    extra = ",read_use text,already_ready boolean,id uuid,state text,expires_at timestamptz,created_at timestamptz"
    fn(
        "wso_begin_asset_validation(uuid,text)",
        f"wso_begin_asset_validation(p_id uuid,p_session text) RETURNS TABLE({MANIFEST_COLUMNS}{extra})",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE; expiration timestamptz; token text:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-',''); lid uuid:=gen_random_uuid();
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        IF a.state='READY' THEN
          RETURN QUERY SELECT null::uuid,a.tenant_id,a.id,null::uuid,a.store_id,a.parent_asset_id,a.purpose,a.byte_size,a.content_type,a.checksum_sha256,
            null::text,null::text,null::bytea,null::bytea,null::bytea,null::uuid,null::bigint,null::timestamptz,null::integer,null::text,null::bigint,null::bigint,null::integer,
            null::text,true,a.id,a.state,a.expires_at,a.created_at; RETURN;
        END IF;
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_uploads.asset_id=p_id FOR UPDATE;
        IF a.state<>'PENDING' OR u.status='ALLOCATED' OR u.lease_expires_at>clock_timestamp() THEN RAISE EXCEPTION 'asset state conflict' USING ERRCODE='55000'; END IF;
        IF u.session_digest IS DISTINCT FROM p_session OR u.creator_id<>public.wso_asset_actor(p_session,a.store_id,false) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        IF u.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset upload expired' USING ERRCODE='WA410'; END IF;
        IF a.policy_version<>(SELECT version FROM wso_private.asset_settings WHERE singleton) THEN RAISE EXCEPTION 'asset configuration unavailable' USING ERRCODE='WA503'; END IF;
        expiration:=least(a.expires_at,u.expires_at,clock_timestamp()+(SELECT make_interval(secs=>verification_seconds) FROM wso_private.asset_settings WHERE singleton),(SELECT s.expires_at FROM public.web_sessions s WHERE s.session_digest=p_session),(SELECT p.expires_at FROM public.assets p WHERE p.id=a.parent_asset_id));
        UPDATE wso_private.asset_uploads SET status='VERIFYING',generation=generation+1,lease_id=lid,lease_digest=sha256(convert_to(token,'UTF8')),lease_expires_at=expiration WHERE asset_uploads.asset_id=p_id;
        RETURN QUERY SELECT m.*,'VALIDATE'::text,false,null::uuid,null::text,null::timestamptz,null::timestamptz FROM public.wso_asset_manifest(p_id,'VALIDATE',lid,token) m;
      END;""",
        "wso_app",
    )
    fn(
        "wso_finish_asset_validation(uuid,bigint,text,jsonb,text)",
        f"wso_finish_asset_validation(p_id uuid,p_generation bigint,p_token text,p_receipt jsonb,p_session text) RETURNS TABLE({ASSET_COLUMNS})",
        f"""
      DECLARE target public.assets%ROWTYPE; s wso_private.asset_settings%ROWTYPE; k text;
      BEGIN
        target:=public.wso_asset_upload_lease(p_id,p_generation,p_token,p_session,'VERIFYING');
        SELECT * INTO s FROM wso_private.asset_settings WHERE singleton;
        IF p_receipt IS NULL OR jsonb_typeof(p_receipt)<>'object' OR p_receipt-ARRAY['policy_version','byte_size','checksum_sha256','content_type','width','height','oriented_width','oriented_height','frame_count']<>'{{}}'::jsonb THEN RAISE EXCEPTION 'asset receipt invalid' USING ERRCODE='22023'; END IF;
        FOREACH k IN ARRAY ARRAY['policy_version','byte_size','width','height','oriented_width','oriented_height','frame_count'] LOOP
          IF jsonb_typeof(p_receipt->k) IS DISTINCT FROM 'number' OR coalesce(p_receipt->>k,'') !~ '^[0-9]{{1,10}}$' THEN RAISE EXCEPTION 'asset receipt invalid' USING ERRCODE='22023'; END IF;
        END LOOP;
        IF (p_receipt->>'policy_version')::bigint<>s.version OR (p_receipt->>'byte_size')::bigint<>target.byte_size OR p_receipt->>'checksum_sha256' IS DISTINCT FROM target.checksum_sha256 OR p_receipt->>'content_type' IS DISTINCT FROM target.content_type
          OR (p_receipt->>'frame_count')::bigint<>1 OR (p_receipt->>'width')::bigint NOT BETWEEN 1 AND s.max_dimension OR (p_receipt->>'height')::bigint NOT BETWEEN 1 AND s.max_dimension
          OR (p_receipt->>'oriented_width')::bigint NOT BETWEEN 1 AND s.max_dimension OR (p_receipt->>'oriented_height')::bigint NOT BETWEEN 1 AND s.max_dimension
          OR (p_receipt->>'width')::bigint*(p_receipt->>'height')::bigint>s.max_pixels OR (p_receipt->>'oriented_width')::bigint*(p_receipt->>'oriented_height')::bigint>s.max_pixels
          THEN RAISE EXCEPTION 'asset receipt invalid' USING ERRCODE='22023'; END IF;
        PERFORM public.wso_asset_actor(p_session,target.store_id,false);
        UPDATE public.assets SET state='READY',width=(p_receipt->>'width')::integer,height=(p_receipt->>'height')::integer,oriented_width=(p_receipt->>'oriented_width')::integer,oriented_height=(p_receipt->>'oriented_height')::integer,frame_count=1 WHERE assets.id=p_id;
        UPDATE wso_private.asset_uploads SET status='FINISHED',lease_digest=null,lease_expires_at=null,remote_uncertain=false,remote_observed=true WHERE asset_uploads.asset_id=p_id;
        PERFORM public.wso_asset_audit(target.tenant_id,target.id,'ASSET_READY',public.wso_asset_actor(p_session,target.store_id,false));
        RETURN QUERY SELECT {ASSET_SELECT} FROM public.assets a WHERE a.id=p_id;
      END;""",
        "wso_app",
    )
    fn(
        "wso_reject_asset_upload(uuid,bigint,text,text,text)",
        "wso_reject_asset_upload(p_id uuid,p_generation bigint,p_token text,p_failure text,p_session text) RETURNS void",
        """
      DECLARE a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=p_id FOR UPDATE;
        IF u.status NOT IN ('WRITING','VERIFYING') THEN RAISE EXCEPTION 'asset lease conflict' USING ERRCODE='55000'; END IF;
        IF a.state<>'PENDING' OR u.generation IS DISTINCT FROM p_generation OR u.lease_digest IS DISTINCT FROM sha256(convert_to(p_token,'UTF8')) OR u.lease_expires_at<=clock_timestamp() OR u.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset lease conflict' USING ERRCODE='55000'; END IF;
        IF u.session_digest IS DISTINCT FROM p_session OR u.creator_id<>public.wso_asset_actor(p_session,a.store_id,false) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        IF p_failure NOT IN ('TYPE','INTEGRITY','LIMIT','DECODE','PIXELS','DIMENSIONS','FRAMES','ABANDONED','REMOTE_UNKNOWN','RETRY') THEN RAISE EXCEPTION 'asset failure invalid' USING ERRCODE='22023'; END IF;
        IF p_failure='RETRY' AND u.status='VERIFYING' THEN
          IF NOT EXISTS(SELECT 1 FROM wso_private.asset_uploads WHERE asset_id=p_id AND completion_dispatched) THEN RAISE EXCEPTION 'asset completion not dispatched' USING ERRCODE='55000'; END IF;
        UPDATE wso_private.asset_uploads SET status='SEALED',lease_digest=null,lease_expires_at=null WHERE asset_id=p_id; RETURN;
        END IF;
        UPDATE wso_private.asset_uploads SET failure_code=p_failure,remote_uncertain=CASE WHEN p_failure IN ('TYPE','INTEGRITY','LIMIT','DECODE','PIXELS','DIMENSIONS','FRAMES') THEN false ELSE remote_uncertain END WHERE asset_id=p_id;
        UPDATE public.assets SET state='REJECTED',access_generation=access_generation+1 WHERE id=p_id;
        INSERT INTO wso_private.asset_cleanup(tenant_id,asset_id,attempt_id,operation,due_at) VALUES(a.tenant_id,a.id,u.id,'DELETE_OBJECT',greatest(clock_timestamp(),u.lease_expires_at)+interval '10 seconds') ON CONFLICT(asset_id,attempt_id,operation,multipart_id) DO NOTHING;
        PERFORM public.wso_asset_audit(a.tenant_id,a.id,'ASSET_REJECTED',public.wso_asset_actor(p_session,a.store_id,false));
      END;""",
        "wso_app",
    )


def _read_controls():
    fn(
        "wso_issue_asset_ticket(uuid,text)",
        "wso_issue_asset_ticket(p_id uuid,p_session text) RETURNS TABLE(id uuid,asset_id uuid,download_path text,token text,expires_at timestamptz)",
        """
      DECLARE a public.assets%ROWTYPE; secret text:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-',''); tid uuid:=gen_random_uuid(); expiration timestamptz; actor uuid;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        IF a.state<>'READY' THEN RAISE EXCEPTION 'asset state conflict' USING ERRCODE='55000'; END IF;
        actor:=public.wso_asset_actor(p_session,a.store_id,false);
        expiration:=least(clock_timestamp()+interval '30 seconds',a.expires_at,(SELECT p.expires_at FROM public.assets p WHERE p.id=a.parent_asset_id),(SELECT s.expires_at FROM public.web_sessions s WHERE s.session_digest=p_session));
        INSERT INTO wso_private.asset_tickets(id,tenant_id,asset_id,token_digest,actor_id,session_digest,access_generation,parent_access_generation,expires_at)
          VALUES(tid,a.tenant_id,a.id,sha256(convert_to(secret,'UTF8')),actor,p_session,a.access_generation,(SELECT p.access_generation FROM public.assets p WHERE p.id=a.parent_asset_id),expiration);
        PERFORM public.wso_asset_audit(a.tenant_id,a.id,'ASSET_TICKET_ISSUED',actor);
        RETURN QUERY SELECT tid,a.id,'/api/v1/assets/'||a.id||'/content?tenant_id='||a.tenant_id,secret,expiration;
      END;""",
        "wso_app",
    )
    fn(
        "wso_redeem_asset_ticket(uuid,text,text)",
        f"wso_redeem_asset_ticket(p_id uuid,p_token text,p_session text) RETURNS TABLE({MANIFEST_COLUMNS},read_use text)",
        """
      DECLARE a public.assets%ROWTYPE; t wso_private.asset_tickets%ROWTYPE; lid uuid:=gen_random_uuid(); expiration timestamptz; actor uuid;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        SELECT * INTO t FROM wso_private.asset_tickets WHERE asset_tickets.asset_id=p_id AND token_digest=sha256(convert_to(p_token,'UTF8')) FOR UPDATE;
        actor:=public.wso_asset_actor(p_session,a.store_id,false);
        IF NOT FOUND OR t.id IS NULL OR t.expires_at<=clock_timestamp() OR t.redeemed_at IS NOT NULL OR t.session_digest IS DISTINCT FROM p_session OR t.actor_id IS DISTINCT FROM actor
          OR a.state<>'READY' OR t.access_generation<>a.access_generation OR t.parent_access_generation IS DISTINCT FROM (SELECT p.access_generation FROM public.assets p WHERE p.id=a.parent_asset_id) THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        expiration:=least(a.expires_at,clock_timestamp()+(SELECT make_interval(secs=>download_seconds) FROM wso_private.asset_settings WHERE singleton),(SELECT s.expires_at FROM public.web_sessions s WHERE s.session_digest=p_session),(SELECT p.expires_at FROM public.assets p WHERE p.id=a.parent_asset_id));
        UPDATE wso_private.asset_tickets SET redeemed_at=clock_timestamp() WHERE asset_tickets.id=t.id;
        INSERT INTO wso_private.asset_read_leases(id,tenant_id,asset_id,access_generation,parent_access_generation,reader_kind,actor_id,session_digest,expires_at)
          VALUES(lid,a.tenant_id,a.id,a.access_generation,t.parent_access_generation,'DOWNLOAD',actor,p_session,expiration);
        PERFORM public.wso_asset_audit(a.tenant_id,a.id,'ASSET_TICKET_REDEEMED',actor);
        RETURN QUERY SELECT m.*,'DOWNLOAD'::text FROM public.wso_asset_manifest(p_id,'DOWNLOAD',lid,null) m;
      END;""",
        "wso_app",
    )
    fn(
        "wso_revalidate_asset_read(uuid,uuid,text)",
        "wso_revalidate_asset_read(p_id uuid,p_lease uuid,p_session text) RETURNS boolean",
        """
      DECLARE a public.assets%ROWTYPE; l wso_private.asset_read_leases%ROWTYPE;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,true);
        SELECT * INTO l FROM wso_private.asset_read_leases WHERE id=p_lease AND asset_id=p_id FOR UPDATE;
        RETURN l.id IS NOT NULL AND l.reader_kind='DOWNLOAD' AND l.actor_id=public.wso_asset_actor(p_session,a.store_id,false) AND l.session_digest=p_session
          AND l.closed_at IS NULL AND l.expires_at>clock_timestamp() AND a.state='READY' AND l.access_generation=a.access_generation
          AND l.parent_access_generation IS NOT DISTINCT FROM (SELECT access_generation FROM public.assets WHERE id=a.parent_asset_id);
      END;""",
        "wso_app",
    )
    fn(
        "wso_close_asset_read(uuid,uuid,text)",
        "wso_close_asset_read(p_id uuid,p_lease uuid,p_session text) RETURNS void",
        """
      DECLARE a public.assets%ROWTYPE; actor uuid;
      BEGIN
        a:=public.wso_asset_lock(p_id,p_session,false); actor:=public.wso_asset_actor(p_session,a.store_id,false);
        UPDATE wso_private.asset_read_leases SET closed_at=clock_timestamp() WHERE id=p_lease AND asset_id=p_id AND reader_kind='DOWNLOAD' AND actor_id=actor AND session_digest=p_session AND closed_at IS NULL;
      END;""",
        "wso_app",
    )


def _maintenance():
    op.execute(
        "ALTER TABLE wso_private.asset_cleanup ADD COLUMN IF NOT EXISTS attention_at timestamptz"
    )
    fn(
        "wso_sweep_assets(integer)",
        "wso_sweep_assets(p_limit integer) RETURNS integer",
        """
      DECLARE root_id uuid; roots uuid[]; child record; count integer:=0;
      BEGIN
        IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'asset limit invalid' USING ERRCODE='22023'; END IF;
        SELECT coalesce(array_agg(candidate.id ORDER BY candidate.id),'{}'::uuid[]) INTO roots FROM (
          SELECT DISTINCT coalesce(a.parent_asset_id,a.id) AS id FROM public.assets a JOIN wso_private.asset_uploads u ON u.asset_id=a.id
          WHERE a.state IN ('PENDING','READY','REJECTED') AND (a.expires_at<=clock_timestamp() OR (a.state='PENDING' AND u.expires_at<=clock_timestamp()) OR a.state='REJECTED') ORDER BY id LIMIT p_limit) candidate;
        PERFORM 1 FROM public.assets WHERE id=ANY(roots) ORDER BY id FOR UPDATE;
        PERFORM 1 FROM public.assets WHERE parent_asset_id=ANY(roots) ORDER BY id FOR UPDATE;
        FOREACH root_id IN ARRAY roots LOOP
          FOR child IN SELECT a.* FROM public.assets a JOIN wso_private.asset_uploads u ON u.asset_id=a.id
            WHERE (a.id=root_id OR a.parent_asset_id=root_id) AND a.state IN ('PENDING','READY','REJECTED')
            AND (a.expires_at<=clock_timestamp() OR (a.state='PENDING' AND u.expires_at<=clock_timestamp()) OR a.state='REJECTED'
              OR EXISTS(SELECT 1 FROM public.assets p WHERE p.id=root_id AND p.state IN ('DELETING','DELETED'))) ORDER BY a.id LOOP
            PERFORM public.wso_asset_schedule_delete(child.id); count:=count+1;
            PERFORM public.wso_asset_audit(child.tenant_id,child.id,'ASSET_EXPIRED',null);
          END LOOP;
        END LOOP;
        RETURN count;
      END;""",
        "wso_asset_maintenance",
    )
    fn(
        "wso_claim_asset_cleanup(integer,text)",
        "wso_claim_asset_cleanup(p_limit integer,p_worker text) RETURNS TABLE(work_id uuid,installation_id uuid,tenant_id uuid,asset_id uuid,attempt_id uuid,operation text,multipart_id text,lease_id uuid,lease_generation bigint,lease_expires_at timestamptz,lease_remaining_ms integer,lease_token text)",
        """
      DECLARE work wso_private.asset_cleanup%ROWTYPE; token text; lid uuid; expiration timestamptz;
      BEGIN
        IF p_limit IS DISTINCT FROM 1 OR p_worker IS NULL OR length(p_worker) NOT BETWEEN 1 AND 128 OR p_worker ~ '[[:cntrl:]]' THEN RAISE EXCEPTION 'asset claim invalid' USING ERRCODE='22023'; END IF;
        SELECT * INTO work FROM wso_private.asset_cleanup c WHERE c.status<>'DONE' AND c.due_at<=clock_timestamp()
          AND (c.status='READY' OR c.lease_expires_at<=clock_timestamp()) ORDER BY c.due_at,c.id LIMIT 1 FOR UPDATE SKIP LOCKED;
        IF NOT FOUND THEN RETURN; END IF;
        token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-',''); lid:=gen_random_uuid();
        expiration:=clock_timestamp()+(SELECT make_interval(secs=>cleanup_seconds) FROM wso_private.asset_settings WHERE singleton);
        UPDATE wso_private.asset_cleanup SET status='LEASED',generation=generation+1,lease_id=lid,lease_digest=sha256(convert_to(token,'UTF8')),lease_expires_at=expiration,worker_id=p_worker,attempts=attempts+1 WHERE id=work.id;
        RETURN QUERY SELECT work.id,s.installation_id,work.tenant_id,work.asset_id,work.attempt_id,work.operation,work.multipart_id,lid,work.generation+1,expiration,
          greatest(1,floor(extract(epoch FROM expiration-clock_timestamp())*1000)::integer),token FROM wso_private.asset_settings s WHERE s.singleton AND s.installation_id IS NOT NULL;
      END;""",
        "wso_asset_maintenance",
    )
    fn(
        "wso_asset_cleanup_lock(uuid,bigint,text)",
        "wso_asset_cleanup_lock(p_work uuid,p_generation bigint,p_token text) RETURNS wso_private.asset_cleanup",
        """
      DECLARE work wso_private.asset_cleanup%ROWTYPE; a public.assets%ROWTYPE;
      BEGIN
        SELECT * INTO work FROM wso_private.asset_cleanup WHERE id=p_work;
        IF NOT FOUND THEN RAISE EXCEPTION 'asset cleanup missing' USING ERRCODE='P0002'; END IF;
        SELECT * INTO a FROM public.assets WHERE id=work.asset_id;
        IF a.parent_asset_id IS NOT NULL THEN PERFORM 1 FROM public.assets WHERE id=a.parent_asset_id FOR UPDATE; END IF;
        PERFORM 1 FROM public.assets WHERE id=work.asset_id FOR UPDATE;
        UPDATE public.assets SET state='DELETING',access_generation=access_generation+1,tombstoned_at=clock_timestamp() WHERE id=work.asset_id AND state='REJECTED';
        PERFORM 1 FROM wso_private.asset_uploads WHERE asset_id=work.asset_id FOR UPDATE;
        SELECT * INTO work FROM wso_private.asset_cleanup WHERE id=p_work FOR UPDATE;
        IF work.status<>'LEASED' OR work.generation IS DISTINCT FROM p_generation OR work.lease_digest IS DISTINCT FROM sha256(convert_to(p_token,'UTF8')) OR work.lease_expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset cleanup lease conflict' USING ERRCODE='55000'; END IF;
        RETURN work;
      END;""",
    )
    fn(
        "wso_finish_asset_cleanup(uuid,bigint,text,boolean)",
        "wso_finish_asset_cleanup(p_work uuid,p_generation bigint,p_token text,p_absent boolean) RETURNS boolean",
        """
      DECLARE work wso_private.asset_cleanup%ROWTYPE; a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE;
      BEGIN
        work:=public.wso_asset_cleanup_lock(p_work,p_generation,p_token);
        SELECT * INTO a FROM public.assets WHERE id=work.asset_id;
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=work.asset_id;
        IF p_absent IS DISTINCT FROM true OR (a.id IS NOT NULL AND a.state NOT IN ('DELETING','REJECTED','DELETED'))
          OR (u.id IS NOT NULL AND (u.id<>work.attempt_id OR u.lease_expires_at+(SELECT make_interval(secs=>grace_seconds) FROM wso_private.asset_settings WHERE singleton)>clock_timestamp() OR (u.remote_uncertain AND u.completion_dispatched AND NOT u.remote_observed)))
          OR EXISTS(SELECT 1 FROM wso_private.asset_read_leases WHERE asset_id=work.asset_id AND closed_at IS NULL AND expires_at>clock_timestamp()) THEN RETURN false; END IF;
        UPDATE wso_private.asset_cleanup SET status='DONE',lease_digest=null,lease_expires_at=null,error_code=null WHERE id=p_work;
        IF a.id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM wso_private.asset_cleanup WHERE asset_id=a.id AND status<>'DONE') THEN
          UPDATE public.assets SET state='DELETED',deleted_at=clock_timestamp() WHERE id=a.id;
          UPDATE wso_private.asset_uploads SET wrapped_dek=null,wrap_nonce=null,object_nonce=null,key_id=null,remote_uncertain=false,lease_digest=null WHERE asset_id=a.id;
          PERFORM public.wso_asset_audit(a.tenant_id,a.id,'ASSET_CLEANUP_SUCCESS',null);
        END IF;
        RETURN true;
      END;""",
        "wso_asset_maintenance",
    )
    fn(
        "wso_retry_asset_cleanup(uuid,bigint,text,text)",
        "wso_retry_asset_cleanup(p_work uuid,p_generation bigint,p_token text,p_error text) RETURNS void",
        """
      DECLARE work wso_private.asset_cleanup%ROWTYPE;
      BEGIN
        work:=public.wso_asset_cleanup_lock(p_work,p_generation,p_token);
        IF p_error IS NULL OR p_error NOT IN ('NOT_FOUND','DENIED','UNAVAILABLE','DEADLINE','LIMIT','INTEGRITY','UNSUPPORTED','REMOTE_UNKNOWN') THEN RAISE EXCEPTION 'asset cleanup error invalid' USING ERRCODE='22023'; END IF;
        UPDATE wso_private.asset_cleanup SET status='READY',due_at=clock_timestamp()+make_interval(secs=>(least(300,5*power(2,least(work.attempts-1,6)))+random()*5)),lease_digest=null,lease_expires_at=null,error_code=p_error WHERE id=p_work;
        IF EXISTS(SELECT 1 FROM public.assets WHERE id=work.asset_id) THEN
          PERFORM public.wso_asset_audit(work.tenant_id,work.asset_id,'ASSET_CLEANUP_RETRY',null);
          IF (work.attempts>=10 OR work.due_at<clock_timestamp()-interval '1 hour')
            AND (work.attention_at IS NULL OR work.attention_at<clock_timestamp()-interval '1 hour') THEN
            PERFORM public.wso_asset_audit(work.tenant_id,work.asset_id,'ASSET_CLEANUP_ATTENTION',null);
            UPDATE wso_private.asset_cleanup SET attention_at=clock_timestamp() WHERE id=p_work;
          END IF;
        END IF;
      END;""",
        "wso_asset_maintenance",
    )
    fn(
        "wso_reconcile_asset_candidate(jsonb,timestamptz)",
        "wso_reconcile_asset_candidate(p_locator jsonb,p_observed_before timestamptz) RETURNS boolean",
        """
      DECLARE installation uuid; tenant uuid; aid uuid; attempt uuid; a public.assets%ROWTYPE; u wso_private.asset_uploads%ROWTYPE; mid text;
      BEGIN
        IF p_locator IS NULL OR jsonb_typeof(p_locator)<>'object' OR p_locator-ARRAY['installation_id','tenant_id','asset_id','attempt_id','multipart_id']<>'{}'::jsonb OR p_observed_before IS NULL OR p_observed_before>clock_timestamp() THEN RAISE EXCEPTION 'asset candidate invalid' USING ERRCODE='22023'; END IF;
        installation:=(p_locator->>'installation_id')::uuid; tenant:=(p_locator->>'tenant_id')::uuid; aid:=(p_locator->>'asset_id')::uuid; attempt:=(p_locator->>'attempt_id')::uuid; mid:=p_locator->>'multipart_id';
        IF installation IS DISTINCT FROM (SELECT installation_id FROM wso_private.asset_settings WHERE singleton) OR tenant IS NULL OR aid IS NULL OR attempt IS NULL OR (mid IS NOT NULL AND length(mid) NOT BETWEEN 1 AND 1024) THEN RAISE EXCEPTION 'asset candidate denied' USING ERRCODE='42501'; END IF;
        SELECT * INTO a FROM public.assets WHERE id=aid;
        IF a.parent_asset_id IS NOT NULL THEN PERFORM 1 FROM public.assets WHERE id=a.parent_asset_id FOR UPDATE; END IF;
        SELECT * INTO a FROM public.assets WHERE id=aid FOR UPDATE;
        SELECT * INTO u FROM wso_private.asset_uploads WHERE asset_id=aid FOR UPDATE;
        IF a.id IS NOT NULL THEN
          IF a.tenant_id<>tenant OR u.id<>attempt OR a.state NOT IN ('DELETING','REJECTED','DELETED') OR u.lease_expires_at+(SELECT make_interval(secs=>grace_seconds) FROM wso_private.asset_settings WHERE singleton)>clock_timestamp() THEN RETURN false; END IF;
          -- A positive completed-object observation resolves unknown remote writes;
          -- multipart presence alone cannot prove that a late completion has stopped.
          IF mid IS NULL THEN UPDATE wso_private.asset_uploads SET remote_observed=true WHERE asset_id=aid; END IF;
        ELSIF p_observed_before>clock_timestamp()-interval '1 hour' THEN RETURN false;
        END IF;
        IF mid IS NOT NULL AND p_observed_before>clock_timestamp()-(SELECT make_interval(secs=>session_seconds) FROM wso_private.asset_settings WHERE singleton) THEN RETURN false; END IF;
        INSERT INTO wso_private.asset_cleanup(tenant_id,asset_id,attempt_id,operation,multipart_id,due_at)
          VALUES(tenant,aid,attempt,CASE WHEN mid IS NULL THEN 'DELETE_OBJECT' ELSE 'ABORT_MULTIPART' END,mid,clock_timestamp())
          ON CONFLICT(asset_id,attempt_id,operation,multipart_id) DO UPDATE SET status='READY',due_at=clock_timestamp()
            WHERE asset_cleanup.status='DONE';
        RETURN true;
      END;""",
        "wso_asset_maintenance",
    )


def _job_reads():
    fn(
        "wso_attach_job_asset(uuid,uuid)",
        "wso_attach_job_asset(p_job uuid,p_asset uuid) RETURNS void",
        """
      DECLARE j record; a public.assets%ROWTYPE; c record; parent public.assets%ROWTYPE;
      BEGIN
        SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
        SELECT id,tenant_id,actor_user_id,store_id,kind,state INTO j FROM public.jobs WHERE id=p_job;
        IF c.user_id IS NULL OR c.role<>'OWNER' OR j.id IS NULL OR j.tenant_id IS DISTINCT FROM c.tenant_id OR j.actor_user_id IS DISTINCT FROM c.user_id OR NOT public.wso_job_authorized(p_job) THEN RAISE EXCEPTION 'asset job denied' USING ERRCODE='42501'; END IF;
        SELECT id,tenant_id,actor_user_id,store_id,kind,state INTO j FROM public.jobs WHERE id=p_job FOR UPDATE;
        IF j.state NOT IN ('QUEUED','RUNNING') THEN RAISE EXCEPTION 'asset job unavailable' USING ERRCODE='55000'; END IF;
        SELECT * INTO a FROM public.assets WHERE id=p_asset AND tenant_id=j.tenant_id;
        IF a.parent_asset_id IS NOT NULL THEN SELECT * INTO parent FROM public.assets WHERE id=a.parent_asset_id FOR UPDATE; END IF;
        SELECT * INTO a FROM public.assets WHERE id=p_asset AND tenant_id=j.tenant_id FOR UPDATE;
        IF NOT FOUND OR a.state<>'READY' OR a.expires_at<=clock_timestamp() OR a.store_id IS DISTINCT FROM j.store_id
          OR (a.parent_asset_id IS NOT NULL AND (parent.state<>'READY' OR parent.expires_at<=clock_timestamp()))
          OR NOT EXISTS(SELECT 1 FROM wso_private.asset_job_kinds WHERE kind=j.kind AND purpose=a.purpose AND operation='READ') THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        INSERT INTO public.job_assets VALUES(a.tenant_id,j.id,a.id,a.access_generation) ON CONFLICT DO NOTHING;
      END;""",
        "wso_app",
    )
    fn(
        "wso_begin_job_asset_read(uuid)",
        f"wso_begin_job_asset_read(p_asset uuid) RETURNS TABLE({MANIFEST_COLUMNS},read_use text)",
        """
      DECLARE jid uuid; j record; a public.assets%ROWTYPE; parent public.assets%ROWTYPE; lid uuid:=gen_random_uuid(); ending timestamptz; ctx record;
      BEGIN
        jid:=public.wso_current_job_id();
        IF jid IS NULL OR NOT public.wso_job_authorized(jid) THEN RAISE EXCEPTION 'asset job denied' USING ERRCODE='42501'; END IF;
        SELECT id,tenant_id,actor_user_id,store_id,kind,state,lease_generation,lease_expires_at,cancel_requested_at INTO j FROM public.jobs WHERE id=jid FOR UPDATE;
        SELECT expires_at,lease_generation INTO ctx FROM wso_private.job_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current() AND job_id=jid;
        SELECT * INTO a FROM public.assets WHERE id=p_asset AND tenant_id=j.tenant_id;
        IF a.parent_asset_id IS NOT NULL THEN SELECT * INTO parent FROM public.assets WHERE id=a.parent_asset_id FOR UPDATE; END IF;
        SELECT * INTO a FROM public.assets WHERE id=p_asset AND tenant_id=j.tenant_id FOR UPDATE;
        IF NOT FOUND OR a.state<>'READY' OR a.expires_at<=clock_timestamp() OR a.store_id IS DISTINCT FROM j.store_id OR j.state<>'RUNNING' OR j.cancel_requested_at IS NOT NULL OR j.lease_expires_at<=clock_timestamp() OR ctx.expires_at<=clock_timestamp() OR j.lease_generation IS DISTINCT FROM ctx.lease_generation
          OR (a.parent_asset_id IS NOT NULL AND (parent.state<>'READY' OR parent.expires_at<=clock_timestamp()))
          OR NOT EXISTS(SELECT 1 FROM public.job_assets r WHERE r.job_id=jid AND r.asset_id=a.id AND r.tenant_id=a.tenant_id AND r.access_generation=a.access_generation)
          OR NOT EXISTS(SELECT 1 FROM wso_private.asset_job_kinds WHERE kind=j.kind AND purpose=a.purpose AND operation='READ') THEN RAISE EXCEPTION 'asset missing' USING ERRCODE='P0002'; END IF;
        ending:=least(a.expires_at,parent.expires_at,j.lease_expires_at,ctx.expires_at,clock_timestamp()+(SELECT make_interval(secs=>job_read_seconds) FROM wso_private.asset_settings WHERE singleton));
        INSERT INTO wso_private.asset_read_leases(id,tenant_id,asset_id,access_generation,parent_access_generation,reader_kind,actor_id,job_id,job_generation,expires_at) VALUES(lid,a.tenant_id,a.id,a.access_generation,parent.access_generation,'JOB',j.actor_user_id,j.id,j.lease_generation,ending);
        RETURN QUERY SELECT m.*,'JOB'::text FROM public.wso_asset_manifest(a.id,'JOB',lid,null) m;
      END;""",
        "wso_job_worker",
    )
    fn(
        "wso_revalidate_asset_read(uuid,uuid)",
        "wso_revalidate_asset_read(p_asset uuid,p_lease uuid) RETURNS boolean",
        """
      SELECT EXISTS(SELECT 1 FROM wso_private.asset_read_leases l JOIN public.assets a ON a.id=l.asset_id
        JOIN wso_private.job_contexts c ON c.job_id=l.job_id AND c.backend_pid=pg_backend_pid() AND c.transaction_id=txid_current()
        JOIN public.jobs j ON j.id=c.job_id WHERE l.id=p_lease AND l.asset_id=p_asset AND l.reader_kind='JOB' AND l.closed_at IS NULL
        AND l.expires_at>clock_timestamp() AND c.expires_at>clock_timestamp() AND j.lease_expires_at>clock_timestamp() AND j.state='RUNNING' AND j.cancel_requested_at IS NULL
        AND l.job_generation=c.lease_generation AND c.lease_generation=j.lease_generation AND l.actor_id=c.actor_id AND a.state='READY' AND a.expires_at>clock_timestamp() AND a.access_generation=l.access_generation
        AND (a.parent_asset_id IS NULL OR EXISTS(SELECT 1 FROM public.assets p WHERE p.id=a.parent_asset_id AND p.state='READY' AND p.expires_at>clock_timestamp() AND p.access_generation=l.parent_access_generation)))
      """,
        "wso_job_worker",
        language="sql",
    )
    fn(
        "wso_close_asset_read(uuid,uuid)",
        "wso_close_asset_read(p_asset uuid,p_lease uuid) RETURNS void",
        """
      BEGIN
        UPDATE wso_private.asset_read_leases SET closed_at=clock_timestamp() WHERE id=p_lease AND asset_id=p_asset AND reader_kind='JOB' AND job_id=public.wso_current_job_id() AND closed_at IS NULL;
      END;""",
        "wso_job_worker",
    )


def downgrade():
    op.execute("DROP TABLE wso_private.asset_reconciliation CASCADE")
    op.execute("DROP TABLE wso_private.asset_audit_outbox CASCADE")
    # Used only by the explicitly disposable migration roundtrip gate.
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table} CASCADE")
    op.execute(
        "DO $$ DECLARE f record; BEGIN FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p WHERE p.pronamespace='public'::regnamespace AND p.proowner='wso_asset_owner'::regrole LOOP EXECUTE 'DROP FUNCTION IF EXISTS '||f.signature||' CASCADE'; END LOOP; END $$"
    )
    for table in (
        "public.memberships",
        "public.tenants",
        "public.stores",
        "public.web_sessions",
        "public.jobs",
        "wso_private.job_contexts",
        "wso_private.tenant_contexts",
    ):
        op.execute(f"DROP POLICY IF EXISTS asset_authority_read ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM wso_asset_owner")
    op.execute("DROP POLICY asset_audit ON public.audit_events")
    op.execute("REVOKE ALL ON public.audit_events FROM wso_asset_owner")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.wso_current_job_id(),public.wso_job_authorized(uuid) FROM wso_asset_owner"
    )
    op.execute("REVOKE USAGE ON SCHEMA wso_private FROM wso_asset_owner")
    op.execute(
        "REVOKE USAGE ON SCHEMA public FROM wso_asset_owner,wso_asset_maintenance"
    )


def _reconciliation():
    op.execute(
        "CREATE TABLE wso_private.asset_reconciliation(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),object_cursor text,multipart_cursor text)"
    )
    op.execute("ALTER TABLE wso_private.asset_reconciliation OWNER TO wso_migrator")
    op.execute(
        "GRANT SELECT,UPDATE ON wso_private.asset_reconciliation TO wso_asset_owner"
    )
    op.execute("ALTER TABLE wso_private.asset_reconciliation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wso_private.asset_reconciliation FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON wso_private.asset_reconciliation FROM PUBLIC")
    op.execute(
        "CREATE POLICY reconciliation_owner ON wso_private.asset_reconciliation TO wso_asset_owner USING(true) WITH CHECK(true)"
    )
    op.execute(
        "CREATE POLICY reconciliation_migrator ON wso_private.asset_reconciliation TO wso_migrator USING(true) WITH CHECK(true)"
    )
    op.execute("GRANT ALL ON wso_private.asset_reconciliation TO wso_migrator")
    op.execute("INSERT INTO wso_private.asset_reconciliation(singleton) VALUES(true)")
    fn(
        "wso_asset_reconciliation_state()",
        "wso_asset_reconciliation_state() RETURNS TABLE(object_cursor text,multipart_cursor text)",
        "SELECT object_cursor,multipart_cursor FROM wso_private.asset_reconciliation WHERE singleton",
        "wso_asset_maintenance",
        language="sql",
    )
    fn(
        "wso_checkpoint_asset_reconciliation(text,text,text)",
        "wso_checkpoint_asset_reconciliation(p_kind text,p_expected text,p_next text) RETURNS boolean",
        """
      DECLARE changed integer;
      BEGIN
        IF p_kind NOT IN ('OBJECTS','MULTIPART') OR (p_next IS NOT NULL AND length(p_next) NOT BETWEEN 1 AND 4096) THEN RAISE EXCEPTION 'asset cursor invalid' USING ERRCODE='22023'; END IF;
        IF p_kind='OBJECTS' THEN
          UPDATE wso_private.asset_reconciliation SET object_cursor=p_next WHERE singleton AND object_cursor IS NOT DISTINCT FROM p_expected;
        ELSE
          UPDATE wso_private.asset_reconciliation SET multipart_cursor=p_next WHERE singleton AND multipart_cursor IS NOT DISTINCT FROM p_expected;
        END IF;
        GET DIAGNOSTICS changed=ROW_COUNT; RETURN changed=1;
      END;""",
        "wso_asset_maintenance",
    )


def _guards():
    fn(
        "wso_asset_immutable_guard()",
        "wso_asset_immutable_guard() RETURNS trigger",
        """
      DECLARE parent public.assets%ROWTYPE;
      BEGIN
        IF TG_OP='UPDATE' THEN
          IF ROW(NEW.id,NEW.tenant_id,NEW.store_id,NEW.purpose,NEW.parent_asset_id,NEW.creator_id,NEW.checksum_sha256,NEW.byte_size,NEW.content_type,NEW.created_at,NEW.expires_at,NEW.policy_version)
            IS DISTINCT FROM ROW(OLD.id,OLD.tenant_id,OLD.store_id,OLD.purpose,OLD.parent_asset_id,OLD.creator_id,OLD.checksum_sha256,OLD.byte_size,OLD.content_type,OLD.created_at,OLD.expires_at,OLD.policy_version)
            THEN RAISE EXCEPTION 'asset metadata immutable' USING ERRCODE='22023'; END IF;
          IF NEW.state<>OLD.state AND NOT ((OLD.state='PENDING' AND NEW.state IN ('READY','REJECTED','DELETING')) OR (OLD.state IN ('READY','REJECTED') AND NEW.state='DELETING') OR (OLD.state='DELETING' AND NEW.state='DELETED')) THEN RAISE EXCEPTION 'asset state invalid' USING ERRCODE='55000'; END IF;
          IF NEW.access_generation<OLD.access_generation THEN RAISE EXCEPTION 'asset generation invalid' USING ERRCODE='22023'; END IF;
        ELSIF NEW.parent_asset_id IS NOT NULL THEN
          SELECT * INTO parent FROM public.assets WHERE id=NEW.parent_asset_id AND tenant_id=NEW.tenant_id FOR SHARE;
          IF NOT FOUND OR parent.purpose<>'IMPORT_PHOTO' OR parent.state<>'READY' OR parent.store_id IS DISTINCT FROM NEW.store_id OR parent.expires_at<NEW.expires_at OR parent.expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'asset parent invalid' USING ERRCODE='22023'; END IF;
        END IF;
        RETURN NEW;
      END;""",
    )
    op.execute(
        "CREATE TRIGGER asset_immutable_guard BEFORE INSERT OR UPDATE ON public.assets FOR EACH ROW EXECUTE FUNCTION public.wso_asset_immutable_guard()"
    )
