"""Pure orchestration codecs; PostgreSQL acceptance lives in the separate file."""
import pytest

from application.night_case import NightCaseError, parse_start_request
from storage.night_cases import json_hash


def test_implicit_start_preserves_the_author_released_fingerprint():
    command = {'command_id': 'start-001', 'expected_lobby_revision': 4, 'params': {}}
    parsed = parse_start_request(command)
    assert parsed.payload_hash == json_hash({'kind': 'start_game', 'expected_lobby_revision': 4, 'params': {}})
    explicit = parse_start_request({**command, 'params': {'ai': {'mode': 'admin', 'expected_epoch': 0, 'staged_credential_id': None}}})
    assert explicit.payload_hash != parsed.payload_hash


@pytest.mark.parametrize('ai', [
    {'mode': 'admin', 'expected_epoch': True, 'staged_credential_id': None},
    {'mode': 'byok', 'expected_epoch': 0, 'staged_credential_id': None},
    {'mode': 'authored', 'expected_epoch': 0, 'staged_credential_id': 'forged'},
    {'mode': 'admin', 'expected_epoch': 0},
])
def test_start_options_are_closed(ai):
    with pytest.raises(NightCaseError):
        parse_start_request({'command_id': 'start-001', 'expected_lobby_revision': 0, 'params': {'ai': ai}})


def test_prepared_codec_rejects_extra_fields_invalid_pins_and_bool_fences():
    import copy
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from uuid import uuid4
    from application.night_case_orchestrator import _decode
    now=datetime(2026,11,15,tzinfo=timezone.utc)
    token={'schema':'night-ai-intent-token/1','request_token':'a'*64,'case_hash':'b'*64,'rules_hash':'c'*64,
        'engine_build':'synthetic/1','window_idx':1,'window_seq':1,'actor_seq':0,
        'prepared_at':'2026-11-15T00:00:00Z','expires_at':'2026-11-15T00:02:00Z',
        'text':'look','config_hash':'d'*64,'caps_hash':'e'*64}
    row=SimpleNamespace(token=token,legal_candidates={'schema':'night-ai-legal/1','items':[]},status='prepared',
        binding_id=uuid4(),created_at=now,expires_at=now+timedelta(seconds=120))
    assert _decode(row)[0]==token
    for changed in ({'extra':'forbidden'},{'config_hash':None},{'request_token':'x'*64},{'actor_seq':True},{'text':'x'*1001}):
        row.token={**copy.deepcopy(token),**changed}
        with pytest.raises(NightCaseError): _decode(row)


def test_jsonb_bound_accounts_for_postgres_spacing_and_nul_without_truncation():
    from application.night_case_orchestrator import _jsonb_bound
    from storage.night_cases import canonical_json
    value={'a':[1,2,3]}
    assert len(canonical_json(value))==13
    with pytest.raises(ValueError): _jsonb_bound(value,13)
    with pytest.raises(ValueError): _jsonb_bound({'text':'a\x00b'},100)
    _jsonb_bound({'text':r'literal\u0000'},100)


def test_legal_uses_authorized_menu_labels_across_id_namespaces():
    import json
    from application.night_case_orchestrator import NightCaseOrchestrator
    from domain.night_case_engine import _initialize
    from domain.night_case_projection import MenuChoice, available_actions
    from domain.night_case_state import PlayerActor, rules_snapshot
    from domain.night_case_v2_format import compile_v2, load_v2
    from tests.test_night_case_engine import FIXTURE, NOW

    def rename(value):
        if type(value) is dict: return {key: rename(item) for key, item in value.items()}
        if type(value) is list: return [rename(item) for item in value]
        return 'platform' if value == 'proof_a' else value

    document = rename(json.loads(FIXTURE.read_text(encoding='utf8')))
    next(item for item in document['observations'] if item['id'] == 'platform')['title'] = 'SEALED_OTHER_VARIANT_CANARY'
    case = compile_v2(load_v2(json.dumps(document, ensure_ascii=False).encode('utf8')))
    rules = rules_snapshot('Europe/Berlin')
    roster = {'players': [{'account_id': f'account{i}', 'display_name': f'Player {i}'} for i in range(4)],
              'npc_name_pool': [f'NPC {i}' for i in range(20)]}
    state = _initialize(case, rules, roster, game_id='testgame', seed=42,
                        composition_id='players_04', selected_variant_id='variant_b', now_utc=NOW).state
    menu = available_actions(case, rules, state, PlayerActor('account0'), now_utc=NOW)
    move = next(choice for choice in menu if isinstance(choice, MenuChoice) and choice.quote.kind == 'move'
                and choice.quote.target_id == 'platform')
    act = next(choice for choice in menu if isinstance(choice, MenuChoice) and choice.quote.kind == 'act'
               and choice.quote.target_id == 'inspect_desk')
    legal = NightCaseOrchestrator._legal(case, rules, state, 'account0', NOW)['items']
    legal_move = next(item for item in legal if item['selection_id'] == move.quote.selection_id)
    legal_act = next(item for item in legal if item['selection_id'] == act.quote.selection_id)
    assert move.label == 'platform'
    assert legal_move['label'] == 'move: ' + move.label
    assert 'SEALED_OTHER_VARIANT_CANARY' not in json.dumps(legal, ensure_ascii=False)
    assert legal_act['label'] == 'act: ' + act.label

