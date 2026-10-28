# Поле: новый экран, этап 1

Статус: **выложено в песочницу, приёмка владельцем/Telegram не завершена** (2026-10-28).
Решение владельца 2026-10-28: сначала заменить старый экран поля на текущих
серверных правилах; опрыскиватель, урон/состояние, поворот орудия, per-cell
посев и тестовая экономика 85–125/90 — отдельный этап 2.

## Что входит

- Новый полноэкранный overlay поля: canvas-сцена в стиле утверждённого макета,
  качества/охват/счётчик операции, бонус времени, D-pad, результат, журнал
  техники на ПК, мобильная легенда, день/ночь и контрастный режим.
- Три текущие операции (`cultivate`, `sow`, `harvest`), ширины 1–3 и размеры
  1/2/3 га из живого каталога; экономика не менялась.
- Для новых уборочных заходов грузовик стоит у верхнего края; сервер принимает
  `X` только у точки выгрузки. Заходы без маркера `unload_zone` сохраняют
  прежнее правило «верхний край».
- Плавная выгрузка — визуальная: база 2,4 с, удержание кнопки ×3, при уходе
  с точки перекачка отменяется; сервер получает один `X` после завершения.
  Частичная выгрузка на сервере не менялась.
- Старый DOM/canvas-код `openFieldGame` удалён из `tractor_game.js`; модуль
  оставлен чистым для серверного паритета и тестов. Общие `.fg-*` стили не
  удалялись: их использует походная мини-игра.

## Файлы

- `qw_farm/static/field_overlay.js`, `qw_farm/static/field_overlay.css`
- `qw_farm/static/tractor_game.js` (чистые правила, без UI)
- `qw_farm/static/app.js`, `qw_farm/static/index.html`, `qw_farm/api.py`
- `qw_farm/catalog.py`, `qw_farm/fields.py`
- `tests/js/farm_tractor.test.cjs`, `tests/test_farm_fields_r9.py`

## Проверки

- `python -m pytest tests/test_farm_fields_r9.py -q` — 64 passed.
- `node --test tests/js/farm_tractor.test.cjs` — 11 passed.
- `node --test tests/js/ui_rules.test.cjs tests/js/ui_layout.test.cjs` — 12 passed, 2 skipped без `QW_UI_BASE_URL`.
- `python scripts/project_checks.py --worktree` — exit 0.
- `python tests/ui/ui_check.py gaps --base http://127.0.0.1:4185 --only farm` — 51 passed.
- Живой dev: cultivate 1 га, sow 1/2 га, harvest 1/3 га, фиксированный грузовик,
  авто-выгрузка и удержание, автопилот, закрытие с подтверждением и возврат к
  заходу; 375×812, 390×844, 1280×800; день, ночь, контраст.
- Полный `scripts/Test-LocalMilestone.ps1` запущен, но общий набор упирается в
  существующий сбой `tests/test_account_contrast_mode.py::test_farm_client_applies_the_mode_and_draws_it`
  из-за незакоммиченного блока контрастных правил в `qw_farm/static/style.css`
  (правило без `:root[data-qw-contrast="1"]` в селекторе). Это не полевой код;
  полевые и интерфейсные проверки выше зелёные. Полный gate нельзя считать
  пройденным до отдельного решения по этому чужому diff.

## Песочница

- 2026-10-28 выложены 8 файлов в `/home/lizard/mqb-rehearsal`; сервис
  `mqb-mini-app.service` активен.
- Бэкап исходных файлов:
  `/home/lizard/mqb-rehearsal/backups/field-redesign-20261028-1509/files.tgz`
  (новые `field_overlay.*` в бэкап не входят — их до выкладки не было).
- PostgreSQL, миграции и данные игроков не менялись; дамп не снимался, потому
  что в песочнице PostgreSQL-сервис неактивен и выкладка не меняет БД.
- `/app/farm`, `/app/farm/assets/field_overlay.js`, `field_overlay.css`,
  `tractor_game.js`, `app.js` и `/api/farm/v1/config` отдают HTTP 200;
  в `app.js` есть импорт `./field_overlay.js`, в `index.html` — новый CSS,
  в `tractor_game.js` нет старого `.fg-overlay`.
- Авторизованная игровая сессия и Telegram WebView в песочнице ещё не проверены;
  это остаётся за владельцем и тестировщиком.

## Этап 2

- **2A — поворот и per-cell посев:** реализовано в dev и выложено в песочницу
  2026-10-28, см. [FARM_FIELD_TURN_PER_CELL](FARM_FIELD_TURN_PER_CELL.md).
- **2B/2C — опрыскиватель, урон/состояние/ремонт, экономика 85–125/90 и
  частичная перекачка:** реализовано для новых заходов `rules=3` и выложено в
  песочницу 2026-10-28, см. [FARM_FIELD_SPRAY_AND_TRANSFER](FARM_FIELD_SPRAY_AND_TRANSFER.md).
- Цепочка (chain bonus) осталась вне объёма: правила не были согласованы.
- Живой Telegram WebView и приёмка владельцем — после проверки песочницы.
