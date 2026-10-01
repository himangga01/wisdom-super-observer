"""Checked operations on the existing T05 lifecycle and T04 encrypted storage."""

from alembic import op

revision = "0008_tvt_operation_engine"
down_revision = "0007_tvt_account_sessions"
branch_labels = None
depends_on = None
OWNER = "wso_operation_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
KINDS = "'TVT_ACCOUNT_OPERATION','TVT_DEVICE_OPERATION','TYCO_OPERATION'"
TABLES = (
    "operations",
    "operation_holds",
    "operation_tickets",
    "operation_constraint_backup",
    "operation_target_observations",
)
ACCESS = (
    "wso_private.tenant_contexts",
    "public.memberships",
    "public.stores",
    "public.store_memberships",
    "public.connections",
    "public.tenants",
    "public.jobs",
    "public.outbox",
    "wso_private.dispatch_ready",
    "wso_private.job_contexts",
    "wso_private.connection_secrets",
    "wso_private.tvt_account_sessions",
    "wso_private.tvt_account_tokens",
    "wso_private.tvt_account_storage",
    *(
        "wso_private." + d + "_" + t
        for d in ("tvt", "tyco")
        for t in (
            "identities",
            "identity_grants",
            "upstream_grants",
            "capability_snapshots",
        )
    ),
    "wso_private.tvt_device_links",
    "wso_private.tvt_channels",
    "wso_private.tvt_device_store_links",
    "wso_private.tyco_panels",
)
WRAPPERS = (
    "wso_enqueue_job(uuid,text,uuid,text,integer,jsonb,text)",
    "wso_job_authorized(uuid)",
    "wso_cancel_job(uuid)",
    "wso_finish_job(uuid,text,text,jsonb)",
    "wso_issue_job_connection_handle(uuid,text,uuid)",
)


def function(signature, returns, body, grantees="", language="plpgsql"):
    op.execute(
        f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE {language} VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $op$ {body} $op$"
    )
    name = signature.split("(")[0]
    op.execute(f"""DO $$ DECLARE f regprocedure; BEGIN
      FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='{name.split(".")[0]}' AND p.proname='{name.split(".")[1]}' LOOP
        EXECUTE 'ALTER FUNCTION '||f||' OWNER TO {OWNER}';
        EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM {RUNTIME}';
        {"EXECUTE 'GRANT EXECUTE ON FUNCTION '||f||' TO " + grantees + "';" if grantees else ""}
      END LOOP; END $$""")


def patch(signature, needle, replacement):
    old = needle.replace("'", "''")
    new = replacement.replace("'", "''")
    op.execute(f"""DO $$ DECLARE source text; BEGIN
      source:=pg_get_functiondef('public.{signature}'::regprocedure);
      IF (length(source)-length(replace(source,'{old}','')))/length('{old}')<>1 THEN
        RAISE EXCEPTION 'unexpected operation foundation definition'; END IF;
      EXECUTE replace(source,'{old}','{new}'); END $$""")


def upgrade():
    op.execute(f"""DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{OWNER}') THEN
       CREATE ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      END IF; END $$;
      ALTER ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_auth_members WHERE member='{OWNER}'::regrole OR roleid='{OWNER}'::regrole)
        THEN RAISE EXCEPTION 'operation role membership forbidden'; END IF; END $$;
      GRANT USAGE ON SCHEMA public,wso_private TO {OWNER};
      CREATE TABLE wso_private.operations(
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),tenant_id uuid NOT NULL REFERENCES public.tenants(id),
        actor_id uuid NOT NULL,actor_role text NOT NULL,intent jsonb NOT NULL,payload_hash bytea NOT NULL,
        intent_key bytea NOT NULL,idempotency_key varchar(128) NOT NULL,confirmation_digest bytea NOT NULL,
        expires_at timestamptz NOT NULL,state text NOT NULL CHECK(state IN ('CONFIRMING','SUBMITTED','VERIFYING','SUCCEEDED','FAILED','UNKNOWN_OUTCOME')),
        job_id uuid UNIQUE REFERENCES public.jobs(id),facts jsonb NOT NULL,readback_reference text,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        UNIQUE(tenant_id,actor_id,idempotency_key),UNIQUE(tenant_id,id));
      CREATE TABLE wso_private.operation_holds(tenant_id uuid NOT NULL,intent_key bytea NOT NULL,operation_id uuid NOT NULL UNIQUE,
        PRIMARY KEY(tenant_id,intent_key),FOREIGN KEY(tenant_id,operation_id) REFERENCES wso_private.operations(tenant_id,id));
      CREATE TABLE wso_private.operation_tickets(digest bytea PRIMARY KEY,lease_digest bytea UNIQUE,
        operation_id uuid NOT NULL REFERENCES wso_private.operations(id),job_id uuid NOT NULL REFERENCES public.jobs(id),
        job_generation bigint NOT NULL,connection_id uuid NOT NULL,connection_generation bigint NOT NULL,version_id uuid NOT NULL,
        facts jsonb NOT NULL,expires_at timestamptz NOT NULL);
      CREATE TABLE wso_private.operation_target_observations(
        tenant_id uuid NOT NULL REFERENCES public.tenants(id),intent_key bytea NOT NULL,
        connection_generation bigint NOT NULL CHECK(connection_generation>0),revision bigint NOT NULL CHECK(revision>0),
        upstream_verified boolean NOT NULL DEFAULT false,capability_verified boolean NOT NULL DEFAULT false,
        observed_at timestamptz NOT NULL,expires_at timestamptz NOT NULL CHECK(expires_at>observed_at),
        PRIMARY KEY(tenant_id,intent_key));
      CREATE TABLE wso_private.operation_constraint_backup(table_name text NOT NULL,constraint_name text NOT NULL,definition text NOT NULL,
        PRIMARY KEY(table_name,constraint_name));
    """)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} OWNER TO {OWNER}; ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY; REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
          GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY operation_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY operation_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);""")
    for table in ACCESS:
        permissions = "SELECT"
        if table in ("public.jobs", "public.outbox", "wso_private.dispatch_ready"):
            permissions = "SELECT,INSERT,UPDATE"
        op.execute(
            f"GRANT {permissions} ON {table} TO {OWNER}; CREATE POLICY operation_access ON {table} TO {OWNER} USING(true) WITH CHECK(true)"
        )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.wso_begin_job_step(uuid,text),public.wso_complete_job(uuid,text,jsonb,text,text),public.wso_cancel_job(uuid) TO {OWNER}"
    )
    for signature in WRAPPERS:
        name = signature.split("(")[0]
        op.execute(f"""DO $$ DECLARE source text; BEGIN source:=pg_get_functiondef('public.{signature}'::regprocedure);
          EXECUTE replace(source,'public.{name}(', 'wso_private.operation_original_{name}('); END $$;
          ALTER FUNCTION wso_private.operation_original_{signature} OWNER TO wso_migrator;
          REVOKE ALL ON FUNCTION wso_private.operation_original_{signature} FROM {RUNTIME};""")
    _write_constraints()
    function("wso_private.wso_operation_canonical(p jsonb)", "jsonb", CANONICAL, OWNER)
    function(
        "wso_private.wso_operation_facts(t uuid,a uuid,r text,p jsonb)",
        "jsonb",
        FACTS,
        OWNER,
    )
    function(
        "public.wso_operation_job_authorized(p_job uuid)",
        "boolean",
        JOB_AUTH,
        "wso_job_owner,wso_migrator",
    )
    function("public.wso_operation_visible(p_job uuid)", "boolean", VISIBLE, "wso_app")
    function(
        "public.wso_operation_prepare(p_intent jsonb,p_key text)",
        "TABLE(operation_id uuid,state text,expires_at timestamptz,confirmation text,job_id uuid)",
        PREPARE,
        "wso_app",
    )
    function(
        "public.wso_operation_get(p_id uuid)",
        "TABLE(operation_id uuid,state text,expires_at timestamptz,job_id uuid)",
        GET,
        "wso_app",
    )
    function(
        "public.wso_operation_submit(p_id uuid,p_confirmation text,p_intent jsonb,p_key text)",
        "TABLE(operation_id uuid,state text,expires_at timestamptz,job_id uuid)",
        SUBMIT,
        "wso_app",
    )
    function("public.wso_operation_cancel(p_id uuid)", "boolean", CANCEL, "wso_app")
    function(
        "public.wso_operation_reconcile(p_id uuid)", "boolean", RECONCILE, "wso_app"
    )
    function(
        "public.wso_operation_finish(p_job uuid)", "boolean", FINISH, "wso_job_owner"
    )
    function(
        "public.wso_operation_terminal(p_job uuid)",
        "boolean",
        "SELECT EXISTS(SELECT 1 FROM wso_private.operations WHERE job_id=p_job AND state IN ('SUCCEEDED','FAILED'))",
        "wso_job_owner",
        "sql",
    )
    function(
        "public.wso_operation_readback(p_job uuid,p_token text,p_generation bigint,p_outcome text,p_reference text)",
        "boolean",
        READBACK,
        "wso_job_worker",
    )
    _credentials()
    op.execute("""INSERT INTO wso_private.job_kinds VALUES
      ('TVT_ACCOUNT_OPERATION',1,'TENANT','STAFF','wso.default','EXTERNAL_WRITE',1,true),
      ('TVT_DEVICE_OPERATION',1,'STORE','STAFF','wso.default','EXTERNAL_WRITE',1,true),
      ('TYCO_OPERATION',1,'TENANT','STAFF','wso.default','EXTERNAL_WRITE',1,true);
      CREATE POLICY operation_job_visibility ON public.jobs AS RESTRICTIVE FOR SELECT TO wso_app USING(public.wso_operation_visible(id));""")
    patch(
        WRAPPERS[0],
        "BEGIN",
        f"BEGIN IF p_kind IN ({KINDS}) THEN RAISE EXCEPTION 'checked operation submission required' USING ERRCODE='42501'; END IF;",
    )
    patch(
        WRAPPERS[1],
        "RETURN EXISTS(SELECT 1 FROM wso_private.job_kinds",
        f"IF j.kind IN ({KINDS}) AND NOT public.wso_operation_job_authorized(p_id) THEN RETURN false; END IF; RETURN EXISTS(SELECT 1 FROM wso_private.job_kinds",
    )
    patch(
        WRAPPERS[2],
        "PERFORM public.wso_job_authorized(p_id);",
        "IF NOT public.wso_job_authorized(p_id) THEN RAISE EXCEPTION 'job denied' USING ERRCODE='42501'; END IF; IF NOT public.wso_operation_visible(p_id) THEN RAISE EXCEPTION 'job denied' USING ERRCODE='42501'; END IF;",
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION public.wso_operation_visible(uuid) TO wso_job_owner"
    )
    patch(
        WRAPPERS[3],
        "BEGIN",
        "BEGIN IF public.wso_operation_finish(p_id) THEN p_state:='NEEDS_USER_INPUT'; p_code:='UNKNOWN_REMOTE_STATE'; p_result:=NULL; END IF;",
    )
    patch(
        WRAPPERS[3],
        "IF p_state IN ('FAILED','CANCELLED') AND EXISTS",
        "IF p_state IN ('FAILED','CANCELLED') AND NOT public.wso_operation_terminal(p_id) AND EXISTS",
    )
    patch(
        WRAPPERS[4],
        "BEGIN",
        f"BEGIN IF EXISTS(SELECT 1 FROM public.jobs WHERE id=p_job AND kind IN ({KINDS})) THEN RETURN NULL; END IF;",
    )


def _write_constraints():
    for domain in ("tvt", "tyco"):
        for table in ("identity_grants", "upstream_grants", "capability_snapshots"):
            full = f"wso_private.{domain}_{table}"
            actions = (
                "'account.delete','account.purchase','device.delete','device.firmware','device.purchase'"
                if domain == "tvt"
                else "'account.delete','panel.delete','panel.unlock','panel.relay','panel.arm','panel.disarm'"
            )
            op.execute(f"""DO $$ DECLARE c record; BEGIN
              FOR c IN SELECT conname,pg_get_constraintdef(oid) AS def FROM pg_constraint
                WHERE conrelid='{full}'::regclass AND contype='c' AND pg_get_constraintdef(oid) LIKE '%action%' LOOP
                INSERT INTO wso_private.operation_constraint_backup VALUES('{full}',c.conname,c.def);
                EXECUTE format('ALTER TABLE {full} DROP CONSTRAINT %I',c.conname);
                EXECUTE format('ALTER TABLE {full} ADD CONSTRAINT %I CHECK ((%s) OR action IN ({actions.replace(chr(39), chr(39) * 2)}))',c.conname,substring(c.def from 8 for length(c.def)-8));
              END LOOP; END $$""")


CANONICAL = """
DECLARE k text; d text; keys text[]; q jsonb; act text; parts jsonb;
BEGIN
 IF p IS NULL OR jsonb_typeof(p)<>'object' OR octet_length(p::text)>8192 THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
 p:=jsonb_strip_nulls(p); k:=p->>'kind'; d:=p->>'domain';
 IF d IS NULL OR d NOT IN ('TVT','TYCO') OR p->>'identity_id' IS NULL THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
 FOR q IN SELECT jsonb_build_object('key',key,'value',value) FROM jsonb_each(p) LOOP
   IF q->>'key' LIKE '%_id' THEN p:=jsonb_set(p,ARRAY[q->>'key'],to_jsonb((q->>'value')::uuid::text)); END IF;
 END LOOP;
 IF k='payment' AND d='TVT' THEN
   keys:=ARRAY['kind','domain','identity_id','product','term','quoted_price_version','device_id','channel_id','store_id'];
   act:=CASE WHEN p ? 'device_id' THEN 'device.purchase' ELSE 'account.purchase' END;
   IF NOT p ?& ARRAY['product','term','quoted_price_version'] OR (p ? 'device_id')<>(p ? 'store_id') OR (p ? 'channel_id' AND NOT p ? 'device_id') THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
   parts:=jsonb_build_array(k,p->'identity_id',p->'product',p->'device_id',p->'channel_id',p->'term',p->'quoted_price_version');
 ELSIF k='firmware' AND d='TVT' THEN
   keys:=ARRAY['kind','domain','identity_id','device_id','store_id','target_version']; act:='device.firmware';
   IF NOT p ?& ARRAY['device_id','store_id','target_version'] THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
   parts:=jsonb_build_array(k,p->'identity_id',p->'device_id',p->'target_version');
 ELSIF k='tyco' AND d='TYCO' THEN
   keys:=ARRAY['kind','domain','identity_id','panel_id','action','target','requested_state']; act:='panel.'||(p->>'action');
   IF NOT p ?& ARRAY['panel_id','action','target','requested_state'] OR p->>'action' NOT IN ('unlock','relay','arm','disarm') THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
   parts:=jsonb_build_array(k,p->'identity_id',p->'panel_id',p->'action',p->'target',p->'requested_state');
 ELSIF k='delete' THEN
   keys:=ARRAY['kind','domain','identity_id','target_kind','target_id','device_id','store_id','panel_id']; act:=(p->>'target_kind')||'.delete';
   IF NOT p ?& ARRAY['target_kind','target_id'] OR (
     (p->>'target_kind'='account' AND p->>'target_id'=p->>'identity_id' AND NOT p ?| ARRAY['device_id','store_id','panel_id']) OR
     (d='TVT' AND p->>'target_kind'='device' AND p->>'target_id'=p->>'device_id' AND p ? 'store_id' AND NOT p ? 'panel_id') OR
     (d='TYCO' AND p->>'target_kind'='panel' AND p->>'target_id'=p->>'panel_id' AND NOT p ?| ARRAY['device_id','store_id'])) IS NOT TRUE THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
   parts:=jsonb_build_array(k,d,p->'identity_id',p->'target_kind',p->'target_id');
 ELSE RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
 IF p-keys<>'{}'::jsonb THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
 FOR q IN SELECT jsonb_build_object('key',key,'value',value) FROM jsonb_each(p) LOOP
   IF jsonb_typeof(q->'value')<>'string' OR q->>'value' !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN RAISE EXCEPTION 'invalid intent' USING ERRCODE='22023'; END IF;
   IF q->>'key' LIKE '%_id' THEN PERFORM (q->>'value')::uuid; END IF;
 END LOOP;
 RETURN jsonb_build_object('intent',p,'action',act,'key',encode(sha256(convert_to(parts::text,'UTF8')),'hex'));
END;
"""

FACTS = """
DECLARE f record; observation record; act text; ident uuid; dev uuid; ch uuid; st uuid; panel uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR NOT EXISTS(SELECT 1 FROM public.memberships WHERE tenant_id=t AND user_id=a AND role=r) THEN RETURN NULL; END IF;
 act:=wso_private.wso_operation_canonical(p)->>'action'; ident:=(p->>'identity_id')::uuid; dev:=(p->>'device_id')::uuid;
 ch:=(p->>'channel_id')::uuid; st:=(p->>'store_id')::uuid; panel:=(p->>'panel_id')::uuid;
 IF p->>'domain'='TVT' THEN
 SELECT i.connection_id,c.generation,g.id AS grant_id,g.revision AS gr,u.revision AS ur,v.revision AS vr,coalesce(l.revision,0) AS lr,
   least(g.expires_at,u.expires_at,v.expires_at) AS expiry INTO f
 FROM wso_private.tvt_identities i JOIN public.connections c ON c.tenant_id=i.tenant_id AND c.id=i.connection_id AND c.kind='TVT_ACCOUNT' AND c.status='NOT_VERIFIED'
 JOIN wso_private.tvt_identity_grants g ON g.tenant_id=i.tenant_id AND g.identity_id=i.id AND g.actor_id=a AND g.action=act
 LEFT JOIN wso_private.tvt_device_store_links l ON l.tenant_id=g.tenant_id AND l.identity_id=g.identity_id AND l.id=g.link_id
 JOIN wso_private.tvt_upstream_grants u ON u.tenant_id=i.tenant_id AND u.identity_id=i.id AND u.action=act AND u.device_id IS NOT DISTINCT FROM dev AND u.channel_id IS NOT DISTINCT FROM ch
 JOIN wso_private.tvt_capability_snapshots v ON v.tenant_id=i.tenant_id AND v.identity_id=i.id AND v.action=act AND v.device_id IS NOT DISTINCT FROM dev AND v.channel_id IS NOT DISTINCT FROM ch
 WHERE i.tenant_id=t AND i.id=ident AND i.active AND u.verified AND v.verified AND u.connection_generation=c.generation AND v.connection_generation=c.generation
   AND u.observed_at<=clock_timestamp() AND v.observed_at<=clock_timestamp() AND least(g.expires_at,u.expires_at,v.expires_at)>clock_timestamp()
   AND ((dev IS NULL AND g.link_id IS NULL) OR (dev IS NOT NULL AND l.active AND l.device_id=dev AND l.channel_id IS NOT DISTINCT FROM ch AND l.store_id=st
     AND EXISTS(SELECT 1 FROM public.stores s JOIN public.store_memberships sm ON sm.tenant_id=s.tenant_id AND sm.store_id=s.id WHERE s.tenant_id=t AND s.id=st AND s.active AND sm.user_id=a)
     AND EXISTS(SELECT 1 FROM wso_private.tvt_device_links x WHERE x.tenant_id=t AND x.identity_id=ident AND x.id=dev AND x.active)
     AND (ch IS NULL OR EXISTS(SELECT 1 FROM wso_private.tvt_channels x WHERE x.tenant_id=t AND x.identity_id=ident AND x.device_id=dev AND x.id=ch AND x.active))))
   AND (NOT EXISTS(SELECT 1 FROM wso_private.tvt_account_storage storage WHERE storage.connection_id=i.connection_id) OR EXISTS(
     SELECT 1 FROM wso_private.tvt_account_sessions s
     JOIN wso_private.tvt_account_tokens tok ON tok.identity_id=s.identity_id AND tok.tenant_id=s.tenant_id
     JOIN wso_private.connection_secrets secret ON secret.connection_id=tok.connection_id AND secret.tenant_id=tok.tenant_id AND secret.version_id=tok.version_id
     WHERE s.identity_id=i.id AND s.tenant_id=t AND s.actor_id=a AND s.state='READY'
       AND tok.connection_id=i.connection_id AND tok.kind='USER' AND tok.generation=c.generation AND tok.renewal_state='IDLE'));
 ELSE
 SELECT i.connection_id,c.generation,g.id AS grant_id,g.revision AS gr,u.revision AS ur,v.revision AS vr,0 AS lr,
   least(g.expires_at,u.expires_at,v.expires_at) AS expiry INTO f
 FROM wso_private.tyco_identities i JOIN public.connections c ON c.tenant_id=i.tenant_id AND c.id=i.connection_id AND c.kind='TYCO_ACCOUNT' AND c.status='NOT_VERIFIED'
 JOIN wso_private.tyco_identity_grants g ON g.tenant_id=i.tenant_id AND g.identity_id=i.id AND g.actor_id=a AND g.action=act AND g.panel_id IS NOT DISTINCT FROM panel
 JOIN wso_private.tyco_upstream_grants u ON u.tenant_id=i.tenant_id AND u.identity_id=i.id AND u.action=act AND u.panel_id IS NOT DISTINCT FROM panel
 JOIN wso_private.tyco_capability_snapshots v ON v.tenant_id=i.tenant_id AND v.identity_id=i.id AND v.action=act AND v.panel_id IS NOT DISTINCT FROM panel
 WHERE i.tenant_id=t AND i.id=ident AND i.active AND u.verified AND v.verified AND u.connection_generation=c.generation AND v.connection_generation=c.generation
   AND u.observed_at<=clock_timestamp() AND v.observed_at<=clock_timestamp() AND least(g.expires_at,u.expires_at,v.expires_at)>clock_timestamp()
   AND (panel IS NULL OR EXISTS(SELECT 1 FROM wso_private.tyco_panels x WHERE x.tenant_id=t AND x.identity_id=ident AND x.id=panel AND x.active));
 END IF;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO observation FROM wso_private.operation_target_observations x WHERE x.tenant_id=t
   AND x.intent_key=decode(wso_private.wso_operation_canonical(p)->>'key','hex')
   AND x.connection_generation=f.generation AND x.upstream_verified AND x.capability_verified
   AND x.observed_at<=clock_timestamp() AND x.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN to_jsonb(f)||jsonb_build_object('target_revision',observation.revision,'target_expires_at',observation.expires_at);
END;
"""

JOB_AUTH = """
DECLARE o wso_private.operations%ROWTYPE; j public.jobs%ROWTYPE;
BEGIN SELECT * INTO j FROM public.jobs WHERE id=p_job;
 SELECT * INTO o FROM wso_private.operations WHERE job_id=p_job;
 RETURN coalesce(FOUND AND j.tenant_id=o.tenant_id AND j.actor_user_id=o.actor_id AND j.actor_role_at_enqueue=o.actor_role
   AND o.state IN ('SUBMITTED','VERIFYING','UNKNOWN_OUTCOME')
   AND j.payload=jsonb_build_object('schema_version',1,'operation_id',o.id)
   AND j.kind=CASE WHEN o.intent->>'domain'='TYCO' THEN 'TYCO_OPERATION' WHEN o.intent ? 'device_id' THEN 'TVT_DEVICE_OPERATION' ELSE 'TVT_ACCOUNT_OPERATION' END
   AND j.store_id IS NOT DISTINCT FROM (o.intent->>'store_id')::uuid
   AND wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent)=o.facts,false);
END;
"""
VISIBLE = """
DECLARE o wso_private.operations%ROWTYPE; c wso_private.tenant_contexts%ROWTYPE; k text;
BEGIN SELECT kind INTO k FROM public.jobs WHERE id=p_job;
 IF k NOT IN ('TVT_ACCOUNT_OPERATION','TVT_DEVICE_OPERATION','TYCO_OPERATION') THEN RETURN true; END IF;
 SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
 SELECT * INTO o FROM wso_private.operations WHERE job_id=p_job AND tenant_id=c.tenant_id AND actor_id=c.user_id;
 RETURN coalesce(FOUND AND wso_private.wso_operation_facts(o.tenant_id,c.user_id,c.role,o.intent) IS NOT NULL,false);
END;
"""
PREPARE = """
DECLARE c wso_private.tenant_contexts%ROWTYPE; v jsonb; f jsonb; o wso_private.operations%ROWTYPE; existing wso_private.operations%ROWTYPE; token text; hash bytea; hold bytea;
BEGIN
 SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
 IF NOT FOUND THEN RAISE EXCEPTION 'operation denied' USING ERRCODE='42501'; END IF;
 v:=wso_private.wso_operation_canonical(p_intent); p_intent:=v->'intent';
 f:=wso_private.wso_operation_facts(c.tenant_id,c.user_id,c.role,p_intent);
 IF f IS NULL THEN RAISE EXCEPTION 'operation denied' USING ERRCODE='42501'; END IF;
 IF p_key IS NULL OR p_key !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN RAISE EXCEPTION 'invalid key' USING ERRCODE='22023'; END IF;
 hash:=sha256(convert_to(p_intent::text,'UTF8')); hold:=decode(v->>'key','hex');
 PERFORM pg_advisory_xact_lock(hashtextextended(c.tenant_id::text||c.user_id::text||p_key,0));
 SELECT * INTO existing FROM wso_private.operations WHERE tenant_id=c.tenant_id AND actor_id=c.user_id AND idempotency_key=p_key;
 IF FOUND THEN
   IF existing.payload_hash<>hash THEN RAISE EXCEPTION 'idempotency conflict' USING ERRCODE='40001'; END IF;
   PERFORM public.wso_operation_get(existing.id);
   SELECT * INTO existing FROM wso_private.operations WHERE id=existing.id;
   RETURN QUERY SELECT existing.id,existing.state,existing.expires_at,NULL::text,existing.job_id; RETURN;
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(c.tenant_id::text||encode(hold,'hex'),0));
 SELECT x.* INTO existing FROM wso_private.operations x JOIN wso_private.operation_holds h ON h.operation_id=x.id WHERE h.tenant_id=c.tenant_id AND h.intent_key=hold FOR UPDATE OF x;
 IF FOUND THEN
   IF existing.state='CONFIRMING' AND existing.job_id IS NULL AND existing.expires_at<=clock_timestamp() THEN
     UPDATE wso_private.operations SET state='FAILED',updated_at=clock_timestamp() WHERE id=existing.id;
     DELETE FROM wso_private.operation_holds h WHERE h.operation_id=existing.id;
   ELSE RAISE EXCEPTION 'business intent held' USING ERRCODE='40001'; END IF;
 END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 INSERT INTO wso_private.operations(tenant_id,actor_id,actor_role,intent,payload_hash,intent_key,idempotency_key,confirmation_digest,expires_at,state,facts)
 VALUES(c.tenant_id,c.user_id,c.role,p_intent,hash,hold,p_key,sha256(convert_to(token,'UTF8')),clock_timestamp()+interval '5 minutes','CONFIRMING',f) RETURNING * INTO o;
 INSERT INTO wso_private.operation_holds VALUES(c.tenant_id,hold,o.id);
 RETURN QUERY SELECT o.id,o.state,o.expires_at,token,o.job_id;
END;
"""
GET = """
DECLARE o wso_private.operations%ROWTYPE; c wso_private.tenant_contexts%ROWTYPE;
BEGIN SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
 SELECT * INTO o FROM wso_private.operations WHERE id=p_id AND tenant_id=c.tenant_id AND actor_id=c.user_id FOR UPDATE;
 IF NOT FOUND OR wso_private.wso_operation_facts(o.tenant_id,c.user_id,c.role,o.intent) IS NULL THEN RAISE EXCEPTION 'operation missing' USING ERRCODE='P0002'; END IF;
 IF o.state='CONFIRMING' AND o.job_id IS NULL AND o.expires_at<=clock_timestamp() THEN
   UPDATE wso_private.operations x SET state='FAILED',updated_at=clock_timestamp() WHERE x.id=o.id AND x.state='CONFIRMING' AND x.job_id IS NULL RETURNING * INTO o;
   IF FOUND THEN DELETE FROM wso_private.operation_holds h WHERE h.operation_id=o.id; END IF;
 END IF;
 RETURN QUERY SELECT o.id,o.state,o.expires_at,o.job_id;
END;
"""
SUBMIT = """
DECLARE o wso_private.operations%ROWTYPE; c wso_private.tenant_contexts%ROWTYPE; f jsonb; jid uuid; oid uuid; kind text; scope text;
BEGIN
 PERFORM public.wso_operation_get(p_id);
 SELECT * INTO c FROM wso_private.tenant_contexts WHERE backend_pid=pg_backend_pid() AND transaction_id=txid_current();
 SELECT * INTO o FROM wso_private.operations WHERE id=p_id FOR UPDATE;
 IF o.idempotency_key IS DISTINCT FROM p_key OR o.intent IS DISTINCT FROM (wso_private.wso_operation_canonical(p_intent)->'intent')
 OR o.confirmation_digest IS DISTINCT FROM sha256(convert_to(p_confirmation,'UTF8')) THEN RAISE EXCEPTION 'operation conflict' USING ERRCODE='40001'; END IF;
 IF o.job_id IS NOT NULL THEN RETURN QUERY SELECT o.id,o.state,o.expires_at,o.job_id; RETURN; END IF;
 f:=wso_private.wso_operation_facts(o.tenant_id,c.user_id,c.role,o.intent);
 IF o.state<>'CONFIRMING' OR o.actor_role<>c.role OR o.expires_at<=clock_timestamp() OR f IS NULL OR f<>o.facts THEN RAISE EXCEPTION 'confirmation unavailable' USING ERRCODE='42501'; END IF;
 kind:=CASE WHEN o.intent->>'domain'='TYCO' THEN 'TYCO_OPERATION' WHEN o.intent ? 'device_id' THEN 'TVT_DEVICE_OPERATION' ELSE 'TVT_ACCOUNT_OPERATION' END;
 scope:=CASE WHEN kind='TVT_DEVICE_OPERATION' THEN 'STORE' ELSE 'TENANT' END;
 INSERT INTO public.jobs(tenant_id,scope_kind,store_id,actor_user_id,actor_role_at_enqueue,tenant_generation,kind,payload_version,payload,payload_hash,idempotency_key,operation_target,max_attempts)
 SELECT o.tenant_id,scope,(o.intent->>'store_id')::uuid,o.actor_id,c.role,t.job_generation,kind,1,jsonb_build_object('schema_version',1,'operation_id',o.id),o.payload_hash,o.id::text,'operation:'||o.id,1
 FROM public.tenants t WHERE t.id=o.tenant_id RETURNING id INTO jid;
 INSERT INTO public.outbox(tenant_id,job_id) VALUES(o.tenant_id,jid) RETURNING id INTO oid;
 INSERT INTO wso_private.dispatch_ready(outbox_id,job_id,tenant_id,kind,queue) VALUES(oid,jid,o.tenant_id,kind,'wso.default');
 UPDATE wso_private.operations SET state='SUBMITTED',job_id=jid,updated_at=clock_timestamp() WHERE id=o.id;
 RETURN QUERY SELECT o.id,'SUBMITTED'::text,o.expires_at,jid;
END;
"""
CANCEL = """
DECLARE o wso_private.operations%ROWTYPE;
BEGIN PERFORM public.wso_operation_get(p_id);
 SELECT * INTO o FROM wso_private.operations WHERE id=p_id FOR UPDATE;
 IF o.state='CONFIRMING' AND o.job_id IS NULL THEN
   UPDATE wso_private.operations SET state='FAILED',updated_at=clock_timestamp() WHERE id=o.id;
   DELETE FROM wso_private.operation_holds WHERE operation_id=o.id;
 ELSIF o.job_id IS NOT NULL AND o.state NOT IN ('SUCCEEDED','FAILED') THEN
   PERFORM public.wso_cancel_job(o.job_id);
 END IF; RETURN true;
END;
"""
FINISH = """
BEGIN
 UPDATE wso_private.operations SET state='UNKNOWN_OUTCOME',updated_at=clock_timestamp()
 WHERE job_id=p_job AND state NOT IN ('SUCCEEDED','FAILED'); RETURN FOUND;
END;
"""
RECONCILE = """
DECLARE o wso_private.operations%ROWTYPE;
BEGIN PERFORM public.wso_operation_get(p_id);
 SELECT * INTO o FROM wso_private.operations WHERE id=p_id FOR UPDATE;
 IF o.state<>'UNKNOWN_OUTCOME' OR wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent) IS NULL THEN RAISE EXCEPTION 'reconciliation denied' USING ERRCODE='42501'; END IF;
 UPDATE public.jobs SET state='QUEUED',attempts=0,lease_generation=lease_generation+1,lease_digest=NULL,lease_expires_at=NULL,cancel_requested_at=NULL,
   completed_at=NULL,failure_code=NULL,next_attempt_at=clock_timestamp(),submitted_at=coalesce(submitted_at,clock_timestamp()) WHERE id=o.job_id;
 UPDATE public.outbox SET completed_at=NULL WHERE job_id=o.job_id;
 UPDATE wso_private.dispatch_ready SET state='READY',due_at=clock_timestamp(),dispatch_owner=NULL,dispatch_lease_expires_at=NULL WHERE job_id=o.job_id;
 UPDATE wso_private.operations SET state='VERIFYING',facts=wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent),updated_at=clock_timestamp() WHERE id=o.id; RETURN true;
END;
"""
READBACK = """
DECLARE o wso_private.operations%ROWTYPE;
BEGIN
 PERFORM public.wso_begin_job_step(p_job,p_token);
 IF p_outcome IS NULL OR p_outcome NOT IN ('SUCCEEDED','FAILED') OR p_reference IS NULL OR p_reference !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
 OR NOT EXISTS(SELECT 1 FROM public.jobs WHERE id=p_job AND lease_generation=p_generation) THEN RAISE EXCEPTION 'readback denied' USING ERRCODE='42501'; END IF;
 SELECT * INTO o FROM wso_private.operations WHERE job_id=p_job FOR UPDATE;
 IF NOT FOUND OR o.state NOT IN ('SUBMITTED','VERIFYING','UNKNOWN_OUTCOME') OR wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent) IS DISTINCT FROM o.facts THEN RAISE EXCEPTION 'readback denied' USING ERRCODE='42501'; END IF;
 UPDATE wso_private.operations SET state=p_outcome,readback_reference=p_reference,updated_at=clock_timestamp() WHERE id=o.id;
 DELETE FROM wso_private.operation_holds WHERE operation_id=o.id;
 PERFORM public.wso_complete_job(p_job,p_token,'{}'::jsonb,p_outcome,CASE WHEN p_outcome='FAILED' THEN 'UPSTREAM_REJECTED' ELSE NULL END); RETURN true;
END;
"""


def _credentials():
    op.execute(f"GRANT EXECUTE ON FUNCTION public.wso_revoke_job(uuid) TO {OWNER}")
    function(
        "public.wso_operation_uncertain(p_lease text)",
        "boolean",
        """
      DECLARE t wso_private.operation_tickets%ROWTYPE; j public.jobs%ROWTYPE;
      BEGIN
        SELECT * INTO t FROM wso_private.operation_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8'));
        IF NOT FOUND THEN RETURN false; END IF;
        SELECT * INTO j FROM public.jobs WHERE id=t.job_id FOR UPDATE;
        IF j.lease_generation IS DISTINCT FROM t.job_generation OR j.state NOT IN ('QUEUED','RUNNING') THEN RETURN false; END IF;
        PERFORM public.wso_revoke_job(j.id); RETURN true;
      END;
    """,
        "wso_connection_worker",
    )
    function(
        "public.wso_operation_ticket(p_job uuid,p_token text,p_generation bigint)",
        "text",
        TICKET,
        "wso_job_worker",
    )
    function(
        "wso_private.wso_operation_ticket_valid(t wso_private.operation_tickets)",
        "boolean",
        TICKET_VALID,
        OWNER,
    )
    function(
        "public.wso_operation_redeem(p_ticket text,p_lease text)",
        "boolean",
        REDEEM,
        "wso_connection_worker",
    )
    function(
        "public.wso_operation_secret(p_lease text)",
        "TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea)",
        SECRET,
        "wso_connection_worker",
    )
    function(
        "public.wso_operation_credential_check(p_lease text)",
        "boolean",
        "SELECT coalesce((SELECT wso_private.wso_operation_ticket_valid(t) FROM wso_private.operation_tickets t WHERE lease_digest=sha256(convert_to(p_lease,'UTF8'))),false)",
        "wso_connection_worker",
        "sql",
    )


TICKET = """
DECLARE o wso_private.operations%ROWTYPE; c public.connections%ROWTYPE; ver uuid; token text;
BEGIN
 PERFORM public.wso_begin_job_step(p_job,p_token);
 IF NOT EXISTS(SELECT 1 FROM public.jobs WHERE id=p_job AND lease_generation=p_generation) THEN RETURN NULL; END IF;
 SELECT * INTO o FROM wso_private.operations WHERE job_id=p_job;
 IF NOT FOUND OR o.facts IS DISTINCT FROM wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent) THEN RETURN NULL; END IF;
 SELECT * INTO c FROM public.connections WHERE id=(o.facts->>'connection_id')::uuid AND tenant_id=o.tenant_id AND status='NOT_VERIFIED';
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT s.version_id INTO ver FROM wso_private.connection_secrets s WHERE s.connection_id=c.id AND s.tenant_id=c.tenant_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_account_storage WHERE connection_id=c.id) AND NOT EXISTS(
   SELECT 1 FROM wso_private.tvt_account_tokens t JOIN wso_private.tvt_account_sessions s ON s.identity_id=t.identity_id AND s.tenant_id=t.tenant_id
   WHERE t.connection_id=c.id AND t.kind='USER' AND t.version_id=ver AND t.generation=c.generation AND t.renewal_state='IDLE' AND s.actor_id=o.actor_id AND s.state='READY' AND t.identity_id=(o.intent->>'identity_id')::uuid) THEN RETURN NULL; END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 INSERT INTO wso_private.operation_tickets(digest,operation_id,job_id,job_generation,connection_id,connection_generation,version_id,facts,expires_at)
 VALUES(sha256(convert_to(token,'UTF8')),o.id,p_job,p_generation,c.id,c.generation,ver,o.facts,least((o.facts->>'expiry')::timestamptz,clock_timestamp()+interval '20 seconds'));
 RETURN token;
END;
"""
TICKET_VALID = """
DECLARE o wso_private.operations%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR t.expires_at<=clock_timestamp() THEN RETURN false; END IF;
 SELECT * INTO o FROM wso_private.operations WHERE id=t.operation_id AND job_id=t.job_id;
 RETURN coalesce(FOUND AND o.state IN ('SUBMITTED','VERIFYING','UNKNOWN_OUTCOME') AND o.facts=t.facts
 AND wso_private.wso_operation_facts(o.tenant_id,o.actor_id,o.actor_role,o.intent)=t.facts
 AND EXISTS(SELECT 1 FROM public.jobs j JOIN public.tenants tenant ON tenant.id=j.tenant_id AND tenant.job_generation=j.tenant_generation
   WHERE j.id=t.job_id AND j.tenant_id=o.tenant_id AND j.actor_user_id=o.actor_id AND j.state='RUNNING' AND j.lease_generation=t.job_generation
   AND j.cancel_requested_at IS NULL AND j.lease_expires_at>clock_timestamp())
 AND EXISTS(SELECT 1 FROM public.connections c JOIN wso_private.connection_secrets s ON s.connection_id=c.id AND s.tenant_id=c.tenant_id
   WHERE c.id=t.connection_id AND c.tenant_id=o.tenant_id AND c.status='NOT_VERIFIED' AND c.generation=t.connection_generation AND s.version_id=t.version_id)
 AND (NOT EXISTS(SELECT 1 FROM wso_private.tvt_account_storage WHERE connection_id=t.connection_id) OR EXISTS(
   SELECT 1 FROM wso_private.tvt_account_tokens tok JOIN wso_private.tvt_account_sessions s ON s.identity_id=tok.identity_id AND s.tenant_id=tok.tenant_id
   WHERE tok.connection_id=t.connection_id AND tok.kind='USER' AND tok.version_id=t.version_id AND tok.generation=t.connection_generation AND tok.renewal_state='IDLE' AND s.actor_id=o.actor_id AND s.state='READY'
   AND tok.identity_id=(o.intent->>'identity_id')::uuid)),false);
END;
"""
REDEEM = """
DECLARE t wso_private.operation_tickets%ROWTYPE;
BEGIN
 IF p_ticket IS NULL OR p_lease IS NULL OR p_lease !~ '^[0-9a-f]{64}$' THEN RETURN false; END IF;
 SELECT * INTO t FROM wso_private.operation_tickets WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND lease_digest IS NULL FOR UPDATE;
 IF NOT FOUND OR NOT wso_private.wso_operation_ticket_valid(t) THEN RETURN false; END IF;
 UPDATE wso_private.operation_tickets SET lease_digest=sha256(convert_to(p_lease,'UTF8')) WHERE digest=t.digest; RETURN true;
END;
"""
SECRET = """
DECLARE t wso_private.operation_tickets%ROWTYPE;
BEGIN
 SELECT * INTO t FROM wso_private.operation_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8'));
 IF NOT FOUND OR NOT wso_private.wso_operation_ticket_valid(t) THEN RETURN; END IF;
 RETURN QUERY SELECT s.tenant_id,s.connection_id,s.version_id,s.nonce,s.ciphertext FROM wso_private.connection_secrets s WHERE s.connection_id=t.connection_id AND s.version_id=t.version_id;
END;
"""


def downgrade():
    # Restore only this revision's exact installed preimages; no CASCADE.
    op.execute("DROP POLICY operation_job_visibility ON public.jobs")
    for signature in WRAPPERS:
        name = signature.split("(")[0]
        op.execute(f"""DO $$ DECLARE source text; BEGIN source:=pg_get_functiondef('wso_private.operation_original_{signature}'::regprocedure);
          EXECUTE replace(source,'wso_private.operation_original_{name}(', 'public.{name}('); END $$;
          DROP FUNCTION wso_private.operation_original_{signature};""")
    op.execute(f"DELETE FROM wso_private.job_kinds WHERE kind IN ({KINDS})")
    op.execute(f"""DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
      JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','wso_private') AND p.proowner='{OWNER}'::regrole
      LOOP EXECUTE 'DROP FUNCTION '||f; END LOOP; END $$""")
    op.execute("""DO $$ DECLARE c record; BEGIN
      FOR c IN SELECT * FROM wso_private.operation_constraint_backup LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I',c.table_name,c.constraint_name);
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s',c.table_name,c.constraint_name,c.definition);
      END LOOP; END $$""")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE wso_private.{table}")
    for table in ACCESS:
        op.execute(
            f"DROP POLICY operation_access ON {table}; REVOKE ALL ON {table} FROM {OWNER}"
        )
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION public.wso_begin_job_step(uuid,text),public.wso_complete_job(uuid,text,jsonb,text,text),public.wso_cancel_job(uuid),public.wso_revoke_job(uuid) FROM {OWNER}"
    )
