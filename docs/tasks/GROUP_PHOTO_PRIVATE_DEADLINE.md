# Group Photo: приватные ответы и завершение по дедлайну

Дата: 2026-11-15. Статус: implemented_rehearsal_verified (ручная приёмка Telegram-клиентов открыта). Разрешение владельца: реализация,
проверка и выкладка в `/home/lizard/mqb-rehearsal`; production не входит.
Источник: AUD-019 / QW-11 в QUIZZYWIZZY-2026-10-08.md.

## Контракт

- Новый явный `config.answer_policy`: `personal` или `group_private_deadline`.
  Старое состояние без поля сохраняет прежнее поведение. Личные browser/Telegram
  серии остаются личными. Название комнаты не определяет политику.
- В группе все проверенные участники отвечают через приватную форму одного
  сервиса. Каноническая личность — Account; Telegram identity необязательна.
- Вопрос открыт на полуинтервале `[opened_at, closes_at)`. Производственное время
  вычисляется после получения блокировки игры. Правильный ответ не закрывает раунд.
- Неограниченные неверные попытки до успеха/дедлайна, как в существующем Photo;
  попытки, feedback и рассчитанные очки — персональные. Формула очков и подсказки
  сохраняются. После успеха новый command ID не даёт повторной награды.
- До дедлайна видны только собственные attempts/feedback/answered; чужие ответы,
  solved-факты и очки не выходят в HTTP, public events, outbox или общий рейтинг.
- По дедлайну независимый worker атомарно закрывает вопрос, начисляет каждому
  правильно ответившему однократную награду, сохраняет результат и открывает
  следующий вопрос. После простоя следующий вопрос получает полную длительность.
- После закрытия показываются ответ, список правильно ответивших и очки.
  Неверные тексты публично не раскрываются.
- Telegram-группа показывает фото/таймер и кнопку личной Mini App формы.
  Обычные сообщения группы не считаются скрытыми ответами. Личные чаты и старые
  игры сохраняют совместимость.
- Ручная остановка group означает остановку после текущего дедлайна, без
  досрочного раскрытия ответа. Аварийное административное прерывание — отмена.

## Серверные инварианты

- Общий домен и один путь group settlement используются Room и Telegram сервисами.
- Независимые игроки не конфликтуют из-за общей revision: fence ответа —
  game/round/actor/command ID. Повторы возвращают только свой receipt.
- Авторизация Photo write выполняется без раннего actor row lock
  (`room_principal(write=True, lock=False)`), затем game lock и повторная проверка
  доступа. Не вводить Account→game / game→Account инверсию.
- Перед batch awards блокировать всех User по возрастанию id, затем Accounts по
  id. Разрешать merged_into_id; несколько ответов объединённого Account дают
  одну награду с максимальными честно заработанными очками, а не сумму.
- Состояние, ledger/статистика, deadline replacement, outbox и receipts меняются
  в одной транзакции. Private group events не используют public photo_answered.
- SQL-миграция не ожидается: состояние JSON и существующие ledger/commands.
  При выкладке согласованно обновить API, worker и Telegram deliverer.

## Приёмка

- [x] A/B одновременно отвечают верно, до дедлайна наград нет, после — обе один раз.
- [x] Ошибки A не снижают награду B; успех A не меняет доступность B.
- [x] Повторы command ID / новый ID / чужой receipt / новая серия безопасны.
- [x] Deadline−epsilon / ровно deadline / поздний ответ; answer vs worker,
      два worker и пересекающиеся batch awards проверены на PostgreSQL.
- [x] Pending round переживает restart; merge до deadline не блокирует settlement.
- [x] HTTP, events, outbox, общий рейтинг не раскрывают чужой результат до deadline.
- [x] Room membership и Telegram membership проверяются сервером, deep link не даёт прав.
- [x] Personal/legacy серии и media outsider/stale-round регрессии проходят.
- [x] Приватная форма/ожидание/результат/следующий вопрос проверены браузером и JS.
- [x] Обязательные UI renders, gaps и farm pre-deploy screenshots просмотрены.
- [x] Полный локальный PG gate и независимое ревью завершены.
- [x] Узкая выкладка с backup кода, checksum и stamp; данные песочницы сохранены.
- [x] Sandbox smoke и feedback после выкладки проверены.

## План реализации

Независимая архитектурная проверка выполнена до реализации. Backend владеет
domain/photo.py, application/photo.py, room_photo.py, общим group settlement,
storage/games.py и серверными тестами. HTTP/UI владеет Photo routes mini_app.py,
app.js/play-ui.js и JS/API tests. Координатор владеет Telegram Photo adapter,
Photo notifications/launch, интеграцией, проверками и выкладкой.

## Проверки и результат

Заполняется свежими результатами после реализации. Данные предыдущего аудита
не подтверждают эту реализацию. В начале задачи feedback песочницы прочитан
read-only: manual done=2, auto_error done=2, открытых записей 0.

### Локальный срез

- Реализация завершена; независимое ревью исправленных backend/HTTP/UI/Telegram
  переходов не нашло оставшихся подтверждённых P1/P2.
- Финальный focused Docker PG: 62 passed, 0 skipped. Включены per-player attempts,
  два победителя, deadline boundary, worker/answer, два worker, overlapping award
  batches, настоящая merge_in/settlement гонка, история/PollAnswer и legacy/personal.
- Реальный браузерный цикл на собственном loopback QA API подтверждает два
  приватных ответа, нулевые очки до deadline, обе награды после, следующий раунд,
  outsider 404 и deferred stop. Повтор с настоящим рестартом worker, пока ответы
  ожидают deadline, прошёл. Это dev-проверка, не настоящие Telegram-клиенты.
- Farm pre-deploy baseline: 12 просмотренных кадров (home/menu/catalog-all,
  360×780/384×832, day/night, inset48), без игровых команд чужим игрокам.
- Артефакты: `F:\Temp\mqb-group-photo-20261115\`; тестовые комнаты и гостевые
  аккаунты имеют QA-названия. Данные игроков не заменяются тестовой БД.
- Штатный full gate выявил инфраструктуру незакоммиченных Night City тестов:
  import из tests и отсутствующие в образе JSON схемы. Исходники этих тестов
  не менялись; повтор запускается с `PYTHONPATH=/app:/app/tests` и read-only mount
  `docs/tasks/night_city:/app/docs/tasks/night_city`. Три старых Photo ожидания
  обновлены под принятый групповой контракт и отдельно прошли focused PG.
- Полный Docker gate: 2791 passed, 1 skipped, 1 xpassed, 133 subtests passed;
  JUnit: 0 failures, 0 errors. Единственный skip —
  `test_farm_order_variety::test_sonya_sometimes_gets_a_signature_item`: текущая
  прогрессия фермы не достигает нужных signature items. Это не пропуск PG/Photo.
  Миграции, Alembic check, dump/restore и JS syntax checks завершились exit 0.
- UI/JS с настоящим QA base URL: 183 passed, 0 skipped; отдельный `ui_check.py gaps`
  дал 84 passed, 0 failed. Инфраструктура Git gates: 17 passed; worktree guard и
  diff check прошли. Штатный `Test-LocalMilestone.ps1` теперь сам добавляет тот же
  read-only mount тестовых схем и PYTHONPATH, не меняя runtime services.

### Результат песочницы

- URL: `https://quiz.mr-lizard.ru/app`; версия `bde8342-dirty`, stamp
  `2026-11-15T21:07:02+00:00`. Это незакоммиченный проверенный рабочий срез,
  а не утверждение о чистом HEAD. SHA256 всех 11 файлов совпали и на host,
  и в существующем Telegram-контейнере.
- API/worker/rehearsal admin active, sandbox bot running. Новый polling-процесс
  не создавался; токен и production не менялись. SQL-миграция не понадобилась.
- Read-only `getMe` через штатный настроенный Telegram proxy подтвердил
  `Quizywizzy_bot`; настройка личной Mini App формы и построение scoped Photo
  deep link на развёрнутом контейнере проверены. Сообщения тестировщикам не отправлялись.
- Реальный двухпользовательский браузерный цикл: собственная QA Room
  `937326be-0b5a-4d41-8002-fd3cdc98ac3d`, Game
  `85947c33-596a-47d5-ab90-de9d8a0e8300`. Два принятых ответа с нулевыми очками
  до deadline, настоящий restart worker, затем два solvers и следующий вопрос;
  outsider denied, page_errors пусто. Deferred stop завершился штатно по дедлайну.
- Read-only сверка БД после smoke: Game stopped/finished, ровно 2 ScoreEvent на
  сумму 10.000. У Guest Room нет PollAnswer (он требует Telegram chat/user FK):
  результаты сохранены в Game.state.solvers/last_result и ScoreEvent. Проверка
  PollAnswer и `/api/mini/history` в PG относится к Telegram Photo; общую историю
  гостевых Room игр этот срез не реализует.
- После выкладки feedback: manual done=2, auto_error done=2, открытых записей 0.
- Просмотрены все 26 Photo кадров (top/bottom и closeups, три размера, две темы)
  и 12 farm-after кадров. При длинной форме используется обычная прокрутка;
  после прокрутки поле/кнопки/результаты доступны выше нижней панели.
- Временный собственный локальный QA API остановлен. F:\Temp артефакты,
  QA-аккаунты/комнаты и backup намеренно сохранены; чужие данные не очищались.
- Реальные Telegram Desktop/Android/iOS вручную не проверялись: Telegram
  membership/deep link/delivery подтверждены адаптерными и PG/API-тестами,
  а не живым устройством. Это остаётся отдельной ручной приёмкой.

### Выкладка и откат

Только 11 runtime-файлов Photo; без миграции, копирования БД, .env с секретами,
публикации production или нового polling-процесса. Существующий Telegram adapter
подтверждён как testing-контейнер с БД `morning_quiz_rehearsal`; его исходники
до выкладки совпадали с исходниками песочницы. Согласованное обновление требует
краткого перезапуска только rehearsal API/worker/adapter (и rehearsal admin,
который импортирует общий runtime). Новая несекретная настройка Mini App URL для
Telegram adapter добавляется отдельно, без изменения токена.

Резервная копия до выкладки:
`/home/lizard/mqb-rehearsal/backups/group-photo-20261115T203535Z-22d93d`:
закрытый pg_dump, исходники host и bot, штамп и статусы служб. Новые записи
после этой точки не следует затирать восстановлением dump.

Откат старого кода допустим только после штатного завершения всех group Photo,
сверки ledger и отсутствия необработанных групповых notifications. При незавершённых
group states старый worker не запускать: остановить запись API/adapter, сохранить
актуальную БД, использовать group-aware worker для завершения или исправить новую
версию. Не обнулять responses/deadlines и не помечать игры finished вручную.
