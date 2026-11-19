# Следующая приёмка платформы после group Photo

2026-11-15. Read-only сверка исходников и тестов; приложение, БД и production
этой проверкой не изменялись. Чужой diff сохранён. Это не повторный аудит backlog
и не основание закрыть MQB-001/002/003/005/006 или QW целиком.

## Уже доказано автоматикой

По переданному координатором свежему JUnit: 2791 passed, 0 failed/errors,
1 skipped; skip — `tests.test_farm_order_variety::test_sonya_sometimes_gets_a_signature_item`
(доступная progression не достигает signature). Farm migration **прошла**.
Отдельно переданы 183 JS и 62 focused Photo passed. Я эти команды не повторяла.

В полном gate действительно включены не только unit-тесты:

- `compose.dev.yml:215` включает `MQB_TEST_DUMP_RESTORE=1`, `:222` запускает
  Alembic upgrade/check и pytest; `tests/test_local_acceptance.py:172` реально
  dump/restore синтетической private schema, сравнивает все rows, moderation receipt
  и баллы. Это доказательство механизма, не retained backup песочницы.
- Account registration/новый HTTP client (`tests/test_account_password.py:61`),
  guest expiry/logout/moderation/revision (`tests/test_guest_accounts.py:33`),
  повтор renewal/lost response (`:67`), повторный экземпляр ASGI app без Telegram
  (`:78`) покрыты. Последнее не является реальным restart сервисов.
- Linking сохраняет farm/progress, preview не пишет, повтор идемпотентен,
  rollback и конкурирующие login/link проверены
  (`tests/test_account_linking.py:120`, `:193`, `:214`, `:250`).
  Сервис перепроверяет initData и expiry после ownership locks
  (`application/account_linking.py:81`).
- Merge обеих непустых сторон и оба выбора main, пустая сторона, чужой browser,
  неверные IDs, повтор, просроченные initData покрыты
  (`tests/test_account_merge_flow.py:153`, `:188`, `:213`, `:248`, `:266`, `:337`).
  Детальные политики FK/баллов/farm/login/session/rollback проверяет
  `tests/test_account_merge.py:71`, `:195`, `:295`, `:374`, `:432`, `:459`.
- Password change/recovery отзывает остальные guest/mini sessions; свежая и
  старая Telegram proof различаются; чужой session ID не отзывается
  (`tests/test_account_security.py:111`, `:148`, `:210`, `:246`;
  `application/account_security.py:90`, `:123`).
- Bot-approved browser login имеет expiry/cancel/replay/чужую cookie/проверку
  того, кому показано подтверждение (`tests/test_telegram_login.py:171`, `:194`,
  `:217`, `:512`). Transport синтетический, живой Telegram этим не доказан.
- Два отдельных worker process и новый процесс после завершения не повторяют
  Classic transition (`tests/test_game_worker_concurrency.py:107`); отдельно
  проверены Photo/Mafia/standalone Mafia (`:169`, `:203`, `:254`, `:309`).
- Outbox: dedupe и конкурирующий claim, fencing старого callback, RetryAfter
  против uncertain (`tests/test_notifications.py:27`, `:71`, `:116`).
  Операторы: replay/conflict/rollback/квитанции и карантин orphan claim
  (`tests/test_notification_resolution.py:37`, `:92`;
  `tests/test_notification_quarantine.py:36`, `:73`, `:121`).

## Четыре следующих сценария

1. **Реальный browser/new device**, на собственном тестовом аккаунте песочницы:
   создать credentials → независимый browser context входит тем же login →
   те же account/farm/room/progress → выход/повторный вход → отзыв второго
   устройства → второй видит истечение и может снова войти → смена пароля
   сохраняет текущую сессию и закрывает остальные. Координатор выполняет этот
   цикл сейчас. ASGI и VM JS tests не заменяют сетевые cookie, UI и HTTP ошибки.

2. **Retained sandbox backup → отдельная local test DB**: сверить конкретный
   архив и manifest/checksums/media, восстановить исключительно в disposable
   local DB, проверить schema/version и accounts/session/rooms/progress/receipts,
   затем применимость upgrade. Не восстанавливать ничего на сервере. Успешный
   synthetic dump/restore выше и mocked `tests/test_dev_backups.py:82` не
   закрывают этот пункт. Координатор выполняет отдельную проверку архива.
   `storage/dev_backups.py:195` — local-dev ZIP verifier с жёстким guard,
   это не универсальный импорт произвольного server archive.

3. **Merge против действующих команд**: оба непустых аккаунта, main выбирается
   явно; конкурентно подтверждение merge и craft/claim либо room action.
   Проверить отсутствие deadlock/500, ровно один receipt/reward, канонический
   account в обеих сессиях, чужая сессия не получает доступ. Это конкретный
   пробел существующих suites: merge_flow проверяет порядок SQL locks
   (`tests/test_account_merge_flow.py:392`), но в этом файле и test_account_merge
   нет настоящей конкурентной пары merge с gameplay. Linking race уже покрыта.
   Выполнять только на disposable PG fixture; чужие аккаунты не объединять.

   Дополнение: добавлена свежая runnable проверка
   `tests/test_account_merge_game_races.py`: две пары public HTTP merge с
   approved login против guest craft и rated Telegram craft, `asyncio.Barrier`,
   `gather` и timeout 20 секунд; SQL решает сериализацию. Проверяются union
   прогресса, verified steam, владение единственной command receipt, ScoreEvent/
   ScoreTotal/points_total и replay из другого канала. Узкий запуск в local
   Docker: **2 passed in 10.28s**. Это не forced coverage всех возможных порядков
   блокировок; claim и room action в новые случаи не вошли.

   Связанный запуск new races + `test_account_merge_flow.py` +
   `test_account_linking.py`: **21 passed in 38.96s**, local `morning_quiz_test`.
   Команда: `docker compose -p mqb-local-dev -f compose.dev.yml --profile test run
   --rm --no-deps -e QW_FARM_MERCHANT_SECRET=merge-race-synthetic-test-secret-20261115
   tests python -m pytest -q -p no:cacheprovider tests/test_account_merge_game_races.py
   tests/test_account_merge_flow.py tests/test_account_linking.py`.
   Первый связанный запуск без явного test merchant key: 20 passed/1 failed
   в existing farm bootstrap (`qw_farm/merchant.py:228`, required persistent key).
   Повтор использует только синтетический ключ; product code не менялся.

4. **API/worker restart при живой комнате** на выделенном изолированном контуре:
   создать due game без Telegram → остановить только собственные API/worker →
   поднять их → один deadline transition, тот же account/room, повтор команды
   не удваивает награду; проверить очередь notifications отдельно. Process suites
   выше уже доказывают PG locks, но не compose/service restart и UI reconnect.
   Крах после claim до delivery оставляет `sending`: это предусмотренный
   эксплуатационный путь, не гарантия автоматической доставки после restart.
   `storage/notifications.py:54` прямо запрещает слепой retry sending;
   `:153` требует независимого подтверждения остановки sender для карантина.

## Что остаётся внешней приёмкой

Реальные Telegram Desktop/Android/iOS, HTTPS/WebView, bot approval, quiz poll и
видимость одного прогресса в двух каналах требуют действующего тестового клиента
и разрешённого тестового бота. Не выдавать signed initData/AsyncMock за device pass.
Production cutover, рабочий token, рассылки и restore production требуют отдельного
явного разрешения; эти действия здесь не планировались и не выполнялись.

`docs/engineering/RELEASE_CRITERIA.md:53` требует настоящую матрицу сценариев,
а `:110` — evidence ревизии/среды, миграции и backup/restore. Поэтому зелёный full
gate закрывает перечисленные автоматические инварианты, но не целиком этапы 1/3/5/6.
Старый абзац RELEASE_CRITERIA о ещё отсутствующих linking/recovery/group Photo
устарел относительно кода: его нельзя использовать как список отсутствующей реализации.
