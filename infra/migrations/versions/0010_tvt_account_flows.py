"""Separate prelogin flow capabilities and durable business-intent witnesses.

Metadata only. No password, account, cookie, native challenge, RSA or code data.
"""

from alembic import op

revision = "0010_tvt_account_flows"
down_revision = "0009_asset_read_denial"
branch_labels = None
depends_on = None
OWNER = "wso_account_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = ("tvt_flows", "tvt_flow_tickets", "tvt_flow_intents", "tvt_flow_policies")


def function(
    signature, returns, body, role="wso_connection_worker", language="plpgsql"
):
    op.execute(
        f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE {language} VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $flow$ {body} $flow$"
    )
    schema, name = signature.split("(")[0].split(".")
    op.execute(f"""DO $$ DECLARE f regprocedure; BEGIN
      FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='{schema}' AND p.proname='{name}' LOOP
        EXECUTE 'ALTER FUNCTION '||f||' OWNER TO {OWNER}';
        EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM {RUNTIME}';
        {"EXECUTE 'GRANT EXECUTE ON FUNCTION '||f||' TO " + role + "';" if role else ""}
      END LOOP; END $$""")


def upgrade():
    op.execute("""
      CREATE TABLE wso_private.tvt_flow_policies(
        region text NOT NULL CHECK(region ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        brand text NOT NULL CHECK(brand ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        profile_id text NOT NULL CHECK(profile_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        consent_version text NOT NULL CHECK(consent_version ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'),
        key_commitment bytea NOT NULL CHECK(octet_length(key_commitment)=32),
        revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
        enabled boolean NOT NULL DEFAULT false, PRIMARY KEY(region,brand));
      CREATE TABLE wso_private.tvt_flows(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, actor_id uuid NOT NULL,
        actor_role text NOT NULL CHECK(actor_role IN ('OWNER','MANAGER','STAFF')),
        session_digest text NOT NULL CHECK(session_digest ~ '^[0-9a-f]{64}$'),
        region text NOT NULL, brand text NOT NULL,
        profile_id text NOT NULL, consent_version text NOT NULL,
        policy_revision bigint NOT NULL, consent_decided_at timestamptz NOT NULL,
        key_commitment bytea NOT NULL CHECK(octet_length(key_commitment)=32),
        purpose text NOT NULL CHECK(purpose IN ('register','recover')),
        generation bigint NOT NULL DEFAULT 1 CHECK(generation>0),
        state text NOT NULL DEFAULT 'CREATED' CHECK(state IN ('CREATED','EXISTENCE','IMAGE_AVAILABLE','IMAGE_REQUIRED','IMAGE_REJECTED','CODE_SENT','COMPLETE','FAILED','UNKNOWN_OUTCOME','CLOSED','EXPIRED')),
        busy_digest bytea, final_consumed boolean NOT NULL DEFAULT false,
        expires_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        CHECK(expires_at<=created_at+interval '300 seconds'));
      CREATE TABLE wso_private.tvt_flow_tickets(
        digest bytea PRIMARY KEY, lease_digest bytea UNIQUE,
        flow_id uuid NOT NULL REFERENCES wso_private.tvt_flows(id),
        generation bigint NOT NULL,
        operation text NOT NULL CHECK(operation IN ('start','state','existence','image','issue_code','register','recover','cancel')),
        used boolean NOT NULL DEFAULT false, expires_at timestamptz NOT NULL);
      CREATE TABLE wso_private.tvt_flow_intents(
        digest bytea NOT NULL CHECK(octet_length(digest)=32),
        key_commitment bytea NOT NULL CHECK(octet_length(key_commitment)=32),
        tenant_id uuid NOT NULL, purpose text NOT NULL CHECK(purpose IN ('register','recover')),
        flow_id uuid PRIMARY KEY REFERENCES wso_private.tvt_flows(id),
        generation bigint NOT NULL, admitted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        outcome text NOT NULL DEFAULT 'UNKNOWN_OUTCOME' CHECK(outcome IN ('UNKNOWN_OUTCOME','COMPLETE','FAILED')));
      CREATE UNIQUE INDEX tvt_flow_unsettled_intent ON wso_private.tvt_flow_intents(digest) WHERE outcome='UNKNOWN_OUTCOME';
    """)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} OWNER TO {OWNER};
          ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON wso_private.{table} FROM {RUNTIME};
          GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY flow_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY flow_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);""")
    for table in ("public.web_sessions", "wso_private.tvt_user_consents"):
        op.execute(f"GRANT SELECT ON {table} TO {OWNER}")
        op.execute(
            f"CREATE POLICY flow_authority_read ON {table} FOR SELECT TO {OWNER} USING(true)"
        )
    for signature, returns, body, role, language in FUNCTIONS:
        function(signature, returns, body, role, language)
    op.execute(
        "CREATE TRIGGER flow_key_guard BEFORE INSERT OR UPDATE OF key_commitment ON wso_private.tvt_flow_policies FOR EACH ROW EXECUTE FUNCTION wso_private.wso_tvt_flow_key_guard()"
    )


LIVE = """
 SELECT current_setting('transaction_isolation')='read committed'
 AND f.id IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM wso_private.tvt_flow_intents i WHERE i.outcome='UNKNOWN_OUTCOME' AND i.key_commitment<>f.key_commitment)
 AND EXISTS(SELECT 1 FROM public.memberships m WHERE m.tenant_id=f.tenant_id AND m.user_id=f.actor_id AND m.role=f.actor_role)
 AND EXISTS(SELECT 1 FROM public.web_sessions s WHERE s.session_digest=f.session_digest AND s.user_id=f.actor_id AND s.revoked_at IS NULL AND s.expires_at>clock_timestamp())
 AND EXISTS(SELECT 1 FROM wso_private.tvt_flow_policies p
   JOIN wso_private.tvt_user_consents c ON c.profile_id=p.profile_id AND c.version=p.consent_version
   WHERE p.region=f.region AND p.brand=f.brand AND p.enabled AND p.revision=f.policy_revision
   AND p.key_commitment=f.key_commitment
   AND p.profile_id=f.profile_id AND p.consent_version=f.consent_version
   AND c.tenant_id=f.tenant_id AND c.user_id=f.actor_id AND c.status='accepted' AND c.decided_at=f.consent_decided_at)
"""
ISSUE = """
DECLARE a record; f wso_private.tvt_flows; s record; p record; c record; token text; expiry timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_operation IS NULL OR p_operation NOT IN ('start','state','existence','image','issue_code','register','recover','cancel')
 OR p_purpose IS NULL OR p_purpose NOT IN ('register','recover') OR p_session IS NULL OR p_session!~'^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
 SELECT * INTO a FROM public.wso_authorize_domain('TVT',NULL,NULL,NULL,NULL,NULL,'account.login');
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO s FROM public.web_sessions WHERE session_digest=p_session AND user_id=a.actor_id AND revoked_at IS NULL AND expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF p_operation='start' THEN
   IF p_flow IS NOT NULL THEN RETURN NULL; END IF;
   SELECT * INTO p FROM wso_private.tvt_flow_policies WHERE region=p_region AND brand=p_brand AND enabled;
   IF NOT FOUND THEN RETURN NULL; END IF;
   SELECT * INTO c FROM wso_private.tvt_user_consents WHERE tenant_id=a.tenant_id AND user_id=a.actor_id AND profile_id=p.profile_id AND version=p.consent_version AND status='accepted';
   IF NOT FOUND THEN RETURN NULL; END IF;
   -- Serialize capacity allocation; no network transaction is held.
   PERFORM pg_advisory_xact_lock(710100001);
   IF (SELECT count(*) FROM wso_private.tvt_flows WHERE expires_at>clock_timestamp() AND state NOT IN ('COMPLETE','FAILED','UNKNOWN_OUTCOME','CLOSED','EXPIRED'))>=128
      OR (SELECT count(*) FROM wso_private.tvt_flows WHERE tenant_id=a.tenant_id AND actor_id=a.actor_id AND expires_at>clock_timestamp() AND state NOT IN ('COMPLETE','FAILED','UNKNOWN_OUTCOME','CLOSED','EXPIRED'))>=4 THEN RETURN NULL; END IF;
   INSERT INTO wso_private.tvt_flows(id,tenant_id,actor_id,actor_role,session_digest,region,brand,profile_id,consent_version,policy_revision,consent_decided_at,key_commitment,purpose,expires_at)
     VALUES(gen_random_uuid(),a.tenant_id,a.actor_id,a.role,p_session,p_region,p_brand,p.profile_id,p.consent_version,p.revision,c.decided_at,p.key_commitment,p_purpose,least(s.expires_at,clock_timestamp()+interval '300 seconds')) RETURNING * INTO f;
 ELSE
   SELECT * INTO f FROM wso_private.tvt_flows WHERE id=p_flow;
   IF NOT FOUND OR f.tenant_id<>a.tenant_id OR f.actor_id<>a.actor_id OR f.session_digest<>p_session
     OR f.region IS DISTINCT FROM p_region OR f.brand IS DISTINCT FROM p_brand OR f.purpose IS DISTINCT FROM p_purpose THEN RETURN NULL; END IF;
 END IF;
 IF NOT wso_private.wso_tvt_flow_live(f) OR (p_operation='register' AND f.purpose<>'register') OR (p_operation='recover' AND f.purpose<>'recover') THEN RETURN NULL; END IF;
 expiry:=least(s.expires_at,clock_timestamp()+interval '30 seconds');
 IF p_operation NOT IN ('state','cancel') THEN expiry:=least(expiry,f.expires_at); END IF;
 IF expiry<=clock_timestamp() THEN RETURN NULL; END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 INSERT INTO wso_private.tvt_flow_tickets(digest,flow_id,generation,operation,expires_at)
 VALUES(sha256(convert_to(token,'UTF8')),f.id,f.generation,p_operation,expiry);
 RETURN token;
END;
"""
CHECK = """
DECLARE t wso_private.tvt_flow_tickets; f wso_private.tvt_flows;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_lease IS NULL OR p_lease!~'^[0-9a-f]{64}$' OR p_key IS NULL OR p_key!~'^[0-9a-f]{64}$' THEN RETURN NULL; END IF;
 SELECT * INTO t FROM wso_private.tvt_flow_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8')) AND operation=p_operation AND expires_at>clock_timestamp();
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_flows WHERE id=t.flow_id AND generation=t.generation;
 IF NOT FOUND OR f.key_commitment<>decode(p_key,'hex') OR NOT wso_private.wso_tvt_flow_live(f) THEN RETURN NULL; END IF;
 RETURN t;
END;
"""
REDEEM = """
DECLARE t wso_private.tvt_flow_tickets;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_ticket IS NULL OR p_lease IS NULL OR p_ticket!~'^[0-9a-f]{64}$' OR p_lease!~'^[0-9a-f]{64}$' THEN RETURN false; END IF;
 UPDATE wso_private.tvt_flow_tickets SET lease_digest=sha256(convert_to(p_lease,'UTF8'))
 WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND lease_digest IS NULL AND operation=p_operation AND expires_at>clock_timestamp() RETURNING * INTO t;
 IF NOT FOUND THEN RETURN false; END IF;
 t:=wso_private.wso_tvt_flow_check(p_lease,p_operation,p_key);
 RETURN t.digest IS NOT NULL;
END;
"""
CONTEXT = """
DECLARE t wso_private.tvt_flow_tickets;
BEGIN
 t:=wso_private.wso_tvt_flow_check(p_lease,p_operation,p_key);
 IF t.digest IS NULL THEN RETURN; END IF;
 RETURN QUERY SELECT f.tenant_id,f.actor_id,f.session_digest,f.id,f.region,f.brand,f.purpose,f.generation,CASE WHEN f.busy_digest IS NOT NULL THEN 'UNKNOWN_OUTCOME' ELSE f.state END,f.expires_at,encode(f.key_commitment,'hex')
 FROM wso_private.tvt_flows f WHERE f.id=t.flow_id;
END;
"""
CLAIM = """
DECLARE t wso_private.tvt_flow_tickets; f wso_private.tvt_flows; affected integer;
BEGIN
 -- Serialize key-policy rotation and every initial final admission. A new
 -- commitment can never race an old-key pending witness into existence.
 IF p_operation IN ('register','recover') THEN PERFORM pg_advisory_xact_lock(710100002); END IF;
 t:=wso_private.wso_tvt_flow_check(p_lease,p_operation,p_key);
 IF t.digest IS NULL OR t.used THEN RETURN 'DENIED'; END IF;
 SELECT * INTO f FROM wso_private.tvt_flows WHERE id=t.flow_id FOR UPDATE;
 IF t.expires_at<=clock_timestamp() OR f.generation<>t.generation OR NOT wso_private.wso_tvt_flow_live(f) THEN RETURN 'DENIED'; END IF;
 IF f.busy_digest IS NOT NULL THEN RETURN 'BUSY'; END IF;
 IF p_operation IN ('register','recover') THEN
   IF f.final_consumed OR f.state IN ('COMPLETE','FAILED','UNKNOWN_OUTCOME','CLOSED','EXPIRED') OR f.purpose<>p_operation OR p_intent IS NULL OR p_intent!~'^[0-9a-f]{64}$' THEN RETURN 'DENIED'; END IF;
 ELSIF p_intent IS NOT NULL THEN RETURN 'DENIED'; END IF;
 UPDATE wso_private.tvt_flow_tickets SET used=true WHERE digest=t.digest AND NOT used;
 GET DIAGNOSTICS affected=ROW_COUNT;
 IF affected<>1 THEN RETURN 'DENIED'; END IF;
 UPDATE wso_private.tvt_flows SET busy_digest=t.lease_digest WHERE id=f.id;
 IF p_operation IN ('register','recover') THEN
   -- The witness and consumed state commit before the caller may perform I/O.
   UPDATE wso_private.tvt_flows SET final_consumed=true,state='UNKNOWN_OUTCOME' WHERE id=f.id;
   INSERT INTO wso_private.tvt_flow_intents(digest,key_commitment,tenant_id,purpose,flow_id,generation)
   VALUES(decode(p_intent,'hex'),f.key_commitment,f.tenant_id,f.purpose,f.id,f.generation) ON CONFLICT(digest) WHERE outcome='UNKNOWN_OUTCOME' DO NOTHING;
   GET DIAGNOSTICS affected=ROW_COUNT;
   IF affected<>1 THEN RETURN 'UNKNOWN_OUTCOME'; END IF;
 END IF;
 RETURN 'CLAIMED';
END;
"""
PUBLISH = """
DECLARE t wso_private.tvt_flow_tickets; f wso_private.tvt_flows;
BEGIN
 t:=wso_private.wso_tvt_flow_check(p_lease,p_operation,p_key);
 IF t.digest IS NULL OR NOT t.used OR p_state IS NULL OR p_state NOT IN ('CREATED','EXISTENCE','IMAGE_AVAILABLE','IMAGE_REQUIRED','IMAGE_REJECTED','CODE_SENT','COMPLETE','FAILED','UNKNOWN_OUTCOME','CLOSED','EXPIRED') THEN RETURN NULL; END IF;
 SELECT * INTO f FROM wso_private.tvt_flows WHERE id=t.flow_id FOR UPDATE;
 IF t.expires_at<=clock_timestamp() OR f.generation<>t.generation OR f.busy_digest IS DISTINCT FROM t.lease_digest OR NOT wso_private.wso_tvt_flow_live(f) THEN RETURN NULL; END IF;
 IF p_state='IMAGE_REJECTED' AND f.purpose<>'register' THEN RETURN NULL; END IF;
 IF f.final_consumed AND p_state NOT IN ('COMPLETE','FAILED','UNKNOWN_OUTCOME') THEN RETURN NULL; END IF;
 IF p_state='COMPLETE' AND (NOT f.final_consumed OR NOT EXISTS(SELECT 1 FROM wso_private.tvt_flow_intents WHERE flow_id=f.id)) THEN RETURN NULL; END IF;
 IF p_operation IN ('register','recover') AND p_state NOT IN ('COMPLETE','FAILED','UNKNOWN_OUTCOME') THEN RETURN NULL; END IF;
 UPDATE wso_private.tvt_flows SET state=p_state,generation=generation+1,busy_digest=NULL WHERE id=f.id;
 IF f.final_consumed THEN UPDATE wso_private.tvt_flow_intents SET outcome=p_state WHERE flow_id=f.id; END IF;
 RETURN f.generation+1;
END;
"""
KEY_GUARD = """
BEGIN
 PERFORM pg_advisory_xact_lock(710100002);
 IF EXISTS(SELECT 1 FROM wso_private.tvt_flow_intents WHERE outcome='UNKNOWN_OUTCOME' AND key_commitment IS DISTINCT FROM NEW.key_commitment) THEN
   RAISE EXCEPTION 'flow key rotation denied' USING ERRCODE='42501';
 END IF;
 RETURN NEW;
END;
"""
FUNCTIONS = (
    ("wso_private.wso_tvt_flow_key_guard()", "trigger", KEY_GUARD, "", "plpgsql"),
    (
        "wso_private.wso_tvt_flow_live(f wso_private.tvt_flows)",
        "boolean",
        LIVE,
        "",
        "sql",
    ),
    (
        "public.wso_tvt_flow_issue(p_session text,p_operation text,p_region text,p_brand text,p_purpose text,p_flow uuid)",
        "text",
        ISSUE,
        "wso_app",
        "plpgsql",
    ),
    (
        "wso_private.wso_tvt_flow_check(p_lease text,p_operation text,p_key text)",
        "wso_private.tvt_flow_tickets",
        CHECK,
        "",
        "plpgsql",
    ),
    (
        "public.wso_tvt_flow_redeem(p_ticket text,p_lease text,p_operation text,p_key text)",
        "boolean",
        REDEEM,
        "wso_connection_worker",
        "plpgsql",
    ),
    (
        "public.wso_tvt_flow_context(p_lease text,p_operation text,p_key text)",
        "TABLE(tenant_id uuid,actor_id uuid,session_digest text,flow_id uuid,region text,brand text,purpose text,generation bigint,state text,expires_at timestamptz,key_commitment text)",
        CONTEXT,
        "wso_connection_worker",
        "plpgsql",
    ),
    (
        "public.wso_tvt_flow_claim(p_lease text,p_operation text,p_intent text,p_key text)",
        "text",
        CLAIM,
        "wso_connection_worker",
        "plpgsql",
    ),
    (
        "public.wso_tvt_flow_publish(p_lease text,p_operation text,p_state text,p_key text)",
        "bigint",
        PUBLISH,
        "wso_connection_worker",
        "plpgsql",
    ),
)


def downgrade():
    op.execute("DROP TRIGGER flow_key_guard ON wso_private.tvt_flow_policies")
    for signature in (
        "wso_private.wso_tvt_flow_key_guard()",
        "public.wso_tvt_flow_publish(text,text,text,text)",
        "public.wso_tvt_flow_claim(text,text,text,text)",
        "public.wso_tvt_flow_context(text,text,text)",
        "public.wso_tvt_flow_redeem(text,text,text,text)",
        "wso_private.wso_tvt_flow_check(text,text,text)",
        "public.wso_tvt_flow_issue(text,text,text,text,text,uuid)",
        "wso_private.wso_tvt_flow_live(wso_private.tvt_flows)",
    ):
        op.execute(f"DROP FUNCTION {signature}")
    for table in (
        "tvt_flow_tickets",
        "tvt_flow_intents",
        "tvt_flows",
        "tvt_flow_policies",
    ):
        op.execute(f"DROP TABLE wso_private.{table}")
    for table in ("public.web_sessions", "wso_private.tvt_user_consents"):
        op.execute(f"DROP POLICY flow_authority_read ON {table}")
        op.execute(f"REVOKE SELECT ON {table} FROM {OWNER}")
