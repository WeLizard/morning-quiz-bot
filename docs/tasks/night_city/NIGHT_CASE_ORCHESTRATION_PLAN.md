# Night Case: orchestration start и intent

Статус: план для независимого review, **реализация не начата**. Основа — принятые
[application contract](NIGHT_CASE_APPLICATION_CONTRACT.md) и
[AI access contract](NIGHT_CASE_AI_ACCESS.md). S/A/W, recovery, AI0049/control приняты
отдельно; этот документ уточняет их соединение, а не переоткрывает правила игры.

## 1. Границы среза и фактические точки кода

- `application/night_case.py::_lobby_command` сейчас блокирует Room/Game до lookup
  start receipt; start требует пустые params. `Game.started_at` выставляется после
  `_persist`. Это две точечные перестановки для нового orchestrated start.
- A уже проверяет owner/ready/roster/membership/case/build/runtime health и выполняет
  единственный domain `start`, `_persist`, receipt. Эти проверки и domain rules
  остаются в A. `_persist` вызывает существующий `transition_hook` после snapshot,
  событий, MessageRecord и deadline, в той же транзакции.
- `GameCommand` содержит actor Account, закрытый command payload с hash, status,
  exact result и created/processed time. У Game **нет started_by**. После старта
  sealed.lobby удалён; original roster доказывается decoded kernel
  `sealed.assignments` и неизменяемыми исходными GamePlayer Account/seat.
- `propose_intent` сейчас поддерживает выбранный selection_id; свободный text
  возвращает clarification. `confirm_intent` уже делает own command replay до
  expiry и вызывает обычный execute. Его поведение сохраняется.
- `night_ai_intent_requests` уже имеет durable prepare identity, binding/epoch,
  token, legal_candidates, deadline и terminal safe_result. Prepared metadata
  immutable; повтор не продлевает expires_at.
- HTTP `web/night_case_routes.py::invoke` сейчас держит principal/session context
  вокруг service call. Его нельзя оставить открытым вокруг нового transport await.

В этом срезе: общий orchestrator, минимальные A/S helpers, lobby empty control,
start/control atomicity, durable intent prepare/finalize с transport protocol.
Реальные provider adapters, quota reservations/dispatch leases, director algorithm,
HTTP/UI подключение и включение egress — следующие отдельные срезы.

## 2. API и владение

Новый `application/night_case_orchestration.py`:

```python
NightCaseOrchestrator(db, factory, ai, transport=None)
# factory(session) -> NightCaseApplicationService
# ai(session) -> NightAIControlService

async create_lobby(*, account_id, room_id, command) -> dict
async start_game(*, account_id, game_id, command) -> dict
async propose_intent(*, account_id, game_id, request_id,
                     selection_id=None, text=None) -> dict
async prepare_intent(*, account_id, game_id, request_id, text) -> PreparedIntent | dict
async finalize_intent(*, account_id, game_id, request_id, transport_result) -> dict
```

`db.transaction()` принадлежит orchestrator; `factory` и `ai` получают **одну и ту
же session** внутри соответствующей операции. prepare/finalize доступны доверенному
application caller, не отдельные произвольные HTTP endpoints. PreparedIntent —
закрытый internal DTO, не ORM row, не browser JSON и не raw kernel. В его repr нет
user text, prompt, credential или provider body. Остальные A методы не экспортируются
через generic `__getattr__`; существующие адаптеры используют явные сервисные методы.

Изменяемые файлы будущей реализации:

| Файл | Узкая ответственность |
| --- | --- |
| новый `application/night_case_orchestration.py` | Transaction boundaries, start/intent orchestration, safe DTO и codecs |
| `application/night_case.py` | Общий pure start parser/receipt helper; доверенный start callback; started_at до `_persist`; initial starter при direct authored start; общий intent replay до branch и helper обычного proposal с заданным prepare deadline |
| `application/night_case_ai.py` | Legacy original-starter bootstrap при явной настройке; общий read-only eligibility/pin snapshot для prepare/finalize |
| `storage/night_ai_control.py` | Empty lobby insert/direct-start identity finalization; общий lookup двух intent tables; strict ninth-table insert/load/terminal CAS; exact replay without new expiry |
| `storage/night_cases.py` | Только узкий own start-receipt reader без Game lock, с populate_existing; owning A/S delta согласуется перед правкой |
| новые `tests/test_night_case_orchestration*.py` | Pure и real PG сценарии ниже |

`storage/models.py`,0045–0049, domain rules, W/recovery и существующий vault не
менять в этом срезе. Если bounded codecs не помещаются в существующие поля —
clarification/fail closed, не скрытая миграция и не усечение. Будущий H adapter
потребует отдельного ownership для закрытия principal tx перед transport; текущий
session-bound invoke не объявляется готовым orchestrator adapter.

## 3. Start DTO, hash и старые receipts

Внешняя форма command остаётся `LobbyCommand`. Только start получает новый вариант
params: `{}` либо `{"ai":{"mode":...,"expected_epoch":int,
"staged_credential_id":null|canonicalUUID}}`. Три ключа ai обязательны;
mode=`authored|admin|byok`; staged ID nonnull ровно для byok. Bool не int, extras
запрещены. Secret в start не передаётся. Один pure parser используется A и orchestrator.

Отсутствие ai сохраняется как отдельный факт, **не переписывается в hash**:

| Вход | Receipt fingerprint и эффект |
| --- | --- |
| Старый или новый command с params={} | Точный прежний hash `{kind:start_game,expected_lobby_revision,params:{}}`; найденный receipt возвращается byte/JSON-exact без новых control effects |
| Новый params={} без receipt | В новом orchestrator default admin_request; implicit expected AI epoch0; полный эффект одного нового старта |
| Явный ai объект | Hash включает весь закрытый нормализованный ai объект; logical default не удаляет explicit presence |
| Старый command_id + явный ai, даже mode=admin | command_conflict; legacy receipt не превращается в новое разрешение |
| Повтор после finish/expiry/kill flag/master loss | Usable principal + proven own receipt replay раньше новых fences; никакой активации/уведомления/новой epoch |

Исторический payload/result не дописываются. Внешний start result остаётся A envelope;
AI status читается отдельной будущей safe projection, а не модифицирует старый replay.
Прямой legacy A.start_game с params={} сохраняет старую authored семантику; явные
AI params без доверенного orchestrated path отвергаются. Новое default admin_request
начинается только после явного переключения caller на orchestrator после review.

## 4. Одна start-транзакция

1. Shared `operation_fence` первым; usable canonical Account. Pure DTO validation,
   proven aliases; разрешение читать собственный receipt по original actor, без
   выдачи чужого результата. Read-only lookup Game identity/own receipt не берёт
   Game/Room locks. Own exact FULL-payload replay/conflict — до clock, flags и build.
2. `AI_CONFIG_LOCK` через тот же control repository, **до Room/Game locks**.
   Повторить own receipt lookup после ожидания advisory lock.
3. Existing family/mode Room lock → Room row → Game → sealed → control. Все SELECT
   с блокировкой обновляют cached ORM state. A повторяет fresh membership/owner,
   lobby revision/ready/roster/usable participants, pinned case/build/rules и W
   availability. UI owner/read projection не заменяет эти проверки.
4. A захватывает одно UTC now и выполняет domain start. `Game.started_at=now`
   устанавливается **до trusted callback и до первого `_persist`**.
5. A вызывает доверенный callback на валидированном start context. Callback
   использует `NightAIControlService.start_in_locked_game`: original starter,
   новая epoch, pending+admin pointer или authored/BYOK grant. Selected staged
   BYOK принадлежит этой игре/actor, не expired: новый usable credential ID/nonce/AAD,
   новая pinned revision, erase staged — в этой же tx; старый staged receipt не
   переупаковывается и остаётся только receipt.
6. A создаёт roster GamePlayers и единожды `_persist` переход. Existing
   transition_hook получает уже зафиксированные в tx started_at и AI control.
   Director seam может добавить frozen jobs/immutable assignments без HTTP.
7. A сохраняет exact FULL-payload start receipt; один commit. Любая ошибка callback,
   `_persist`, director hook или receipt откатывает весь start, включая started_at,
   roster, control, ciphertext rotation, jobs и outbox. Orchestrator не ловит ошибку
   внутри write tx с последующим commit; нет вложенной независимой DB session.

Минимальная доверенная A-сигнатура:

```python
async _lobby_command(..., kind, *, parsed_start=None, before_start=None)
# parsed_start: strict internal StartRequest, не входной произвольный dict
StartHook = Callable[[ValidatedStartContext], Awaitable[None]]
# context: locked SealedGame, case, rules, UTC now, actor_id, normalized AI options
```

Обычные join/ready/leave не принимают эти аргументы из DTO. Existing public start
wrapper остаётся совместимым; orchestrator вызывает внутренний общий путь с
проверенным parser result и callback, предварительно `ai.acquire_start_config`.
Никаких новых правил в callback: readiness, health, random seed и domain start
по-прежнему принадлежат A/domain. Hook не выбирает outcome, не меняет transition.

`NIGHT_NARRATOR_ENABLED`/egress flags управляют model dispatch, не разрешением
игрового старта. Authored/default admin_request не требуют master key, transport
или рабочей модели. Current API/worker health из W всё ещё необходима для нового
start. Selected BYOK при missing master даёт понятный `ai_unavailable` и полный
rollback; caller может повторить новый authored выбор с новым command_id.

## 5. Lobby control и партии авторского 0048 без control

Для новой lobby A после создания Game/sealed вызывает storage helper
`ensure_empty_lobby_control_locked(game_id, now)`. Он допускается под уже взятым
Game lock **без позднего AI advisory**: вставляет только новый row
`epoch=0,starter=null,current_binding=null`; existing row только проверяет/возвращает,
не исправляет и не меняет. `ON CONFLICT DO NOTHING` + exact read/validation. Helper не
создаёт credential/profile/request/outbox. Так у обычного create нет обратного порядка
Game→AI_CONFIG_LOCK. Старый create receipt replay возвращается до helper без backfill.
Это прямой вызов owning S repository только в ветке фактической вставки новой lobby;
новый constructor hook/factory argument для create не нужен. DB0049 readiness —
предусловие выкладки этого A delta, как и для всего orchestration artifact.

**Direct A.start_game тоже завершает initial identity.** В каждом успешном новом
старте без orchestrated callback A после своих owner/roster/ready проверок, под уже
взятым Game/control lock и до `_persist`, вызывает
`finalize_authored_starter_locked(game_id, validated_starter, now)`. Если control
пустой (`epoch=0,starter=null,binding=null`), helper фиксирует validated original
starter, сохраняя epoch0/bindingnull. Никаких request/grant/outbox/AI config changes
или позднего AI advisory: это однократная фиксация identity из того же принятого
старта. Начатый orchestrated callback уже заполнил control — повторно он не
инициализируется. Initial identity и start receipt коммитятся/откатываются вместе.
Если у старой lobby control вообще отсутствует, direct start не выдумывает
backfill permission; остаётся путь доказательства receipt ниже.

Так direct create → direct authored start оставляет control со starter и epoch0;
его последующий явный request_admin(expected_epoch=0) разрешён original starter
и создаёт первую request epoch1. Нельзя оставить running game с существующим
пустым control/starternull: это нарушает и bootstrap, и DB invariant0049.

Existing running Game без control читается как authored. Read/view/director и старый
start retry не создают permission автоматически. Первая явная настройка original
starter (request_admin / running BYOK / off) может bootstrap control под штатным
fence→own operation replay→AI advisory→Game/sealed порядком, с expected_epoch=0.

Доказательство original starter, без нового Game.started_by и без текущего Room owner:

- Загрузить и проверить pinned snapshot через существующий decoder/hash/build/rules
  checks. original roster — UUID из sealed.assignments, согласованные с players и
  неизменяемыми original GamePlayer seats.
- Найти **ровно один** applied `GameCommand.kind='start_game'` для game. Actor Account
  nonnull, actor_key — тот же canonical UUID из original roster. Internal system
  namespace/Telegram/user_id не рассматриваются.
- Strict payload envelope, client command_id, `command_key`, payload_hash и command
  kind/accepted result согласованы; result receipt.command_id совпадает; status=applied,
  error=null, Game.started_at nonnull и совпадает с created_at/processed_at start.
- Эти данные записывались owning A только после проверки Room owner == lobby owner ==
  actor; sealed.lobby после start уже нет. Это доказательство принятого start,
  а не вывод из нынешнего владельца комнаты, seat01, timestamp сортировки или имён.
- Отсутствие/несколько/несогласованность доказательств → `starter_unproven` и authored;
  не выбрать первого. Новый grant требует именно usable original Account и active
  seat; merge aliases дают historical replay, не новые active права.

Bootstrap вставляет control со **доказанным starter**, epoch0, binding null, затем
исполняет явную настройку в той же tx. Не переписывает kernel, GamePlayer, receipts,
Game revision или старые результаты. Interrupted/frozen/corrupt/terminal не получают
новых AI grants; исходные игровые/исторические сценарии остаются доступны по A ACL.

## 6. Intent: prepare → commit → transport → finalize

Button selection_id сохраняет прежний builder обычного A proposal, но **не отдельное
пространство idempotency**. Сочетание selection_id+text не получает новый неявный
смысл: прежние fingerprint/validated selection semantics сохраняются; для model
intent нужен text и selection_id=null.

### Единая identity до выбора button / free text

Логическая identity всех intent путей — `(game, original actor, request_id)`;
fingerprint всегда `json_hash({selection_id,text})` в прежней точной форме.
Proven aliases разрешают читать original-actor receipt, но не склеивают несколько
разных original identities в одну; неоднозначный historical lookup fail closed,
без выбора первого alias и без создания новой записи.
После shared fence/usable Account и own historical-receipt ACL выполняется **общий
lookup NightIntentProposal и night_ai_intent_requests до любого branch**. A direct
button path, orchestrator button, prepare и finalize используют один helper;
отдельных per-table unique constraints для этой гарантии недостаточно.

- Same identity + same fingerprint: вернуть уже сохранённый exact proposal или
  terminal clarification. Matching prepared row возвращает ту же internal work
  identity/deadline, не новую работу и не продление.
- Same identity + другой fingerprint: command_conflict независимо от источника
  receipt. После terminal free-text clarification R кнопка с тем же R не создаёт
  новую proposal. Симметрично button R исключает новый free-text R.
- Если обе строки существуют, это допустимо только для атомарно finalized AI
  proposal: одинаковые fingerprint, original actor и тот же exact proposal result.
  Другие сочетания (prepared+proposal, clarification+proposal, разные results)
  считаются corruption/fail closed, а не выбираются по приоритету таблицы.

Перед любой первой записью helper повторяется под общим Game lock. **Все** writers,
включая оставшийся public A.propose_intent для кнопок, обязаны брать этот lock и
повторять lookup обеих таблиц. Поэтому button-vs-text R сериализуется на Game:
первый фиксирует identity/result, второй replay/conflict, без двойной записи между
таблицами. Text берёт AI advisory до Game; button может брать только Game, не
запрашивая AI advisory из-под него. Button builder/обычный proposal не мутирует AI
control. Confirm сохраняет прежние command-receipt гарантии.

Прежний button request_id **8..128** сохраняется, включая retained receipts. NEW AI
prepare допускает только string **8..96** из-за owning ninth-table поля. Сначала
общая bounded envelope validation до128 и lookup обеих таблиц; branch-specific
предел96 применяется только если действительно требуется **новый AI prepare**.
97/128 для нового AI prepare → явный validation error до INSERT/эффектов, не PG
DataError/усечение; same-ID retained receipt по-прежнему replay/conflict раньше
ограничений новой работы. Нельзя урезать ID, хешировать его вместо сохранённого ID
или глобально уменьшить прежний button limit до96.

### Prepare transaction

1. Shared fence → usable Account + own historical-receipt ACL → общий replay двух
   таблиц выше, без требования active participation/running lifecycle. Departed или
   terminal owner может повторить свой receipt; blocked/archived Account — нет.
   Не вызывать `_access` до AI advisory: он блокирует Game. Нужен узкий read-only
   identity/ancestry/receipt ACL helper без Game lock и без runtime/state fences.
   Fingerprint тот же исходный `{selection_id:null,text:<exact validated text>}`,
   без hash текущей модели/epoch. Prepared replay сам по себе не разрешает HTTP:
   для нового dispatch всё равно нужны fresh eligibility и durable permit.
2. AI advisory **до Game**, затем Game/sealed/control. Обновить cached rows;
   общий lookup обеих intent tables ещё раз **до** проверки новых work
   fences. Только при отсутствии receipt проверить lifecycle, pins, W availability
   и active own participation; затем closed NEW-prepare request_id bound до INSERT.
3. Получить только own available_actions/quotes текущего domain state. Никакого step,
   AP, seen, AFK heartbeat, receipt игрового command, fake NarrativeJob/ActionProposal.
   Forms без materialized LegalAction не превращаются в придуманные model params.
4. Snapshot текущего binding/config/caps + BYOK owner-private eligibility. Нет
   control/binding, flags off, transport/dispatch capability unavailable, invalid
   pin, quota denied → durable safe clarification без HTTP и без proposal.
5. Вставить ninth row с `prepared_at=now`, `expires_at=now+120s`, epoch/binding и
   immutable bounded token/legal document. Commit. Повтор prepared row возвращает
   тот же work identity/deadline, не создаёт новую reservation и не продлевает TTL.

Closed token codec `night-ai-intent-token/1` (≤8KiB): opaque random request_token,
case_hash/rules_hash/build, window_idx/window_seq/actor_seq, UTC prepared_at и
expires_at, exact user text (1..1000 chars/≤4096 UTF8 bytes, без silent normalization).
Identity game/account/request/epoch/binding хранится в owning columns; token проверяется
с ними, internal DTO не раскрывается клиенту. Это own private application storage,
не provider dump, outbox или public state.

Closed `legal_candidates` codec `night-ai-legal/1` (≤32KiB): максимум64 записей
`selection_id,kind,target_id,cost,resource_id,resource_revision,params` + проверенные
подписи для выбора. `LegalAction.params` сейчас canonical JSON string: при сохранении
нужно вернуть JSON value, при decode восстановить LegalAction без double encoding.
Хранится полный binding доступного действия, не client params и не raw kernel.
Переполнение/неподдержанные формы → terminal `clarification:choose_available_action`;
не усекать меню или произвольно добавлять action.

### Transport boundary, без DB transaction/session

Orchestrator освобождает prepare session/locks **до** await transport. Transport
получает internal request, но provider payload строится отдельным whitelist:
opaque request_token, kind=`intent_selection`, user text и bounded choices. Labels
берутся из pinned public content/authorized own menu; не добавляются реальные
display names, Account UUID, case truth, raw messages или sealed state. Credentials,
endpoint и внутренние pins — только trusted transport metadata, не model JSON.
Choices имеют ровно `{selection_id,kind,label}`, максимум64; label1..256 символов,
provider JSON≤32KiB. Legal target/resource/params не копируются в provider JSON;
label строится из разрешённого pinned content, а не произвольного player display_name.
Невозможность безопасно построить bounded labels даёт clarification, не скрытое
расширение контекста или урезание доступных действий.

Transport response закрыт: `{request_token,kind,selection_id}`; иной token/kind,
extras, произвольные params/cost/target, unknown selection, timeout/error → clarification.
Ответ разбирается strict JSON codec (≤4096 bytes, без duplicate keys); selection_id
имеет тот же bounded string type, что LegalAction, и принадлежит этому prepare.
Новый intent codec использует реальные LegalAction/propose_action; не притворяется
существующим narrative `validate_narrative_result`, у которого другой contract.
`transport=None` всегда authored clarification; тестовый fake transport доказывает
orchestration, не работоспособность провайдера.

### Finalize transaction

1. Новый shared fence → заново usable Account/authenticated identity + own historical
   receipt ACL → общий lookup двух intent tables раньше active participation,
   lifecycle, expiry/epoch/clock. `_access` до AI advisory не используется. Source
   principal после merge разрешён только доказанной ancestry для historical replay.
2. AI advisory → Game/sealed/control → ninth-row lock. Recheck terminal winner,
   fingerprint/token/epoch/current binding, flags, health/lifecycle/participation,
   profile enabled/credential usable/expiry, BYOK owner-private scope и pinned hashes.
3. `now < prepared.expires_at`; actor/window fences совпадают. Пересчитать **fresh**
   legal actions через domain. Выбранный action должен совпасть с подготовленным
   полным params/cost/resource revision binding и быть доступным сейчас. Не сравнивать
   Game.revision: независимый другой actor не должен вызывать ложный global conflict.
4. Валидный выбор передать A helper обычного proposal, задав **created_at prepare time
   и expires_at исходного prepare**, а command actor_seq — проверенный исходный seq.
   Сохранить обычную NightIntentProposal и ninth terminal safe_result одним commit.
   Не вызывать существующий propose_intent так, чтобы он выдал новые now+120s.
5. Late/stale/disabled/error — terminal clarification/expired, proposal отсутствует.
   Terminal safe_result хранит только точный клиентский proposal envelope либо
   clarification code; не raw response/prompt. Duplicate/late HTTP responses не
   меняют победителя. Terminal status/result immutable по existing trigger.

Обычный confirm_intent не меняется: own command receipt до expiry, затем fresh
confirm_action/execute. Только execute/shared step расходует AP и меняет правила.

## 7. Dispatcher/director seams и условия реального включения

Director подключается через существующий transition_hook после control callback,
в единственной game tx. Он создаёт frozen NarrativeJobs и night_ai_job_bindings по
committed control snapshot, **без AI advisory из-под Game**. Null assignment имеет
authored/pending/denied reason. Нет assignment у старого job → authored навсегда,
не backfill новой текущей моделью. BYOK audience проверяется до assignment и повторно
перед reservation/send/response. Алгоритм director в этом плане не реализуется.

T предоставляет typed `IntentDispatchPermit` для конкретных ninth request ID,
binding/epoch/config hash/token/deadline, с durable budget/lease; проверяется перед
send и при finalize. Без такого permit **реальный transport остаётся выключенным**.
Подготовка строки — не разрешение оплаченного HTTP и не reservation сама по себе.

Важный фактический storage gap для T: binding.inflight_job_id — FK **только** на
NightRenderJob; ninth row не имеет mutable claim/lease. Нельзя подставлять туда
intent ID, создавать fake job или использовать circuit timestamp как semaphore.
T потребует отдельно reviewed typed intent lease/общий binding slot (например,
nullable intent-request FK с XOR job/intent и общей lease) и своих counters/claims.
Этот schema delta не скрывается внутри orchestration и не входит в текущий план
реализации. Повтор prepared intent без рабочего permit не вызывает новый HTTP.

HTTP adapter будущего среза закрывает existing principal tx после initial auth и
повторно проверяет authenticated identity/expected viewer на finalize. Запрещено
вызывать orchestrator с HTTP внутри нынешнего `invoke` outer write transaction.
Orchestrator получает trusted canonical Account, а не account_id из browser body.

## 8. RED → GREEN и порядок внедрения

Сначала pure codecs/legacy hash fixtures; затем real PG только в согласованном own
slot, без reset public retained Night. Нужные сценарии:

- Legacy0048 start receipt/no control: implicit exact retry после finish/kill flags/
  master loss возвращает старые bytes; explicit ai same ID conflict; нет control,
  новых requests/jobs/outbox. New implicit start создаёт ровно один request.
- New empty lobby control без позднего advisory; concurrent create/join/start и
  existing receipt replay не backfill. Гонки start/control/moderation/Room leave
  следуют одному lock order; cached state не скрывает проигравшую смену.
- Direct A.create_lobby → direct A.start_game без callback фиксирует original
  starter/epoch0/null binding без AI advisory/request/grant; последующий явный
  request_admin(expected_epoch=0) успешно получает starter и создаёт epoch1.
- Start callback/director failure полностью откатывает start; director видит already
  set started_at и control; default authored/admin start не зависит от vault/model;
  selected missing-master BYOK rollback и новый authored start успешны.
- Legacy starter proof positive; owner transferred, forged/multiple/missing receipt,
  invalid hash/actor/roster/timestamp → no grant/no invented owner. Bootstrap только
  на явной разрешённой настройке; reads, old retries и merged aliases grant не создают.
- Prepare commit виден второй PG session; zero proposal/render job/AP/AFK effects;
  no session/lock во время fake transport await (вторая session может выполнить
  обычную игровую команду). Prepared retry сохраняет request/token/expiry.
- Same request ID concurrent prepare/finalize → один terminal result/proposal;
  conflict text не перетирает запись. Crash after prepare/after HTTP/after finalize
  commit сохраняет exact replay; duplicate response не создаёт вторую proposal.
- Free-text R terminal clarification → button R conflict, proposal не появляется;
  button R → text R conflict; concurrent button-vs-text R (включая direct A button
  caller) фиксирует identity только одного пути. Matching finalized proposal в двух
  таблицах replay, inconsistent pair fail closed. Проверяются обе реальные PG rows.
- ID96/97/128: new AI96 accepted, AI97/128 validation error **до INSERT**; обычные
  button96/97/128 accepted и exact legacy retry не меняется. Same-ID cross-path
  receipt conflict/replay предшествует новому bound96, никакого обрезания ID.
- Prepare existing proposal/terminal clarification после departure/finish/expiry
  возвращает own exact receipt без active-gate; prepared replay сохраняет identity,
  но не выдаёт dispatch permit. Чужой/blocked principal не получает replay; Game
  lock не приобретается до AI advisory в prepare/finalize.
- Finalize после epoch/revoke/block/leave/window/own actor/resource change/expiry
  → clarification без AP; unrelated actor без изменения relevant eligibility
  не конфликтует. BYOK other/multi-private canaries не доходят до transport.
- Fresh selection exact allowed binding, original prepare deadline в proposal;
  confirm/retry после expiry сохраняют existing A command receipt semantics.
- Невалидные DTO/token/legal codec/oversize/unknown response → fail closed, без raw
  provider body или private metadata в result/errors/outbox.

После targeted GREEN — независимый review полного delta и только затем HTTP/director/T
срезы. Ни fake transport, ни этот план, ни backend PG tests не означают «AI работает».

## 9. Rollback / совместимость выпуска

AI0049 уже additive; новые orchestration writers включаются отдельно после migration
readiness и review. Авторский0048 artifact остаётся отдельным: не переносить туда
workspace AI imports/requirements/models. Kill egress/transport оставляет A/W и
authored narration работоспособными; pending/старые grants не дают HTTP без T gates.

Rollback code — снять orchestrator adapter/feature wiring, вернуть прежние A routes;
новые control/intent rows остаются retained, не стираются и не изменяют kernel rules.
Нельзя возвращать старый A wrapper для обработки **новых** explicit-ai start retry:
до истечения supported retry/history окна нужен совместимый receipt-only reader,
возвращающий уже сохранённый результат или conflict, но не запускающий start заново.
Новых migration/drop/reset этот срез не требует;0049 downgrade с retained AI rows
по принятому guard запрещён. Дальнейшая rehearsal/production выкладка требует
отдельного разрешения владельца, а не этого плана.
