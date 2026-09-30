"""Durable jobs with separate execution and projection authorities."""

from __future__ import annotations

import ast
from pathlib import Path

from alembic import op

revision = "0003_jobs"
down_revision = "0002_connections"
branch_labels = None
depends_on = None


def fn(signature, body, grantee="", owner="wso_job_owner"):
    if signature.startswith(("wso_claim_", "wso_ack_", "wso_heartbeat_", "wso_begin_")):
        for seconds, key in [
            (60, "lease"),
            (15, "dispatch"),
            (30, "watchdog"),
            (20, "step"),
        ]:
            body = body.replace(
                f"interval '{seconds} seconds'",
                f"(public.wso_job_timing('{key}')*interval '1 second')",
            )
        body = body.replace(
            "least(30,power(2,least(j.attempts,5)))",
            "least(30,public.wso_job_timing('retry')*power(2,least(j.attempts-1,4)))",
        )
    op.execute(body)
    op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {owner}")
    op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    if grantee:
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {grantee}")


def upgrade():
    for role, login in [
        ("wso_dispatcher", "LOGIN"),
        ("wso_job_worker", "LOGIN"),
        ("wso_dispatch_owner", "NOLOGIN"),
        ("wso_job_owner", "NOLOGIN"),
    ]:
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role}; END IF; END $$"
        )
        op.execute(
            f"ALTER ROLE {role} {login} NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
        )
        op.execute(
            f"DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_auth_members WHERE member='{role}'::regrole OR roleid='{role}'::regrole) THEN RAISE EXCEPTION 'job role membership is forbidden'; END IF; END $$"
        )
        op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    op.execute("GRANT USAGE ON SCHEMA wso_private TO wso_job_owner,wso_dispatch_owner")
    _timing()
    op.execute("""
      ALTER TABLE public.tenants ADD COLUMN job_generation bigint NOT NULL DEFAULT 1 CHECK(job_generation>0);
      CREATE TABLE public.jobs(
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(id),
        scope_kind text NOT NULL CHECK(scope_kind IN ('TENANT','STORE')),store_id uuid,
        actor_user_id uuid NOT NULL,actor_role_at_enqueue text NOT NULL,tenant_generation bigint NOT NULL CHECK(tenant_generation>0),
        kind text NOT NULL,payload_version integer NOT NULL,payload jsonb NOT NULL CHECK(octet_length(payload::text)<=65536),
        payload_hash bytea NOT NULL,idempotency_key varchar(200) NOT NULL CHECK(length(idempotency_key)>0),operation_target text NOT NULL,
        state text NOT NULL DEFAULT 'QUEUED' CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','NEEDS_USER_INPUT','CANCELLED')),
        attempts integer NOT NULL DEFAULT 0,max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
        next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),lease_generation bigint NOT NULL DEFAULT 0,
        lease_digest bytea,worker_id text,lease_expires_at timestamptz,heartbeat_at timestamptz,cancel_requested_at timestamptz,
        failure_code text,result jsonb CHECK(octet_length(result::text)<=65536),submitted_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),completed_at timestamptz,
        UNIQUE(tenant_id,id),UNIQUE(tenant_id,kind,operation_target,idempotency_key),
        CHECK((scope_kind='TENANT' AND store_id IS NULL) OR (scope_kind='STORE' AND store_id IS NOT NULL)),
        FOREIGN KEY(tenant_id,store_id) REFERENCES public.stores(tenant_id,id));
      CREATE TABLE public.job_connections(tenant_id uuid NOT NULL,job_id uuid NOT NULL,connection_id uuid NOT NULL,generation bigint NOT NULL,
        PRIMARY KEY(tenant_id,job_id,connection_id),FOREIGN KEY(tenant_id,job_id) REFERENCES public.jobs(tenant_id,id) ON DELETE CASCADE);
      CREATE TABLE public.job_items(tenant_id uuid NOT NULL,job_id uuid NOT NULL,item_key text NOT NULL,
        state text NOT NULL CHECK(state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','NEEDS_USER_INPUT','CANCELLED')),
        attempt integer NOT NULL,lease_generation bigint NOT NULL,result jsonb CHECK(octet_length(result::text)<=65536),failure_code text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(tenant_id,job_id,item_key),FOREIGN KEY(tenant_id,job_id) REFERENCES public.jobs(tenant_id,id) ON DELETE CASCADE);
      CREATE TABLE public.outbox(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL,job_id uuid NOT NULL,
        event_type text NOT NULL DEFAULT 'JOB_READY' CHECK(event_type='JOB_READY'),schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version=1),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),completed_at timestamptz,
        UNIQUE(tenant_id,id),UNIQUE(tenant_id,job_id,event_type),FOREIGN KEY(tenant_id,job_id) REFERENCES public.jobs(tenant_id,id) ON DELETE CASCADE);
      CREATE TABLE public.inbox_dedup(tenant_id uuid NOT NULL,consumer_name text NOT NULL,outbox_id uuid NOT NULL,job_id uuid NOT NULL,
        state text NOT NULL CHECK(state IN ('PROCESSING','COMPLETED')),lease_generation bigint NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        PRIMARY KEY(tenant_id,consumer_name,outbox_id),FOREIGN KEY(tenant_id,job_id) REFERENCES public.jobs(tenant_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,outbox_id) REFERENCES public.outbox(tenant_id,id) ON DELETE CASCADE);
      CREATE TABLE wso_private.dispatch_ready(outbox_id uuid PRIMARY KEY REFERENCES public.outbox(id) ON DELETE CASCADE,
        job_id uuid NOT NULL,tenant_id uuid NOT NULL,kind text NOT NULL,queue text NOT NULL,due_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        dispatch_generation bigint NOT NULL DEFAULT 0,dispatch_owner text,dispatch_lease_expires_at timestamptz,last_published_at timestamptz,
        state text NOT NULL DEFAULT 'READY' CHECK(state IN ('READY','LEASED','WAITING','DONE')),publish_attempts integer NOT NULL DEFAULT 0,error_code text);
      CREATE INDEX ix_dispatch_due ON wso_private.dispatch_ready(state,due_at,dispatch_lease_expires_at);
      CREATE TABLE wso_private.job_contexts(backend_pid integer PRIMARY KEY,transaction_id bigint NOT NULL,job_id uuid NOT NULL,tenant_id uuid NOT NULL,
        actor_id uuid NOT NULL,lease_generation bigint NOT NULL,expires_at timestamptz NOT NULL);
      CREATE TABLE wso_private.job_kinds(kind text NOT NULL,payload_version integer NOT NULL,scope_kind text NOT NULL CHECK(scope_kind IN ('TENANT','STORE')),
        permission text NOT NULL CHECK(permission IN ('OWNER','MANAGER','STAFF')),queue text NOT NULL CHECK(queue IN ('wso.default','wso.browser','wso.cli','wso.media')),
        effect_mode text NOT NULL CHECK(effect_mode IN ('LOCAL_ATOMIC','READ','EXTERNAL_WRITE')),max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
        credential_use boolean NOT NULL DEFAULT false,PRIMARY KEY(kind,payload_version));
      INSERT INTO wso_private.job_kinds VALUES('IMPORT',1,'TENANT','OWNER','wso.browser','READ',3,true),('REGISTRATION',1,'STORE','OWNER','wso.browser','EXTERNAL_WRITE',1,true);
    """)
    for table in [
        "public.jobs",
        "public.job_connections",
        "public.job_items",
        "public.outbox",
        "public.inbox_dedup",
        "wso_private.dispatch_ready",
        "wso_private.job_contexts",
        "wso_private.job_kinds",
    ]:
        name = table.split(".")[1]
        owner = "wso_dispatch_owner" if name == "dispatch_ready" else "wso_migrator"
        op.execute(f"ALTER TABLE {table} OWNER TO {owner}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"REVOKE ALL ON {table} FROM PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher"
        )
        op.execute(
            f"CREATE POLICY {name}_migration_policy ON {table} TO wso_migrator USING(true) WITH CHECK(true)"
        )
        op.execute(
            f"CREATE POLICY {name}_job_policy ON {table} TO wso_job_owner USING(true) WITH CHECK(true)"
        )
        privilege = "SELECT" if name == "job_kinds" else "SELECT,INSERT,UPDATE,DELETE"
        op.execute(f"GRANT {privilege} ON {table} TO wso_job_owner")
    op.execute(
        "CREATE POLICY dispatch_owner_policy ON wso_private.dispatch_ready TO wso_dispatch_owner USING(true) WITH CHECK(true)"
    )
    op.execute("GRANT ALL ON wso_private.dispatch_ready TO wso_migrator")
    for table in [
        "public.memberships",
        "public.tenants",
        "public.connections",
        "public.stores",
        "public.store_memberships",
        "wso_private.tenant_contexts",
    ]:
        name = table.split(".")[1]
        op.execute(f"GRANT SELECT ON {table} TO wso_job_owner")
        op.execute(
            f"CREATE POLICY {name}_job_metadata_policy ON {table} TO wso_job_owner USING(true)"
        )
        if name != "tenant_contexts":
            col = {
                "memberships": "role",
                "tenants": "job_generation",
                "connections": "generation",
                "stores": "active",
                "store_memberships": "user_id",
            }[name]
            op.execute(f"GRANT UPDATE({col}) ON {table} TO wso_job_owner")
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_current_tenant_id() TO wso_job_owner"
    )
    _functions()
    _lifecycle()
    _secrets()


def _timing():
    op.execute("""
      CREATE TABLE wso_private.job_settings(singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
        lease_seconds integer NOT NULL DEFAULT 60 CHECK(lease_seconds BETWEEN 2 AND 300),
        dispatch_seconds integer NOT NULL DEFAULT 15 CHECK(dispatch_seconds BETWEEN 1 AND 60),
        watchdog_seconds integer NOT NULL DEFAULT 30 CHECK(watchdog_seconds BETWEEN 1 AND 120),
        step_seconds integer NOT NULL DEFAULT 20 CHECK(step_seconds BETWEEN 1 AND 20 AND step_seconds<lease_seconds),
        retry_seconds integer NOT NULL DEFAULT 2 CHECK(retry_seconds BETWEEN 1 AND 30));
      ALTER TABLE wso_private.job_settings OWNER TO wso_migrator;
      ALTER TABLE wso_private.job_settings ENABLE ROW LEVEL SECURITY;
      ALTER TABLE wso_private.job_settings FORCE ROW LEVEL SECURITY;
      REVOKE ALL ON wso_private.job_settings FROM PUBLIC;
      CREATE POLICY job_settings_migration_policy ON wso_private.job_settings TO wso_migrator USING(true) WITH CHECK(true);
      INSERT INTO wso_private.job_settings(singleton) VALUES(true);
    """)
    fn(
        "wso_job_timing(text)",
        """
      CREATE FUNCTION public.wso_job_timing(p_key text) RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT CASE p_key WHEN 'lease' THEN lease_seconds WHEN 'dispatch' THEN dispatch_seconds WHEN 'watchdog' THEN watchdog_seconds
          WHEN 'step' THEN step_seconds WHEN 'retry' THEN retry_seconds END FROM wso_private.job_settings WHERE singleton;
      $wso$""",
        "wso_job_owner,wso_dispatch_owner",
        "wso_migrator",
    )


def _functions():
    fn(
        "wso_validate_job_registry(jsonb)",
        """
      CREATE FUNCTION public.wso_validate_job_registry(p_registry jsonb) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      BEGIN
        IF p_registry IS NULL OR jsonb_typeof(p_registry)<>'array' OR jsonb_array_length(p_registry) NOT BETWEEN 1 AND 100 OR octet_length(p_registry::text)>65536 THEN RETURN false; END IF;
        RETURN NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_registry) d WHERE NOT EXISTS(
          SELECT 1 FROM wso_private.job_kinds k WHERE k.kind=d->>'kind' AND k.payload_version=(d->>'payload_version')::integer
          AND k.scope_kind=d->>'scope_kind' AND k.permission=d->>'permission' AND k.queue=d->>'queue'
          AND k.effect_mode=d->>'effect_mode' AND k.max_attempts=(d->>'max_attempts')::integer AND k.credential_use=(d->>'credential_use')::boolean));
      END; $wso$""",
        "wso_app,wso_job_worker",
    )
    fn(
        "wso_job_json_safe(jsonb)",
        """
      CREATE FUNCTION public.wso_job_json_safe(p_value jsonb) RETURNS boolean LANGUAGE sql IMMUTABLE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
        SELECT p_value IS NOT NULL AND jsonb_typeof(p_value)='object' AND octet_length(p_value::text)<=65536
          AND p_value::text !~* '"(password|secret|credential|credentials|token|lease_token|capability|handle|ciphertext|presigned_url)"[[:space:]]*:'
          AND p_value::text !~* 'https?://'
          AND p_value::text !~ '"[0-9a-f]{64}"';
      $wso$""",
    )
    fn(
        "wso_job_authorized(uuid)",
        """
    CREATE FUNCTION public.wso_job_authorized(p_id uuid) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE; r text; epoch bigint; c record; actual bigint;
    BEGIN
      SELECT * INTO j FROM public.jobs WHERE id=p_id; IF NOT FOUND THEN RETURN false; END IF;
      SELECT role INTO r FROM public.memberships WHERE tenant_id=j.tenant_id AND user_id=j.actor_user_id FOR SHARE;
      IF r IS DISTINCT FROM j.actor_role_at_enqueue THEN RETURN false; END IF;
      SELECT job_generation INTO epoch FROM public.tenants WHERE id=j.tenant_id FOR SHARE;
      IF epoch IS DISTINCT FROM j.tenant_generation THEN RETURN false; END IF;
      FOR c IN SELECT * FROM public.job_connections WHERE job_id=j.id ORDER BY connection_id LOOP
        SELECT generation INTO actual FROM public.connections WHERE id=c.connection_id AND tenant_id=j.tenant_id AND status='NOT_VERIFIED' FOR SHARE;
        IF actual IS DISTINCT FROM c.generation THEN RETURN false; END IF;
      END LOOP;
      IF j.store_id IS NOT NULL THEN
        PERFORM 1 FROM public.stores WHERE id=j.store_id AND tenant_id=j.tenant_id AND active FOR SHARE;
        IF NOT FOUND THEN RETURN false; END IF;
        IF r<>'OWNER' THEN
          PERFORM 1 FROM public.store_memberships WHERE tenant_id=j.tenant_id AND store_id=j.store_id AND user_id=j.actor_user_id FOR SHARE;
          IF NOT FOUND THEN RETURN false; END IF;
        END IF;
      END IF;
      RETURN EXISTS(SELECT 1 FROM wso_private.job_kinds k WHERE k.kind=j.kind AND k.payload_version=j.payload_version AND k.scope_kind=j.scope_kind
        AND (r='OWNER' OR r=k.permission OR (r='MANAGER' AND k.permission='STAFF')));
    END; $wso$""",
        "wso_migrator",
    )
    fn(
        "wso_job_visible(uuid,uuid,uuid,text)",
        """
    CREATE FUNCTION public.wso_job_visible(p_tenant uuid,p_store uuid,p_actor uuid,p_scope text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE c wso_private.tenant_contexts%ROWTYPE;
    BEGIN
      IF public.wso_current_tenant_id() IS DISTINCT FROM p_tenant THEN RETURN false; END IF;
      SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
      IF c.role<>'OWNER' AND c.user_id<>p_actor THEN RETURN false; END IF;
      IF p_scope='TENANT' THEN RETURN true; END IF;
      RETURN EXISTS(SELECT 1 FROM public.stores s WHERE s.tenant_id=p_tenant AND s.id=p_store AND s.active
        AND (c.role='OWNER' OR EXISTS(SELECT 1 FROM public.store_memberships m WHERE m.tenant_id=s.tenant_id AND m.store_id=s.id AND m.user_id=c.user_id)));
    END; $wso$""",
        "wso_app",
    )
    fn(
        "wso_current_job_id()",
        """
    CREATE FUNCTION public.wso_current_job_id() RETURNS uuid LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE c wso_private.job_contexts%ROWTYPE;
    BEGIN
      SELECT * INTO c FROM wso_private.job_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current() AND expires_at>clock_timestamp();
      IF NOT FOUND THEN RETURN NULL; END IF;
      IF EXISTS(SELECT 1 FROM public.jobs WHERE id=c.job_id AND tenant_id=c.tenant_id AND actor_user_id=c.actor_id AND lease_generation=c.lease_generation
        AND state='RUNNING' AND cancel_requested_at IS NULL AND lease_expires_at>clock_timestamp()) THEN RETURN c.job_id; END IF;
      RETURN NULL;
    END; $wso$""",
        "wso_job_worker",
    )
    op.execute("GRANT SELECT ON public.jobs,public.job_items TO wso_app")
    op.execute(
        "CREATE POLICY jobs_app_policy ON public.jobs TO wso_app USING(public.wso_job_visible(tenant_id,store_id,actor_user_id,scope_kind))"
    )
    op.execute(
        "CREATE POLICY job_items_app_policy ON public.job_items TO wso_app USING(EXISTS(SELECT 1 FROM public.jobs j WHERE j.id=job_id))"
    )
    for table in ["jobs", "job_items", "outbox", "job_connections"]:
        col = "id" if table == "jobs" else "job_id"
        op.execute(f"GRANT SELECT ON public.{table} TO wso_job_worker")
        op.execute(
            f"CREATE POLICY {table}_worker_policy ON public.{table} TO wso_job_worker USING({col}=public.wso_current_job_id())"
        )
    _enqueue()
    _finish()
    _dispatch_functions()
    _worker_functions()


def _enqueue():
    fn(
        "wso_enqueue_job(uuid,text,uuid,text,integer,jsonb,text)",
        """
    CREATE FUNCTION public.wso_enqueue_job(p_tenant uuid,p_scope text,p_store uuid,p_kind text,p_version integer,p_payload jsonb,p_key text)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE ctx wso_private.tenant_contexts%ROWTYPE; k wso_private.job_kinds%ROWTYPE; epoch bigint; target text; hash bytea; jid uuid; oid uuid; cid uuid; gen bigint; existing public.jobs%ROWTYPE;
    BEGIN
      IF public.wso_current_tenant_id() IS DISTINCT FROM p_tenant THEN RAISE EXCEPTION 'job denied' USING ERRCODE='42501'; END IF;
      SELECT * INTO ctx FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
      SELECT * INTO k FROM wso_private.job_kinds WHERE kind=p_kind AND payload_version=p_version;
      IF NOT FOUND OR k.scope_kind<>p_scope OR p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 200 OR p_payload IS NULL OR jsonb_typeof(p_payload)<>'object'
        OR NOT public.wso_job_json_safe(p_payload) OR jsonb_typeof(p_payload->'schema_version') IS DISTINCT FROM 'number' OR (p_payload->>'schema_version') IS DISTINCT FROM '1'
        OR (p_scope='TENANT' AND p_store IS NOT NULL) OR (p_scope='STORE' AND p_store IS NULL) THEN RAISE EXCEPTION 'invalid job' USING ERRCODE='22023'; END IF;
      IF NOT(ctx.role='OWNER' OR ctx.role=k.permission OR (ctx.role='MANAGER' AND k.permission='STAFF')) THEN RAISE EXCEPTION 'job denied' USING ERRCODE='42501'; END IF;
      IF p_kind='IMPORT' AND (p_payload->>'import_id' IS NULL OR p_payload-ARRAY['schema_version','import_id','connection_id']<>'{}'::jsonb) THEN RAISE EXCEPTION 'invalid payload' USING ERRCODE='22023'; END IF;
      IF p_kind='REGISTRATION' AND (p_payload->>'registration_id' IS NULL OR p_payload->>'connection_id' IS NULL OR p_payload-ARRAY['schema_version','registration_id','connection_id']<>'{}'::jsonb) THEN RAISE EXCEPTION 'invalid payload' USING ERRCODE='22023'; END IF;
      IF p_kind='IMPORT' THEN PERFORM (p_payload->>'import_id')::uuid; END IF;
      IF p_kind='REGISTRATION' THEN PERFORM (p_payload->>'registration_id')::uuid; END IF;
      SELECT job_generation INTO epoch FROM public.tenants WHERE id=p_tenant FOR SHARE;
      cid:=(p_payload->>'connection_id')::uuid;
      IF cid IS NOT NULL THEN
        SELECT generation INTO gen FROM public.connections WHERE id=cid AND tenant_id=p_tenant AND status='NOT_VERIFIED' FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'connection missing' USING ERRCODE='P0002'; END IF;
      END IF;
      IF p_store IS NOT NULL THEN
        PERFORM 1 FROM public.stores WHERE tenant_id=p_tenant AND id=p_store AND active FOR SHARE;
        IF NOT FOUND THEN RAISE EXCEPTION 'store missing' USING ERRCODE='P0002'; END IF;
        IF ctx.role<>'OWNER' THEN
          PERFORM 1 FROM public.store_memberships WHERE tenant_id=p_tenant AND store_id=p_store AND user_id=ctx.user_id FOR SHARE;
          IF NOT FOUND THEN RAISE EXCEPTION 'store missing' USING ERRCODE='P0002'; END IF;
        END IF;
      END IF;
      target:=CASE WHEN p_scope='TENANT' THEN 'tenant:'||p_tenant ELSE 'store:'||p_store END;
      hash:=sha256(convert_to(jsonb_build_object('hash_version',1,'scope_kind',p_scope,'tenant_id',p_tenant,'store_id',p_store,'kind',p_kind,'payload_version',p_version,'payload',p_payload,'operation_target',target)::text,'UTF8'));
      INSERT INTO public.jobs(tenant_id,scope_kind,store_id,actor_user_id,actor_role_at_enqueue,tenant_generation,kind,payload_version,payload,payload_hash,idempotency_key,operation_target,max_attempts)
        VALUES(p_tenant,p_scope,p_store,ctx.user_id,ctx.role,epoch,p_kind,p_version,p_payload,hash,p_key,target,k.max_attempts)
        ON CONFLICT(tenant_id,kind,operation_target,idempotency_key) DO NOTHING RETURNING id INTO jid;
      IF jid IS NULL THEN
        SELECT * INTO existing FROM public.jobs WHERE tenant_id=p_tenant AND kind=p_kind AND operation_target=target AND idempotency_key=p_key;
        IF NOT public.wso_job_visible(existing.tenant_id,existing.store_id,existing.actor_user_id,existing.scope_kind) THEN RAISE EXCEPTION 'job missing' USING ERRCODE='P0002'; END IF;
        IF existing.payload_hash<>hash THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='40001'; END IF;
        RETURN existing.id;
      END IF;
      IF cid IS NOT NULL THEN INSERT INTO public.job_connections VALUES(p_tenant,jid,cid,gen); END IF;
      INSERT INTO public.outbox(tenant_id,job_id) VALUES(p_tenant,jid) RETURNING id INTO oid;
      INSERT INTO wso_private.dispatch_ready(outbox_id,job_id,tenant_id,kind,queue) VALUES(oid,jid,p_tenant,p_kind,k.queue);
      RETURN jid;
    END; $wso$""",
        "wso_app",
    )


def _finish():
    fn(
        "wso_finish_job(uuid,text,text,jsonb)",
        """
    CREATE FUNCTION public.wso_finish_job(p_id uuid,p_state text,p_code text,p_result jsonb) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    BEGIN
      IF p_state IS NULL OR p_state NOT IN ('SUCCEEDED','PARTIAL','FAILED','NEEDS_USER_INPUT','CANCELLED') OR (p_result IS NOT NULL AND NOT public.wso_job_json_safe(p_result)) THEN RAISE EXCEPTION 'invalid result' USING ERRCODE='22023'; END IF;
      IF p_state IN ('FAILED','CANCELLED') AND EXISTS(SELECT 1 FROM public.jobs WHERE id=p_id AND submitted_at IS NOT NULL) THEN
        p_state:='NEEDS_USER_INPUT'; p_code:='UNKNOWN_REMOTE_STATE'; p_result:=NULL;
      END IF;
      UPDATE public.jobs SET state=p_state,failure_code=p_code,result=p_result,lease_digest=NULL,lease_expires_at=NULL,updated_at=clock_timestamp(),completed_at=clock_timestamp() WHERE id=p_id;
      UPDATE public.inbox_dedup SET state='COMPLETED',updated_at=clock_timestamp() WHERE job_id=p_id;
      UPDATE public.outbox SET completed_at=clock_timestamp() WHERE job_id=p_id;
      UPDATE wso_private.dispatch_ready SET state='DONE',dispatch_owner=NULL,dispatch_lease_expires_at=NULL WHERE job_id=p_id;
    END; $wso$""",
    )
    fn(
        "wso_revoke_job(uuid)",
        """
    CREATE FUNCTION public.wso_revoke_job(p_id uuid) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE;
    BEGIN
      SELECT * INTO j FROM public.jobs WHERE id=p_id FOR UPDATE;
      IF j.state NOT IN ('QUEUED','RUNNING') THEN RETURN; END IF;
      UPDATE public.jobs SET cancel_requested_at=clock_timestamp() WHERE id=p_id;
      PERFORM public.wso_finish_job(p_id,CASE WHEN j.submitted_at IS NULL THEN 'CANCELLED' ELSE 'NEEDS_USER_INPUT' END,
        CASE WHEN j.submitted_at IS NULL THEN 'AUTHORIZATION_REVOKED' ELSE 'UNKNOWN_REMOTE_STATE' END,NULL);
    END; $wso$""",
        "wso_migrator",
    )
    fn(
        "wso_cancel_job(uuid)",
        """
    CREATE FUNCTION public.wso_cancel_job(p_id uuid) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE; c wso_private.tenant_contexts%ROWTYPE;
    BEGIN
      SELECT * INTO j FROM public.jobs WHERE id=p_id;
      IF NOT FOUND OR NOT public.wso_job_visible(j.tenant_id,j.store_id,j.actor_user_id,j.scope_kind) THEN RAISE EXCEPTION 'job missing' USING ERRCODE='P0002'; END IF;
      SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
      IF c.role<>'OWNER' AND (c.user_id<>j.actor_user_id OR NOT EXISTS(SELECT 1 FROM wso_private.job_kinds k WHERE k.kind=j.kind AND k.payload_version=j.payload_version
        AND (c.role=k.permission OR (c.role='MANAGER' AND k.permission='STAFF')))) THEN RAISE EXCEPTION 'job missing' USING ERRCODE='P0002'; END IF;
      PERFORM public.wso_job_authorized(p_id);
      PERFORM public.wso_revoke_job(p_id); RETURN p_id;
    END; $wso$""",
        "wso_app",
    )


def _dispatch_functions():
    fn(
        "wso_claim_dispatch_batch(integer,text)",
        """
    CREATE FUNCTION public.wso_claim_dispatch_batch(p_limit integer,p_worker text)
    RETURNS TABLE(schema_version integer,job_id uuid,outbox_id uuid,tenant_id uuid,kind text,lease_generation bigint,queue text)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    BEGIN
      IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100 OR length(p_worker) NOT BETWEEN 1 AND 100 OR p_worker IS NULL THEN RAISE EXCEPTION 'invalid dispatcher' USING ERRCODE='22023'; END IF;
      RETURN QUERY WITH due AS(SELECT d.outbox_id FROM wso_private.dispatch_ready d WHERE d.state<>'DONE' AND d.due_at<=clock_timestamp()
          AND (d.state<>'LEASED' OR d.dispatch_lease_expires_at<=clock_timestamp()) ORDER BY d.due_at,d.outbox_id FOR UPDATE SKIP LOCKED LIMIT p_limit)
        UPDATE wso_private.dispatch_ready d SET state='LEASED',dispatch_generation=d.dispatch_generation+1,dispatch_owner=p_worker,
          dispatch_lease_expires_at=clock_timestamp()+interval '15 seconds',publish_attempts=d.publish_attempts+1 FROM due WHERE d.outbox_id=due.outbox_id
        RETURNING 1,d.job_id,d.outbox_id,d.tenant_id,d.kind,d.dispatch_generation,d.queue;
    END; $wso$""",
        "wso_dispatcher",
        "wso_dispatch_owner",
    )
    fn(
        "wso_ack_dispatch(uuid,bigint,text)",
        """
    CREATE FUNCTION public.wso_ack_dispatch(p_outbox uuid,p_generation bigint,p_worker text) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      UPDATE wso_private.dispatch_ready SET state='WAITING',last_published_at=clock_timestamp(),due_at=greatest(due_at,clock_timestamp()+interval '30 seconds'),dispatch_owner=NULL,dispatch_lease_expires_at=NULL,error_code=NULL
      WHERE outbox_id=p_outbox AND dispatch_generation=p_generation AND dispatch_owner=p_worker AND state='LEASED';
    $wso$""",
        "wso_dispatcher",
        "wso_dispatch_owner",
    )
    fn(
        "wso_nack_dispatch(uuid,bigint,text,text)",
        """
    CREATE FUNCTION public.wso_nack_dispatch(p_outbox uuid,p_generation bigint,p_worker text,p_error text) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      UPDATE wso_private.dispatch_ready SET state='WAITING',due_at=greatest(due_at,clock_timestamp()+make_interval(secs=>least(30,power(2,least(publish_attempts,5))))+random()*interval '1 second'),dispatch_owner=NULL,dispatch_lease_expires_at=NULL,error_code='PUBLISH_FAILED'
      WHERE outbox_id=p_outbox AND dispatch_generation=p_generation AND dispatch_owner=p_worker AND state='LEASED';
    $wso$""",
        "wso_dispatcher",
        "wso_dispatch_owner",
    )


def _worker_functions():
    fn(
        "wso_record_job_item(uuid,text,text,text,jsonb,text)",
        """
      CREATE FUNCTION public.wso_record_job_item(p_id uuid,p_token text,p_key text,p_state text,p_result jsonb,p_code text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      DECLARE j public.jobs%ROWTYPE;
      BEGIN
        IF public.wso_current_job_id() IS DISTINCT FROM p_id THEN PERFORM public.wso_begin_job_step(p_id,p_token); END IF;
        SELECT * INTO j FROM public.jobs WHERE id=p_id;
        IF j.lease_digest IS DISTINCT FROM sha256(convert_to(p_token,'UTF8')) OR j.lease_expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'stale lease' USING ERRCODE='42501'; END IF;
        IF p_key IS NULL OR length(p_key) NOT BETWEEN 1 AND 200 OR p_state IS NULL OR p_state NOT IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','NEEDS_USER_INPUT','CANCELLED') OR NOT public.wso_job_json_safe(p_result)
          OR (p_code IS NOT NULL AND p_code !~ '^[A-Z_]{1,64}$') THEN RAISE EXCEPTION 'invalid item' USING ERRCODE='22023'; END IF;
        INSERT INTO public.job_items(tenant_id,job_id,item_key,state,attempt,lease_generation,result,failure_code)
          VALUES(j.tenant_id,j.id,p_key,p_state,j.attempts,j.lease_generation,p_result,p_code)
          ON CONFLICT(tenant_id,job_id,item_key) DO UPDATE SET state=EXCLUDED.state,attempt=EXCLUDED.attempt,lease_generation=EXCLUDED.lease_generation,result=EXCLUDED.result,failure_code=EXCLUDED.failure_code,updated_at=clock_timestamp()
          WHERE job_items.state NOT IN ('SUCCEEDED','FAILED','CANCELLED');
      END; $wso$""",
        "wso_job_worker",
    )
    fn(
        "wso_claim_job(uuid,text,uuid,uuid,text,bigint)",
        """
    CREATE FUNCTION public.wso_claim_job(p_id uuid,p_worker text,p_outbox uuid,p_tenant uuid,p_kind text,p_dispatch bigint)
    RETURNS TABLE(token text,generation bigint,expires_at timestamptz,reconcile boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE; ok boolean; t text;
    BEGIN
      IF length(p_worker) NOT BETWEEN 1 AND 100 OR p_worker IS NULL THEN RAISE EXCEPTION 'invalid worker' USING ERRCODE='22023'; END IF;
      SELECT * INTO j FROM public.jobs WHERE id=p_id;
      IF NOT FOUND OR j.tenant_id IS DISTINCT FROM p_tenant OR j.kind IS DISTINCT FROM p_kind OR p_dispatch<1
        OR NOT EXISTS(SELECT 1 FROM wso_private.dispatch_ready WHERE outbox_id=p_outbox AND job_id=p_id AND tenant_id=p_tenant AND kind=p_kind AND dispatch_generation>=p_dispatch)
        THEN RAISE EXCEPTION 'invalid reference' USING ERRCODE='22023'; END IF;
      ok:=public.wso_job_authorized(p_id);
      SELECT * INTO j FROM public.jobs WHERE id=p_id FOR UPDATE;
      IF j.state NOT IN ('QUEUED','RUNNING') THEN RETURN; END IF;
      IF NOT ok THEN PERFORM public.wso_revoke_job(p_id); RETURN; END IF;
      IF j.state='RUNNING' AND j.lease_expires_at>clock_timestamp() THEN RETURN; END IF;
      IF j.state='RUNNING' THEN
        IF j.attempts>=j.max_attempts THEN
          PERFORM public.wso_finish_job(p_id,CASE WHEN j.submitted_at IS NULL THEN 'FAILED' ELSE 'NEEDS_USER_INPUT' END,
            CASE WHEN j.submitted_at IS NULL THEN 'RETRY_EXHAUSTED' ELSE 'UNKNOWN_REMOTE_STATE' END,NULL); RETURN;
        END IF;
        UPDATE public.jobs SET state='QUEUED',lease_digest=NULL,next_attempt_at=clock_timestamp()+make_interval(secs=>least(30,power(2,least(j.attempts,5)))) WHERE id=p_id;
        UPDATE wso_private.dispatch_ready SET state='WAITING',due_at=clock_timestamp()+make_interval(secs=>least(30,power(2,least(j.attempts,5)))),dispatch_owner=NULL WHERE job_id=p_id;
        RETURN;
      END IF;
      IF j.next_attempt_at>clock_timestamp() THEN RETURN; END IF;
      t:=encode(sha256(convert_to(gen_random_uuid()::text||gen_random_uuid()::text||gen_random_uuid()::text,'UTF8')),'hex');
      UPDATE public.jobs SET state='RUNNING',attempts=attempts+1,lease_generation=lease_generation+1,lease_digest=sha256(convert_to(t,'UTF8')),worker_id=p_worker,
        heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() WHERE id=p_id RETURNING * INTO j;
      INSERT INTO public.inbox_dedup(tenant_id,consumer_name,outbox_id,job_id,state,lease_generation) VALUES(j.tenant_id,'wso.execute_job',p_outbox,j.id,'PROCESSING',j.lease_generation)
        ON CONFLICT(tenant_id,consumer_name,outbox_id) DO UPDATE SET state='PROCESSING',lease_generation=EXCLUDED.lease_generation,updated_at=clock_timestamp();
      UPDATE wso_private.dispatch_ready SET state='WAITING',due_at=j.lease_expires_at,dispatch_owner=NULL,dispatch_lease_expires_at=NULL WHERE job_id=p_id;
      RETURN QUERY SELECT t,j.lease_generation,j.lease_expires_at,j.submitted_at IS NOT NULL;
    END; $wso$""",
        "wso_job_worker",
    )

    fn(
        "wso_begin_job_step(uuid,text)",
        """
    CREATE FUNCTION public.wso_begin_job_step(p_id uuid,p_token text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE;
    BEGIN
      IF EXISTS(SELECT 1 FROM wso_private.job_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current() AND expires_at<=clock_timestamp()) THEN RAISE EXCEPTION 'step expired' USING ERRCODE='42501'; END IF;
      IF NOT public.wso_job_authorized(p_id) THEN RAISE EXCEPTION 'job revoked' USING ERRCODE='42501'; END IF;
      SELECT * INTO j FROM public.jobs WHERE id=p_id FOR UPDATE;
      IF j.state IS DISTINCT FROM 'RUNNING' OR j.cancel_requested_at IS NOT NULL OR j.lease_expires_at<=clock_timestamp() OR j.lease_digest IS DISTINCT FROM sha256(convert_to(p_token,'UTF8')) THEN RAISE EXCEPTION 'stale job lease' USING ERRCODE='42501'; END IF;
      INSERT INTO wso_private.job_contexts VALUES(pg_backend_pid(),txid_current(),j.id,j.tenant_id,j.actor_user_id,j.lease_generation,least(j.lease_expires_at,clock_timestamp()+interval '20 seconds'))
        ON CONFLICT(backend_pid) DO UPDATE SET transaction_id=EXCLUDED.transaction_id,job_id=EXCLUDED.job_id,tenant_id=EXCLUDED.tenant_id,actor_id=EXCLUDED.actor_id,lease_generation=EXCLUDED.lease_generation,expires_at=EXCLUDED.expires_at;
    END; $wso$""",
        "wso_job_worker,wso_migrator",
    )
    fn(
        "wso_complete_job(uuid,text,jsonb,text,text)",
        """
    CREATE FUNCTION public.wso_complete_job(p_id uuid,p_token text,p_result jsonb,p_state text,p_code text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    BEGIN
      IF public.wso_current_job_id() IS DISTINCT FROM p_id THEN PERFORM public.wso_begin_job_step(p_id,p_token); END IF;
      IF NOT EXISTS(SELECT 1 FROM public.jobs WHERE id=p_id AND lease_digest=sha256(convert_to(p_token,'UTF8')) AND lease_expires_at>clock_timestamp()) THEN RAISE EXCEPTION 'stale lease' USING ERRCODE='42501'; END IF;
      IF p_code IS NOT NULL AND p_code !~ '^[A-Z_]{1,64}$' THEN RAISE EXCEPTION 'invalid code' USING ERRCODE='22023'; END IF;
      IF p_state='PARTIAL' AND NOT(EXISTS(SELECT 1 FROM public.job_items WHERE job_id=p_id AND state='SUCCEEDED') AND EXISTS(SELECT 1 FROM public.job_items WHERE job_id=p_id AND state IN ('FAILED','NEEDS_USER_INPUT'))) THEN RAISE EXCEPTION 'partial lacks items' USING ERRCODE='22023'; END IF;
      PERFORM public.wso_finish_job(p_id,p_state,p_code,p_result);
    END; $wso$""",
        "wso_job_worker",
    )
    fn(
        "wso_heartbeat_job(uuid,text)",
        """
    CREATE FUNCTION public.wso_heartbeat_job(p_id uuid,p_token text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    BEGIN
      PERFORM public.wso_begin_job_step(p_id,p_token);
      UPDATE public.jobs SET heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() WHERE id=p_id;
      UPDATE wso_private.dispatch_ready SET due_at=clock_timestamp()+interval '60 seconds' WHERE job_id=p_id AND state<>'DONE';
    END; $wso$""",
        "wso_job_worker",
    )
    fn(
        "wso_mark_job_submitted(uuid,text)",
        """
    CREATE FUNCTION public.wso_mark_job_submitted(p_id uuid,p_token text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    BEGIN
      PERFORM public.wso_begin_job_step(p_id,p_token);
      IF NOT EXISTS(SELECT 1 FROM public.jobs j JOIN wso_private.job_kinds k ON k.kind=j.kind AND k.payload_version=j.payload_version WHERE j.id=p_id AND k.effect_mode='EXTERNAL_WRITE') THEN RAISE EXCEPTION 'invalid write intent' USING ERRCODE='22023'; END IF;
      UPDATE public.jobs SET submitted_at=coalesce(submitted_at,clock_timestamp()) WHERE id=p_id;
    END; $wso$""",
        "wso_job_worker",
    )


def _lifecycle():
    fn(
        "wso_job_revocation_trigger()",
        """
    CREATE FUNCTION public.wso_job_revocation_trigger() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j record;
    BEGIN
      IF TG_TABLE_NAME='connection_revocations' THEN
        FOR j IN SELECT x.id FROM public.jobs x JOIN public.job_connections c ON c.job_id=x.id WHERE c.connection_id=NEW.connection_id AND c.generation=NEW.generation AND x.state IN ('QUEUED','RUNNING') ORDER BY x.id LOOP PERFORM public.wso_revoke_job(j.id); END LOOP;
      ELSIF TG_TABLE_NAME='memberships' THEN
        IF TG_OP='DELETE' OR NEW.role IS DISTINCT FROM OLD.role OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.user_id IS DISTINCT FROM OLD.user_id THEN
          FOR j IN SELECT id FROM public.jobs WHERE tenant_id=OLD.tenant_id AND actor_user_id=OLD.user_id AND state IN ('QUEUED','RUNNING') ORDER BY id LOOP PERFORM public.wso_revoke_job(j.id); END LOOP;
        END IF;
      ELSIF TG_TABLE_NAME='store_memberships' THEN
        IF TG_OP='DELETE' OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.store_id IS DISTINCT FROM OLD.store_id OR NEW.user_id IS DISTINCT FROM OLD.user_id THEN
          FOR j IN SELECT id FROM public.jobs WHERE tenant_id=OLD.tenant_id AND store_id=OLD.store_id AND actor_user_id=OLD.user_id AND state IN ('QUEUED','RUNNING') ORDER BY id LOOP PERFORM public.wso_revoke_job(j.id); END LOOP;
        END IF;
      ELSIF TG_TABLE_NAME='stores' THEN
        IF NOT NEW.active THEN
          FOR j IN SELECT id FROM public.jobs WHERE tenant_id=NEW.tenant_id AND store_id=NEW.id AND state IN ('QUEUED','RUNNING') ORDER BY id LOOP PERFORM public.wso_revoke_job(j.id); END LOOP;
        END IF;
      ELSIF TG_TABLE_NAME='tenants' THEN
        IF NEW.job_generation<>OLD.job_generation THEN
          FOR j IN SELECT id FROM public.jobs WHERE tenant_id=NEW.id AND state IN ('QUEUED','RUNNING') ORDER BY id LOOP PERFORM public.wso_revoke_job(j.id); END LOOP;
        END IF;
      END IF;
      RETURN NULL;
    END; $wso$""",
        "",
        "wso_migrator",
    )
    for table, event in [
        ("wso_private.connection_revocations", "INSERT"),
        ("public.memberships", "UPDATE OR DELETE"),
        ("public.store_memberships", "UPDATE OR DELETE"),
        ("public.stores", "UPDATE OF active"),
        ("public.tenants", "UPDATE OF job_generation"),
    ]:
        op.execute(
            f"CREATE TRIGGER jobs_revoke AFTER {event} ON {table} FOR EACH ROW EXECUTE FUNCTION public.wso_job_revocation_trigger()"
        )
    fn(
        "wso_revoke_tenant_jobs(uuid)",
        """
    CREATE FUNCTION public.wso_revoke_tenant_jobs(p_tenant uuid) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
      UPDATE public.tenants SET job_generation=job_generation+1 WHERE id=p_tenant;
    $wso$""",
        "wso_migrator",
        "wso_migrator",
    )


def _t04_functions():
    tree = ast.parse(
        Path(__file__).with_name("0002_connections.py").read_text(encoding="utf-8")
    )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "function"
        ):
            signature = ast.literal_eval(node.args[0])
            if signature.startswith(
                (
                    "wso_issue_connection_handle(",
                    "wso_redeem_connection_handle(",
                    "wso_use_connection_lease(",
                )
            ):
                yield (
                    signature,
                    ast.literal_eval(node.args[1]),
                    ast.literal_eval(node.args[2]),
                )


def _secrets():
    op.execute(
        "ALTER TABLE wso_private.connection_handles ADD COLUMN job_id uuid,ADD COLUMN job_lease_generation bigint; ALTER TABLE wso_private.connection_leases ADD COLUMN job_id uuid,ADD COLUMN job_lease_generation bigint"
    )
    fn(
        "wso_issue_job_connection_handle(uuid,text,uuid)",
        """
    CREATE FUNCTION public.wso_issue_job_connection_handle(p_job uuid,p_token text,p_connection uuid) RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $wso$
    DECLARE j public.jobs%ROWTYPE; c public.job_connections%ROWTYPE; version uuid; token text;
    BEGIN
      PERFORM public.wso_begin_job_step(p_job,p_token);
      SELECT * INTO j FROM public.jobs WHERE id=p_job;
      IF j.actor_role_at_enqueue<>'OWNER' OR NOT EXISTS(SELECT 1 FROM wso_private.job_kinds WHERE kind=j.kind AND payload_version=j.payload_version AND credential_use) THEN RETURN NULL; END IF;
      SELECT * INTO c FROM public.job_connections WHERE job_id=p_job AND connection_id=p_connection;
      IF NOT FOUND THEN RETURN NULL; END IF;
      SELECT version_id INTO version FROM wso_private.connection_secrets WHERE connection_id=p_connection AND tenant_id=j.tenant_id;
      IF NOT FOUND THEN RETURN NULL; END IF;
      token:=encode(sha256(convert_to(gen_random_uuid()::text||gen_random_uuid()::text||gen_random_uuid()::text,'UTF8')),'hex');
      INSERT INTO wso_private.connection_handles VALUES(sha256(convert_to(token,'UTF8')),j.tenant_id,p_connection,j.actor_user_id,c.generation,version,clock_timestamp()+interval '30 seconds',j.id,j.lease_generation);
      RETURN token;
    END; $wso$""",
        "wso_job_worker",
        "wso_migrator",
    )
    for signature, body, grantee in _t04_functions():
        body = body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION")
        if signature.startswith("wso_issue_connection_handle"):
            body = body.replace(
                "INSERT INTO wso_private.connection_handles VALUES",
                "INSERT INTO wso_private.connection_handles(digest,tenant_id,connection_id,actor_id,generation,version_id,expires_at) VALUES",
            )
        else:
            marker = "SELECT role INTO member_role"
            authorization = """IF h.job_id IS NOT NULL THEN
              IF NOT public.wso_job_authorized(h.job_id) THEN RETURN REJECT; END IF;
            END IF;
            """.replace(
                "RETURN REJECT", "RETURN false" if "redeem" in signature else "RETURN"
            )
            body = body.replace(marker, authorization + marker)
            body = body.replace(
                "member_role text;", "member_role text; job_row public.jobs%ROWTYPE;"
            )
            # Finish metadata authorization before taking the job lock. PostgreSQL
            # can evaluate a WHERE time predicate before waiting on FOR SHARE, so
            # inspect the locked current row with a fresh clock in a later statement.
            check = """IF h.job_id IS NOT NULL THEN
              SELECT * INTO job_row FROM public.jobs j WHERE j.id=h.job_id FOR SHARE;
              IF NOT FOUND OR job_row.tenant_id IS DISTINCT FROM h.tenant_id
                OR job_row.actor_user_id IS DISTINCT FROM h.actor_id
                OR job_row.lease_generation IS DISTINCT FROM h.job_lease_generation
                OR job_row.state IS DISTINCT FROM 'RUNNING' OR job_row.lease_digest IS NULL
                OR job_row.cancel_requested_at IS NOT NULL OR job_row.lease_expires_at IS NULL
                OR job_row.lease_expires_at<=clock_timestamp()
                OR h.expires_at<=clock_timestamp() THEN RETURN REJECT; END IF;
            END IF;
            """.replace(
                "RETURN REJECT", "RETURN false" if "redeem" in signature else "RETURN"
            )
            marker = (
                "DELETE FROM wso_private.connection_handles"
                if "redeem" in signature
                else "RETURN QUERY SELECT"
            )
            body = body.replace(marker, check + marker)
            if "redeem" in signature:
                # Consuming a handle may itself wait for another redemption.
                # Never issue a lease after either deadline elapsed during that wait.
                body = body.replace(
                    "INSERT INTO wso_private.connection_leases",
                    "IF h.expires_at<=clock_timestamp() OR (h.job_id IS NOT NULL AND "
                    "job_row.lease_expires_at<=clock_timestamp()) THEN RETURN false; END IF;\n"
                    "        INSERT INTO wso_private.connection_leases",
                )
            body = body.replace(
                "h.version_id,h.expires_at);",
                "h.version_id,h.expires_at,h.job_id,h.job_lease_generation);",
            )
        fn(signature, body, grantee, "wso_migrator")


def downgrade():
    for table in [
        "wso_private.connection_revocations",
        "public.memberships",
        "public.store_memberships",
        "public.stores",
        "public.tenants",
    ]:
        op.execute(f"DROP TRIGGER jobs_revoke ON {table}")
    for table in ["job_connections", "job_items", "inbox_dedup", "outbox", "jobs"]:
        op.execute(f"DROP TABLE public.{table} CASCADE")
    for table in ["dispatch_ready", "job_contexts", "job_kinds"]:
        op.execute(f"DROP TABLE IF EXISTS wso_private.{table} CASCADE")
    for name in [
        "wso_record_job_item(uuid,text,text,text,jsonb,text)",
        "wso_validate_job_registry(jsonb)",
        "wso_job_json_safe(jsonb)",
        "wso_job_authorized(uuid)",
        "wso_job_visible(uuid,uuid,uuid,text)",
        "wso_current_job_id()",
        "wso_enqueue_job(uuid,text,uuid,text,integer,jsonb,text)",
        "wso_finish_job(uuid,text,text,jsonb)",
        "wso_revoke_job(uuid)",
        "wso_cancel_job(uuid)",
        "wso_claim_dispatch_batch(integer,text)",
        "wso_ack_dispatch(uuid,bigint,text)",
        "wso_nack_dispatch(uuid,bigint,text,text)",
        "wso_claim_job(uuid,text,uuid,uuid,text,bigint)",
        "wso_begin_job_step(uuid,text)",
        "wso_complete_job(uuid,text,jsonb,text,text)",
        "wso_heartbeat_job(uuid,text)",
        "wso_mark_job_submitted(uuid,text)",
        "wso_job_revocation_trigger()",
        "wso_revoke_tenant_jobs(uuid)",
        "wso_issue_job_connection_handle(uuid,text,uuid)",
    ]:
        op.execute(f"DROP FUNCTION IF EXISTS public.{name}")
    for table in ["connection_handles", "connection_leases"]:
        op.execute(
            f"ALTER TABLE wso_private.{table} DROP COLUMN job_id,DROP COLUMN job_lease_generation"
        )
    for signature, body, grantee in _t04_functions():
        fn(
            signature,
            body.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"),
            grantee,
            "wso_migrator",
        )
    for table in [
        "public.memberships",
        "public.tenants",
        "public.connections",
        "public.stores",
        "public.store_memberships",
        "wso_private.tenant_contexts",
    ]:
        op.execute(f"DROP POLICY {table.split('.')[1]}_job_metadata_policy ON {table}")
        op.execute(f"REVOKE ALL ON {table} FROM wso_job_owner")
    op.execute(
        "REVOKE EXECUTE ON FUNCTION public.wso_current_tenant_id() FROM wso_job_owner"
    )
    op.execute("ALTER TABLE public.tenants DROP COLUMN job_generation")
    op.execute("DROP FUNCTION public.wso_job_timing(text)")
    op.execute("DROP TABLE wso_private.job_settings")
    op.execute(
        "REVOKE USAGE ON SCHEMA wso_private FROM wso_job_owner,wso_dispatch_owner"
    )
    op.execute(
        "REVOKE USAGE ON SCHEMA public FROM wso_job_owner,wso_dispatch_owner,wso_job_worker,wso_dispatcher"
    )
