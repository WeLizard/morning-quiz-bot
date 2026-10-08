import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.audit_question_bank import ROOT, audit_category, audit_seed, run


def test_audit_reports_invalid_records_and_normalized_duplicate_prompts():
    report = audit_category('Логика', [
        {'question': '  Что такое ответ? ', 'options': ['Да', 'Нет'], 'correct': 'Да'},
        {'question': 'Что такое ответ!', 'options': ['Да', 'Нет'], 'correct': 'Да'},
        {'question': 'Повтор опций', 'options': ['Нет', 'Нет'], 'correct': 'Нет'},
    ], 'json')
    assert report['count'] == 3 and report['invalid'] == 1
    assert report['errors'][0]['index'] == 3
    assert report['errors'][0]['reason'].startswith('options: ')
    assert report['duplicates'][0]['indexes'] == [1, 2]
    assert [item['correct'] for item in report['duplicates'][0]['variants']] == ['Да', 'Да']


def test_json_audit_reports_control_characters_without_mutating_source(tmp_path):
    path = tmp_path / 'Категория.json'
    original = [{'question': 'Вопрос\x01', 'options': ['Да', 'Нет'], 'correct': 'Да'}]
    path.write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
    report = audit_seed(tmp_path)
    assert report[0]['invalid'] == 1
    assert report[0]['errors'][0]['reason'] == 'forbidden control character'
    assert json.loads(path.read_text(encoding='utf-8')) == original


def test_checked_in_seed_has_no_fatal_audit_findings():
    report = audit_seed(ROOT / 'data' / 'questions')
    assert len(report) == 63
    assert sum(item['count'] for item in report) == 6706
    assert sum(item['invalid'] for item in report) == 0


def test_postgres_audit_requires_explicit_test_database_url(monkeypatch, tmp_path):
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    (tmp_path / 'Факты.json').write_text('[]', encoding='utf-8')
    args = SimpleNamespace(seed_directory=tmp_path, postgres=True,
                           json_output=tmp_path / 'report.json',
                           markdown_output=tmp_path / 'report.md')
    with pytest.raises(SystemExit, match='TEST_DATABASE_URL'):
        asyncio.run(run(args))
    assert not args.json_output.exists() and not args.markdown_output.exists()


def test_postgres_audit_refuses_non_disposable_remote_database(monkeypatch, tmp_path):
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://mqb_dev:secret@db.example.com:5432/production')
    (tmp_path / 'Факты.json').write_text('[]', encoding='utf-8')
    args = SimpleNamespace(seed_directory=tmp_path, postgres=True,
                           json_output=tmp_path / 'report.json',
                           markdown_output=tmp_path / 'report.md')
    with pytest.raises(SystemExit, match='disposable local'):
        asyncio.run(run(args))
    assert not args.json_output.exists() and not args.markdown_output.exists()


def test_audit_refuses_missing_seed_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match='Question directory'):
        audit_seed(tmp_path / 'missing')
