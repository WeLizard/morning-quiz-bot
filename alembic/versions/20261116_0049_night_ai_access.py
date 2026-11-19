"""Night AI access tables: immutable pins, encrypted credentials and durable prepare.

Frozen PostgreSQL DDL, independent of future application model changes. No legacy
rows are rewritten or silently enrolled into AI access. Existing narration stays
authored until separately integrated trusted control/orchestration permits it.
"""
from alembic import op
from sqlalchemy import DDL

revision = '20261116_0049'
down_revision = '20261116_0048'
branch_labels = None
depends_on = None


_TABLE_DDL = (
    """CREATE TABLE night_ai_credentials (
	id UUID NOT NULL, 
	scope VARCHAR(8) NOT NULL, 
	owner_subject VARCHAR(96) NOT NULL, 
	game_id VARCHAR(64), 
	preset VARCHAR(32) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	key_id VARCHAR(64), 
	nonce BYTEA, 
	ciphertext BYTEA, 
	aad_version INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	erased_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_nai_credential_scope CHECK (scope = 'admin' AND game_id IS NULL AND (owner_subject ~ '^admin:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}:operator$') OR scope = 'game' AND game_id IS NOT NULL AND (owner_subject ~ '^account:[a-f0-9-]{36}$')), 
	CONSTRAINT ck_nai_credential_status CHECK (status IN ('staged','usable','revoked','erased') AND (status <> 'staged' OR scope='game')), 
	CONSTRAINT ck_nai_credential_secret CHECK ((status='erased' AND key_id IS NULL AND nonce IS NULL AND ciphertext IS NULL AND aad_version IS NULL AND erased_at IS NOT NULL) OR (status <> 'erased' AND key_id IS NOT NULL AND octet_length(nonce)=12 AND nonce IS NOT NULL AND octet_length(ciphertext) BETWEEN 17 AND 8208 AND ciphertext IS NOT NULL AND aad_version=1 AND aad_version IS NOT NULL AND erased_at IS NULL)), 
	CONSTRAINT ck_nai_credential_expiry CHECK ((scope <> 'game' OR expires_at IS NOT NULL) AND (expires_at IS NULL OR expires_at > created_at)), 
	CONSTRAINT uq_nai_credential_nonce UNIQUE (key_id, nonce), 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_nai_credential_expiry ON night_ai_credentials (status, expires_at)""",
    """CREATE TABLE night_ai_profiles (
	id UUID NOT NULL, 
	scope VARCHAR(8) NOT NULL, 
	game_id VARCHAR(64), 
	label VARCHAR(80) NOT NULL, 
	current_revision INTEGER NOT NULL, 
	enabled BOOLEAN DEFAULT 'false' NOT NULL, 
	is_default BOOLEAN DEFAULT 'false' NOT NULL, 
	created_by_subject VARCHAR(96) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_nai_profile_scope CHECK ((scope='admin' AND game_id IS NULL) OR (scope='game' AND game_id IS NOT NULL)), 
	CONSTRAINT ck_nai_profile_revision CHECK (current_revision >= 1 AND length(label) BETWEEN 1 AND 80), 
	CONSTRAINT ck_nai_profile_default CHECK (NOT is_default OR (scope='admin' AND enabled)), 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT
)""",
    """CREATE UNIQUE INDEX uq_nai_profile_default ON night_ai_profiles (is_default) WHERE is_default""",
    """CREATE TABLE night_ai_profile_revisions (
	profile_id UUID NOT NULL, 
	revision INTEGER NOT NULL, 
	config JSONB NOT NULL, 
	config_hash VARCHAR(64) NOT NULL, 
	credential_id UUID, 
	created_by_subject VARCHAR(96) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (profile_id, revision), 
	CONSTRAINT ck_nai_revision_identity CHECK (revision >= 1 AND config_hash ~ '^[a-f0-9]{64}$'), 
	CONSTRAINT ck_nai_revision_config CHECK (jsonb_typeof(config)='object' AND octet_length(config::text)<=16384), 
	FOREIGN KEY(profile_id) REFERENCES night_ai_profiles (id) ON DELETE RESTRICT, 
	FOREIGN KEY(credential_id) REFERENCES night_ai_credentials (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE night_ai_bindings (
	id UUID NOT NULL, 
	game_id VARCHAR(64) NOT NULL, 
	epoch INTEGER NOT NULL, 
	mode VARCHAR(8) NOT NULL, 
	profile_id UUID NOT NULL, 
	profile_revision INTEGER NOT NULL, 
	config_hash VARCHAR(64) NOT NULL, 
	granted_by_subject VARCHAR(96) NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	valid_until TIMESTAMP WITH TIME ZONE NOT NULL, 
	caps JSONB NOT NULL, 
	health VARCHAR(16) DEFAULT 'ok' NOT NULL, 
	inflight_job_id VARCHAR(96), 
	inflight_lease_until TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_nai_binding_revision FOREIGN KEY(profile_id, profile_revision) REFERENCES night_ai_profile_revisions (profile_id, revision) ON DELETE RESTRICT, 
	CONSTRAINT ck_nai_binding_identity CHECK (epoch >= 1 AND mode IN ('admin','byok') AND config_hash ~ '^[a-f0-9]{64}$'), 
	CONSTRAINT ck_nai_binding_status CHECK (status IN ('active','revoked','superseded','expired','closed') AND ((status='active') = (closed_at IS NULL))), 
	CONSTRAINT ck_nai_binding_health CHECK (health IN ('ok','auth_error','config_error') AND ((inflight_job_id IS NULL) = (inflight_lease_until IS NULL))), 
	CONSTRAINT ck_nai_binding_expiry CHECK (valid_until > created_at AND valid_until <= created_at + interval '30 days'), 
	CONSTRAINT ck_nai_binding_caps CHECK (jsonb_typeof(caps)='object' AND octet_length(caps::text)<=8192), 
	CONSTRAINT uq_nai_binding_epoch UNIQUE (game_id, epoch), 
	CONSTRAINT uq_nai_binding_pointer UNIQUE (id, game_id, epoch), 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, 
	FOREIGN KEY(inflight_job_id) REFERENCES night_render_jobs (job_id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_nai_binding_expiry ON night_ai_bindings (status, valid_until)""",
    """CREATE UNIQUE INDEX uq_nai_binding_active ON night_ai_bindings (game_id) WHERE status='active'""",
    """CREATE TABLE night_ai_game_control (
	game_id VARCHAR(64) NOT NULL, 
	starter_account_id UUID, 
	epoch INTEGER DEFAULT '0' NOT NULL, 
	current_binding_id UUID, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (game_id), 
	CONSTRAINT ck_nai_control_epoch CHECK (epoch >= 0 AND (starter_account_id IS NOT NULL OR (epoch=0 AND current_binding_id IS NULL))), 
	CONSTRAINT fk_nai_control_binding FOREIGN KEY(current_binding_id, game_id, epoch) REFERENCES night_ai_bindings (id, game_id, epoch) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, 
	FOREIGN KEY(starter_account_id) REFERENCES accounts (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE night_ai_requests (
	id UUID NOT NULL, 
	game_id VARCHAR(64) NOT NULL, 
	epoch INTEGER NOT NULL, 
	requester_account_id UUID NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	decided_at TIMESTAMP WITH TIME ZONE, 
	decided_by_subject VARCHAR(96), 
	binding_id UUID, 
	reason VARCHAR(32), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_nai_request_status CHECK (epoch >= 1 AND status IN ('pending','approved','denied','expired','cancelled') AND ((status='approved') = (binding_id IS NOT NULL)) AND ((status='pending') = (decided_at IS NULL))), 
	CONSTRAINT ck_nai_request_expiry CHECK (expires_at=created_at + interval '24 hours'), 
	CONSTRAINT ck_nai_request_reason CHECK (reason IS NULL OR reason IN ('operator_denied','expired','superseded','terminal','starter_unusable','profile_unavailable')), 
	CONSTRAINT fk_nai_request_binding FOREIGN KEY(binding_id, game_id, epoch) REFERENCES night_ai_bindings (id, game_id, epoch) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED, 
	CONSTRAINT uq_nai_request_epoch UNIQUE (game_id, epoch), 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, 
	FOREIGN KEY(requester_account_id) REFERENCES accounts (id) ON DELETE RESTRICT
)""",
    """CREATE UNIQUE INDEX uq_nai_request_pending ON night_ai_requests (game_id) WHERE status='pending'""",
    """CREATE TABLE night_ai_job_bindings (
	job_id VARCHAR(96) NOT NULL, 
	game_id VARCHAR(64) NOT NULL, 
	epoch INTEGER NOT NULL, 
	binding_id UUID, 
	fallback_reason VARCHAR(40), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (job_id), 
	CONSTRAINT ck_nai_job_assignment CHECK (epoch >= 0 AND ((binding_id IS NULL AND fallback_reason IS NOT NULL) OR (binding_id IS NOT NULL AND fallback_reason IS NULL))), 
	CONSTRAINT ck_nai_job_fallback CHECK (fallback_reason IS NULL OR fallback_reason IN ('authored','pending_approval','binding_unavailable','byok_audience_denied','runtime_unavailable')), 
	CONSTRAINT fk_nai_job_binding FOREIGN KEY(binding_id, game_id, epoch) REFERENCES night_ai_bindings (id, game_id, epoch) ON DELETE RESTRICT, 
	FOREIGN KEY(job_id) REFERENCES night_render_jobs (job_id) ON DELETE RESTRICT, 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE night_ai_operations (
	principal_subject VARCHAR(96) NOT NULL, 
	client_request_id VARCHAR(96) NOT NULL, 
	operation VARCHAR(40) NOT NULL, 
	target_id VARCHAR(96) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	fingerprint_version VARCHAR(80) NOT NULL, 
	safe_result JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (principal_subject, client_request_id), 
	CONSTRAINT ck_nai_operation_fingerprint CHECK (fingerprint ~ '^[a-f0-9]{64}$' AND (fingerprint_version='sha256:1' OR fingerprint_version ~ '^hmac-sha256:[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')), 
	CONSTRAINT ck_nai_operation_result CHECK (jsonb_typeof(safe_result)='object' AND octet_length(safe_result::text)<=8192)
)""",
    """CREATE TABLE night_ai_intent_requests (
	id UUID NOT NULL, 
	game_id VARCHAR(64) NOT NULL, 
	requester_account_id UUID NOT NULL, 
	client_request_id VARCHAR(96) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	epoch INTEGER NOT NULL, 
	binding_id UUID, 
	token JSONB NOT NULL, 
	legal_candidates JSONB NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	finalized_at TIMESTAMP WITH TIME ZONE, 
	safe_result JSONB, 
	PRIMARY KEY (id), 
	CONSTRAINT fk_nai_intent_binding FOREIGN KEY(binding_id, game_id, epoch) REFERENCES night_ai_bindings (id, game_id, epoch) ON DELETE RESTRICT, 
	CONSTRAINT ck_nai_intent_status CHECK (epoch >= 0 AND fingerprint ~ '^[a-f0-9]{64}$' AND status IN ('prepared','finalized','expired','cancelled') AND ((status='prepared') = (finalized_at IS NULL)) AND ((status='prepared') = (safe_result IS NULL))), 
	CONSTRAINT ck_nai_intent_expiry CHECK (expires_at > created_at AND expires_at <= created_at + interval '5 minutes'), 
	CONSTRAINT ck_nai_intent_documents CHECK (jsonb_typeof(token)='object' AND octet_length(token::text)<=8192 AND jsonb_typeof(legal_candidates)='object' AND octet_length(legal_candidates::text)<=32768 AND (safe_result IS NULL OR (jsonb_typeof(safe_result)='object' AND octet_length(safe_result::text)<=8192))), 
	CONSTRAINT uq_nai_intent_request UNIQUE (game_id, requester_account_id, client_request_id), 
	FOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, 
	FOREIGN KEY(requester_account_id) REFERENCES accounts (id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_nai_intent_expiry ON night_ai_intent_requests (status, expires_at)""",
)


def upgrade():
    for statement in _TABLE_DDL:
        # Frozen DDL is SQL, not a textual query with bind parameters. DDL avoids
        # text() interpreting the regex literal ':operator' as a bind name.
        op.execute(DDL(statement))
    _install_guards()


def downgrade():
    # Serialize against inserts before inspecting retention. Row DELETE guards
    # cannot protect DROP TABLE, and a preflight without these locks would race.
    op.execute("""LOCK TABLE night_ai_credentials, night_ai_profiles,
        night_ai_profile_revisions, night_ai_bindings, night_ai_game_control,
        night_ai_requests, night_ai_job_bindings, night_ai_operations,
        night_ai_intent_requests IN ACCESS EXCLUSIVE MODE""")
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM night_ai_credentials)
        OR EXISTS (SELECT 1 FROM night_ai_profiles)
        OR EXISTS (SELECT 1 FROM night_ai_profile_revisions)
        OR EXISTS (SELECT 1 FROM night_ai_bindings)
        OR EXISTS (SELECT 1 FROM night_ai_game_control)
        OR EXISTS (SELECT 1 FROM night_ai_requests)
        OR EXISTS (SELECT 1 FROM night_ai_job_bindings)
        OR EXISTS (SELECT 1 FROM night_ai_operations)
        OR EXISTS (SELECT 1 FROM night_ai_intent_requests) THEN
        RAISE EXCEPTION 'night_ai_retention_required: downgrade refused because AI history exists';
      END IF;
    END $$""")
    op.execute("DROP TABLE night_ai_intent_requests")
    op.execute("DROP TABLE night_ai_operations")
    op.execute("DROP TABLE night_ai_job_bindings")
    op.execute("DROP TABLE night_ai_requests")
    op.execute("DROP TABLE night_ai_game_control")
    op.execute("DROP TABLE night_ai_bindings")
    op.execute("DROP TABLE night_ai_profile_revisions")
    op.execute("DROP TABLE night_ai_profiles")
    op.execute("DROP TABLE night_ai_credentials")
    op.execute("DROP FUNCTION night_ai_guard()")
    op.execute("DROP FUNCTION night_ai_cross_guard()")


def _install_guards():
    op.execute("""CREATE FUNCTION night_ai_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE previous jsonb; proposed jsonb;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'night_ai_history_retained'; END IF;
      proposed := to_jsonb(NEW);
      IF TG_OP='INSERT' THEN RETURN NEW; END IF;
      previous := to_jsonb(OLD);
      IF previous=proposed THEN RETURN NEW; END IF;
      IF TG_TABLE_NAME IN ('night_ai_profile_revisions','night_ai_job_bindings','night_ai_operations') THEN
        RAISE EXCEPTION 'night_ai_immutable';
      ELSIF TG_TABLE_NAME='night_ai_credentials' THEN
        IF (previous - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])
             IS DISTINCT FROM (proposed - ARRAY['status','key_id','nonce','ciphertext','aad_version','erased_at'])
          OR OLD.status='erased'
          OR (OLD.status <> NEW.status AND NOT (
            (OLD.status='staged' AND NEW.status IN ('usable','revoked','erased')) OR
            (OLD.status='usable' AND NEW.status IN ('revoked','erased')) OR
            (OLD.status='revoked' AND NEW.status='erased'))) THEN
          RAISE EXCEPTION 'night_ai_credential_transition';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_profiles' THEN
        IF (previous - ARRAY['label','current_revision','enabled','is_default'])
             IS DISTINCT FROM (proposed - ARRAY['label','current_revision','enabled','is_default'])
          OR NEW.current_revision < OLD.current_revision OR NEW.current_revision > OLD.current_revision+1 THEN
          RAISE EXCEPTION 'night_ai_profile_transition';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_game_control' THEN
        IF NEW.game_id <> OLD.game_id OR NEW.epoch < OLD.epoch OR NEW.epoch > OLD.epoch+1
          OR (OLD.starter_account_id IS NOT NULL AND NEW.starter_account_id IS DISTINCT FROM OLD.starter_account_id)
          OR NEW.updated_at < OLD.updated_at THEN RAISE EXCEPTION 'night_ai_control_transition'; END IF;
      ELSIF TG_TABLE_NAME='night_ai_requests' THEN
        IF OLD.status <> 'pending' OR NEW.status='pending'
          OR (previous - ARRAY['status','decided_at','decided_by_subject','binding_id','reason'])
             IS DISTINCT FROM (proposed - ARRAY['status','decided_at','decided_by_subject','binding_id','reason']) THEN
          RAISE EXCEPTION 'night_ai_request_transition';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_bindings' THEN
        IF OLD.status <> 'active'
          OR (previous - ARRAY['status','health','inflight_job_id','inflight_lease_until','closed_at'])
             IS DISTINCT FROM (proposed - ARRAY['status','health','inflight_job_id','inflight_lease_until','closed_at']) THEN
          RAISE EXCEPTION 'night_ai_binding_transition';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_intent_requests' THEN
        IF OLD.status <> 'prepared' OR NEW.status='prepared'
          OR (previous - ARRAY['status','finalized_at','safe_result'])
             IS DISTINCT FROM (proposed - ARRAY['status','finalized_at','safe_result']) THEN
          RAISE EXCEPTION 'night_ai_intent_transition';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION night_ai_cross_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE doc jsonb; game_key text; profile_scope text; profile_game text;
      credential_scope text; credential_game text; credential_preset text;
      revision_hash text; revision_config jsonb; revision_credential uuid;
    BEGIN
      -- Read the committed candidate row, not an earlier NEW image queued by an
      -- intermediate flush of this same transaction.
      IF TG_TABLE_NAME='night_ai_game_control' THEN
        SELECT to_jsonb(c) INTO doc FROM night_ai_game_control c WHERE c.game_id=NEW.game_id;
      ELSIF TG_TABLE_NAME='night_ai_profile_revisions' THEN
        SELECT to_jsonb(r) INTO doc FROM night_ai_profile_revisions r WHERE r.profile_id=NEW.profile_id AND r.revision=NEW.revision;
      ELSIF TG_TABLE_NAME='night_ai_job_bindings' THEN
        SELECT to_jsonb(j) INTO doc FROM night_ai_job_bindings j WHERE j.job_id=NEW.job_id;
      ELSE
        EXECUTE format('SELECT to_jsonb(t) FROM %I t WHERE id=$1', TG_TABLE_NAME) INTO doc USING NEW.id;
      END IF;
      IF doc IS NULL THEN RAISE EXCEPTION 'night_ai_missing_row'; END IF;
      game_key := doc->>'game_id';
      IF game_key IS NOT NULL AND NOT EXISTS(SELECT 1 FROM games WHERE id=game_key AND mode='night_case') THEN
        RAISE EXCEPTION 'night_ai_game_mode';
      END IF;
      IF TG_TABLE_NAME='night_ai_game_control' THEN
        IF (doc->>'starter_account_id') IS NULL AND NOT EXISTS(
          SELECT 1 FROM night_game_sealed WHERE game_id=game_key AND lifecycle='lobby') THEN
          RAISE EXCEPTION 'night_ai_starter_required';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_profiles' THEN
        IF NOT EXISTS(SELECT 1 FROM night_ai_profile_revisions r
          WHERE r.profile_id=(doc->>'id')::uuid AND r.revision=(doc->>'current_revision')::int) THEN
          RAISE EXCEPTION 'night_ai_current_revision_missing';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_profile_revisions' THEN
        SELECT scope, game_id INTO profile_scope,profile_game FROM night_ai_profiles WHERE id=(doc->>'profile_id')::uuid;
        IF (doc->'config'->>'credential_id') IS DISTINCT FROM (doc->>'credential_id')
          OR (doc->'config'->>'config_hash') IS DISTINCT FROM (doc->>'config_hash') THEN
          RAISE EXCEPTION 'night_ai_revision_identity';
        END IF;
        IF doc->>'credential_id' IS NOT NULL THEN
          SELECT scope,game_id,preset INTO credential_scope,credential_game,credential_preset
            FROM night_ai_credentials WHERE id=(doc->>'credential_id')::uuid;
          IF credential_scope IS DISTINCT FROM profile_scope OR credential_game IS DISTINCT FROM profile_game
            OR credential_preset IS DISTINCT FROM (doc->'config'->>'preset') THEN
            RAISE EXCEPTION 'night_ai_credential_scope';
          END IF;
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_bindings' THEN
        SELECT p.scope,p.game_id,r.config_hash INTO profile_scope,profile_game,revision_hash
          FROM night_ai_profiles p JOIN night_ai_profile_revisions r ON r.profile_id=p.id
          WHERE p.id=(doc->>'profile_id')::uuid AND r.revision=(doc->>'profile_revision')::int;
        IF revision_hash IS DISTINCT FROM (doc->>'config_hash')
          OR ((doc->>'mode')='admin' AND profile_scope IS DISTINCT FROM 'admin')
          OR ((doc->>'mode')='byok' AND (profile_scope IS DISTINCT FROM 'game' OR profile_game IS DISTINCT FROM game_key)) THEN
          RAISE EXCEPTION 'night_ai_binding_scope';
        END IF;
        IF doc->>'inflight_job_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM night_render_jobs
          WHERE job_id=doc->>'inflight_job_id' AND game_id=game_key) THEN
          RAISE EXCEPTION 'night_ai_inflight_game';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_requests' THEN
        IF NOT EXISTS(SELECT 1 FROM night_ai_game_control c WHERE c.game_id=game_key
          AND c.starter_account_id=(doc->>'requester_account_id')::uuid AND c.epoch >= (doc->>'epoch')::int) THEN
          RAISE EXCEPTION 'night_ai_request_starter';
        END IF;
        IF doc->>'binding_id' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM night_ai_bindings
          WHERE id=(doc->>'binding_id')::uuid AND mode='admin') THEN
          RAISE EXCEPTION 'night_ai_approval_mode';
        END IF;
      ELSIF TG_TABLE_NAME='night_ai_job_bindings' THEN
        IF NOT EXISTS(SELECT 1 FROM night_render_jobs WHERE job_id=doc->>'job_id' AND game_id=game_key) THEN
          RAISE EXCEPTION 'night_ai_job_game';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    for table in (
        'night_ai_credentials', 'night_ai_profiles', 'night_ai_profile_revisions',
        'night_ai_bindings', 'night_ai_game_control', 'night_ai_requests',
        'night_ai_job_bindings', 'night_ai_operations', 'night_ai_intent_requests',
    ):
        op.execute(f'CREATE TRIGGER night_ai_guard BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION night_ai_guard()')
        if table != 'night_ai_operations':
            op.execute(f'CREATE CONSTRAINT TRIGGER night_ai_cross_guard AFTER INSERT OR UPDATE ON {table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION night_ai_cross_guard()')
