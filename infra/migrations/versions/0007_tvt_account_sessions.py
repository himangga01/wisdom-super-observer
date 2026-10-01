"""T04-backed account token metadata and protected worker capabilities.

No secret bytes are added to new tables. Runtime worker transport is injected;
this revision does not grant decrypt authority to the API process.
"""

from alembic import op

revision = "0007_tvt_account_sessions"
down_revision = "0006_tvt_startup"
branch_labels = None
depends_on = None
OWNER = "wso_account_owner"
RUNTIME = "PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance"
TABLES = (
    "tvt_account_sessions",
    "tvt_account_tokens",
    "tvt_account_tickets",
    "tvt_account_challenges",
    "tvt_account_storage",
)
ACCESS = {
    "wso_private.tenant_contexts": "SELECT",
    "public.memberships": "SELECT,UPDATE(role)",
    "public.connections": "SELECT,INSERT,UPDATE",
    "wso_private.connection_secrets": "SELECT,INSERT,UPDATE,DELETE",
    "wso_private.connection_handles": "SELECT,DELETE",
    "wso_private.connection_leases": "SELECT,DELETE",
    "wso_private.connection_revocations": "INSERT",
    "wso_private.domain_credential_connections": "SELECT,INSERT",
    "wso_private.domain_credential_capabilities": "SELECT,INSERT,DELETE",
    "wso_private.tvt_identities": "SELECT,INSERT,UPDATE",
    "wso_private.tvt_identity_grants": "SELECT,INSERT,UPDATE,DELETE",
    "wso_private.tvt_upstream_grants": "SELECT,INSERT,UPDATE",
    "wso_private.tvt_capability_snapshots": "SELECT,INSERT,UPDATE",
}


def function(
    signature, body, returns, role="wso_connection_worker", language="plpgsql"
):
    op.execute(
        f"CREATE FUNCTION {signature} RETURNS {returns} LANGUAGE {language} VOLATILE SECURITY DEFINER SET search_path=pg_catalog SET lock_timeout='3s' AS $wso$ {body} $wso$"
    )
    name = signature.split("(")[0]
    # Arguments below use named parameters; derive identity types from catalog.
    op.execute(
        f"DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='{name.split('.')[0]}' AND p.proname='{name.split('.')[1]}' LOOP EXECUTE 'ALTER FUNCTION '||f||' OWNER TO {OWNER}'; EXECUTE 'REVOKE ALL ON FUNCTION '||f||' FROM {RUNTIME}'; "
        + (f"EXECUTE 'GRANT EXECUTE ON FUNCTION '||f||' TO {role}'; " if role else "")
        + "END LOOP; END $$"
    )


def upgrade():
    op.execute(f"""
      DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{OWNER}') THEN
        CREATE ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      END IF; END $$;
      ALTER ROLE {OWNER} NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_auth_members WHERE member='{OWNER}'::regrole OR roleid='{OWNER}'::regrole) THEN RAISE EXCEPTION 'account role membership forbidden'; END IF; END $$;
      GRANT USAGE ON SCHEMA public,wso_private TO {OWNER};
      CREATE TABLE wso_private.tvt_account_sessions(
        identity_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, actor_id uuid NOT NULL,
        state text NOT NULL CHECK(state IN ('READY','CLOSED')),
        UNIQUE(tenant_id,identity_id),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tvt_identities(tenant_id,id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,actor_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE);
      CREATE TABLE wso_private.tvt_account_storage(
        connection_id uuid PRIMARY KEY REFERENCES public.connections(id) ON DELETE CASCADE,
        tenant_id uuid NOT NULL, kind text NOT NULL CHECK(kind IN ('USER','P2P','DEVICE','CHALLENGE')),
        FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id));
      CREATE TABLE wso_private.tvt_account_tokens(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, identity_id uuid NOT NULL,
        kind text NOT NULL CHECK(kind IN ('USER','P2P','DEVICE')),
        connection_id uuid NOT NULL UNIQUE REFERENCES wso_private.tvt_account_storage(connection_id),
        version_id uuid NOT NULL UNIQUE, generation bigint NOT NULL CHECK(generation>0),
        renewal_sequence bigint NOT NULL DEFAULT 0 CHECK(renewal_sequence>=0), renewal_attempt uuid, renewal_state text NOT NULL DEFAULT 'IDLE' CHECK(renewal_state IN ('IDLE','INFLIGHT','UNKNOWN')),
        UNIQUE(tenant_id,identity_id,kind),
        FOREIGN KEY(tenant_id,identity_id) REFERENCES wso_private.tvt_account_sessions(tenant_id,identity_id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id));
      CREATE TABLE wso_private.tvt_account_tickets(
        digest bytea PRIMARY KEY, lease_digest bytea UNIQUE,
        tenant_id uuid NOT NULL, actor_id uuid NOT NULL, actor_role text NOT NULL CHECK(actor_role IN ('OWNER','MANAGER','STAFF')),
        purpose text NOT NULL CHECK(purpose IN ('login','image','check','profile','renew','logout')),
        region varchar(64) NOT NULL, brand varchar(64) NOT NULL,
        identity_id uuid, kind text NOT NULL CHECK(kind IN ('USER','P2P','DEVICE')),
        generation bigint NOT NULL CHECK(generation>=0), renewal_sequence bigint NOT NULL DEFAULT 0 CHECK(renewal_sequence>=0), cap_id uuid, expires_at timestamptz NOT NULL,
        FOREIGN KEY(tenant_id,actor_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE);
      CREATE TABLE wso_private.tvt_account_challenges(
        id uuid PRIMARY KEY, tenant_id uuid NOT NULL, actor_id uuid NOT NULL,
        region varchar(64) NOT NULL, brand varchar(64) NOT NULL,
        connection_id uuid NOT NULL UNIQUE REFERENCES wso_private.tvt_account_storage(connection_id),
        expires_at timestamptz NOT NULL, consumed boolean NOT NULL DEFAULT false,
        FOREIGN KEY(tenant_id,actor_id) REFERENCES public.memberships(tenant_id,user_id) ON DELETE CASCADE,
        FOREIGN KEY(tenant_id,connection_id) REFERENCES public.connections(tenant_id,id));
    """)
    for table in TABLES:
        op.execute(f"""ALTER TABLE wso_private.{table} ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp(), ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();
          ALTER TABLE wso_private.{table} OWNER TO {OWNER}; ALTER TABLE wso_private.{table} ENABLE ROW LEVEL SECURITY; ALTER TABLE wso_private.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON wso_private.{table} FROM {RUNTIME}; GRANT ALL ON wso_private.{table} TO wso_migrator;
          CREATE POLICY account_owner ON wso_private.{table} TO {OWNER} USING(true) WITH CHECK(true);
          CREATE POLICY account_migrator ON wso_private.{table} TO wso_migrator USING(true) WITH CHECK(true);
          CREATE TRIGGER account_timestamps BEFORE INSERT OR UPDATE ON wso_private.{table} FOR EACH ROW EXECUTE FUNCTION wso_private.wso_domain_timestamps();""")
    for table, permissions in ACCESS.items():
        op.execute(f"GRANT {permissions} ON {table} TO {OWNER}")
        op.execute(
            f"CREATE POLICY account_session_access ON {table} TO {OWNER} USING(true) WITH CHECK(true)"
        )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text) TO {OWNER}"
    )
    function(
        "public.wso_tvt_managed_connection(p_id uuid)",
        "SELECT EXISTS(SELECT 1 FROM wso_private.tvt_account_storage WHERE connection_id=p_id)",
        "boolean",
        "wso_migrator,wso_domain_owner",
        "sql",
    )
    for signature, backup, owner, needle, guard in (
        (
            "public.wso_issue_domain_connection_handle(jsonb,text,timestamptz)",
            "wso_private.account_original_issue_domain_connection_handle",
            "wso_migrator",
            "PERFORM 1 FROM public.connections WHERE id=conn",
            "IF public.wso_tvt_managed_connection(conn) THEN RETURN NULL; END IF;\n PERFORM 1 FROM public.connections WHERE id=conn",
        ),
        (
            "wso_private.wso_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid)",
            "wso_private.account_original_validate_domain_credential",
            "wso_domain_owner",
            "BEGIN",
            "BEGIN IF public.wso_tvt_managed_connection(p_connection) THEN RETURN false; END IF;",
        ),
    ):
        name, types = signature.split("(", 1)
        replacement = guard.replace("'", "''")
        escaped = needle.replace("'", "''")
        op.execute(f"""DO $$ DECLARE source text; BEGIN
          SELECT pg_get_functiondef('{signature}'::regprocedure) INTO source;
          IF (length(source)-length(replace(source,'{escaped}','')))/length('{escaped}')<>1 THEN RAISE EXCEPTION 'unexpected domain credential definition'; END IF;
          EXECUTE replace(source,'{name}(', '{backup}(');
          EXECUTE replace(source,'{escaped}', '{replacement}');
          END $$;
          ALTER FUNCTION {backup}({types} OWNER TO {owner};
          REVOKE ALL ON FUNCTION {backup}({types} FROM {RUNTIME};
        """)
    op.execute(
        f"GRANT EXECUTE ON FUNCTION wso_private.account_original_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid) TO {OWNER}"
    )
    function(
        "public.wso_tvt_auxiliary(p_id uuid)",
        "SELECT EXISTS(SELECT 1 FROM wso_private.tvt_account_storage WHERE connection_id=p_id AND kind<>'USER')",
        "boolean",
        "wso_app,wso_migrator",
        "sql",
    )
    op.execute(
        "CREATE POLICY account_hide_auxiliary ON public.connections AS RESTRICTIVE FOR SELECT TO wso_app USING(NOT public.wso_tvt_auxiliary(id))"
    )
    # Preserve exact foundation body/owner/ACL, adding only the auxiliary guard.
    op.execute("""DO $$ DECLARE source text; BEGIN
      SELECT pg_get_functiondef('public.wso_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text)'::regprocedure) INTO source;
      IF position('BEGIN' in source)=0 THEN RAISE EXCEPTION 'unexpected connection mutator'; END IF;
      EXECUTE replace(source,'public.wso_mutate_connection(', 'wso_private.account_original_mutate_connection(');
      EXECUTE replace(source,'BEGIN', 'BEGIN IF public.wso_tvt_auxiliary(p_id) THEN RAISE EXCEPTION ''connection denied'' USING ERRCODE=''42501''; END IF;');
      END $$;
      ALTER FUNCTION wso_private.account_original_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text) OWNER TO wso_migrator;
      REVOKE ALL ON FUNCTION wso_private.account_original_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text) FROM PUBLIC,wso_app,wso_identity_bootstrap,wso_web_session,wso_connection_worker,wso_job_worker,wso_dispatcher,wso_asset_maintenance;
    """)
    function(
        "public.wso_tvt_account_describe(p_identity uuid)",
        DESCRIBE,
        "TABLE(identity_id uuid,region text,brand text,generation bigint)",
        "wso_app",
    )
    function(
        "public.wso_tvt_account_issue(p_purpose text,p_region text,p_brand text,p_identity uuid,p_kind text,p_generation bigint)",
        ISSUE,
        "text",
        "wso_app",
    )
    function(
        "wso_private.wso_tvt_account_check(p_lease text,p_purpose text,p_authority boolean DEFAULT true)",
        CHECK,
        "wso_private.tvt_account_tickets",
        "",
    )
    function(
        "public.wso_tvt_account_redeem(p_ticket text,p_lease text)", REDEEM, "boolean"
    )
    function(
        "public.wso_tvt_account_context(p_lease text,p_purpose text)",
        CONTEXT,
        "TABLE(tenant_id uuid,actor_id uuid,identity_id uuid,region text,brand text,generation bigint)",
    )
    function(
        "public.wso_tvt_account_publish(p_lease text,p_identity uuid,p_user_connection uuid,p_user_version uuid,p_user_nonce bytea,p_user_cipher bytea,p_p2p_connection uuid,p_p2p_version uuid,p_p2p_nonce bytea,p_p2p_cipher bytea)",
        PUBLISH,
        "uuid",
    )
    function(
        "public.wso_tvt_account_secret(p_lease text,p_purpose text)",
        SECRET,
        "TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea,generation bigint)",
    )
    function(
        "public.wso_tvt_account_renew_claim(p_lease text,p_attempt uuid)", CLAIM, "text"
    )
    function(
        "public.wso_tvt_account_renew_publish(p_lease text,p_attempt uuid,p_version uuid,p_nonce bytea,p_cipher bytea)",
        ROTATE,
        "bigint",
    )
    function(
        "public.wso_tvt_account_close(p_identity uuid)",
        LOCAL_CLOSE,
        "boolean",
        "wso_app",
    )
    function("public.wso_tvt_account_revoke(p_lease text)", REVOKE, "boolean")
    function(
        "public.wso_tvt_challenge_publish(p_lease text,p_id uuid,p_connection uuid,p_version uuid,p_nonce bytea,p_cipher bytea)",
        CHALLENGE_PUBLISH,
        "uuid",
    )
    function(
        "public.wso_tvt_challenge_consume(p_lease text,p_id uuid)",
        CHALLENGE_CONSUME,
        "TABLE(tenant_id uuid,connection_id uuid,version_id uuid,nonce bytea,ciphertext bytea)",
    )


DESCRIBE = """
DECLARE f record;
BEGIN
 SELECT * INTO f FROM public.wso_authorize_domain('TVT',NULL,NULL,NULL,NULL,NULL,'account.login');
 IF NOT FOUND THEN RETURN; END IF;
 RETURN QUERY SELECT i.id,i.region::text,i.brand::text,t.generation
 FROM wso_private.tvt_identities i JOIN wso_private.tvt_account_sessions s ON s.identity_id=i.id AND s.tenant_id=i.tenant_id
 JOIN wso_private.tvt_account_tokens t ON t.identity_id=i.id AND t.tenant_id=i.tenant_id AND t.kind='USER'
 WHERE i.id=p_identity AND i.tenant_id=f.tenant_id AND s.actor_id=f.actor_id AND s.state='READY' AND i.active;
END;
"""
ISSUE = """
DECLARE f record; token text; cap uuid; ident record; conn uuid; ver uuid; gen bigint; seq bigint:=0; lf record;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_purpose IS NULL OR p_purpose NOT IN ('login','image','check','profile','renew','logout')
 OR p_kind IS NULL OR p_kind NOT IN ('USER','P2P','DEVICE') OR p_region IS NULL OR p_brand IS NULL
 OR p_region!~'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$' OR p_brand!~'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$' THEN RETURN NULL; END IF;
 IF p_purpose IN ('login','image','check') THEN
   IF p_identity IS NOT NULL OR p_kind<>'USER' OR p_generation IS DISTINCT FROM 0 THEN RETURN NULL; END IF;
   SELECT * INTO f FROM public.wso_authorize_domain('TVT',NULL,NULL,NULL,NULL,NULL,'account.login');
   IF NOT FOUND THEN RETURN NULL; END IF;
 ELSE
   IF p_identity IS NULL THEN RETURN NULL; END IF;
   SELECT * INTO f FROM public.wso_authorize_domain('TVT',NULL,NULL,NULL,NULL,NULL,'account.login');
   IF NOT FOUND THEN RETURN NULL; END IF;
   SELECT i.* INTO ident FROM wso_private.tvt_identities i JOIN wso_private.tvt_account_sessions s ON s.identity_id=i.id AND s.tenant_id=i.tenant_id
     WHERE i.id=p_identity AND i.tenant_id=f.tenant_id AND s.actor_id=f.actor_id AND s.state='READY' AND i.active;
   IF NOT FOUND OR ident.region<>p_region OR ident.brand<>p_brand THEN RETURN NULL; END IF;
   IF p_purpose<>'logout' THEN
     SELECT * INTO f FROM public.wso_authorize_domain('TVT',p_identity,NULL,NULL,NULL,NULL,'account.read');
     IF NOT FOUND THEN RETURN NULL; END IF;
     SELECT t.connection_id,t.version_id,t.generation,t.renewal_sequence INTO conn,ver,gen,seq FROM wso_private.tvt_account_tokens t
       WHERE t.tenant_id=f.tenant_id AND t.identity_id=p_identity AND t.kind=p_kind;
     IF NOT FOUND OR gen IS DISTINCT FROM p_generation OR p_kind<>'USER' THEN RETURN NULL; END IF;
     cap:=gen_random_uuid();
     INSERT INTO wso_private.domain_credential_capabilities(id,tenant_id,actor_id,connection_id,generation,version_id,purpose,facts,expires_at)
       VALUES(cap,f.tenant_id,f.actor_id,conn,f.connection_generation,ver,'account.read',to_jsonb(f),least(f.valid_until,clock_timestamp()+interval '30 seconds'));
   END IF;
 END IF;
 IF p_purpose='logout' THEN
   SELECT * INTO lf FROM public.wso_authorize_domain('TVT',p_identity,NULL,NULL,NULL,NULL,'account.read');
   IF FOUND THEN
     SELECT tok.connection_id,tok.version_id,tok.generation INTO conn,ver,gen FROM wso_private.tvt_account_tokens tok WHERE tok.tenant_id=lf.tenant_id AND tok.identity_id=p_identity AND tok.kind='USER';
     IF FOUND THEN
       cap:=gen_random_uuid();
       INSERT INTO wso_private.domain_credential_capabilities(id,tenant_id,actor_id,connection_id,generation,version_id,purpose,facts,expires_at)
       VALUES(cap,lf.tenant_id,lf.actor_id,conn,lf.connection_generation,ver,'account.read',to_jsonb(lf),least(lf.valid_until,clock_timestamp()+interval '30 seconds'));
       p_generation:=gen;
     END IF;
   END IF;
 END IF;
 token:=replace(gen_random_uuid()::text,'-','')||replace(gen_random_uuid()::text,'-','');
 INSERT INTO wso_private.tvt_account_tickets(digest,tenant_id,actor_id,actor_role,purpose,region,brand,identity_id,kind,generation,renewal_sequence,cap_id,expires_at)
 VALUES(sha256(convert_to(token,'UTF8')),f.tenant_id,f.actor_id,f.role,p_purpose,p_region,p_brand,p_identity,p_kind,p_generation,seq,cap,clock_timestamp()+interval '30 seconds');
 RETURN token;
END;
"""
CHECK = """
DECLARE t wso_private.tvt_account_tickets; v record; i record;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_lease IS NULL OR length(p_lease)<>64 THEN RETURN NULL; END IF;
 SELECT * INTO t FROM wso_private.tvt_account_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8')) AND purpose=p_purpose AND expires_at>clock_timestamp() FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM 1 FROM public.memberships WHERE tenant_id=t.tenant_id AND user_id=t.actor_id AND role=t.actor_role FOR SHARE;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF t.identity_id IS NOT NULL THEN
   SELECT s.* INTO i FROM wso_private.tvt_account_sessions s JOIN wso_private.tvt_identities d ON d.id=s.identity_id AND d.tenant_id=s.tenant_id
     WHERE s.identity_id=t.identity_id AND s.tenant_id=t.tenant_id AND s.actor_id=t.actor_id AND s.state='READY' AND d.active AND d.region=t.region AND d.brand=t.brand FOR SHARE OF s,d;
   IF NOT FOUND THEN RETURN NULL; END IF;
   IF p_authority THEN
     SELECT * INTO v FROM wso_private.tvt_account_tokens WHERE tenant_id=t.tenant_id AND identity_id=t.identity_id AND kind=t.kind FOR SHARE;
     IF NOT FOUND OR v.generation<>t.generation OR t.kind<>'USER' OR t.cap_id IS NULL THEN RETURN NULL; END IF;
     IF NOT wso_private.account_original_validate_domain_credential(t.cap_id,t.tenant_id,t.actor_id,v.connection_id,v.generation,v.version_id) THEN RETURN NULL; END IF;
   END IF;
 END IF;
 RETURN t;
END;
"""
REDEEM = """
DECLARE t wso_private.tvt_account_tickets;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR p_lease!~'^[0-9a-f]{64}$' OR p_ticket!~'^[0-9a-f]{64}$' THEN RETURN false; END IF;
 UPDATE wso_private.tvt_account_tickets SET lease_digest=sha256(convert_to(p_lease,'UTF8')) WHERE digest=sha256(convert_to(p_ticket,'UTF8')) AND lease_digest IS NULL AND expires_at>clock_timestamp() RETURNING * INTO t;
 IF NOT FOUND THEN RETURN false; END IF;
 t:=wso_private.wso_tvt_account_check(p_lease,t.purpose,t.purpose NOT IN ('logout','renew'));
 RETURN t.digest IS NOT NULL;
END;
"""
CONTEXT = """
DECLARE t wso_private.tvt_account_tickets;
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,p_purpose,p_purpose NOT IN ('logout','renew'));
 IF t.digest IS NULL THEN RETURN; END IF;
 RETURN QUERY SELECT t.tenant_id,t.actor_id,t.identity_id,t.region::text,t.brand::text,t.generation;
END;
"""
PUBLISH = """
DECLARE t wso_private.tvt_account_tickets; expiry timestamptz:=clock_timestamp()+interval '5 minutes';
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,'login');
 IF t.digest IS NULL OR p_identity IS NULL OR p_user_connection IS NULL OR p_user_version IS NULL OR p_user_nonce IS NULL OR p_user_cipher IS NULL
 OR ((p_p2p_connection IS NULL) IS DISTINCT FROM (p_p2p_version IS NULL)) OR ((p_p2p_connection IS NULL) IS DISTINCT FROM (p_p2p_nonce IS NULL)) OR ((p_p2p_connection IS NULL) IS DISTINCT FROM (p_p2p_cipher IS NULL)) THEN RETURN NULL; END IF;
 INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(p_user_connection,t.tenant_id,'TVT_ACCOUNT','TVT account','Private account','NOT_VERIFIED',1);
 INSERT INTO wso_private.connection_secrets VALUES(p_user_connection,t.tenant_id,p_user_version,p_user_nonce,p_user_cipher);
 INSERT INTO wso_private.tvt_identities(id,tenant_id,connection_id,region,brand) VALUES(p_identity,t.tenant_id,p_user_connection,t.region,t.brand);
 INSERT INTO wso_private.tvt_account_sessions(identity_id,tenant_id,actor_id,state) VALUES(p_identity,t.tenant_id,t.actor_id,'READY');
 INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(p_user_connection,t.tenant_id,'USER');
 INSERT INTO wso_private.tvt_account_tokens(id,tenant_id,identity_id,kind,connection_id,version_id,generation) VALUES(gen_random_uuid(),t.tenant_id,p_identity,'USER',p_user_connection,p_user_version,1);
 IF p_p2p_connection IS NOT NULL THEN
   INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(p_p2p_connection,t.tenant_id,'TVT_ACCOUNT','Private token','Private token','NOT_VERIFIED',1);
   INSERT INTO wso_private.domain_credential_connections(connection_id,tenant_id) VALUES(p_p2p_connection,t.tenant_id);
   INSERT INTO wso_private.connection_secrets VALUES(p_p2p_connection,t.tenant_id,p_p2p_version,p_p2p_nonce,p_p2p_cipher);
   INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(p_p2p_connection,t.tenant_id,'P2P');
   INSERT INTO wso_private.tvt_account_tokens(id,tenant_id,identity_id,kind,connection_id,version_id,generation) VALUES(gen_random_uuid(),t.tenant_id,p_identity,'P2P',p_p2p_connection,p_p2p_version,1);
 END IF;
 INSERT INTO wso_private.tvt_identity_grants(id,tenant_id,identity_id,actor_id,action,revision,expires_at) VALUES(gen_random_uuid(),t.tenant_id,p_identity,t.actor_id,'account.read',1,expiry);
 INSERT INTO wso_private.tvt_upstream_grants(id,tenant_id,identity_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(gen_random_uuid(),t.tenant_id,p_identity,'account.read',true,1,1,clock_timestamp(),expiry);
 INSERT INTO wso_private.tvt_capability_snapshots(id,tenant_id,identity_id,action,verified,connection_generation,revision,observed_at,expires_at) VALUES(gen_random_uuid(),t.tenant_id,p_identity,'account.read',true,1,1,clock_timestamp(),expiry);
 DELETE FROM wso_private.tvt_account_tickets WHERE digest=t.digest;
 RETURN p_identity;
END;
"""
SECRET = """
DECLARE t wso_private.tvt_account_tickets; v record;
BEGIN
 IF p_purpose NOT IN ('profile','renew','logout') THEN RETURN; END IF;
 t:=wso_private.wso_tvt_account_check(p_lease,p_purpose);
 IF t.digest IS NULL THEN RETURN; END IF;
 SELECT tok.* INTO v FROM wso_private.tvt_account_tokens tok WHERE tok.identity_id=t.identity_id AND tok.tenant_id=t.tenant_id AND tok.kind='USER' FOR SHARE;
 RETURN QUERY SELECT s.tenant_id,s.connection_id,s.version_id,s.nonce,s.ciphertext,v.generation FROM wso_private.connection_secrets s
   WHERE s.connection_id=v.connection_id AND s.tenant_id=t.tenant_id AND s.version_id=v.version_id FOR SHARE OF s;
END;
"""
CLAIM = """
DECLARE t wso_private.tvt_account_tickets; v record;
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,'renew',false);
 IF t.digest IS NULL OR t.kind<>'USER' OR t.cap_id IS NULL OR p_attempt IS NULL THEN RETURN 'DENIED'; END IF;
 SELECT * INTO v FROM wso_private.tvt_account_tokens WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id AND kind=t.kind FOR UPDATE;
 IF NOT FOUND THEN RETURN 'DENIED'; END IF;
 IF v.generation<>t.generation OR v.renewal_sequence<>t.renewal_sequence THEN
   PERFORM 1 FROM wso_private.tvt_identity_grants g JOIN wso_private.tvt_upstream_grants u USING(tenant_id,identity_id,action)
   JOIN wso_private.tvt_capability_snapshots c USING(tenant_id,identity_id,action)
   JOIN public.connections conn ON conn.id=v.connection_id AND conn.tenant_id=t.tenant_id
   WHERE g.tenant_id=t.tenant_id AND g.identity_id=t.identity_id AND g.actor_id=t.actor_id AND g.action='account.read' AND g.link_id IS NULL
   AND u.device_id IS NULL AND c.device_id IS NULL AND u.channel_id IS NULL AND c.channel_id IS NULL
   AND u.verified AND c.verified AND u.observed_at<=clock_timestamp() AND c.observed_at<=clock_timestamp() AND u.connection_generation=v.generation AND c.connection_generation=v.generation
   AND conn.generation=v.generation AND conn.status='NOT_VERIFIED'
   AND least(g.expires_at,u.expires_at,c.expires_at)>clock_timestamp() FOR SHARE OF g,u,c,conn;
   IF NOT FOUND THEN RETURN 'DENIED'; END IF;
   RETURN 'CURRENT:'||v.generation::text;
 END IF;
 IF NOT wso_private.account_original_validate_domain_credential(t.cap_id,t.tenant_id,t.actor_id,v.connection_id,v.generation,v.version_id) THEN RETURN 'DENIED'; END IF;
 IF v.renewal_state<>'IDLE' THEN RETURN 'UNKNOWN'; END IF;
 UPDATE wso_private.tvt_account_tokens SET renewal_attempt=p_attempt,renewal_state='INFLIGHT' WHERE id=v.id;
 RETURN 'CLAIMED';
END;
"""
ROTATE = """
DECLARE t wso_private.tvt_account_tickets; v record; next_gen bigint; expiry timestamptz:=clock_timestamp()+interval '5 minutes';
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,'renew');
 IF t.digest IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO v FROM wso_private.tvt_account_tokens WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id AND kind=t.kind FOR UPDATE;
 IF NOT FOUND OR v.generation<>t.generation OR v.renewal_attempt IS DISTINCT FROM p_attempt OR v.renewal_state<>'INFLIGHT' THEN RETURN NULL; END IF;
 IF p_version IS NULL THEN
   IF p_nonce IS NOT NULL OR p_cipher IS NOT NULL THEN RETURN NULL; END IF;
   next_gen:=v.generation;
   UPDATE wso_private.tvt_account_tokens SET renewal_state='IDLE',renewal_attempt=NULL,renewal_sequence=renewal_sequence+1 WHERE id=v.id;
 ELSE
   IF p_nonce IS NULL OR p_cipher IS NULL THEN RETURN NULL; END IF;
   next_gen:=v.generation+1;
   UPDATE public.connections SET generation=next_gen WHERE id=v.connection_id AND tenant_id=t.tenant_id AND generation=v.generation AND status='NOT_VERIFIED';
   IF NOT FOUND THEN RETURN NULL; END IF;
   UPDATE wso_private.connection_secrets SET version_id=p_version,nonce=p_nonce,ciphertext=p_cipher WHERE connection_id=v.connection_id AND tenant_id=t.tenant_id AND version_id=v.version_id;
   IF NOT FOUND THEN RAISE EXCEPTION 'account unavailable'; END IF;
   UPDATE wso_private.tvt_account_tokens SET version_id=p_version,generation=next_gen,renewal_state='IDLE',renewal_attempt=NULL,renewal_sequence=renewal_sequence+1 WHERE id=v.id;
   DELETE FROM wso_private.connection_handles WHERE connection_id=v.connection_id;
   DELETE FROM wso_private.connection_leases WHERE connection_id=v.connection_id;
 END IF;
 UPDATE wso_private.tvt_identity_grants SET revision=revision+1,expires_at=expiry WHERE tenant_id=t.tenant_id AND identity_id=t.identity_id AND actor_id=t.actor_id AND action='account.read';
 UPDATE wso_private.tvt_upstream_grants SET revision=revision+1,connection_generation=next_gen,observed_at=clock_timestamp(),expires_at=expiry WHERE tenant_id=t.tenant_id AND identity_id=t.identity_id AND action='account.read';
 UPDATE wso_private.tvt_capability_snapshots SET revision=revision+1,connection_generation=next_gen,observed_at=clock_timestamp(),expires_at=expiry WHERE tenant_id=t.tenant_id AND identity_id=t.identity_id AND action='account.read';
 RETURN next_gen;
END;
"""
REVOKE = """
DECLARE t wso_private.tvt_account_tickets; v record;
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,'logout',false);
 IF t.digest IS NULL THEN RETURN false; END IF;
 FOR v IN SELECT * FROM wso_private.tvt_account_tokens WHERE tenant_id=t.tenant_id AND identity_id=t.identity_id ORDER BY connection_id FOR UPDATE LOOP
   UPDATE public.connections SET status='DISCONNECTED',generation=generation+1 WHERE id=v.connection_id AND tenant_id=t.tenant_id;
   DELETE FROM wso_private.connection_secrets WHERE connection_id=v.connection_id;
   DELETE FROM wso_private.connection_handles WHERE connection_id=v.connection_id;
   DELETE FROM wso_private.connection_leases WHERE connection_id=v.connection_id;
   INSERT INTO wso_private.connection_revocations(tenant_id,connection_id,generation,reason) VALUES(t.tenant_id,v.connection_id,v.generation,'tvt_logout');
 END LOOP;
 UPDATE wso_private.tvt_account_sessions SET state='CLOSED' WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id;
 UPDATE wso_private.tvt_identities SET active=false WHERE id=t.identity_id AND tenant_id=t.tenant_id;
 DELETE FROM wso_private.tvt_identity_grants WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id;
 DELETE FROM wso_private.tvt_account_tickets WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id;
 RETURN true;
END;
"""
LOCAL_CLOSE = REVOKE.replace(
    "t:=wso_private.wso_tvt_account_check(p_lease,'logout',false);\n IF t.digest IS NULL THEN RETURN false; END IF;",
    """SELECT f.tenant_id,f.actor_id INTO t.tenant_id,t.actor_id FROM public.wso_authorize_domain('TVT',NULL,NULL,NULL,NULL,NULL,'account.login') f;
 IF NOT FOUND THEN RETURN false; END IF;
 t.identity_id:=p_identity;
 PERFORM 1 FROM public.memberships WHERE tenant_id=t.tenant_id AND user_id=t.actor_id FOR SHARE;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM 1 FROM wso_private.tvt_account_sessions WHERE identity_id=t.identity_id AND tenant_id=t.tenant_id AND actor_id=t.actor_id FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM wso_private.tvt_account_sessions WHERE identity_id=t.identity_id AND state='CLOSED') THEN RETURN true; END IF;""",
)
CHALLENGE_PUBLISH = """
DECLARE t wso_private.tvt_account_tickets;
BEGIN
 t:=wso_private.wso_tvt_account_check(p_lease,'image');
 IF t.digest IS NULL THEN RETURN NULL; END IF;
 INSERT INTO public.connections(id,tenant_id,kind,alias,site,status,generation) VALUES(p_connection,t.tenant_id,'TVT_ACCOUNT','Private challenge','Private challenge','NOT_VERIFIED',1);
 INSERT INTO wso_private.domain_credential_connections(connection_id,tenant_id) VALUES(p_connection,t.tenant_id);
 INSERT INTO wso_private.tvt_account_storage(connection_id,tenant_id,kind) VALUES(p_connection,t.tenant_id,'CHALLENGE');
 INSERT INTO wso_private.connection_secrets VALUES(p_connection,t.tenant_id,p_version,p_nonce,p_cipher);
 INSERT INTO wso_private.tvt_account_challenges(id,tenant_id,actor_id,region,brand,connection_id,expires_at) VALUES(p_id,t.tenant_id,t.actor_id,t.region,t.brand,p_connection,clock_timestamp()+interval '120 seconds');
 DELETE FROM wso_private.tvt_account_tickets WHERE digest=t.digest;
 RETURN p_id;
END;
"""
CHALLENGE_CONSUME = """
DECLARE t wso_private.tvt_account_tickets; c record;
BEGIN
 SELECT * INTO t FROM wso_private.tvt_account_tickets WHERE lease_digest=sha256(convert_to(p_lease,'UTF8'));
 IF NOT FOUND OR t.purpose NOT IN ('login','check') THEN RETURN; END IF;
 t:=wso_private.wso_tvt_account_check(p_lease,t.purpose);
 IF t.digest IS NULL THEN RETURN; END IF;
 UPDATE wso_private.tvt_account_challenges ch SET consumed=true WHERE ch.id=p_id AND ch.tenant_id=t.tenant_id AND ch.actor_id=t.actor_id AND ch.region=t.region AND ch.brand=t.brand AND NOT ch.consumed AND ch.expires_at>clock_timestamp() RETURNING ch.* INTO c;
 IF NOT FOUND THEN RETURN; END IF;
 RETURN QUERY DELETE FROM wso_private.connection_secrets s WHERE s.connection_id=c.connection_id AND s.tenant_id=t.tenant_id RETURNING s.tenant_id,s.connection_id,s.version_id,s.nonce,s.ciphertext;
END;
"""


def downgrade():
    # Existing connection rows/secret bytes/sticky mappings are retained. They
    # cannot become legacy credentials after account metadata is removed.
    for signature, backup in (
        (
            "public.wso_issue_domain_connection_handle(jsonb,text,timestamptz)",
            "wso_private.account_original_issue_domain_connection_handle",
        ),
        (
            "wso_private.wso_validate_domain_credential(uuid,uuid,uuid,uuid,bigint,uuid)",
            "wso_private.account_original_validate_domain_credential",
        ),
    ):
        name, types = signature.split("(", 1)
        op.execute(f"""DO $$ DECLARE source text; BEGIN
          SELECT pg_get_functiondef('{backup}({types}'::regprocedure) INTO source;
          EXECUTE replace(source,'{backup}(', '{name}(');
          END $$;
          DROP FUNCTION {backup}({types};
        """)
    op.execute("""DO $$ DECLARE source text; BEGIN
      SELECT pg_get_functiondef('wso_private.account_original_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text)'::regprocedure) INTO source;
      EXECUTE replace(source,'wso_private.account_original_mutate_connection(', 'public.wso_mutate_connection(');
      END $$;
      DROP FUNCTION wso_private.account_original_mutate_connection(uuid,bigint,text,jsonb,uuid,bytea,bytea,text);
      DROP POLICY account_hide_auxiliary ON public.connections;
    """)
    for name in (
        "wso_tvt_account_describe",
        "wso_tvt_account_issue",
        "wso_tvt_account_redeem",
        "wso_tvt_account_context",
        "wso_tvt_account_publish",
        "wso_tvt_account_secret",
        "wso_tvt_account_renew_claim",
        "wso_tvt_account_renew_publish",
        "wso_tvt_account_revoke",
        "wso_tvt_account_close",
        "wso_tvt_challenge_publish",
        "wso_tvt_challenge_consume",
        "wso_tvt_auxiliary",
        "wso_tvt_managed_connection",
    ):
        op.execute(
            f"DO $$ DECLARE f regprocedure; BEGIN FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname='{name}' LOOP EXECUTE 'DROP FUNCTION '||f; END LOOP; END $$"
        )
    op.execute("DROP FUNCTION wso_private.wso_tvt_account_check(text,text,boolean)")
    for table in reversed(TABLES):
        # storage is referenced by tokens/challenges, handled after them below
        if table != "tvt_account_storage":
            op.execute(f"DROP TABLE wso_private.{table}")
    op.execute("DROP TABLE wso_private.tvt_account_storage")
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION public.wso_authorize_domain(text,uuid,uuid,uuid,uuid,uuid,text) FROM {OWNER}"
    )
    for table, permissions in ACCESS.items():
        op.execute(f"DROP POLICY account_session_access ON {table}")
        op.execute(f"REVOKE {permissions} ON {table} FROM {OWNER}")
    op.execute(f"REVOKE USAGE ON SCHEMA public,wso_private FROM {OWNER}")
    # Roles are cluster-wide and deliberately not dropped by a database down.
