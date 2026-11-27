# Night Case: приложение и первая браузерная обкатка

Дата: 2026-11-15. Статус: **план/контракт для независимого ревью; не реализовано**.
Владелец разрешил разработку до первых тестов Manor; production и рассылки не разрешены.
Этот документ не закрывает MQB-010, платформенную A.4 или полную игровую приёмку.

Источники: [MQB-010](../MQB-010-night-city-weekly-stages.md),
[факты текущего кода](NIGHT_CASE_INTEGRATION_FACTS.md),
[runtime](../NIGHT_CITY_RUNTIME_CONTRACT.md), [core](EXECUTABLE_FORMAT_V2.md),
[модули](MANOR_MODULES_V2.md), [личные задачи](MANOR_PERSONAL_TASKS_V2.md),
[DEVELOPMENT](../../engineering/DEVELOPMENT.md),
[RELEASE_CRITERIA](../../engineering/RELEASE_CRITERIA.md),
[UI_RULES](../../design/UI_RULES.md). Адресные факты сверены с owning source:
storage/models.py, storage/games.py, storage/admin_actions.py,
application/account_merge.py, application/rooms.py, application/game_deadlines.py,
domain/night_case_state.py, domain/night_case_engine.py, domain/night_case_narrative.py.

## 1. Результат и границы

Одна браузерная комната, четыре реальных Account, лобби → роли/имена → карта и действия
→ общение/доска → слушание/финал → перечитывание после рестарта. JSON Manor содержит
три варианта и составы 4/5/8/12; автоматическая матрица проверяет их все, первая живая
обкатка начинается с четырёх человек. Рабочий Telegram bot/token не включается.
Приложение, Room и Game не принадлежат Telegram-чату. Mode ровно `night_case`.

До подключения сервиса завершаются недостающие pure-domain границы из §2–3 и личные
задачи. Application не дописывает knowledge, не тратит AP и не назначает результаты
по ответу AI. Один step остаётся единственным исполнителем правил. Наличие admin_ai
или pure decide_slip не объявляется готовым narrator/provider или действующей оговоркой.

Для первого теста допустим полностью authored narrator при выключенном провайдере.
Тем не менее регулируемый provider path, durable jobs/renderings и гонка первого
показа проходят fake-transport тесты. Истории сохраняются по ACL; reusable drafts
отделены от переписки. Конструктор, другие миры, экономика, новая авторизация,
автоматическая публикация AI-эпизодов и отправка уведомлений в рабочие чаты не входят.

## 2. Чистая граница человеческого общения

Явная capability `communication:{version:1,max_messages_per_window:20}` добавляется в ещё pre-release profile/2
и content_hash. Это не module. Отсутствующая capability и core/1 отвергают новые kinds.
До выпуска окончательный build/profile фиксируется вместе с personal/NPC capabilities;
после выпуска любое несовместимое изменение получает новую версию, не тихий codec default.

Новая player-команда `say`, в обычном command envelope:

```text
params = {channel:"square"|"whisper"|"ghost", recipients:CharacterId[0..2], text:string}
```

Все поля обязательны, extras запрещены. text — plain Unicode, NFC, 1..1000 символов и
не более 4096 UTF-8 bytes после нормализации; whitespace-only, NUL/control кроме LF
отклоняются. Никакого HTML/Markdown исполнения, link preview или вложений. Нормализация
происходит ДО fingerprint; повтор сверяется по canonical нормализованному payload.
Непустые recipients сортируются и уникальны; actor в них не входит.

- Square: recipients=[], active/fog человек, 0 AP. Читают участники партии; ghost
  может читать, но писать сюда не может. Departed — только ранее разрешённая история.
- Whisper: 1–2 других человека, всего 2–3. Все active/fog и **сейчас** в месте actor.
  Каждый send стоит 1 AP, проверяется и списывается step атомарно. Групповая личная
  беседа тоже whisper, не бесплатный общий чат. NPC/бывший PC не подставляется за человека.
  Расхождение места/статуса даёт общий отказ «Беседа сейчас недоступна» без чужой location.
- Ghost: recipients=[], только ghost, 0 AP. Аудитория — ghost accounts на момент
  отправки. Вновь отстранённый участник не получает старые чужие сообщения задним числом.
  Square и ghost — разные каналы; публичные улики призрак передаёт только ghost_share.

Получатели каждого private сообщения закрепляются навсегда. Уход из места прекращает
возможность новой отправки, не стирает ранее полученное письмо. Состав беседы нельзя
расширить, дав новичку старую историю. Thread ключ выводится из game/channel/отсортированного
состава, но не используется как bearer access. Sender входит в аудиторию сообщения.
Список предложенных whisper-адресатов содержит только уже видимых рядом human characters;
ошибка guessed recipient не превращается в поиск чужого места.

Каждому actor разрешено 20 успешных say на игровое окно суммарно по каналам. Это
технический anti-flood бюджет, не AP: значение фиксируется в pinned communication capability
и показывается своему игроку. Core RulesSnapshot с AP/слотами не получает незаявленных
полей; лимит входит в case_hash, а whisper_cost=1 — семантика capability/1. Неудачная
команда не расходует квоту; command replay
не повторяет сообщение. Дополнительный HTTP rate limit защищает endpoint, но не
меняет игровые расходы. Frozen/finished не принимают новые say; обычные core seen/
wake правила сохраняются. Принятый say означает presence; чтение истории — нет.

Menu возвращает форму канала/допустимых targets; quote_action материализует конкретный
текст и получателей через общую eligibility, без apply. Revision включает только свои
AP/quota/window и видимую доступность выбранных участников; не общий chat count.
Смена чужого места проверяется повторно при исполнении, без утечки значения места.

State capability точно хранит `communication={version:1,sent:[{account_id,window_idx,count}]}`:
уникальная пара account/window, count exact int1..20, только собственные успешные say,
не более 12×14 строк; отсутствие строки означает0. Счётчик обновляет step. Kernel receipt
связывает message ID/hash, sender и frozen recipients; codec проверяет shape и known
roster refs, replay — совпадение с исходным текстом/выданным MessageRecord. Внешняя
application не может передать новое значение count или самостоятельно создать receipt.

### Сообщение не раздувает kernel текстом

Transition получает backward-compatible `messages=()`; каждый новый MessageRecord:
`{id,channel,thread_key,sender_account_id,recipient_account_ids[],window_idx,text,text_hash}`.
ID = `msg_` + SHA256 canonical JSON `["night-case-message/1",game_id,actor_id,command_id]`.
Thread key аналогично хеширует game/channel/sorted recipients, без общей последовательности.
Hash — SHA256 точного нормализованного UTF-8 text. Получатели — frozen UUID roster,
для square — весь состав на старте, для whisper/ghost — адресный снимок выше.

Внутренняя receipt сохраняет прежние ровно семь полей
`{actor_key,command_id,payload_hash,accepted,code,actor_revision,result_ref}`.
При communication/1 `result_ref` — закрытый union:
`null | {kind:"event",event_id:EventId} | {kind:"message",message_id:MessageId,
text_hash:SHA256,channel:"square"|"whisper"|"ghost",thread_key:SHA256,
recipient_account_ids:AccountId[1..12],window_idx:Window}`. Все поля обязательны,
extras запрещены. Новый branch допустим только для accepted say своего human actor;
отказ say имеет result_ref=null. /1 и /2 без capability сохраняют event|null.
Sender выводится из actor_key, не выбирается повторным параметром. Получатели уникальны,
sorted, содержат sender и существуют в frozen roster; whisper имеет 2–3 участника,
square — исходный состав. MessageId/hash/thread/window сверяются с MessageRecord.
Thread hash точно SHA256 canonical JSON
`["night-case-thread/1",game_id,channel,sorted_recipient_account_ids]`.
Codec проверяет форму/roster/детерминированные IDs и scope; историческую colocation/статус
в момент отправки доказывает replay через step, не текущее положение игроков в snapshot.

Внешняя domain receipt остаётся `{accepted,code,actor_revision}`. Application envelope
отдельно возвращает whitelist `caused_event_ids:EventId[]` (только public/own события
этой команды) и `caused_message_ids:MessageId[]` (для say — ровно собственный message ID,
для отказа — []). Никакие result_ref/recipient UUID/text_hash/internal actor_key не
копируются в этот ответ. Envelope сохраняется в GameCommand.result для точного replay.
Повтор pure step не создаёт MessageRecord второй раз (`messages=[]`), сохраняет прежнюю
receipt; первый transition/replay trace проверяет payload и result_ref. Application retry
возвращает сохранённые whitelist IDs, а не выводит их из пустого повторного delta.

MessageRecord — typed immutable effect, возвращённый step только после всех проверок.
Application записывает его целиком в PG той же транзакцией. В KernelState остаются
собственные счётчики и receipt с message ID/hash; raw text не попадает в retained
public/private Event streams, body snippets, AI context или generic GameEvent.
Текст при replay берётся из PG по исходному message ID; дубликат сверяет hash/ACL,
а не перезаписывает строку. Pure replay проверяет MessageRecord вместе с receipt/hash.
Разговоры имеют свою адресную историю, не маскируются под narrative/window_digest.

Текущий state codec имеет общий предел 2 MiB/100000 nodes. До PG нагрузочный fixture
проверяет полный недельный максимум core+personal+say receipts. Для profile/2 вводится
явный snapshot budget 16 MiB/500000 nodes; profile/1 и case loader сохраняют 2 MiB/100000.
Это предел trusted snapshot, не расширение размера HTTP command/case. Parser выбирает
profile по trusted game registration, не верит присланному version ради обхода лимита.
Все message quotas/aggregate bounds доказываются fixture; отказ по скрытому общему
объёму не должен становиться штатным завершением недели. Нет удаления истории ради лимита.

## 3. NPC: авторские варианты и применяемые оговорки

Optional capability `npc_delivery` profile/2, exact closed data:

```text
{version:1, window_reveal_budget:int[0..3], game_reveal_budget:int[0..12],
 topics:[{id:ID,npc:CharacterId,dialogue:DialogueId,node:NodeId,option:OptionId,
   lines:[{id:ID,body:Body}][1..4],
   slip:null|{rule_id:ID,version:1,probability_bp:int[0..10000],
              observation:ObservationId,requires:VisiblePredicate[0..8]}}][1..32]}
```

Topic uniquely maps one NPC/dialogue/node/option; IDs unique, refs strict. Lines are
варианты безопасного вступления к **тому же** authored outcome, не замена результата
и proof. Все линии допускают одинаковый набор известных NPC/actor фактов; отсутствие
случайного текста не меняет правила. Если такое равенство не подтверждено авторским
ревью, оставить одну линию. Полный outcome и exact карточки показывает сервер.

Slip observation — только authored claim, speaker равен topic.npc, exists_in покрывает
все варианты; не proof, не автоматически истинный fact. Автор задаёт допустимую подсказку
из знаний этого NPC. Требования slip читают разрешённое знание actor/публичные guards;
сами никогда не показываются как «у NPC есть секрет». Меню/quote не содержат шанс,
решение, budget, выбранный line ID или скрытый guard. NPC должен быть активен, видим,
colocated и изначально NPC; бывший PC не говорит. Ordinary talk по-прежнему стоит 1 AP.

Общий helper вызывается ИЗ talk внутри step: сначала обычный outcome, затем разрешённая
линия и slip. Если requirements ещё не выполнены, decision не создаётся; нет reroll
путём смены текста/worker/transport. При первой eligible попытке ключ:
`(game_id,npc,topic,window_idx,rule_version)`; правило для ключа ровно одно.
В sealed snapshot `npc_delivery={version:1,decisions:SlipDecision[],lines:LineDecision[]}`.
LineDecision={npc,topic,window_idx,line_id}; one per key, selected uniformly из разрешённого
фиксированного списка, без зависимости от скрытого culprit. Decisions используют текущий
Task2 codec; `SlipRule.fact_id` — legacy field: adapter передаёт туда claim ObservationId,
это НЕ разрешение записать Fact или признать claim истинным. Проверяется соответствие каталогу.

Выбранная line.body добавляется к личному action_result.body перед exact authored
outcome body; соединение через LF, mentions — уникальное объединение. Compile проверяет
все сочетания на core Body bounds/mentions. Exact observation cards не переписываются.
Отдельного события с internal line/rule ID, шансом или decision нет. Проекция не отдаёт
сырые topic каталоги; сохранённый личный action_result воспроизводит реально услышанное.

Draw детерминирован из отдельной seed domain: HMAC-SHA256(secret_game_seed,
canonical `["night-case-slip/1",npc,topic,window,rule_version]`), первые 64 bits,
rejection sampling в 0..9999 (следующий counter при отбрасывании). Для линии отдельный
domain `night-case-line/1`. Seed/draw никогда в projections/provider. `decide_slip`
вызывается с прежним decision и min(remaining per-NPC-window, remaining per-NPC-game).
Расход budget ровно один на первое revealed=true независимо от числа людей; суммы
выводятся из сохранённых decisions, не счётчиков провайдера. Exhausted budget сохраняет
false с draw=null; более поздняя формулировка не меняет решение этого scope.

При revealed=true step выдаёт claim текущему actor через обычный grant с dialogue
provenance. Следующий eligible actor в том же scope может услышать ту же оговорку:
decision reuse, budget_delta=0, знание выдаётся адресно только спросившему. Ещё не
выполненные actor requirements повторно проверяются; reuse не обходит их. Никакого
автоматического распространения на всех. При повторе command не повторяются grants.
Ключевые proof имеют независимый гарантированный путь; V4 fixture принудительно
делает все slips false и всё равно закрывает дело. Число claim/тайминги не служат
доказательством culprit. Case validation проверяет refs; смысл подсказок — авторское ревью.

## 4. PG: один authority и точная поверхность записи

Account/Room/Game/GamePlayer остаются существующими сущностями. `games.state` для
night_case содержит только whitelist публичного envelope:
`{storage_version:1,case_ref:{id,version,hash},lifecycle,public_projection}`.
В нём нет kernel, seed, variant, private events, message counts, jobs, recipients или
личных результатов. Game.revision — только public projection revision; приватная
команда его не меняет. ETag/room.updated_at/общий GameEvent count тоже не должны
сигнализировать о частном действии. Публичные допустимые последствия остаются видимы.

Техническая конкретизация предварительной таблицы weekly §13: полный проверяемый
KernelState хранится одним trusted snapshot в закрытой таблице, а не разбирается на
независимо изменяемые SQL правила. Knowledge/board/hearing находятся в этом snapshot;
индексы событий являются производными. Не заводить вторую authority night_knowledge/
night_board_items, которую сервис меняет в обход step. PG JSONB — серверное хранение,
не локальный JSON backend. Raw chat вынесен отдельно по §2. Если зрелому объёму позднее
понадобится partition/storage codec, это отдельная миграция, не незаметное изменение hash.

Минимальные новые таблицы (все timestamps aware UTC; FK игры ON DELETE RESTRICT;
Account FK сохраняет исторические UUID; секреты не выбираются generic serializers):

| Таблица | Ключи, обязательные данные и инварианты |
| --- | --- |
| `night_cases` | PK(case_id,version int>0), UNIQUE(content_hash); original content JSONB, content_hash, compiler_version, engine_build, validation_report JSONB, registered_at/by. Контент/версия/hash immutable. Отдельное mutable admission=`registered|rehearsal|retired`; оно не часть content hash. |
| `night_game_sealed` | PK/FK game_id; case_id/version/hash FK, rules JSONB/rules_hash, engine_build/compiler_version, storage_version=1, kernel JSONB|null до start, lobby JSONB|null после start, snapshot_hash, storage_revision bigint, lifecycle=`lobby|running|finished|interrupted|stopped`, interruption JSONB|null. Только mode repository читает/пишет. |
| `night_lobby_commands` | PK(room_id,original_actor_account_id,client_command_id); kind=`create_lobby`, fingerprint SHA256, game_id FK, immutable result JSONB с первоначальными LobbyReceipt/LobbyView, created_at. Room-scoped receipt до появления game_id; account FK — history. |
| `night_lobby_messages` | PK(game_id,id), UNIQUE(game_id,sender_account_id,command_id), UNIQUE(game_id,seq) — порядок за столом, выдаётся под блокировкой строки игры; имя и место автора (character_id, look_id) на момент записи, text 1–500, text_hash, created_at. Обсуждение сбора (2026-11-26): пишут игроки за столом (`POST /api/night-case/games/{id}/lobby-chat`), читают участники компании в `lobby.chat` (50 последних, без account_id); не меняет lobby_revision; 8 строк в минуту на автора. Account FK — history. |
| `night_events` | PK(game_id,event_id), UNIQUE(game_id,scope,audience_seq); scope=`public` или `account:<original UUID>`, window_idx, kind, payload JSONB, created_at. Точная append-only проекция kernel Event. Sequence не глобальный SQL counter. |
| `night_messages` | PK(game_id,id), UNIQUE(game_id,sender_account_id,command_id); command_id из проверенного envelope, thread_key, channel, sender_account_id, recipients JSONB, window_idx, text, text_hash, created_at. Только immutable MessageRecord из transition; receipt и payload атомарны. |
| `night_render_jobs` | PK job_id, UNIQUE(game_id,cause_id,kind,audience_key,knowledge_revision,template_version); frozen NarrativeJob/view JSONB, input_hash, expires_at, fallback, status, attempts, lease_owner/lease_until, retry_at, sanitized_error. Scope ACL явный, реальный context не в общих логах. |
| `night_renderings` | PK/FK job_id; text, source=`authored|ai`, content_hash, references/catalog_ids JSONB, created_at, first_shown_at nullable. Content immutable; первый insert выигрывает. |
| `night_intent_proposals` | PK proposal_id; game_id, original actor UUID, request_id, UNIQUE(game_id,actor,request_id), input_hash, exact ActionProposal JSONB, expires_at, confirmed_command_id nullable. Только собственный ACL; менять params после выдачи нельзя. |
| `night_episode_drafts` | PK draft_id; sanitized candidate JSONB/hash, world_id, contract_version, source job pointer PRIVATE nullable, owner_review=`draft|rejected|approved`, reviewed_by/at nullable, immutable approved payload. Без rawchat/имён/разгадки. Одобрение не меняет уже идущие игры. |
| `night_reward_claims` | PK(game_id,original_account_id,kind), kind=`case_result`; immutable reward_facts, seen_observation_ids, formula_version=1, created_at. Только terminal transition, NPC строк нет, ON CONFLICT сверяет тот же payload. |
| `night_runtime_health` | Один row runtime key; api_seen_at,worker_seen_at, active_outage_id FK nullable. Контур dev/rehearsal отделён БД; это метаданные доступности, не время игры. |
| `night_runtime_outages` | PK outage_id, UNIQUE(started_at), started_at, ended_at nullable, detected_by=`api|worker|operator`; интервалы не пересекаются, завершённые immutable. Не перезаписывать предыдущий outage, пока какая-либо партия могла его не применить. |
| `night_narrator_limits` | PK(scope,period_start); reserved_requests/tokens, failures, circuit_open_until. Scope global/game/account, периоды UTC minute/day согласно §9. Нужны межпроцессные лимиты, не in-process lock. |

Existing GameCommand используется без смены общего PK: internal id = SHA256 canonical
`["night-case-command/1",game_id,actor_key,client_command_id]` (64 hex). Actor key —
UUID либо отдельный system namespace; operator audit uses отдельный `operator:<verified
operator_id>` namespace, никогда player input. В result сохраняется исходная actor-local receipt,
в payload — canonical typed command и payload_hash. UNIQUE surrogate обеспечивает
область (game,actor,command), raw client ID сохраняется; expected_revision=NULL.
Generic reserve_command не сравнивает bool/int как равные: night adapter сверяет
canonical JSON hash и exact schema. Отказы step тоже сохраняются; HTTP auth/parse отказ
до команды не резервирует ID. У чужого principal нет endpoint чтения GameCommand.

GamePlayer — immutable seat/account binding для night_case; public_state только
разрешённые name/seat/status, private_state={} (секреты не копируются в generic таблицу).
GameDeadline(kind=`night.phase`) — единственный актуальный deadline projection.
Добавить nullable/default-safe attempts, last_error_code, retry_at, quarantined_at
к общей deadline таблице; старые modes не меняют семантику. Revision deadline привязан
к kernel timer_seq, не к публичной revision/числу private событий.

NotificationOutbox сохраняется, payload только `{game_id,scope,cause_id,kind}`; никакого
текста/досье. ID/dedupe_key детерминированы от разрешённого события/адресата/канала.
В первом тесте включён только in-app reader, внешние transport consumers выключены.
Generic доставщик обязан отбирать свои kinds; новый night.* без разрешённого adapter
не должен уйти в случайный Telegram chat. Разрешённая позднее доставка повторно проверяет ACL.

Все новые account FK добавляются в точный MERGE_POLICY audit как history/explicit;
таблица не становится переносимой только потому, что тест перечня FK упал.
Внутренние event IDs/hashes не заменяют проверку прав. DB role обслуживает приложение,
а не игроков; admin raw JSON endpoints тоже получают отдельную policy, не «все админы видят всё».

## 5. Case registration, lobby, start и совместимость

Rehearsal регистрация — служебная CLI `register_night_case --file ... --environment rehearsal`.
Она читает ограниченный JSON, compile, полный отчёт доступных checks и replay witnesses,
сверяет hash/build; INSERT immutable version либо точный existing hash no-op. Существующая
пара case/version с другим hash — conflict. Нет URL/import внешних refs или загрузки от игрока.
Case admission rehearsal включает только конкретный проверенный артефакт Manor и
test audience; не означает `publication_passed`. Неизвестный check/not_checked остаётся
в отчёте. До открытия теста необходимы все refs/privacy checks, реальные main witnesses
для разрешённых 3×4 пар, личные positive/negative traces и авторское ревью. Budget
inconclusive нельзя назвать unreachable/pass; при нужде добавить вручную построенный
trace и проверить его обычным replay, не обойти step. Полный редактор/публикационный gate
внешних авторов остаётся вне первого среза.

Лобби создаёт owner активной standalone Room. Case ref, rules snapshot, timezone и
composition policy выбираются из серверного allowlist, затем immutable; поменять их
можно отменой пустого лобби и новым созданием. Lobby data закрытого row:
`{version:1,revision,owner_account_id,case_ref,rules_hash,roster:[{account_id,seat,
name,name_forms,ready}],created_at}`. Join даёт одну seat на account; ready после валидного
имени/форм по core. Все lifecycle mutations имеют command receipts. Start только owner,
все ready, число ровно 4/5/8/12 и есть соответствующая composition. Secure seed берёт
application один раз, затем start выбирает вариант/раздачу; API никогда не принимает variant.
Case/rules/build/roster/seed закрепляются в sealed snapshot до первого private ответа.
Создание нового lobby под locks снимает is_current только у прежней night_case со
status finished/stopped; исторический Game не удаляется. Interrupted незавершён и
никогда не заменяется этим путём.

Create_lobby до game_id имеет отдельную room-scoped идемпотентность. Fingerprint =
SHA256 canonical JSON `{kind:"create_lobby",expected_lobby_revision:0,params:<strict
normalized create params>}`; room/actor/client_command_id находятся в PK. Под shared
operation_fence сначала проверяются usable principal и принадлежность receipt, затем
ищется собственный ключ ДО current-game/owner-membership/case-admission/lifecycle
проверок нового создания. Exact match возвращает исходные game_id/LobbyReceipt/LobbyView,
даже если игра уже началась/закончилась/прервана или case retired; свежий view читается
отдельно. Другой fingerprint — command_conflict, никогда создание второй игры.
Для исторического retry разрешены только доказанные original UUID из merge ancestry;
raw actor UUID клиент не задаёт. Если такой client ID неоднозначен среди принадлежащих
principal исторических aliases, вернуть historical_command_ambiguous, ничего не создавать.

Если receipt нет, взять room/night locks и повторить lookup, затем проверить права
на НОВОЕ создание и current blocker. Game/lobby/receipt записываются одной транзакцией.
Unique PK закрывает race двух одинаковых запросов; проигравший перечитывает committed
receipt, не отвечает active_game_conflict вместо успешного retry. Lost response после
commit/lifecycle change и исторический retry после merge проверяются отдельными PG тестами.

Для первого браузерного цикла используются существующие RoomInvite и явное join в
конкретное lobby: принятие ссылки в комнату не делает человека игроком/участником
Telegram-чата автоматически. Приглашения по account в отдельную игру из MQB-010
остаются отдельным незакрытым пунктом, не выдаются за готовые NightGameInvite. Повтор
room invite/ join не создаёт две seats. Lobby максимум 12, наблюдателей с private ACL нет.

Переходный UNIQUE INDEX на room_id WHERE `is_current AND
((mode='night_case' AND status NOT IN ('finished','stopped')) OR
 (mode='mafia' AND status NOT IN ('finished','stopped','interrupted')))`. Таким образом
night_case interrupted блокирует и night_case, и Mafia start; прежний терминальный
смысл interrupted короткой Mafia не меняется. Mode-aware creation/leave/merge predicates
используют тот же критерий, не общий старый TERMINAL_GAME_STATUSES. Перед миграцией проверить
конфликтующие existing строки; abort с операторским отчётом, не удалять чужие партии.
Создание обеих modes и rooms.leave используют общий advisory key семейства room/night,
а также прежние mode keys. Mafia initializer/codec/due обработчик не пытается трактовать
night_case: при wrong mode возвращает None. Старые golden Mafia v1/v2 без изменений.
Старые активные партии продолжаются; новый пользовательский путь создаёт night_case,
а не развивает короткую Mafia.

Room.leave включает night_case. В running/frozen участник сначала явно подтверждает
forfeit обычной командой; leave без него — `forfeit_required`, membership сохраняется.
После departed leave разрешён; owner по прежнему правилу не выходит из своей комнаты.
В lobby участник сначала leave_lobby; неучастник может выйти. Для ghost forfeit тоже
явный, чтобы закрыть доступ/участие корректно. Classic/Photo restrictions сохраняются.
Membership deactivation не удаляет roster, receipts или свои исторические сообщения.

## 6. Транзакция, ACL, merge и модерация

Порядок locks: operation_fence(shared) → общий room/night advisory для lifecycle/leave
→ существующие mode advisory keys в фиксированном порядке classic,mafia,photo,night_case
→ Room/membership при изменении состава → Game FOR UPDATE → night_game_sealed FOR UPDATE
→ command/deadline/job rows. Обычная команда неизменного состава берёт Game/sealed после
fence, не запирает Room без нужды. Никакой сетевой AI вызов под этими locks.
Сериализация короткой PG записи всей игры нужна для одного snapshot; это не причина
требовать от независимых actors общую expected_revision.

Shared operation_fence берётся первым действием транзакции, ДО account/ACL/receipt
lookup. Это касается также history, get_view, get_rendering и чтения уже готового
render/предложения: затем Account проверяется внутри той же транзакции. Нельзя выполнить
проверку доступа вне fence и вернуть результат после параллельного block/archive.

`execute` в одной транзакции:

1. В начале tx взять shared operation_fence, затем проверить principal,
   account.bot_blocked/archived/merged_into_id, mode и участие.
   Право на replay также проверяется заново; старая receipt не обходит block.
2. Найти own (game,actor,command_id), сравнить fingerprint и вернуть прежнюю receipt
   ДО domain actor/window/resource fences и clock, но ПОСЛЕ operation_fence и ACL.
   Payload mismatch — command_conflict, не новое действие.
3. Decode pinned case/rules/kernel; проверить хеши/build/roster equality. Завершить
   необходимый outage resume по §8, затем step с одним now_utc, взятым после locks.
4. Записать exact snapshot/hash/storage_revision, actor receipt, новые night_events и
   MessageRecords, deadline projection, jobs/outbox, terminal reward claims. Всё или ничего.
5. Обновить Game public envelope ТОЛЬКО если изменился public projection; commit.
   Return исходная receipt, её разрешённые event/message IDs; актуальный view читается отдельно.

Реальный `_sync_state` сейчас всегда создаёт GameEvent и переносит revision. Для night_case
нужна явная ветка/delegation в mode repository, которая НЕ вызывает общий append side effect.
Private effects пишутся только в night_events/messages/commands. Даже для публичных
изменений canonical history — night_events; generic GameEvent для night_case не нужен.
Generic room/game/history/admin endpoints либо маршрутизируют к whitelist projection,
либо явно не поддерживают mode; ни SELECT row.*, ни serialized state, ни глобальные
event indices/storage revision/updated_at не уходят игроку. Не лечить утечку только UI.

Чтение живой игры — active membership + frozen roster participation + usable Account.
Room owner не получает private view остальных. Просмотр своей законченной/покинутой
истории допускается по immutable participation без active membership; departed получает
только историю до своего cutoff и разрешённый итог дела, не новые чужие беседы.
Postmortem раскрывает authored truth по core, но не отменяет private-chat ACL.

### Merge: узкая безопасная policy

Пока любой из main/secondary UUID — owner комнаты с незавершённой night_case или
числится в её lobby/frozen roster (включая departed), merge отклоняется
`night_case_merge_active`; нужно дождаться завершения/отмены. Это ограничение первого
среза, не автоматический выход и не перенос чужой роли. Link Telegram к тому же UUID
без merge разрешён обычным verified identity flow.

Merge commit с САМОГО НАЧАЛА своей транзакции берёт exclusive operation_fence; обычные
night join/start/commands/leave берут shared. Не повышать shared→exclusive посреди
транзакции. Повторить проверку активных игр после fence, до любых merge mutations.
Это адресное изменение merge entrypoints, не переписывание его общей логики. Простой
shared fence текущего merge эту гонку не закрывает; account check вне fence недостаточен.

В `_merge_games` исключить night_case из move_no_conflict: GamePlayer такого режима
остаётся историческим UUID даже после terminal, как GameCommand/Event и sealed roster.
Новый canonical principal читает историю original UUID только по подтверждённой
AccountMerge/merged_into ancestry, через account-scoped resolver с cycle/depth guard.
Сырая archived secondary session ничего не получает. Старые source UUID не меняются
в hash, event IDs, receipts, reward keys или ACL. Объединение двух принадлежащих владельцу
законченных мест даёт ему обе свои истории, но не право выполнить прошлую команду от них.
Новые игры используют canonical account. Active-room membership конфликт merge не
пересчитывает приватную историю и не раздаёт доступ посторонним.

### Модерация

Current admin selection по chat/user не покрывает standalone Account roster — это
реальный пробел. Новый сервис явно проверяет Account.archived и bot_blocked при каждом
read/write/render/message/proposal/notification доступе, под тем же shared fence.
Archive вследствие доказанного merge учитывается только history resolver выше; обычный
archived/blocked account доступа не имеет. Нужна узкая admin account-UUID команда
block/archive с existing admin auth/CSRF и exclusive fence; существующую поддержку
этого пути не объявлять. Она отзывает сессии/доступ, но не раскрывает чужие данные.

Block одного account не прерывает стол целиком и не исполняет чужой forfeit: персонаж
остаётся по принятым AFK/idle правилам. Отправка ему notifications прекращается сразу,
history/render ACL тоже. Administrative interruption всей игры — отдельная операция
с reason/operator audit: sealed kernel сохраняется неизменным, lifecycle=interrupted,
Game.status/phase=interrupted, is_current=true. Это блокирующее НЕЗАВЕРШЁННОЕ состояние;
deadlines отменены, rewards не сочиняются. Mode loader понимает этот storage envelope,
не подмешивает status/revision поля в strict KernelState. Generic interrupt для night_case
делегирует mode repository; rollback/рестарт не возобновляет его автоматически.

Для первого среза единственное завершающее операторское решение — `close_interrupted`
с собственным action_id/reason и audit: под exclusive fence и room/Game locks переводит
storage lifecycle и Game.status/phase в stopped, is_current=false. Last kernel и история
сохраняются побайтово; это прекращение, не игровой финал, не новые rewards/postmortem truth.
Операция идемпотентна; её receipt хранится в GameCommand с отдельным operator actor key.
До решения interrupted продолжает блокировать создание и merge; неснятый участник
не обходит forfeit через Room.leave (получает game_interrupted). После stopped leave
идёт по обычным terminal правилам. Автовосстановление или скрытое снятие is_current
не допускаются; возобновление interrupted не входит в этот первый срез.

## 7. Методы сервиса и HTTP DTO

Новый `NightCaseApplicationService(session,clock,registry)` не импортирует HTTP/Telegram.
Principal = verified Account UUID от существующего room_principal, не из JSON запроса.

| Метод | Вход / результат |
| --- | --- |
| create_lobby/join_lobby/leave_lobby/set_ready/start_game | room/game ID, client_command_id, typed params; LobbyReceipt + безопасный LobbyView. Case/timezone из allowlist, имя только своё. |
| get_view | game_id, principal; `{game_id,mode,public,self,menu,server_now,runtime_status}`. Self только свой, никаких raw snapshot/seed/общих counters. |
| quote | game_id, CommandIntent; конкретный LegalAction/cost/own revision. Не расходует AP/квоту. |
| execute | game_id, строгий Command; `{receipt,caused_event_ids,caused_message_ids}` по own/public scope. Повтор не приклеивает свежий чужой view к старой receipt. |
| history | game_id, stream=`public|self|messages`, cursor, limit1..50, latest=false; разрешённые страницы, отдельные cursors. Никакого общего total count. Каждая запись несёт `at` (время записи, UTC). `latest=true` (2026-11-27, лента «Гостиная у камина»): первая страница — самые новые записи, внутри страницы от старых к новым; cursor ведёт к более старым; cursor одного порядка не принимается в другом. |
| propose_intent / confirm_intent | Собственный request_id/text → Task2 ActionProposal/уточнение; confirmation только proposal_id, не новые params/cost. |
| get_rendering | game_id,job_id; проверенный ACL → first-write-wins RenderingDTO. |
| advance_due / resume_outage | Только SystemActor из worker, не HTTP player route. |

Точные lifecycle params: create_lobby `{case_id,case_version,timezone}`; join_lobby `{}`;
leave_lobby `{}`; set_ready `{name,name_forms,ready:bool}`; start_game `{}`. Общий вход
`{command_id,expected_lobby_revision:int>=0,params}`; create имеет expected=0. Revision
лобби допустима, потому что все изменения состава/ready публичны; это не fence running
действий. Имя валидируется существующим roster contract и уникально в текущем lobby.
LobbyReceipt=`{command_id,accepted,code,lobby_revision,self_seat:null|string}`.
LobbyView=`{game_id,mode:"night_case",case:{id,version,title},timezone,status,
lobby_revision,seats:[{seat,name,ready}],self_seat,can_start}`; case hash остаётся pinned
в storage и не даёт доступа к содержимому. RenderingDTO=`{job_id,text,source,
content_hash,references,catalog_ids}` только разрешённой аудитории. Исторический GET
возвращает committed rendering либо job reference; незаписанный временный текст не
показывается, его материализует отдельный POST get_rendering. Авторские cards доступны сразу.

HTTP namespace `/api/rooms/{room_id}/night-case/...` для lobby, `/api/night-case/games/{id}/...`
для игры/своей истории. Использовать существующий web principal/Origin/CSRF, без токенов
в URL. GET для views/history; quote/propose/confirm/commands и first-render materialization
используют POST+CSRF. Свой request polling не считается игровым seen. Client command UUID
генерируется один раз до отправки и сохраняется для безопасного retry после потери сети.
Чтобы список чужих locations не утёк, whisper target IDs — character IDs, SQL UUID resolves
только сервер. Cursor — opaque signed `{game,scope,last_key}` bound principal/ACL;
message пагинация фильтрует ACL ДО limit/count, использует per-thread authorized order
created_at/id без доступного глобального sequence. Unauthorized cursor/job/message ID =404.

HTTP errors: 401 unauthenticated; 403 account_unavailable/owner_required; 404 unavailable
game/resource (без различения чужого private ID); 409 command_conflict/forfeit_required/
unsupported_count/active_game_conflict/actor_stale/window_closed; 422 invalid_command;
429 rate_limited с own retry_after; 503 runtime_delayed/game_quarantined.
Domain refusal receipt остаётся 200 `{accepted:false,code}` и идемпотентна; HTTP 409
для pre-domain envelope/lifecycle конфликтов. В errors нет case pointers, truth,
ожидаемых скрытых refs, PG exception/stacktrace или AI prompt. Не смешивать это с
доверенным validator report регистратора.

Intent: сервер строит own menu/quotes; AI выбирает только materialized LegalActions.
Free-form params не исполняются как произвольный JSON. Непонятная просьба возвращает
уточнение/кнопки без AP. Proposal хранит full params/target/cost/window/actor/resource
binding и stable command_id, expiry 120s. Confirm начинает tx с shared operation_fence,
проверяет usable account и own proposal, затем ищет confirmed_command_id и committed
own command receipt ДО expiry/requote/Task2 confirm_action. Найденная завершённая
receipt возвращается неизменной, даже после expiry, расхода AP, смены окна или финала.
Если confirmed_command_id записан, а receipt отсутствует, это corruption diagnostic,
не повтор исполнения; запись связи и execute receipt должна быть атомарной.
Только новый confirm перечитывает current quote, проверяет expiry/binding через
Task2 confirm_action и вызывает execute. Предложенный stable command_id резервируется
для этого proposal; если его receipt уже committed, она также проверяется/возвращается
до повторной проверки срока. Любая смена fingerprint — conflict, не восстановление
успеха по чужому ID. Новая стоимость требует нового предложения и подтверждения.
Текст игрока не считается system instruction и не сохраняется в shared episode/context.

## 8. Worker, due и простой

GameDeadlineProcessor явно собирает night_case candidates и вызывает отдельный service;
одна плохая игра не прерывает остальные. Poll 5s, выбор due bounded batch с SKIP LOCKED
либо короткий claim lease; game lock + recheck timer_seq/due_at после claim обязательны.
System command ID выводится из game/window_seq/timer_seq/exact due timestamp, не random
run ID. Два процесса/повтор после commit получают одну receipt. Новый deadline обновляется
в той же транзакции; claimed old generation не перезаписывает новую. Факт отсутствия
Telegram не влияет на запуск worker или сбор candidates.

Kernel.due — единственный список сроков; service не вычисляет своё окончание окна.
Для каждого game сохраняется один ближайший `night.phase`, а внутри step проверяется
точный due. Public/private command не перезапускает phase из-за новой storage_revision.
Системные timer_seq не входят в player fence. DST/quiet/idle/AFK/freeze/wake обрабатывают
принятые domain helpers, включая whole-table idle priority и отсутствие окна15.

Фиксированный runtime health: API и worker пишут heartbeat раз в 30s. Если хотя бы один
не подтверждал работу >120s, это service outage, а не AFK игроков. Persist active outage
начинается с последнего подтверждённого heartbeat недоступного компонента (консервативно,
погрешность ≤30s); ID стабилен. После обоих свежих heartbeat фиксируется once resume_at.
Health row и запись интервала блокируются только при смене outage, commit ДО обхода игр;
их lock не берётся
после Game lock. Изменение wall clock/negative interval — operator diagnostic, не rewind.

Завершённые интервалы хранятся отдельными строками, а не последним значением health:
повторный outage до обхода всех игр не теряет предыдущий. Перед закрывающим due worker
дополнительно проверяет readiness API коротким internal probe вне game locks; ошибка
запускает outage и откладывает tick. Проверяется API/PG readiness, не Telegram. Heartbeat
и probe являются операционным обнаружением, не доказательством доступности каждого
клиента: точность начала ограничена наблюдениями, уже committed переходы не откатываются.
Для управляемого deploy outage открывается ДО остановки API/worker, закрывается после
health; это точный интервал. Для crash в отчёте сохраняется detection uncertainty.

Перед первым due/новой player-командой игра применяет все ещё не применённые завершённые
outages по started_at через настоящий
`system.resume` с этим ID/from/to (для позднего start from=max(game.started_at,from)).
Replay own command проверяется раньше. Outage длительностью 30h не порождает backlog
из 2–3 ретроокон: domain переносит сроки, сохраняет AP/окно/кворум, не начисляет AFK
за недоступность. До восстановления обоих компонентов новые старты и новые commands
возвращают runtime_delayed; свои committed receipts/историю можно читать. No-op resume
для уже обработанного outage не меняет actor fences. После рестарта корректность
опирается на сохранённый ID, не на память процесса.

После трёх ошибок одной deadline generation (backoff 5s,30s,120s) статус quarantined,
sanitized code, operator audit; чужие due продолжаются. Unknown snapshot/ruleset/hash
не «чинится» нормализатором. Failure counter записывается отдельной короткой транзакцией
только если generation ещё та же; DB outage не подтверждает ни failure state, ни успех.
Снятие карантина — операторская CLI с reviewed исправлением и replay/codec check,
новой retry receipt; нельзя просто удалить ошибочное состояние. Публично только
game_quarantined без внутренней причины. Recovery длительного карантина использует
отдельный persisted outage interval через system.resume, чтобы не наказать игроков.

## 9. Narrative jobs, provider и первый показ

Applied Event → deterministic director → frozen минимальный NarrationView → durable job.
Director работает после step В той же PG транзакции и не получает права изменить kernel.
Триггеры первого среза: window_digest к своему digest, npc_reply к своему talk result,
scene_narration к authored public scene/reveal, story_offer к разрешённой декоративной
сценке из каталога (пустой effects). Один trigger/audience/template имеет unique job.
Никаких jobs по каждому private сообщению и никаких «намёков» по скрытому variant.
Job на срок создаётся applied window event, а не отдельным LLM-таймером. Истёкший
deadline не ждёт рассказ; authored result доступен сразу.

View строится whitelist из exact event/body + разрешённых actor/public observations;
NPC получает только разрешённые своей реплике claims/входы, не whole case/truth/secrets.
Максимум Task2: 64 facts по1200, суммарно16000 символов, 64 refs/catalog IDs; выбирать
детерминированно relevant subset, не скрыто обрезать essential source. Имена людей,
Account UUID, private source IDs, sealed branch, raw chat не отправляются. Используются
ролевые placeholders; renderer подставляет разрешённые имена ПОСЛЕ генерации.
Снимок context immutable и его hash в job: новая находка не меняет старый рассказ.
Public job использует только public view. Недопустимый контекст → authored fallback,
а не попытка попросить модель «не раскрывать секрет».

Отдельный transport adapter `infrastructure/night_case_narrator.py` использует механизмы
HTTP/timeouts существующих клиентов, но не admin_ai config/session/confirmed_external
или рабочий ключ. Env: NIGHT_CASE_ENABLED=false, NIGHT_CASE_STARTS_ENABLED=false,
NIGHT_CASE_REHEARSAL_CASE_HASHES=[], NIGHT_NARRATOR_ENABLED=false,
NIGHT_NARRATOR_PROVIDER, NIGHT_NARRATOR_MODEL, NIGHT_NARRATOR_API_KEY,
NIGHT_NARRATOR_EXTERNAL_ALLOWED=false. Наличие admin key не включает narrator.
Provider endpoint из server allowlist, не из пользовательского prompt. Ключи не в PG/job/log.

Фиксированная config/1 для первой обкатки: connect timeout3s, total12s,
max_output_tokens800, response≤4000 символов; max2 attempts/job, lease30s, TTL5min.
Межпроцессный rate/budget до запроса: global10/minute, account4/minute, game60 requests/day,
game120000 зарезервированных input+output tokens/day. Резерв conservatively оценивает
верхнюю границу tokenizer provider, иначе по UTF-8 bytes + output allowance; по факту
usage можно уменьшить, по timeout не возвращать весь резерв. Повтор тоже тратит budget.
Circuit breaker открывается на5min после5 consecutive transport/schema failures,
успешный валидный ответ сбрасывает; disabled/open/budget→fallback без сетевого запроса.
Circuit state живёт в отдельной строке той же limits таблицы scope=`global_circuit`,
period_start=UTC epoch, чтобы minute rollover не сбрасывал consecutive failures.
Quota reservations блокируются в одном фиксированном sorted scope order и коммитятся
до HTTP; отказ любой квоты не оставляет частично зарезервированные другие лимиты.
Значения операторски меняются только versioned config, не client params. Model/region
и реальный внешний send включаются отдельно; fake transport подтверждает путь без ключа.

Worker claims job short tx → HTTP вне locks → validate Task2 exact token/kind/refs/expiry
→ commit результата short tx. ACL/context immutable binding обязателен; неправильный
token, поздний ответ, неизвестные refs, malformed JSON, unsafe markup → fallback.
Validation не доказывает смысл свободной прозы: придуманные причинность/алиби остаются
риском живой приёмки. Exact proof/result показываются отдельной авторской карточкой,
а narration подписан как рассказ и не даёт effects. Ни catalog_ids, ни EpisodeDraft
не исполняются автоматически как команда. Первые тесты допускают декоративную
импровизацию в safe context, а не случайное создание новых веток/доказательств.

First-write-wins: валидный worker может заранее INSERT night_renderings; первый reader,
если строки ещё нет, немедленно INSERT authored fallback. ON CONFLICT читает winner.
Только committed row отправляется браузеру и отмечается first_shown_at; нельзя сначала
отдать временный текст и потом сохранить другой. Поздняя AI запись не заменяет fallback,
две вкладки видят один winner, перечитывание после рестарта не вызывает API заново.
Authored fallback сохраняется и при выключенном provider. Для private rendering право
проверяется при каждом чтении независимо от существования row.

Intent parsing использует отдельный own request без NarrativeJob.kind подмены; допускает
только выбор уже выданных legal selection IDs и уточнение. Тот же transport/budget/ACL,
без main-case mutation. Provider off оставляет кнопки; текст не расходует AP до confirm.

## 10. История, сюжеты, награды и уведомления

History — append-only events, сообщения и committed renderings со своими ACL. Можно
перечитывать public и own историю, сохраняя отдельные stream cursors. Точное общее
wallclock упорядочивание разных private streams не обещается. Private message body
загружается только после проверки immutable recipients; digest не перечисляет чужие
thread IDs, count или последний timestamp. Историческая подпись автора — персонаж
партии, не изменившееся текущее имя Account. Raw logs содержат error codes/correlation,
не body/payload/model output. Резервные копии включают все sealed/private таблицы и
доступны только операторам; recovery тест не публикует их contents.

Episode draft создаётся отдельной operator action из разрешённой декоративной сцены
либо параметризованного авторского текста. Автоматический pipeline не копирует
raw chat, имена, UUID, досье, source private observations, culprit/method или solution.
Draft содержит world/contract, role/location placeholders, public guards, allowed
catalog IDs, prose variants, hash; raw source pointer приватен и не входит в reusable payload.
Программная очистка не доказывает семантическую обезличенность: owner review обязательна.
Approved draft переводится в новую immutable версию content/episode, включённую в
следующий registered case bundle; не hot-inject в текущий game. Ни room owner, ни игрок
не являются автоматически администратором публикации библиотеки. Полный редактор вне scope.

Night rewards не смешиваются с classic ScoreEvent или farm/Alchemy. В первом срезе
claim хранит exact terminal reward_facts и seen card IDs; read profile показывает
проверяемые counts/participation/goal outcome, без придуманной валюты или силовых бонусов.
Расширенная численная репутация/коллекционный UI отдельны; record case_result не
объявляется их реализацией. ON CONFLICT payload mismatch — corruption diagnostic,
не молчаливое пересчитывание награды. Departure/forgotten правила берутся из kernel facts.

Outbox создаётся атомарно с событием и claim. Отложенная доставка учитывает quiet hours
домена/профиля, но история и правила доступны сразу. В первом срезе transport sender
выключен; in-app notification считывает указатель и заново project. Stale pointer после
block/leave не раскрывает старый private payload. Никакого Telegram chat как ACL-границы.

## 11. Клиент и проверяемые срезы реализации

UI reuse shell tokens/navigation/⚙, выбранный noir_print_a kit и реальные asset refs.
World/art для текущей игры и её истории берутся только из pinned case.meta.world и
закреплённого asset manifest этой версии. Изменение Room.world не переоформляет старую
партию и не подменяет её набор assets; current room theme не является историческим источником.
Новый night_case controller не переиспользует Mafia API незаметно. Экраны: room/lobby,
своё досье+criteria, карта/доступные действия, NPC menu/free intent+confirm, square,
whisper2–3, ghost channel, board/hearing, final/history. Показываются AP/цена/сроки,
disconnected/pending/retry и собственная квота сообщений. Серверный command ID не
меняется при retry; новая пользовательская попытка после отказа получает новый ID.
Private контент не сохраняется в общую client cache между account/game; logout очищает
in-memory/session cache. Assets статичны, не содержат sealed truth в скрытом DOM/JSON.

| Срез / владение | Артефакт и доказательство |
| --- | --- |
| R: domain + format/state/projection/simulation | Personal capability, §2 communication/MessageRecord, §3 npc_delivery; один step; negative codec/privacy/replay/AP/budget tests, state-size fixture. Никакой PG до согласованного runtime контракта. |
| S: storage/models + new storage/night_cases.py + Alembic | Registry/sealed/events/messages/jobs/renderings/claims/health; explicit night branch _sync_state/interrupt; PG atomicity, migration old/new, unique indexes, no generic leaks. |
| A: application/night_case.py + rooms/merge/admin boundary | Lobby/start/command/history, cross-mode/leave, immutable history merge, UUID moderation. PG 2-session races, old Mafia regressions. |
| W: game_deadlines + new application/night_case_narrator.py + transport | Due/resume/quarantine, jobs/outbox, rate limits, first-render races, fake transport/provider off/restart tests. |
| H: web adapter + existing principal/CSRF | Typed DTO/routes, intent confirmation, ACL/error tests ASGI with PG, no bot. |
| U: web/mini_client night_case controller/views + shell/art refs | Четыре браузера, полный цикл/reload/reconnect/history; реальные render screenshots и UI gates. |
| P: case authoring + rehearsal registration/runbook | Frozen Manor hashes и replay matrix, local gate, data-preserving deploy, build stamp, первый человеческий тест и feedback. |

Это последовательность законченных reviewable срезов, не разрешение одним PR менять
весь проект. Каждый следующий detailed plan сверяет current source/чужой diff и получает
независимое ревью соразмерно риску. Generic helpers/merge/worker имеют одного владельца
интеграции; параллельные edits не пересекаются. Pure/PG/browser результаты не заменяют друг друга.

## 12. Приёмка и путь в rehearsal

Обязательные автоматические сценарии:

1. Новая и прежняя PG schema upgrade, constraint conflict preflight, restore backup
   на отдельную тестовую БД. Public envelope не содержит kernel. Unknown build/hash/
   codec field → quarantine, без data coercion. Core/1/Mafia golden и active legacy due сохранены.
2. Четыре самостоятельных Account через existing principal/RoomInvite создают один
   night_case без chat/token. Parallel Mafia/night start даёт одного winner; leave/start
   race не теряет membership. Ghost/forfeit/owner leave правила реальные.
   Create_lobby replay после lost response/start/finish/merge возвращает исходные
   game_id/view без новой игры; иной fingerprint и неоднозначный alias ID отвергаются.
   Interrupted блокирует оба starts/merge до explicit close_interrupted; restart не
   меняет is_current и не создаёт награду, stopped освобождает комнату с сохранением истории.
3. Две PG sessions с одним command ID → один AP/result/message/job/outbox/claim;
   иной payload → conflict. Разные actors с актуальными own fences оба проходят;
   timer_seq update не рушит player quote без изменения его окна/resources.
4. Worker vs command на deadline, два worker, crash до commit/после commit, reboot,
   длительный API ИЛИ worker outage30h, DST, freeze/wake, terminal14; нет ретро-AFK,
   двойного финала или пропущенного рескейдюла. Corrupt game не блокирует соседнюю.
5. Private canaries по HTTP view/menu/quotes/history/errors/ETag/room summaries,
   generic GameEvent/Command APIs, outbox, logs, render jobs/provider payload. Чужой
   private act не меняет public IDs/revision/counters. Moderation block сразу отзывает
   read/write/render, включая старую receipt; stale session/CSRF failure не пишет ничего.
   Block/merge race против replay/history/render проверяет начало shared fence ДО
   lookup; никакого чтения usable account вне соответствующей транзакции.
6. Active merge отклоняется до mutations; concurrent start/merge закрыт fence.
   Finished merge сохраняет state/hash/seat/events, canonical owner видит только свои
   исторические aliases. Новый чужой account, ложная ancestry и бывший room owner
   не получают private streams. Generic FK audit обновлён осознанно.
7. Whisper 1 AP и максимум3 colocated; move race даёт корректный отказ без locations,
   replay без второго AP. Square0, ghost закрыт, newcomer не видит раннюю private
   беседу. MessageRecord rollback не оставляет «отправленный» текст, text_hash binding
   при replay, quota20 и max snapshot size доказаны на полном недельном fixture.
   Message result_ref branch принимается только capability codec, event/null /1 прежние;
   подмена message hash/ACL/thread ID отклоняется. Replay pure step даёт messages=[],
   application retry возвращает исходные whitelist IDs без чужих result_ref полей.
8. NPC claims только разрешённые; previous scope/budget reuse0; false→не reroll,
   exhausted→не reroll; разные темы расходуют общий NPC budget; former PC молчит.
   Вся Manor main matrix решается с отключёнными slips и без narrator.
9. Fake provider valid/malformed/wrong token/timeout/late/disabled/rate/circuit,
   одновременный first read/worker, две вкладки/рестарт дают одинаковый текст.
   Proactive applied event создаёт одну job; никакой AI ответ не меняет knowledge/AP.
   Intent expiry/params/cost/recipient tamper не проходят; confirm replay после expiry,
   смены AP/окна/финала возвращает committed receipt до requote и не повторяет действие.
   Missing receipt при confirmed_command_id диагностируется, не повторяется.
10. Эпизод-черновик не публикуется автоматически; contains real name/chat/solution
    canary отклоняется/возвращается owner review. Approved immutable episode включается
    только в новый case snapshot; старые rendered stories побайтово неизменны.
   Изменение Room.world не меняет world/art старой партии: история использует pinned case.

Браузерная приёмка: четыре отдельные сессии, реальные роли, NPC/action/публичная и
личная беседа, публикация proof/claim, обвинение, итог, история. Автоматический
ускоренный clock допустим только в isolated fixture; rehearsal не имеет player debug
endpoint времени/variant. Для живой проверки недельных дедлайнов фиксируются реально
наблюдённые окна; быстрый smoke не выдаётся за прожитую неделю/баланс 12 человек.

До выкладки: связанные unittest/PG/ASGI/JS, `python scripts/project_checks.py --worktree`,
полный `pwsh -File scripts/Test-LocalMilestone.ps1` на отдельной тестовой БД; meaningful
skipped явно перечислить. UI: `node --test tests/js/ui_rules.test.cjs tests/js/ui_layout.test.cjs`,
`python tests/ui/ui_check.py gaps --base <URL>`. Просмотреть 375×812,390×844,1280×800
day/night, затем обязательные farm baseline 360×780 и384×832 с48px Telegram offset
до rehearsal deploy. Не менять оболочку/ферму ради новой игры без её regression проверки.

Rehearsal rollout после local gate: проверить свежий feedback read-only, backup и
миграционный preflight; доставить reviewed артефакт без замены player DB, apply migrations,
register точный case hash, включить только night_case rehearsal/start allowlist.
Narrator off допустим, рабочий bot off. Выполнить
`python scripts/stamp_build.py --remote serverold:/home/lizard/mqb-rehearsal`, затем health,
4-account smoke, screenshots и запись feedback. Production каталог/DB/рассылки не трогать.
Откат после новых записей — выключить новые starts/provider, сохранить case/snapshot
reader и worker совместимого build; destructive downgrade с удалением историй недопустим.

Остаточные границы: полноценная неделя и баланс 5/8/12 требуют живых тестов; semantic
безопасность AI prose и понятность личных критериев не доказаны unit tests; addressed
GameInvites, полноценный редактор, библиотечный UI/репутация, внешний Telegram sender
и live-provider качество отдельно. Эти ограничения не отменяют реального PG сохранения,
своего браузерного пути, работающих fallback/queue и проверяемого first-test цикла.
