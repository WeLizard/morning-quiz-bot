"""Night Case sealed storage and cross-mode room exclusion.

All DDL is frozen here; never import evolving runtime model metadata in migrations.
Downgrade refuses to erase retained Night Case history.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261115_0045"
down_revision = "20261030_0044"
branch_labels = None
depends_on = None

TABLE_DDL = ['CREATE TABLE night_narrator_limits (\n'
 '\tscope VARCHAR(128) NOT NULL, \n'
 '\tperiod_start TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 "\treserved_requests INTEGER DEFAULT '0' NOT NULL, \n"
 "\treserved_tokens BIGINT DEFAULT '0' NOT NULL, \n"
 "\tfailures INTEGER DEFAULT '0' NOT NULL, \n"
 '\tcircuit_open_until TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (scope, period_start), \n'
 '\tCONSTRAINT ck_night_limits_nonnegative CHECK (reserved_requests >= 0 AND reserved_tokens >= 0 '
 'AND failures >= 0)\n'
 ')',
 'CREATE TABLE night_runtime_outages (\n'
 '\toutage_id VARCHAR(96) NOT NULL, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tended_at TIMESTAMP WITH TIME ZONE, \n'
 '\tdetected_by VARCHAR(16) NOT NULL, \n'
 '\tPRIMARY KEY (outage_id), \n'
 "\tCONSTRAINT ck_night_outage_detector CHECK (detected_by IN ('api','worker','operator')), \n"
 '\tCONSTRAINT ck_night_outage_interval CHECK (ended_at IS NULL OR ended_at > started_at), \n'
 '\tUNIQUE (started_at)\n'
 ')',
 'CREATE TABLE night_cases (\n'
 '\tcase_id VARCHAR(96) NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tcontent_hash VARCHAR(64) NOT NULL, \n'
 '\tcontent JSONB NOT NULL, \n'
 '\tcompiler_version VARCHAR(96) NOT NULL, \n'
 '\tengine_build VARCHAR(96) NOT NULL, \n'
 '\tvalidation_report JSONB NOT NULL, \n'
 '\tregistered_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tregistered_by UUID NOT NULL, \n'
 "\tadmission VARCHAR(16) DEFAULT 'registered' NOT NULL, \n"
 '\tPRIMARY KEY (case_id, version), \n'
 '\tCONSTRAINT ck_night_case_version CHECK (version > 0), \n'
 '\tCONSTRAINT ck_night_case_admission CHECK (admission IN '
 "('registered','rehearsal','retired')), \n"
 '\tCONSTRAINT uq_night_case_pinned UNIQUE (case_id, version, content_hash), \n'
 '\tUNIQUE (content_hash), \n'
 '\tFOREIGN KEY(registered_by) REFERENCES accounts (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_runtime_health (\n'
 '\truntime_key VARCHAR(64) NOT NULL, \n'
 '\tapi_seen_at TIMESTAMP WITH TIME ZONE, \n'
 '\tworker_seen_at TIMESTAMP WITH TIME ZONE, \n'
 '\tactive_outage_id VARCHAR(96), \n'
 '\tPRIMARY KEY (runtime_key), \n'
 '\tFOREIGN KEY(active_outage_id) REFERENCES night_runtime_outages (outage_id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_events (\n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\tevent_id VARCHAR(128) NOT NULL, \n'
 '\tscope VARCHAR(64) NOT NULL, \n'
 '\taudience_seq BIGINT NOT NULL, \n'
 '\twindow_idx INTEGER NOT NULL, \n'
 '\tkind VARCHAR(64) NOT NULL, \n'
 '\tpayload JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (game_id, event_id), \n'
 '\tCONSTRAINT uq_night_event_audience UNIQUE (game_id, scope, audience_seq), \n'
 "\tCONSTRAINT ck_night_event_scope CHECK (scope = 'public' OR scope ~ "
 "'^account:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'), \n"
 '\tCONSTRAINT ck_night_event_seq CHECK (audience_seq >= 0), \n'
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_game_sealed (\n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\tcase_id VARCHAR(96) NOT NULL, \n'
 '\tversion INTEGER NOT NULL, \n'
 '\tcontent_hash VARCHAR(64) NOT NULL, \n'
 '\trules JSONB NOT NULL, \n'
 '\trules_hash VARCHAR(64) NOT NULL, \n'
 '\tengine_build VARCHAR(96) NOT NULL, \n'
 '\tcompiler_version VARCHAR(96) NOT NULL, \n'
 "\tstorage_version INTEGER DEFAULT '1' NOT NULL, \n"
 '\tkernel JSONB, \n'
 '\tlobby JSONB, \n'
 '\tsnapshot_hash VARCHAR(64) NOT NULL, \n'
 "\tstorage_revision BIGINT DEFAULT '0' NOT NULL, \n"
 '\tlifecycle VARCHAR(16) NOT NULL, \n'
 '\tinterruption JSONB, \n'
 '\tPRIMARY KEY (game_id), \n'
 '\tFOREIGN KEY(case_id, version, content_hash) REFERENCES night_cases (case_id, version, '
 'content_hash) ON DELETE RESTRICT, \n'
 '\tCONSTRAINT ck_night_sealed_version CHECK (storage_version = 1 AND storage_revision >= 0), \n'
 '\tCONSTRAINT ck_night_sealed_lifecycle CHECK (lifecycle IN '
 "('lobby','running','finished','interrupted','stopped')), \n"
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_intent_proposals (\n'
 '\tproposal_id VARCHAR(96) NOT NULL, \n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\toriginal_actor_account_id UUID NOT NULL, \n'
 '\trequest_id VARCHAR(128) NOT NULL, \n'
 '\tinput_hash VARCHAR(64) NOT NULL, \n'
 '\tproposal JSONB NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tconfirmed_command_id VARCHAR(128), \n'
 '\tPRIMARY KEY (proposal_id), \n'
 '\tCONSTRAINT uq_night_proposal_request UNIQUE (game_id, original_actor_account_id, '
 'request_id), \n'
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(original_actor_account_id) REFERENCES accounts (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_lobby_commands (\n'
 '\troom_id VARCHAR(64) NOT NULL, \n'
 '\toriginal_actor_account_id UUID NOT NULL, \n'
 '\tclient_command_id VARCHAR(128) NOT NULL, \n'
 "\tkind VARCHAR(32) DEFAULT 'create_lobby' NOT NULL, \n"
 '\tfingerprint VARCHAR(64) NOT NULL, \n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\tresult JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (room_id, original_actor_account_id, client_command_id), \n'
 "\tCONSTRAINT ck_night_lobby_kind CHECK (kind = 'create_lobby'), \n"
 '\tFOREIGN KEY(room_id) REFERENCES rooms (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(original_actor_account_id) REFERENCES accounts (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_messages (\n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\tid VARCHAR(128) NOT NULL, \n'
 '\tcommand_id VARCHAR(128) NOT NULL, \n'
 '\tthread_key VARCHAR(128) NOT NULL, \n'
 '\tchannel VARCHAR(16) NOT NULL, \n'
 '\tsender_account_id UUID NOT NULL, \n'
 '\trecipients JSONB NOT NULL, \n'
 '\twindow_idx INTEGER NOT NULL, \n'
 '\ttext TEXT NOT NULL, \n'
 '\ttext_hash VARCHAR(64) NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (game_id, id), \n'
 '\tCONSTRAINT uq_night_message_command UNIQUE (game_id, sender_account_id, command_id), \n'
 "\tCONSTRAINT ck_night_message_channel CHECK (channel IN ('square','whisper','ghost')), \n"
 "\tCONSTRAINT ck_night_message_recipients CHECK (jsonb_typeof(recipients) = 'array' AND "
 'jsonb_array_length(recipients) BETWEEN 1 AND 12), \n'
 '\tCONSTRAINT ck_night_message_text CHECK (length(text) BETWEEN 1 AND 1000 AND octet_length(text) <= 4096), \n'
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(sender_account_id) REFERENCES accounts (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_render_jobs (\n'
 '\tjob_id VARCHAR(96) NOT NULL, \n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\tcause_id VARCHAR(128) NOT NULL, \n'
 '\tkind VARCHAR(64) NOT NULL, \n'
 '\taudience_key VARCHAR(64) NOT NULL, \n'
 '\tknowledge_revision BIGINT NOT NULL, \n'
 '\ttemplate_version VARCHAR(64) NOT NULL, \n'
 '\tfrozen_view JSONB NOT NULL, \n'
 '\tinput_hash VARCHAR(64) NOT NULL, \n'
 '\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tfallback TEXT NOT NULL, \n'
 "\tstatus VARCHAR(24) DEFAULT 'pending' NOT NULL, \n"
 "\tattempts INTEGER DEFAULT '0' NOT NULL, \n"
 '\tlease_owner VARCHAR(96), \n'
 '\tlease_until TIMESTAMP WITH TIME ZONE, \n'
 '\tretry_at TIMESTAMP WITH TIME ZONE, \n'
 '\tsanitized_error VARCHAR(64), \n'
 '\tPRIMARY KEY (job_id), \n'
 '\tCONSTRAINT uq_night_render_cause UNIQUE (game_id, cause_id, kind, audience_key, '
 'knowledge_revision, template_version), \n'
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_reward_claims (\n'
 '\tgame_id VARCHAR(64) NOT NULL, \n'
 '\toriginal_account_id UUID NOT NULL, \n'
 '\tkind VARCHAR(32) NOT NULL, \n'
 '\treward_facts JSONB NOT NULL, \n'
 '\tseen_observation_ids JSONB NOT NULL, \n'
 "\tformula_version INTEGER DEFAULT '1' NOT NULL, \n"
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (game_id, original_account_id, kind), \n'
 "\tCONSTRAINT ck_night_reward_kind CHECK (kind = 'case_result' AND formula_version = 1), \n"
 '\tFOREIGN KEY(game_id) REFERENCES games (id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(original_account_id) REFERENCES accounts (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_episode_drafts (\n'
 '\tdraft_id VARCHAR(96) NOT NULL, \n'
 '\tcandidate JSONB NOT NULL, \n'
 '\tcontent_hash VARCHAR(64) NOT NULL, \n'
 '\tworld_id VARCHAR(64) NOT NULL, \n'
 '\tcontract_version VARCHAR(64) NOT NULL, \n'
 '\tsource_job_id VARCHAR(96), \n'
 "\towner_review VARCHAR(16) DEFAULT 'draft' NOT NULL, \n"
 '\treviewed_by UUID, \n'
 '\treviewed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (draft_id), \n'
 "\tCONSTRAINT ck_night_draft_review CHECK (owner_review IN ('draft','rejected','approved')), \n"
 '\tFOREIGN KEY(source_job_id) REFERENCES night_render_jobs (job_id) ON DELETE RESTRICT, \n'
 '\tFOREIGN KEY(reviewed_by) REFERENCES accounts (id) ON DELETE RESTRICT\n'
 ')',
 'CREATE TABLE night_renderings (\n'
 '\tjob_id VARCHAR(96) NOT NULL, \n'
 '\ttext TEXT NOT NULL, \n'
 '\tsource VARCHAR(16) NOT NULL, \n'
 '\tcontent_hash VARCHAR(64) NOT NULL, \n'
 '\t"references" JSONB NOT NULL, \n'
 '\tcatalog_ids JSONB NOT NULL, \n'
 '\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tfirst_shown_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (job_id), \n'
 "\tCONSTRAINT ck_night_rendering_source CHECK (source IN ('authored','ai') AND length(text) <= "
 '4000), \n'
 '\tFOREIGN KEY(job_id) REFERENCES night_render_jobs (job_id) ON DELETE RESTRICT\n'
 ')']

TABLES = ['night_narrator_limits', 'night_runtime_outages', 'night_cases', 'night_runtime_health', 'night_events', 'night_game_sealed', 'night_intent_proposals', 'night_lobby_commands', 'night_messages', 'night_render_jobs', 'night_reward_claims', 'night_episode_drafts', 'night_renderings']


def upgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT room_id FROM games WHERE is_current AND
        ((mode='night_case' AND status NOT IN ('finished','stopped')) OR
         (mode='mafia' AND status NOT IN ('finished','stopped','interrupted')))
        GROUP BY room_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'night_family_conflict: inspect current games by room; no rows were changed';
      END IF;
    END $$""")
    op.create_index('uq_games_current_night_family', 'games', ['room_id'], unique=True,
        postgresql_where=sa.text("is_current AND ((mode='night_case' AND status NOT IN ('finished','stopped')) OR (mode='mafia' AND status NOT IN ('finished','stopped','interrupted')))"))
    op.add_column('game_deadlines', sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('game_deadlines', sa.Column('last_error_code', sa.String(64)))
    op.add_column('game_deadlines', sa.Column('retry_at', sa.DateTime(timezone=True)))
    op.add_column('game_deadlines', sa.Column('quarantined_at', sa.DateTime(timezone=True)))
    for ddl in TABLE_DDL:
        op.execute(ddl)
    install_guards()


def downgrade():
    for name in TABLES:
        op.execute(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {name}) THEN RAISE EXCEPTION 'night_history_retained: {name} is not empty'; END IF; END $$")
    for name in reversed(TABLES):
        op.drop_table(name)
    for table, trigger in [('games','night_game_guard'),('game_players','night_player_guard'),('game_events','night_event_guard')]:
        op.execute(f'DROP TRIGGER IF EXISTS {trigger} ON {table}')
    op.execute('DROP FUNCTION night_guard()')
    op.drop_index('uq_games_current_night_family', table_name='games')
    for name in ['quarantined_at','retry_at','last_error_code','attempts']:
        op.drop_column('game_deadlines', name)


def install_guards():
    op.execute("""ALTER TABLE night_runtime_outages ADD CONSTRAINT ex_night_outage_overlap
        EXCLUDE USING gist (tstzrange(started_at, ended_at, '[)') WITH &&)""")
    # Bound every JSON value even if a future writer bypasses the repository.
    for table, columns in {
        'night_cases': ['content','validation_report'],
        'night_game_sealed': ['rules','kernel','lobby','interruption'],
        'night_lobby_commands': ['result'], 'night_events': ['payload'],
        'night_messages': ['recipients'], 'night_render_jobs': ['frozen_view'],
        'night_renderings': ['references','catalog_ids'],
        'night_intent_proposals': ['proposal'], 'night_episode_drafts': ['candidate'],
        'night_reward_claims': ['reward_facts','seen_observation_ids'],
    }.items():
        for column in columns:
            bound = 16777216 if column == 'kernel' else (2097152 if column == 'content' else 65536)
            op.execute(f'ALTER TABLE {table} ADD CONSTRAINT ck_{table}_{column}_bound CHECK (octet_length("{column}"::text) <= {bound})')
    op.execute("""CREATE FUNCTION night_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE old_json jsonb; new_json jsonb; game_mode text; key_name text;
    BEGIN
      IF TG_OP = 'DELETE' THEN old_json := to_jsonb(OLD); ELSE new_json := to_jsonb(NEW); END IF;
      IF TG_OP = 'UPDATE' THEN old_json := to_jsonb(OLD); END IF;
      IF TG_TABLE_NAME = 'games' THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        IF TG_OP = 'UPDATE' AND OLD.mode = 'night_case' AND NEW.mode <> 'night_case' THEN RAISE EXCEPTION 'night_mode_immutable'; END IF;
        IF TG_OP <> 'DELETE' AND NEW.mode = 'night_case' THEN
          IF jsonb_typeof(NEW.state::jsonb) <> 'object'
            OR (NEW.state::jsonb - ARRAY['storage_version','case_ref','lifecycle','public_projection']) <> '{}'::jsonb
            OR NOT (NEW.state::jsonb ?& ARRAY['storage_version','case_ref','lifecycle','public_projection'])
            OR NEW.state::jsonb->'storage_version' <> '1'::jsonb
            OR jsonb_typeof(NEW.state::jsonb->'public_projection') <> 'object'
            OR jsonb_typeof(NEW.state::jsonb->'case_ref') <> 'object'
            OR ((NEW.state::jsonb->'case_ref') - ARRAY['id','version','hash']) <> '{}'::jsonb THEN
            RAISE EXCEPTION 'night_public_envelope';
          END IF;
        END IF;
        RETURN NEW;
      END IF;
      IF TG_TABLE_NAME IN ('game_players','game_events') THEN
        SELECT mode INTO game_mode FROM games WHERE id = COALESCE(new_json->>'game_id',old_json->>'game_id');
        IF game_mode = 'night_case' THEN
          IF TG_TABLE_NAME = 'game_events' THEN RAISE EXCEPTION 'night_generic_event_forbidden'; END IF;
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'night_player_history_immutable'; END IF;
          IF NEW.private_state::jsonb <> '{}'::jsonb
            OR (NEW.public_state::jsonb - ARRAY['name','seat','status']) <> '{}'::jsonb
            OR (TG_OP = 'UPDATE' AND
              (old_json - ARRAY['status','public_state']) IS DISTINCT FROM (new_json - ARRAY['status','public_state'])) THEN
            RAISE EXCEPTION 'night_player_binding';
          END IF;
        END IF;
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
      END IF;
      IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'night_history_immutable'; END IF;
      IF TG_OP = 'INSERT' THEN RETURN NEW; END IF;
      IF TG_TABLE_NAME = 'night_cases' THEN
        old_json := old_json - 'admission'; new_json := new_json - 'admission';
      ELSIF TG_TABLE_NAME = 'night_game_sealed' THEN
        FOREACH key_name IN ARRAY ARRAY['game_id','case_id','version','content_hash','rules','rules_hash','engine_build','compiler_version','storage_version'] LOOP
          IF old_json->key_name IS DISTINCT FROM new_json->key_name THEN RAISE EXCEPTION 'night_pin_immutable'; END IF;
        END LOOP;
        IF OLD.lifecycle = 'interrupted' AND NEW.kernel IS DISTINCT FROM OLD.kernel THEN RAISE EXCEPTION 'night_interrupted_kernel_immutable'; END IF;
        IF NEW.storage_revision < OLD.storage_revision THEN RAISE EXCEPTION 'night_revision_regression'; END IF;
        RETURN NEW;
      ELSIF TG_TABLE_NAME = 'night_render_jobs' THEN
        old_json := old_json - ARRAY['status','attempts','lease_owner','lease_until','retry_at','sanitized_error'];
        new_json := new_json - ARRAY['status','attempts','lease_owner','lease_until','retry_at','sanitized_error'];
      ELSIF TG_TABLE_NAME = 'night_renderings' THEN
        IF OLD.first_shown_at IS NOT NULL AND NEW.first_shown_at IS DISTINCT FROM OLD.first_shown_at THEN RAISE EXCEPTION 'night_first_shown_immutable'; END IF;
        old_json := old_json - 'first_shown_at'; new_json := new_json - 'first_shown_at';
      ELSIF TG_TABLE_NAME = 'night_intent_proposals' THEN
        IF OLD.confirmed_command_id IS NOT NULL AND NEW.confirmed_command_id IS DISTINCT FROM OLD.confirmed_command_id THEN RAISE EXCEPTION 'night_confirmation_immutable'; END IF;
        old_json := old_json - 'confirmed_command_id'; new_json := new_json - 'confirmed_command_id';
      ELSIF TG_TABLE_NAME = 'night_episode_drafts' AND OLD.owner_review <> 'approved' THEN
        RETURN NEW;
      ELSIF TG_TABLE_NAME = 'night_runtime_outages' THEN
        IF OLD.ended_at IS NOT NULL THEN RAISE EXCEPTION 'night_completed_outage_immutable'; END IF;
        old_json := old_json - 'ended_at'; new_json := new_json - 'ended_at';
      END IF;
      IF old_json IS DISTINCT FROM new_json THEN RAISE EXCEPTION 'night_history_immutable'; END IF;
      RETURN NEW;
    END $$""")
    for table in TABLES:
        if table in ('night_runtime_health','night_narrator_limits'):
            continue
        op.execute(f'CREATE TRIGGER night_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION night_guard()')
    for table, trigger in [('games','night_game_guard'),('game_players','night_player_guard'),('game_events','night_event_guard')]:
        op.execute(f'CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION night_guard()')
