"""Exact readonly directory authority; W05 tickets remain unchanged."""

from alembic import op

revision = "0011_tvt_directory_read_tickets"
down_revision = "0010_tvt_account_flows"
branch_labels = None
depends_on = None
OWNER = "wso_account_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"


def upgrade():
    op.execute(f"""
      CREATE TABLE wso_private.tvt_directory_tickets(
        digest bytea PRIMARY KEY, lease_digest bytea UNIQUE,
        tenant_id uuid NOT NULL, actor_id uuid NOT NULL, actor_role text NOT NULL,
        session_digest text NOT NULL, identity_id uuid NOT NULL,
        region text NOT NULL, brand text NOT NULL, generation bigint NOT NULL,
        profile_id text NOT NULL, consent_version text NOT NULL,
        policy_revision bigint NOT NULL, consent_decided_at timestamptz NOT NULL,
        account_lease text NOT NULL, renewal_sequence bigint NOT NULL,
        method text NOT NULL CHECK(method IN ('device_list','channel_list','device_detail','channel_detail','sent_shares','received_shares')),
        query jsonb NOT NULL CHECK(octet_length(query::text)<=65536),
        state text NOT NULL DEFAULT 'ISSUED' CHECK(state IN ('ISSUED','REDEEMED','CLAIMED','PUBLISHED')),
        expires_at timestamptz NOT NULL);
      ALTER TABLE wso_private.tvt_directory_tickets OWNER TO {OWNER};
      ALTER TABLE wso_private.tvt_directory_tickets ENABLE ROW LEVEL SECURITY;
      ALTER TABLE wso_private.tvt_directory_tickets FORCE ROW LEVEL SECURITY;
      REVOKE ALL ON wso_private.tvt_directory_tickets FROM {RUNTIME};
      GRANT ALL ON wso_private.tvt_directory_tickets TO wso_migrator;
      CREATE POLICY directory_owner ON wso_private.tvt_directory_tickets TO {OWNER} USING(true) WITH CHECK(true);
      CREATE POLICY directory_migrator ON wso_private.tvt_directory_tickets TO wso_migrator USING(true) WITH CHECK(true);
    """)
    for signature, returns, body, role in FUNCTIONS:
        op.execute(
            f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $directory$ {body} $directory$"
        )
        schema, name = signature.split("(")[0].split(".")
        op.execute(f"""DO $$ DECLARE f regprocedure; BEGIN
          FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='{schema}' AND p.proname='{name}' LOOP
            EXECUTE 'ALTER FUNCTION '||f||' OWNER TO {OWNER}';
            EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM {RUNTIME}';
            {"EXECUTE 'GRANT EXECUTE ON FUNCTION '||f||' TO " + role + "';" if role else ""}
          END LOOP; END $$""")


QUERY = """
DECLARE keys text[]; v jsonb; n numeric; seen text[]:='{}'; item text;
BEGIN
 IF p_method IS NULL OR p_method NOT IN ('device_list','channel_list','device_detail','channel_detail','sent_shares','received_shares') OR p_query IS NULL OR jsonb_typeof(p_query)<>'object' OR octet_length(p_query::text)>65536 THEN RETURN false; END IF;
 keys:=ARRAY['identity_id','region','brand','method'];
 IF p_query->>'method' IS DISTINCT FROM p_method THEN RETURN false; END IF;
 PERFORM (p_query->>'identity_id')::uuid;
 IF p_query->>'identity_id' IS NULL THEN RETURN false; END IF;
 FOREACH item IN ARRAY ARRAY['region','brand'] LOOP
   IF jsonb_typeof(p_query->item) IS DISTINCT FROM 'string' OR (p_query->>item)!~'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$' THEN RETURN false; END IF;
 END LOOP;
 IF p_method IN ('device_list','sent_shares','received_shares') THEN
   keys:=keys||ARRAY['page_num','page_size'];
   FOREACH item IN ARRAY ARRAY['page_num','page_size'] LOOP
     IF jsonb_typeof(p_query->item) IS DISTINCT FROM 'number' THEN RETURN false; END IF;
     n:=(p_query->>item)::numeric;
     IF n<>trunc(n) OR n<0 OR n>(CASE WHEN item='page_size' THEN 1000 ELSE 2147483647 END) THEN RETURN false; END IF;
   END LOOP;
 END IF;
 IF p_method IN ('sent_shares','received_shares') THEN
   keys:=keys||ARRAY['resource_types'];
   IF jsonb_typeof(p_query->'resource_types') IS DISTINCT FROM 'array' OR jsonb_array_length(p_query->'resource_types')>16 THEN RETURN false; END IF;
   FOR v IN SELECT value FROM jsonb_array_elements(p_query->'resource_types') LOOP
     IF jsonb_typeof(v)<>'number' THEN RETURN false; END IF;
     n:=v::text::numeric;
     IF n<>trunc(n) OR n< -2147483648 OR n>2147483647 OR n::text=ANY(seen) THEN RETURN false; END IF;
     seen:=array_append(seen,n::text);
   END LOOP;
 END IF;
 IF p_method='channel_list' THEN
   keys:=keys||ARRAY['sn_list'];
   IF jsonb_typeof(p_query->'sn_list') IS DISTINCT FROM 'array' OR jsonb_array_length(p_query->'sn_list') NOT BETWEEN 1 AND 100 THEN RETURN false; END IF;
   FOR v IN SELECT value FROM jsonb_array_elements(p_query->'sn_list') LOOP
     IF jsonb_typeof(v)<>'string' THEN RETURN false; END IF;
     item:=v#>>'{}';
     IF NOT wso_private.wso_tvt_directory_selector(item) OR item=ANY(seen) THEN RETURN false; END IF;
     seen:=array_append(seen,item);
   END LOOP;
 END IF;
 IF p_method IN ('device_detail','channel_detail') THEN
   keys:=keys||ARRAY['sn'];
   IF jsonb_typeof(p_query->'sn') IS DISTINCT FROM 'string' OR NOT wso_private.wso_tvt_directory_selector(p_query->>'sn') THEN RETURN false; END IF;
   IF p_method='device_detail' THEN
     keys:=keys||ARRAY['return_chl'];
     IF jsonb_typeof(p_query->'return_chl') IS DISTINCT FROM 'boolean' THEN RETURN false; END IF;
   ELSE
     keys:=keys||ARRAY['chl_index'];
     IF jsonb_typeof(p_query->'chl_index') IS DISTINCT FROM 'number' THEN RETURN false; END IF;
     n:=(p_query->>'chl_index')::numeric;
     IF n<>trunc(n) OR n<0 OR n>2147483647 THEN RETURN false; END IF;
   END IF;
 END IF;
 RETURN p_query ?& keys AND (p_query - keys)='{}'::jsonb;
 EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END;
"""
CURRENT_DECISION = """
 t.expires_at>clock_timestamp()
 AND EXISTS(SELECT 1 FROM public.web_sessions s WHERE s.session_digest=t.session_digest AND s.user_id=t.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp())
 AND EXISTS(SELECT 1 FROM wso_private.tvt_user_consents c WHERE c.tenant_id=t.tenant_id AND c.user_id=t.actor_id AND c.profile_id=t.profile_id AND c.version=t.consent_version AND c.status='accepted' AND c.decided_at=t.consent_decided_at)
"""
LIVE = f"""
DECLARE a wso_private.tvt_account_tickets;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR t.digest IS NULL OR t.expires_at<=clock_timestamp() THEN RETURN false; END IF;
 PERFORM 1 FROM public.web_sessions s WHERE s.session_digest=t.session_digest AND s.user_id=t.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM public.memberships m WHERE m.tenant_id=t.tenant_id AND m.user_id=t.actor_id AND m.role=t.actor_role FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_flow_policies p JOIN wso_private.tvt_user_consents c ON c.profile_id=p.profile_id AND c.version=p.consent_version
 WHERE p.region=t.region AND p.brand=t.brand AND p.enabled AND p.revision=t.policy_revision AND p.profile_id=t.profile_id AND p.consent_version=t.consent_version
 AND c.tenant_id=t.tenant_id AND c.user_id=t.actor_id AND c.status='accepted' AND c.decided_at=t.consent_decided_at FOR SHARE OF p;
 IF NOT FOUND THEN RETURN false; END IF;
 a:=wso_private.wso_tvt_account_check(t.account_lease,'profile');
 IF a.digest IS NULL OR a.tenant_id<>t.tenant_id OR a.actor_id<>t.actor_id OR a.identity_id<>t.identity_id OR a.generation<>t.generation OR a.region<>t.region OR a.brand<>t.brand OR a.kind<>'USER' THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_account_tokens v WHERE v.tenant_id=t.tenant_id AND v.identity_id=t.identity_id AND v.kind='USER' AND v.generation=t.generation AND v.renewal_sequence=t.renewal_sequence AND v.renewal_state='IDLE' FOR SHARE;
 RETURN FOUND AND ({CURRENT_DECISION});
END;
"""
ISSUE = """
DECLARE a record; s record; p record; c record; v record; t wso_private.tvt_directory_tickets; token text; delegated text; saved text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_session IS NULL OR p_session!~'^[0-9a-f]{64}$' OR NOT wso_private.wso_tvt_directory_query(p_method,p_query) THEN RETURN NULL; END IF;
 SELECT * INTO a FROM public.wso_authorize_domain('TVT',(p_query->>'identity_id')::uuid,NULL,NULL,NULL,NULL,'account.read');
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO s FROM public.web_sessions WHERE session_digest=p_session AND user_id=a.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO p FROM wso_private.tvt_flow_policies WHERE region=p_query->>'region' AND brand=p_query->>'brand' AND enabled FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO c FROM wso_private.tvt_user_consents WHERE tenant_id=a.tenant_id AND user_id=a.actor_id AND profile_id=p.profile_id AND version=p.consent_version AND status='accepted';
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO v FROM wso_private.tvt_account_tokens WHERE tenant_id=a.tenant_id AND identity_id=(p_query->>'identity_id')::uuid AND kind='USER' AND renewal_state='IDLE' FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM pg_advisory_xact_lock(711100001);
 FOR t IN SELECT * FROM wso_private.tvt_directory_tickets WHERE expires_at<=clock_timestamp() ORDER BY expires_at LIMIT 128 FOR UPDATE SKIP LOCKED LOOP
   PERFORM wso_private.wso_tvt_directory_retire(t);
 END LOOP;
 IF (SELECT count(*) FROM wso_private.tvt_directory_tickets WHERE expires_at>clock_timestamp() AND state<>'PUBLISHED')>=128 OR (SELECT count(*) FROM wso_private.tvt_directory_tickets WHERE tenant_id=a.tenant_id AND actor_id=a.actor_id AND expires_at>clock_timestamp() AND state<>'PUBLISHED')>=4 THEN RETURN NULL; END IF;
 delegated:=public.wso_tvt_account_issue('profile',p.region,p.brand,v.identity_id,'USER',v.generation);
 IF delegated IS NULL THEN RETURN NULL; END IF;
 saved:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 IF NOT public.wso_tvt_account_redeem(delegated,saved) THEN RETURN NULL; END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 INSERT INTO wso_private.tvt_directory_tickets(digest,tenant_id,actor_id,actor_role,session_digest,identity_id,region,brand,generation,profile_id,consent_version,policy_revision,consent_decided_at,account_lease,renewal_sequence,method,query,expires_at)
 VALUES(sha256(convert_to(token,'UTF8')),a.tenant_id,a.actor_id,a.role,p_session,v.identity_id,p.region,p.brand,v.generation,p.profile_id,p.consent_version,p.revision,c.decided_at,saved,v.renewal_sequence,p_method,p_query,least(s.expires_at,clock_timestamp()+interval '30 seconds')) RETURNING * INTO t;
 IF NOT wso_private.wso_tvt_directory_live(t) THEN RAISE EXCEPTION 'directory denied' USING ERRCODE='42501'; END IF;
 RETURN token;
END;
"""
CHECK = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 IF p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
 SELECT * INTO t FROM wso_private.tvt_directory_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8')) AND method=p_method AND query=p_query AND profile_id=p_profile AND consent_version=p_version AND state IN ('REDEEMED','CLAIMED') FOR UPDATE;
 IF NOT FOUND OR NOT wso_private.wso_tvt_directory_live(t) THEN RETURN NULL; END IF;
 RETURN t;
END;
"""
REDEEM = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 IF p_ticket IS NULL OR p_ticket!~'^[0-9a-f]{64}$' OR p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN false; END IF;
 SELECT * INTO t FROM wso_private.tvt_directory_tickets WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND method=p_method AND query=p_query AND profile_id=p_profile AND consent_version=p_version AND state='ISSUED' FOR UPDATE;
 IF NOT FOUND OR NOT wso_private.wso_tvt_directory_live(t) THEN RETURN false; END IF;
 UPDATE wso_private.tvt_directory_tickets SET lease_digest=sha256(convert_to(p_lease,'UTF8')),state='REDEEMED' WHERE digest=t.digest;
 RETURN true;
END;
"""
CONTEXT = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 t:=wso_private.wso_tvt_directory_check(p_lease,p_method,p_query,p_profile,p_version);
 IF t.digest IS NULL THEN RETURN; END IF;
 RETURN QUERY SELECT t.tenant_id,t.actor_id,t.identity_id,t.region,t.brand,t.generation;
END;
"""
CLAIM = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 t:=wso_private.wso_tvt_directory_check(p_lease,p_method,p_query,p_profile,p_version);
 IF t.digest IS NULL OR t.state<>'REDEEMED' THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_directory_tickets SET state='CLAIMED' WHERE digest=t.digest;
 RETURN t.account_lease;
END;
"""
SECRET = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 t:=wso_private.wso_tvt_directory_check(p_lease,p_method,p_query,p_profile,p_version);
 IF t.digest IS NULL OR t.state<>'CLAIMED' THEN RETURN; END IF;
 RETURN QUERY SELECT * FROM public.wso_tvt_account_secret(t.account_lease,'profile');
END;
"""
PUBLISH = f"""
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 t:=wso_private.wso_tvt_directory_check(p_lease,p_method,p_query,p_profile,p_version);
 IF t.digest IS NULL OR t.state<>'CLAIMED' THEN RETURN false; END IF;
 UPDATE wso_private.tvt_directory_tickets SET state='PUBLISHED' WHERE digest=t.digest AND ({CURRENT_DECISION});
 RETURN FOUND;
END;
"""
RETIRE = """
DECLARE cap uuid;
BEGIN
 DELETE FROM wso_private.tvt_directory_tickets WHERE digest=t.digest;
 DELETE FROM wso_private.tvt_account_tickets WHERE lease_digest=sha256(convert_to(t.account_lease,'UTF8')) AND purpose='profile' RETURNING cap_id INTO cap;
 IF cap IS NOT NULL THEN DELETE FROM wso_private.domain_credential_capabilities WHERE id=cap; END IF;
END;
"""
DISPOSE = """
DECLARE t wso_private.tvt_directory_tickets;
BEGIN
 IF p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN; END IF;
 SELECT * INTO t FROM wso_private.tvt_directory_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8')) FOR UPDATE;
 IF FOUND THEN PERFORM wso_private.wso_tvt_directory_retire(t); END IF;
END;
"""
ARGS = "p_lease text,p_method text,p_query jsonb,p_profile text,p_version text"
FUNCTIONS = (
    (
        "wso_private.wso_tvt_directory_retire(t wso_private.tvt_directory_tickets)",
        "void",
        RETIRE,
        "",
    ),
    (
        "wso_private.wso_tvt_directory_selector(v text)",
        "boolean",
        "BEGIN RETURN v IS NOT NULL AND octet_length(v) BETWEEN 1 AND 4096 AND v=btrim(v) AND v!~'[[:cntrl:]]' AND NOT EXISTS(SELECT 1 FROM regexp_split_to_table(v,'') c WHERE ascii(c)>65535); END;",
        "",
    ),
    (
        "wso_private.wso_tvt_directory_query(p_method text,p_query jsonb)",
        "boolean",
        QUERY,
        "",
    ),
    (
        "wso_private.wso_tvt_directory_live(t wso_private.tvt_directory_tickets)",
        "boolean",
        LIVE,
        "",
    ),
    (
        "public.wso_tvt_directory_issue(p_session text,p_method text,p_query jsonb)",
        "text",
        ISSUE,
        "wso_app",
    ),
    (
        f"wso_private.wso_tvt_directory_check({ARGS})",
        "wso_private.tvt_directory_tickets",
        CHECK,
        "",
    ),
    (
        "public.wso_tvt_directory_redeem(p_ticket text," + ARGS + ")",
        "boolean",
        REDEEM,
        "wso_connection_worker",
    ),
    (
        f"public.wso_tvt_directory_context({ARGS})",
        "TABLE(tenant_id uuid,actor_id uuid,identity_id uuid,region text,brand text,generation bigint)",
        CONTEXT,
        "wso_connection_worker",
    ),
    (f"public.wso_tvt_directory_claim({ARGS})", "text", CLAIM, "wso_connection_worker"),
    (
        f"public.wso_tvt_directory_secret({ARGS})",
        "TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea,generation bigint)",
        SECRET,
        "wso_connection_worker",
    ),
    (
        f"public.wso_tvt_directory_publish({ARGS})",
        "boolean",
        PUBLISH,
        "wso_connection_worker",
    ),
    (
        "public.wso_tvt_directory_dispose(p_lease text)",
        "void",
        DISPOSE,
        "wso_connection_worker",
    ),
)


def downgrade():
    for name, args in (
        ("public.wso_tvt_directory_dispose", "text"),
        ("public.wso_tvt_directory_publish", "text,text,jsonb,text,text"),
        ("public.wso_tvt_directory_secret", "text,text,jsonb,text,text"),
        ("public.wso_tvt_directory_claim", "text,text,jsonb,text,text"),
        ("public.wso_tvt_directory_context", "text,text,jsonb,text,text"),
        ("public.wso_tvt_directory_redeem", "text,text,text,jsonb,text,text"),
        ("wso_private.wso_tvt_directory_check", "text,text,jsonb,text,text"),
        ("public.wso_tvt_directory_issue", "text,text,jsonb"),
        ("wso_private.wso_tvt_directory_retire", "wso_private.tvt_directory_tickets"),
        ("wso_private.wso_tvt_directory_live", "wso_private.tvt_directory_tickets"),
        ("wso_private.wso_tvt_directory_query", "text,jsonb"),
        ("wso_private.wso_tvt_directory_selector", "text"),
    ):
        op.execute(f"DROP FUNCTION {name}({args})")
    op.execute("DROP TABLE wso_private.tvt_directory_tickets")
