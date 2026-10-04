import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import httpx
import pytest
from fastapi import FastAPI

from storage.question_bank import BankConflict, QuestionBank
from web.question_bank_admin import make_bank_router
from web.admin_auth import AdminAuth, install_admin_auth
from tests.test_admin_auth import TOKEN, login
from tests.test_postgres_members import pg_env


QUESTION = {'question': 'Кто ведёт квиз?', 'options': ['Сова', 'Лиса'], 'correct': 'Сова', 'explanation': ''}


def test_corrupt_file_repair_keeps_original_and_rejects_stale_or_invalid(tmp_path):
    bank = QuestionBank(tmp_path)
    path = tmp_path / 'Broken.json'
    original = b'{broken json'
    path.write_bytes(original)
    item, = bank.categories()
    assert item['error'] and item['version'] and bank.raw('Broken') == original
    with pytest.raises(ValueError):
        bank.repair('Broken', item['version'], [{'bad': True}])
    assert path.read_bytes() == original
    bank.repair('Broken', item['version'], [QUESTION])
    assert bank.read('Broken')['count'] == 1
    assert next((tmp_path / '.history' / 'Broken').glob('*.json')).read_bytes() == original
    with pytest.raises(BankConflict):
        bank.repair('Broken', item['version'], [QUESTION])


def test_bank_preserves_history_metadata_and_rejects_stale_edit(tmp_path):
    bank = QuestionBank(tmp_path)
    bank.create('Лес')
    (tmp_path / 'Лес.json').write_text(json.dumps([dict(QUESTION, tags=['keep'], correct_option_text='stale')]), encoding='utf-8')
    initial = bank.read('Лес')
    raw = (tmp_path / 'Лес.json').read_bytes()
    changed = bank.change('Лес', initial['version'], index=0, question=dict(QUESTION, correct='Лиса'))
    assert changed['questions'][0]['tags'] == ['keep']
    assert 'correct_option_text' not in changed['questions'][0]
    assert bank.for_quiz()['Лес'][0]['correct_option_text'] == 'Лиса'
    with pytest.raises(BankConflict):
        bank.change('Лес', initial['version'], remove=True)
    assert next((tmp_path / '.history' / 'Лес').glob('*.json')).read_bytes() == raw
    result = bank.change('Лес', changed['version'], remove=True)
    assert result['recoverable'] and not (tmp_path / 'Лес.json').exists()
    assert len(list((tmp_path / '.history' / 'Лес').glob('*.json'))) == 2


def test_concurrent_edits_only_one_wins_and_failed_import_is_atomic(tmp_path):
    bank = QuestionBank(tmp_path)
    initial = bank.create('Тест')
    def write(_):
        try:
            return bank.change('Тест', initial['version'], question=QUESTION)
        except BankConflict:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(result is not None for result in pool.map(write, range(4))) == 1
    before = (tmp_path / 'Тест.json').read_bytes()
    with pytest.raises(ValueError):
        bank.change('Тест', bank.read('Тест')['version'], import_values=[QUESTION, {'bad': 'data'}])
    assert (tmp_path / 'Тест.json').read_bytes() == before


@pytest.mark.parametrize('name', ['../x', 'a/b', 'a\\b', 'C:x', 'CON', '.history', '', 'name.', 'name ', 'LPT1'])
def test_bank_rejects_unsafe_paths(tmp_path, name):
    with pytest.raises(ValueError):
        QuestionBank(tmp_path).create(name)


def test_bank_api_auth_crud_import_export_and_versions(pg_env):
    from tests.local_database import isolated_database
    async def run():
        async with isolated_database(pg_env) as (database, _):
            app = FastAPI(); app.state.admin_database = database
            app.include_router(make_bank_router()); install_admin_auth(app, auth=AdminAuth(TOKEN))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
                assert (await client.get('/api/bank/categories')).status_code == 401
                csrf = await login(client); client.headers['X-CSRF-Token'] = csrf
                path = '/api/bank/categories/Лес'
                assert (await client.post('/api/bank/categories', json={'name': 'Лес'})).status_code == 201
                category = (await client.get(path)).json()
                assert (await client.post(path + '/questions', json=QUESTION)).status_code == 428
                assert (await client.post(path + '/questions', params={'expected_version': category['version']}, json=QUESTION)).status_code == 201
                assert (await client.delete(path, params={'expected_version': category['version']})).status_code == 409
                category = (await client.get(path)).json()
                assert category['questions'][0]['correct'] == 'Сова'
                assert (await client.get(path + '/export')).json() == [QUESTION]
                response = await client.post(path + '/import', params={'expected_version': category['version']}, json={'questions': [dict(QUESTION, correct='wrong')]})
                assert response.status_code == 422
                assert (await client.get(path)).json()['version'] == category['version']
                response = await client.put(path + '/questions/0', params={'expected_version': category['version']}, json=dict(QUESTION, question='Новый вопрос'))
                assert response.status_code == 200
                current = (await client.get(path)).json()
                assert (await client.delete(path + '/questions/0', params={'expected_version': current['version']})).status_code == 200
    asyncio.run(run())


def test_bot_reloads_question_edits_from_postgres_without_legacy_json(pg_env):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from data_manager import DataManager
    from storage.question_bank import PostgresQuestionBank
    from tests.local_database import isolated_database
    async def run():
        async with isolated_database(pg_env) as (database, _):
            bank = PostgresQuestionBank(database)
            version = (await bank.create('Лес'))['version']
            await bank.change('Лес', version, question=QUESTION)
            data = DataManager.__new__(DataManager)
            data.postgres_storage = SimpleNamespace(database=database)
            data.state = SimpleNamespace()
            data._update_categories_file = Mock(side_effect=AssertionError('No JSON projection writes'))
            await data.load_questions_async()
            assert data.state.quiz_data['Лес'][0]['correct_option_text'] == 'Сова'
            current = await bank.read('Лес')
            await bank.change('Лес', current['version'], index=0,
                              question=dict(QUESTION, correct='Лиса'))
            await data.load_questions_async()
            assert data.state.quiz_data['Лес'][0]['correct_option_text'] == 'Лиса'
            data._update_categories_file.assert_not_called()
    asyncio.run(run())
