import json
from pathlib import Path

from storage.json_importer import JsonSnapshot, as_decimal, parse_datetime, source_digest


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_snapshot_counts_and_normalizes_legacy_layout(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    write_json(
        data_dir / "global" / "users.json",
        {
            "10": {
                "name": "Filinych",
                "global_score": 3.5,
                "milestones_achieved": ["first", "first"],
            }
        },
    )
    write_json(
        data_dir / "global" / "chats_index.json",
        {"-20": {"type": "group", "title": "Test"}},
    )
    write_json(
        data_dir / "chats" / "-20" / "settings.json",
        {
            "daily_quiz": {"enabled": True, "times_msk": [{"hour": 8, "minute": 5}]},
            "daily_wisdom": {"enabled": True, "time": "12:20"},
        },
    )
    write_json(
        data_dir / "chats" / "-20" / "users.json",
        {
            "10": {"name": "Filinych", "answered_polls": ["1", "1"]},
            "11": {"name": "New user", "answered_polls": []},
        },
    )
    write_json(data_dir / "chats" / "-20" / "stats.json", {})
    write_json(data_dir / "chats" / "-20" / "categories_stats.json", {})
    write_json(data_dir / "active_quizzes.json", {"active_quizzes": {}})
    write_json(
        data_dir / "photo_quiz_metadata.json",
        {"owl.jpg": {"correct_answer": "Сова", "hints": {"first_letter": "С"}}},
    )

    snapshot = JsonSnapshot.scan(data_dir)

    assert snapshot.errors == []
    assert snapshot.source_counts() == {
        "chats": 1,
        "users": 2,
        "chat_members": 2,
        "achievement_grants": 1,
        "daily_schedules": 2,
        "active_quizzes": 0,
        "photo_quiz_items": 1,
        "question_categories": 0,
        "system_states": 0,
        "message_cleanup_items": 0,
    }
    assert len(snapshot.digest) == 64


def test_legacy_scalar_normalization() -> None:
    assert str(as_decimal(0.30000000000000004)) == "0.300"
    assert parse_datetime("2026-08-30").isoformat() == "2026-08-30T00:00:00+00:00"
    assert parse_datetime("not-a-date") is None


def test_manifest_and_digest_cover_root_state_and_config_maintenance(tmp_path: Path) -> None:
    data_dir = tmp_path / 'data'
    config_dir = tmp_path / 'config'
    write_json(data_dir / 'bot_mode.json', {'mode': 'normal'})
    write_json(config_dir / 'maintenance_status.json', {'maintenance_mode': False})

    first = JsonSnapshot.scan(data_dir)
    assert {item['path'] for item in first.manifest} == {
        'bot_mode.json', 'config/maintenance_status.json'
    }
    assert first.system_states['maintenance_status'] == {'maintenance_mode': False}

    write_json(data_dir / 'bot_mode.json', {'mode': 'maintenance'})
    second_digest = source_digest(data_dir)
    assert second_digest != first.digest
    write_json(config_dir / 'maintenance_status.json', {'maintenance_mode': True})
    assert source_digest(data_dir) != second_digest


def test_snapshot_rejects_lossy_structural_normalization(tmp_path: Path) -> None:
    data_dir = tmp_path / 'data'
    chat = data_dir / 'chats' / '-20'
    write_json(chat / 'settings.json', [])
    write_json(chat / 'stats.json', {})
    write_json(chat / 'categories_stats.json', {})
    write_json(chat / 'users.json', {
        '10': {'score': 'broken', 'answered_polls': 'not-an-array',
               'last_answer_time': 'not-a-date'}
    })
    write_json(data_dir / 'photo_quiz_metadata.json', {
        'owl': {'correct_answer': 'Сова', 'hints': []},
        'missing': {'enabled': True},
    })

    snapshot = JsonSnapshot.scan(data_dir)

    assert any('settings.json: expected an object' in error for error in snapshot.errors)
    assert any('answered_polls: expected an array' in error for error in snapshot.errors)
    assert any('last_answer_time: invalid datetime' in error for error in snapshot.errors)
    assert any('score: invalid score' in error for error in snapshot.errors)
    assert any('owl.hints: expected an object' in error for error in snapshot.errors)
    assert any('missing.correct_answer: required' in error for error in snapshot.errors)


def test_snapshot_rejects_ambiguous_maintenance_sources(tmp_path: Path) -> None:
    data_dir = tmp_path / 'data'
    write_json(data_dir / 'maintenance_status.json', {'maintenance_mode': False})
    write_json(tmp_path / 'config' / 'maintenance_status.json', {'maintenance_mode': True})
    snapshot = JsonSnapshot.scan(data_dir)
    assert any('source is ambiguous' in error for error in snapshot.errors)


def test_static_json_is_excluded_but_question_bank_is_operational(tmp_path: Path) -> None:
    data_dir = tmp_path / 'data'
    write_json(data_dir / 'system' / 'streak_achievements.json', {
        'streak_achievements': {'3': ['Три подряд']}
    })
    write_json(data_dir / 'global' / 'categories.json', {'История': {}})
    write_json(data_dir / 'questions' / 'История.json', [{'question': 'Когда?'}])

    snapshot = JsonSnapshot.scan(data_dir)
    classifications = {item['path']: item['classification'] for item in snapshot.manifest}

    assert snapshot.errors == []
    assert snapshot.system_states == {}
    assert snapshot.source_counts()['system_states'] == 0
    assert classifications['system/streak_achievements.json'] == 'static_configuration'
    assert classifications['global/categories.json'] == 'operational'
    assert classifications['questions/История.json'] == 'operational'
    assert snapshot.source_counts()['question_categories'] == 1
    assert snapshot.manifest_summary() == {
        'operational': 2,
        'static_configuration': 1,
    }

    digest = snapshot.digest
    write_json(data_dir / 'system' / 'streak_achievements.json', {
        'streak_achievements': {'3': ['Другой текст']}
    })
    assert source_digest(data_dir) == digest
    write_json(data_dir / 'questions' / 'История.json', [{'question': 'Где?'}])
    assert source_digest(data_dir) != digest
