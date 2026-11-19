"""Dispatch record-specific Night guards only inside the matching table branch.

The 0045 guard referenced OLD.owner_review while dispatching other record types.
All history/pin constraints remain unchanged; only the table-specific dispatch is
nested. Downgrade intentionally retains this compatible fix on 0046, rather than
reintroducing a runtime failure. A subsequent 0045 downgrade drops the function.
"""
from alembic import op

revision = '20261116_0047'
down_revision = '20261116_0046'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE OR REPLACE FUNCTION night_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
      ELSIF TG_TABLE_NAME = 'night_episode_drafts' THEN
        IF OLD.owner_review <> 'approved' THEN RETURN NEW; END IF;
      ELSIF TG_TABLE_NAME = 'night_runtime_outages' THEN
        IF OLD.ended_at IS NOT NULL THEN RAISE EXCEPTION 'night_completed_outage_immutable'; END IF;
        old_json := old_json - 'ended_at'; new_json := new_json - 'ended_at';
      END IF;
      IF old_json IS DISTINCT FROM new_json THEN RAISE EXCEPTION 'night_history_immutable'; END IF;
      RETURN NEW;
    END $$""")


def downgrade():
    # This replacement is schema-compatible with 0046 and preserves every guard.
    pass
