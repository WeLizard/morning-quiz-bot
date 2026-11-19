"""Unified durable intent/render permits; retained source history is untouched."""
from alembic import op
from sqlalchemy import DDL

revision = '20261116_0050'
down_revision = '20261116_0049'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("LOCK TABLE night_ai_bindings IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM night_ai_bindings WHERE inflight_job_id IS NOT NULL OR inflight_lease_until IS NOT NULL) THEN
        RAISE EXCEPTION 'night_ai_dispatch_drain_required: retained legacy lease; no rows changed';
      END IF;
    END $$""")
    op.execute("ALTER TABLE night_ai_job_bindings ADD CONSTRAINT uq_nai_job_dispatch_source UNIQUE(job_id,game_id,binding_id,epoch)")
    op.execute("ALTER TABLE night_ai_intent_requests ADD CONSTRAINT uq_nai_intent_dispatch_source UNIQUE(id,game_id,binding_id,epoch)")
    op.execute(DDL(TABLE_DDL))
    for statement in INDEX_DDL: op.execute(DDL(statement))
    op.execute("ALTER TABLE night_ai_bindings ADD COLUMN inflight_permit_id UUID")
    op.execute("ALTER TABLE night_ai_bindings DROP CONSTRAINT ck_nai_binding_health")
    op.execute("""ALTER TABLE night_ai_bindings ADD CONSTRAINT ck_nai_binding_health CHECK
      (health IN ('ok','auth_error','config_error') AND inflight_job_id IS NULL AND
       ((inflight_permit_id IS NULL)=(inflight_lease_until IS NULL)))""")
    op.execute("""ALTER TABLE night_ai_bindings ADD CONSTRAINT fk_nai_binding_permit
      FOREIGN KEY(inflight_permit_id,id,game_id,epoch) REFERENCES night_ai_dispatch_attempts(id,binding_id,game_id,epoch)
      ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED""")
    op.execute(DDL(NEW_GUARD))
    _guards()


def downgrade():
    op.execute("LOCK TABLE night_ai_dispatch_attempts,night_ai_bindings,night_narrator_limits IN ACCESS EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM night_ai_dispatch_attempts) OR EXISTS(
        SELECT 1 FROM night_narrator_limits WHERE scope LIKE 'nai:%' AND
        (reserved_requests<>0 OR reserved_tokens<>0 OR failures<>0 OR circuit_open_until IS NOT NULL)) THEN
        RAISE EXCEPTION 'night_ai_dispatch_retention_required: attempts or counters exist';
      END IF;
    END $$""")
    op.execute("DROP TRIGGER nai_dispatch_binding_slot ON night_ai_bindings")
    op.execute("DROP TRIGGER nai_dispatch_render_slot ON night_render_jobs")
    op.execute("ALTER TABLE night_ai_bindings DROP CONSTRAINT fk_nai_binding_permit")
    op.execute("DROP TABLE night_ai_dispatch_attempts")
    op.execute("DROP FUNCTION night_ai_dispatch_guard()")
    op.execute("DROP FUNCTION night_ai_dispatch_slot()")
    op.execute("DROP FUNCTION night_ai_dispatch_caps_hash(jsonb)")
    op.execute("ALTER TABLE night_ai_bindings DROP CONSTRAINT ck_nai_binding_health")
    op.execute("ALTER TABLE night_ai_bindings DROP COLUMN inflight_permit_id")
    op.execute("""ALTER TABLE night_ai_bindings ADD CONSTRAINT ck_nai_binding_health CHECK
      (health IN ('ok','auth_error','config_error') AND ((inflight_job_id IS NULL)=(inflight_lease_until IS NULL)))""")
    op.execute("ALTER TABLE night_ai_job_bindings DROP CONSTRAINT uq_nai_job_dispatch_source")
    op.execute("ALTER TABLE night_ai_intent_requests DROP CONSTRAINT uq_nai_intent_dispatch_source")
    op.execute(DDL(OLD_GUARD))


def _guards():
    # Caps are a closed flat codec (ASCII schema + integers); key order is the
    # exact canonical Python encoding, independent of JSONB storage key order.
    op.execute(DDL("""CREATE FUNCTION night_ai_dispatch_caps_hash(doc jsonb) RETURNS text
      LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT encode(sha256(convert_to(
        '{' || string_agg(to_jsonb(entry.key)::text || ':' || entry.value::text, ',' ORDER BY entry.key COLLATE "C") || '}',
        'UTF8')), 'hex') FROM jsonb_each(doc) AS entry(key,value) $$"""))
    op.execute(DDL("""CREATE FUNCTION night_ai_dispatch_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE b night_ai_bindings; src record; prior night_ai_dispatch_attempts; debit jsonb;
      expected_scopes text[]; actual_scopes text[]; adapter text;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'night_ai_dispatch_history_retained'; END IF;
      IF TG_OP='UPDATE' THEN
        IF to_jsonb(OLD)=to_jsonb(NEW) THEN RETURN NEW; END IF;
        IF OLD.status NOT IN ('reserved','sending') OR
          (to_jsonb(OLD)-ARRAY['status','oauth_claimed_at','sent_at','finished_at','retry_after','error_code','response_hash','usage'])
            IS DISTINCT FROM
          (to_jsonb(NEW)-ARRAY['status','oauth_claimed_at','sent_at','finished_at','retry_after','error_code','response_hash','usage'])
          OR (OLD.oauth_claimed_at IS NOT NULL AND OLD.oauth_claimed_at IS DISTINCT FROM NEW.oauth_claimed_at)
          OR (OLD.sent_at IS NOT NULL AND OLD.sent_at IS DISTINCT FROM NEW.sent_at)
          OR (OLD.status='sending' AND NEW.status NOT IN ('succeeded','failed','cancelled','expired'))
          OR (NEW.status='reserved' AND (OLD.status<>'reserved' OR NEW.oauth_claimed_at IS NULL
              OR OLD.oauth_claimed_at IS NOT NULL))
          OR (NEW.status='succeeded' AND OLD.status<>'sending') THEN
          RAISE EXCEPTION 'night_ai_dispatch_transition';
        END IF;
      END IF;
      IF NEW.status IN ('reserved','sending') AND (NEW.response_hash IS NOT NULL OR NEW.usage IS NOT NULL
          OR NEW.error_code IS NOT NULL OR NEW.retry_after IS NOT NULL) THEN
        RAISE EXCEPTION 'night_ai_dispatch_active_outcome';
      END IF;
      SELECT r.config->>'adapter' INTO adapter FROM night_ai_profile_revisions r JOIN night_ai_bindings profile_binding
        ON profile_binding.profile_id=r.profile_id AND profile_binding.profile_revision=r.revision WHERE profile_binding.id=NEW.binding_id;
      IF NEW.oauth_claimed_at IS NOT NULL AND (adapter IS DISTINCT FROM 'gigachat_chat'
          OR NEW.oauth_claimed_at>=NEW.network_deadline) THEN
        RAISE EXCEPTION 'night_ai_dispatch_oauth';
      END IF;
      IF NEW.retry_after IS NOT NULL AND NEW.error_code='auth_error' AND
          (adapter IS DISTINCT FROM 'gigachat_chat' OR NEW.sent_at IS NULL) THEN
        RAISE EXCEPTION 'night_ai_dispatch_retry';
      END IF;
      IF NEW.usage IS NOT NULL AND (jsonb_typeof(NEW.usage)<>'object'
          OR NOT (NEW.usage ?& ARRAY['input_tokens','output_tokens'])
          OR NEW.usage-ARRAY['input_tokens','output_tokens']<>'{}'::jsonb
          OR (NEW.usage->>'input_tokens') !~ '^(0|[1-9][0-9]{0,18})$'
          OR (NEW.usage->>'output_tokens') !~ '^(0|[1-9][0-9]{0,18})$'
          OR jsonb_typeof(NEW.usage->'input_tokens')<>'number' OR jsonb_typeof(NEW.usage->'output_tokens')<>'number'
          OR (NEW.usage->>'input_tokens')::numeric>9223372036854775807
          OR (NEW.usage->>'output_tokens')::numeric>9223372036854775807) THEN
        RAISE EXCEPTION 'night_ai_dispatch_usage';
      END IF;
      IF TG_OP='UPDATE' THEN RETURN NEW; END IF;
      IF NEW.status<>'reserved' OR NEW.oauth_claimed_at IS NOT NULL OR NEW.sent_at IS NOT NULL THEN
        RAISE EXCEPTION 'night_ai_dispatch_initial_status';
      END IF;
      SELECT binding_row.* INTO b FROM night_ai_bindings binding_row WHERE binding_row.id=NEW.binding_id;
      IF b.status IS DISTINCT FROM 'active' OR b.health<>'ok' OR b.valid_until<=NEW.reserved_at
          OR b.config_hash<>NEW.config_hash OR night_ai_dispatch_caps_hash(b.caps)<>NEW.caps_hash
          OR NOT EXISTS(SELECT 1 FROM night_ai_game_control c WHERE c.game_id=NEW.game_id
            AND c.epoch=NEW.epoch AND c.current_binding_id=NEW.binding_id) THEN
        RAISE EXCEPTION 'night_ai_dispatch_binding_pin';
      END IF;
      IF NEW.source_kind='intent' THEN
        SELECT intent_source.status,intent_source.expires_at,intent_source.token INTO src
          FROM night_ai_intent_requests intent_source WHERE intent_source.id=NEW.intent_id;
        IF NOT FOUND OR src.status<>'prepared' OR src.expires_at<>NEW.source_expires_at
          OR src.token->>'config_hash' IS DISTINCT FROM NEW.config_hash
          OR src.token->>'caps_hash' IS DISTINCT FROM NEW.caps_hash THEN
          RAISE EXCEPTION 'night_ai_dispatch_intent_pin';
        END IF;
      ELSE
        SELECT j.status,j.expires_at INTO src FROM night_render_jobs j JOIN night_ai_job_bindings a ON a.job_id=j.job_id
          WHERE j.job_id=NEW.job_id AND j.game_id=NEW.game_id AND a.game_id=j.game_id;
        IF NOT FOUND OR src.status NOT IN ('pending','retry','leased') OR src.expires_at<>NEW.source_expires_at
          OR EXISTS(SELECT 1 FROM night_renderings existing_render WHERE existing_render.job_id=NEW.job_id) THEN
          RAISE EXCEPTION 'night_ai_dispatch_render_pin';
        END IF;
      END IF;
      IF NEW.attempt_no=2 THEN
        SELECT previous_attempt.* INTO prior FROM night_ai_dispatch_attempts previous_attempt
          WHERE previous_attempt.source_kind=NEW.source_kind AND
          ((NEW.intent_id IS NOT NULL AND previous_attempt.intent_id=NEW.intent_id) OR
           (NEW.job_id IS NOT NULL AND previous_attempt.job_id=NEW.job_id)) AND previous_attempt.attempt_no=1;
        IF NOT FOUND OR prior.status<>'failed' OR prior.retry_after IS NULL OR prior.retry_after>NEW.reserved_at
          OR prior.error_code IS NULL OR prior.error_code NOT IN ('timeout','network_error','rate_limited','provider_error','auth_error')
          OR (prior.error_code='auth_error' AND (adapter IS DISTINCT FROM 'gigachat_chat' OR prior.sent_at IS NULL))
          OR (prior.binding_id,prior.epoch,prior.config_hash,prior.caps_hash,prior.payload_hash,prior.source_expires_at)
            IS DISTINCT FROM (NEW.binding_id,NEW.epoch,NEW.config_hash,NEW.caps_hash,NEW.payload_hash,NEW.source_expires_at) THEN
          RAISE EXCEPTION 'night_ai_dispatch_retry';
        END IF;
      END IF;
      expected_scopes=ARRAY['nai:global:minute','game:'||NEW.game_id||':day','game:'||NEW.game_id||':total'];
      SELECT array_agg(debit_item.value->>'scope') INTO actual_scopes
        FROM jsonb_array_elements(NEW.quota_debits) AS debit_item(value);
      IF NOT (actual_scopes @> expected_scopes) OR
          (SELECT count(DISTINCT scope_item.value) FROM unnest(actual_scopes) AS scope_item(value))<>4 THEN
        RAISE EXCEPTION 'night_ai_dispatch_debits';
      END IF;
      FOR debit IN SELECT debit_item.value FROM jsonb_array_elements(NEW.quota_debits) AS debit_item(value) LOOP
        IF jsonb_typeof(debit)<>'object' OR NOT (debit ?& ARRAY['scope','period_start','requests','tokens'])
          OR debit-ARRAY['scope','period_start','requests','tokens']<>'{}'::jsonb
          OR jsonb_typeof(debit->'scope')<>'string' OR jsonb_typeof(debit->'period_start')<>'string'
          OR debit->>'requests'<>'1' OR jsonb_typeof(debit->'requests')<>'number'
          OR jsonb_typeof(debit->'tokens')<>'number'
          OR (debit->>'tokens') !~ '^[1-9][0-9]{0,18}$'
          OR (debit->>'tokens')::numeric<>NEW.reserved_input_units+NEW.reserved_output_tokens
          OR ((NOT ((debit->>'scope')=ANY(expected_scopes))) AND (debit->>'scope') !~ '^nai:actor:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:minute$')
          OR (debit->>'period_start')::timestamptz IS DISTINCT FROM (CASE
            WHEN debit->>'scope'='game:'||NEW.game_id||':total' THEN timestamptz '1970-01-01 00:00:00+00'
            WHEN debit->>'scope'='game:'||NEW.game_id||':day' THEN date_trunc('day',NEW.reserved_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
            ELSE date_trunc('minute',NEW.reserved_at) END) THEN
          RAISE EXCEPTION 'night_ai_dispatch_debits';
        END IF;
      END LOOP;
      RETURN NEW;
    END $$"""))
    op.execute(DDL("""CREATE FUNCTION night_ai_dispatch_slot() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE binding_key uuid; b night_ai_bindings; active night_ai_dispatch_attempts;
    BEGIN
      IF TG_TABLE_NAME='night_ai_bindings' THEN binding_key=NEW.id;
      ELSIF TG_TABLE_NAME='night_render_jobs' THEN
        SELECT active_attempt.binding_id INTO binding_key FROM night_ai_dispatch_attempts active_attempt
          WHERE active_attempt.job_id=NEW.job_id AND active_attempt.status IN ('reserved','sending');
        IF NOT FOUND THEN RETURN NEW; END IF;
      ELSE binding_key=NEW.binding_id; END IF;
      SELECT binding_row.* INTO b FROM night_ai_bindings binding_row WHERE binding_row.id=binding_key;
      SELECT active_attempt.* INTO active FROM night_ai_dispatch_attempts active_attempt
        WHERE active_attempt.binding_id=binding_key AND active_attempt.status IN ('reserved','sending');
      IF active.id IS NOT NULL THEN
        IF b.status<>'active' OR b.inflight_permit_id IS DISTINCT FROM active.id
          OR b.inflight_lease_until IS DISTINCT FROM active.lease_until THEN RAISE EXCEPTION 'night_ai_dispatch_slot'; END IF;
        IF active.source_kind='render' AND NOT EXISTS(SELECT 1 FROM night_render_jobs render_source
            WHERE render_source.job_id=active.job_id AND render_source.status='leased'
              AND render_source.attempts=active.attempt_no AND render_source.lease_owner=active.worker_id
              AND render_source.lease_until=active.lease_until) THEN RAISE EXCEPTION 'night_ai_dispatch_render_lease'; END IF;
      ELSIF b.inflight_permit_id IS NOT NULL OR b.inflight_lease_until IS NOT NULL THEN
        RAISE EXCEPTION 'night_ai_dispatch_slot';
      END IF;
      RETURN NEW;
    END $$"""))
    op.execute("CREATE TRIGGER nai_dispatch_guard BEFORE INSERT OR UPDATE OR DELETE ON night_ai_dispatch_attempts FOR EACH ROW EXECUTE FUNCTION night_ai_dispatch_guard()")
    op.execute("CREATE CONSTRAINT TRIGGER nai_dispatch_attempt_slot AFTER INSERT OR UPDATE ON night_ai_dispatch_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION night_ai_dispatch_slot()")
    op.execute("CREATE CONSTRAINT TRIGGER nai_dispatch_binding_slot AFTER INSERT OR UPDATE ON night_ai_bindings DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION night_ai_dispatch_slot()")
    op.execute("CREATE CONSTRAINT TRIGGER nai_dispatch_render_slot AFTER UPDATE ON night_render_jobs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION night_ai_dispatch_slot()")

TABLE_DDL = "\nCREATE TABLE night_ai_dispatch_attempts (\n\tid UUID NOT NULL, \n\tsource_kind VARCHAR(8) NOT NULL, \n\tintent_id UUID, \n\tjob_id VARCHAR(96), \n\tgame_id VARCHAR(64) NOT NULL, \n\tbinding_id UUID NOT NULL, \n\tepoch INTEGER NOT NULL, \n\tattempt_no INTEGER NOT NULL, \n\tconfig_hash VARCHAR(64) NOT NULL, \n\tcaps_hash VARCHAR(64) NOT NULL, \n\tpayload_hash VARCHAR(64) NOT NULL, \n\tcontract_version VARCHAR(32) NOT NULL, \n\tsource_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tworker_id VARCHAR(96) NOT NULL, \n\tlease_nonce UUID NOT NULL, \n\treserved_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\tnetwork_deadline TIMESTAMP WITH TIME ZONE NOT NULL, \n\tstatus VARCHAR(12) NOT NULL, \n\toauth_claimed_at TIMESTAMP WITH TIME ZONE, \n\tsent_at TIMESTAMP WITH TIME ZONE, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\treserved_input_units BIGINT NOT NULL, \n\treserved_output_tokens INTEGER NOT NULL, \n\tquota_debits JSONB NOT NULL, \n\tretry_after TIMESTAMP WITH TIME ZONE, \n\terror_code VARCHAR(32), \n\tresponse_hash VARCHAR(64), \n\tusage JSONB, \n\tPRIMARY KEY (id), \n\tCONSTRAINT fk_nai_dispatch_binding FOREIGN KEY(binding_id, game_id, epoch) REFERENCES night_ai_bindings (id, game_id, epoch) ON DELETE RESTRICT, \n\tCONSTRAINT fk_nai_dispatch_intent FOREIGN KEY(intent_id, game_id, binding_id, epoch) REFERENCES night_ai_intent_requests (id, game_id, binding_id, epoch) ON DELETE RESTRICT, \n\tCONSTRAINT fk_nai_dispatch_job FOREIGN KEY(job_id, game_id, binding_id, epoch) REFERENCES night_ai_job_bindings (job_id, game_id, binding_id, epoch) ON DELETE RESTRICT, \n\tCONSTRAINT uq_nai_dispatch_pointer UNIQUE (id, binding_id, game_id, epoch), \n\tCONSTRAINT ck_nai_dispatch_source CHECK ((source_kind='intent' AND intent_id IS NOT NULL AND job_id IS NULL) OR (source_kind='render' AND job_id IS NOT NULL AND intent_id IS NULL)), \n\tCONSTRAINT ck_nai_dispatch_identity CHECK (epoch>=1 AND attempt_no BETWEEN 1 AND 2 AND contract_version='night-ai-transport/1' AND length(worker_id) BETWEEN 1 AND 96), \n\tCONSTRAINT ck_nai_dispatch_hashes CHECK (config_hash ~ '^[a-f0-9]{64}$' AND caps_hash ~ '^[a-f0-9]{64}$' AND payload_hash ~ '^[a-f0-9]{64}$' AND (response_hash IS NULL OR response_hash ~ '^[a-f0-9]{64}$')), \n\tCONSTRAINT ck_nai_dispatch_deadline CHECK (network_deadline=reserved_at+interval '12 seconds' AND network_deadline<=lease_until AND lease_until<=reserved_at+interval '30 seconds' AND lease_until<=source_expires_at), \n\tCONSTRAINT ck_nai_dispatch_status CHECK (status IN ('reserved','sending','succeeded','failed','cancelled','expired') AND ((status IN ('reserved','sending'))=(finished_at IS NULL)) AND (status<>'reserved' OR sent_at IS NULL) AND (status<>'sending' OR sent_at IS NOT NULL) AND (status<>'succeeded' OR (sent_at IS NOT NULL AND response_hash IS NOT NULL))), \n\tCONSTRAINT ck_nai_dispatch_times CHECK ((oauth_claimed_at IS NULL OR oauth_claimed_at>=reserved_at) AND (sent_at IS NULL OR (sent_at>=reserved_at AND sent_at<network_deadline)) AND (finished_at IS NULL OR finished_at>=reserved_at) AND (response_hash IS NULL OR finished_at IS NOT NULL) AND (usage IS NULL OR finished_at IS NOT NULL)), \n\tCONSTRAINT ck_nai_dispatch_budget CHECK (reserved_input_units>=0 AND reserved_output_tokens BETWEEN 1 AND 800 AND jsonb_typeof(quota_debits)='array' AND jsonb_array_length(quota_debits)=4 AND octet_length(quota_debits::text)<=4096), \n\tCONSTRAINT ck_nai_dispatch_retry CHECK (retry_after IS NULL OR (status='failed' AND retry_after>=finished_at+interval '1 second' AND retry_after<=finished_at+interval '30 seconds' AND error_code IS NOT NULL AND error_code IN ('timeout','network_error','rate_limited','provider_error','auth_error'))), \n\tCONSTRAINT ck_nai_dispatch_error CHECK (error_code IS NULL OR error_code IN ('disabled','stale','expired','acl_denied','quota_exhausted','binding_busy','circuit_open','credential_unavailable','endpoint_denied','dns_failed','tls_failed','timeout','network_error','rate_limited','provider_error','auth_error','config_error','oversize','invalid_response','source_closed'))\n)\n\n"
INDEX_DDL = ['CREATE INDEX ix_nai_dispatch_expiry ON night_ai_dispatch_attempts (status, lease_until)', "CREATE UNIQUE INDEX uq_nai_dispatch_active_binding ON night_ai_dispatch_attempts (binding_id) WHERE status IN ('reserved','sending')", 'CREATE UNIQUE INDEX uq_nai_dispatch_intent_attempt ON night_ai_dispatch_attempts (intent_id, attempt_no) WHERE intent_id IS NOT NULL', 'CREATE UNIQUE INDEX uq_nai_dispatch_job_attempt ON night_ai_dispatch_attempts (job_id, attempt_no) WHERE job_id IS NOT NULL']
OLD_GUARD = "CREATE OR REPLACE FUNCTION night_ai_guard() RETURNS trigger LANGUAGE plpgsql AS $$\n    DECLARE previous jsonb; proposed jsonb;\n    BEGIN\n      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'night_ai_history_retained'; END IF;\n      proposed := to_jsonb(NEW);\n      IF TG_OP='INSERT' THEN RETURN NEW; END IF;\n      previous := to_jsonb(OLD);\n      IF previous=proposed THEN RETURN NEW; END IF;\n      IF TG_TABLE_NAME IN ('night_ai_profile_revisions','night_ai_job_bindings','night_ai_operations') THEN\n        RAISE EXCEPTION 'night_ai_immutable';\n      ELSIF TG_TABLE_NAME='night_ai_credentials' THEN\n        IF (previous - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])\n             IS DISTINCT FROM (proposed - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])\n          OR OLD.status='erased'\n          OR (OLD.status <> NEW.status AND NOT (\n            (OLD.status='staged' AND NEW.status IN ('usable','revoked','erased')) OR\n            (OLD.status='usable' AND NEW.status IN ('revoked','erased')) OR\n            (OLD.status='revoked' AND NEW.status='erased'))) THEN\n          RAISE EXCEPTION 'night_ai_credential_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_profiles' THEN\n        IF (previous - ARRAY['label','current_revision','enabled','is_default'])\n             IS DISTINCT FROM (proposed - ARRAY['label','current_revision','enabled','is_default'])\n          OR NEW.current_revision < OLD.current_revision OR NEW.current_revision > OLD.current_revision+1 THEN\n          RAISE EXCEPTION 'night_ai_profile_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_game_control' THEN\n        IF NEW.game_id <> OLD.game_id OR NEW.epoch < OLD.epoch OR NEW.epoch > OLD.epoch+1\n          OR (OLD.starter_account_id IS NOT NULL AND NEW.starter_account_id IS DISTINCT FROM OLD.starter_account_id)\n          OR NEW.updated_at < OLD.updated_at THEN RAISE EXCEPTION 'night_ai_control_transition'; END IF;\n      ELSIF TG_TABLE_NAME='night_ai_requests' THEN\n        IF OLD.status <> 'pending' OR NEW.status='pending'\n          OR (previous - ARRAY['status','decided_at','decided_by_subject','binding_id','reason'])\n             IS DISTINCT FROM (proposed - ARRAY['status','decided_at','decided_by_subject','binding_id','reason']) THEN\n          RAISE EXCEPTION 'night_ai_request_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_bindings' THEN\n        IF OLD.status <> 'active'\n          OR (previous - ARRAY['status','health','inflight_job_id','inflight_lease_until','closed_at'])\n             IS DISTINCT FROM (proposed - ARRAY['status','health','inflight_job_id','inflight_lease_until','closed_at']) THEN\n          RAISE EXCEPTION 'night_ai_binding_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_intent_requests' THEN\n        IF OLD.status <> 'prepared' OR NEW.status='prepared'\n          OR (previous - ARRAY['status','finalized_at','safe_result'])\n             IS DISTINCT FROM (proposed - ARRAY['status','finalized_at','safe_result']) THEN\n          RAISE EXCEPTION 'night_ai_intent_transition';\n        END IF;\n      END IF;\n      RETURN NEW;\n    END $$"
NEW_GUARD = "CREATE OR REPLACE FUNCTION night_ai_guard() RETURNS trigger LANGUAGE plpgsql AS $$\n    DECLARE previous jsonb; proposed jsonb;\n    BEGIN\n      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'night_ai_history_retained'; END IF;\n      proposed := to_jsonb(NEW);\n      IF TG_OP='INSERT' THEN RETURN NEW; END IF;\n      previous := to_jsonb(OLD);\n      IF previous=proposed THEN RETURN NEW; END IF;\n      IF TG_TABLE_NAME IN ('night_ai_profile_revisions','night_ai_job_bindings','night_ai_operations') THEN\n        RAISE EXCEPTION 'night_ai_immutable';\n      ELSIF TG_TABLE_NAME='night_ai_credentials' THEN\n        IF (previous - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])\n             IS DISTINCT FROM (proposed - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])\n          OR OLD.status='erased'\n          OR (OLD.status <> NEW.status AND NOT (\n            (OLD.status='staged' AND NEW.status IN ('usable','revoked','erased')) OR\n            (OLD.status='usable' AND NEW.status IN ('revoked','erased')) OR\n            (OLD.status='revoked' AND NEW.status='erased'))) THEN\n          RAISE EXCEPTION 'night_ai_credential_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_profiles' THEN\n        IF (previous - ARRAY['label','current_revision','enabled','is_default'])\n             IS DISTINCT FROM (proposed - ARRAY['label','current_revision','enabled','is_default'])\n          OR NEW.current_revision < OLD.current_revision OR NEW.current_revision > OLD.current_revision+1 THEN\n          RAISE EXCEPTION 'night_ai_profile_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_game_control' THEN\n        IF NEW.game_id <> OLD.game_id OR NEW.epoch < OLD.epoch OR NEW.epoch > OLD.epoch+1\n          OR (OLD.starter_account_id IS NOT NULL AND NEW.starter_account_id IS DISTINCT FROM OLD.starter_account_id)\n          OR NEW.updated_at < OLD.updated_at THEN RAISE EXCEPTION 'night_ai_control_transition'; END IF;\n      ELSIF TG_TABLE_NAME='night_ai_requests' THEN\n        IF OLD.status <> 'pending' OR NEW.status='pending'\n          OR (previous - ARRAY['status','decided_at','decided_by_subject','binding_id','reason'])\n             IS DISTINCT FROM (proposed - ARRAY['status','decided_at','decided_by_subject','binding_id','reason']) THEN\n          RAISE EXCEPTION 'night_ai_request_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_bindings' THEN\n        IF OLD.status <> 'active'\n          OR (previous - ARRAY['status','health','inflight_job_id','inflight_lease_until','inflight_permit_id','closed_at'])\n             IS DISTINCT FROM (proposed - ARRAY['status','health','inflight_job_id','inflight_lease_until','inflight_permit_id','closed_at']) THEN\n          RAISE EXCEPTION 'night_ai_binding_transition';\n        END IF;\n      ELSIF TG_TABLE_NAME='night_ai_intent_requests' THEN\n        IF OLD.status <> 'prepared' OR NEW.status='prepared'\n          OR (previous - ARRAY['status','finalized_at','safe_result'])\n             IS DISTINCT FROM (proposed - ARRAY['status','finalized_at','safe_result']) THEN\n          RAISE EXCEPTION 'night_ai_intent_transition';\n        END IF;\n      END IF;\n      RETURN NEW;\n    END $$"
