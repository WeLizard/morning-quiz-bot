# Тесты Morning Quiz Bot

Актуальный процесс разработки и проверки описан в [DEVELOPMENT](../docs/engineering/DEVELOPMENT.md), критерии релиза — в [RELEASE_CRITERIA](../docs/engineering/RELEASE_CRITERIA.md), подготовка локальной среды — в [LOCAL_DEVELOPMENT](../docs/LOCAL_DEVELOPMENT.md).

## Быстрые проверки

Запускай применимые к diff проверки из корня репозитория:

```powershell
python scripts/project_checks.py --worktree
python -m unittest discover -s tests -p test_project_checks.py
python -m unittest discover -s tests -p test_codex_hooks.py
node --test tests/js/mini_navigation.test.cjs tests/js/alchemy_sync.test.cjs
```

Это отдельные проверки инфраструктуры, хуков и двух JS-клиентов; они не заменяют полный gate.

## Полный Python/PostgreSQL gate

```powershell
pwsh -File scripts/Test-LocalMilestone.ps1
```

Скрипт собирает воспроизводимый dev-образ, пересоздаёт только базу `morning_quiz_test`, применяет миграции, выполняет Alembic check, pytest и проверки backup/restore согласно конфигурации. Он не должен быть направлен на dev или production БД. В отчёте проверь ошибки и все `skipped`, включая причины: пропуск не считается успешным результатом.

## Исторические тесты

`run_all_tests.py` и старые `*_test.py` относятся к прежнему JSON-контуру и не являются полным gate текущей архитектуры. Их можно запускать для исследования legacy-поведения, но успешный запуск не подтверждает актуальную приёмку.

Сохранённые ранее статусы `passed`, отчёты и даты запусков — исторические свидетельства. Для текущей задачи фиксируй свежую команду, окружение, ревизию и результат. Полная матрица готовности находится в [RELEASE_CRITERIA](../docs/engineering/RELEASE_CRITERIA.md).
