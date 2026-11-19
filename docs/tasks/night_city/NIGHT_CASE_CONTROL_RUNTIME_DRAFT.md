# Night Case: control tickets и runtime registry — draft

Дата: 2026-11-16. **Принятый план реализации R2 после независимого review Sol.**
Проверенная до изменения этой шапки версия: SHA256
`5a7cf42702e78ab94e2279ae98086ab0e435fb67fe147e23303cc7d5062c43fc`.
Редакция R2: исправляет два P2 независимого review. Исходный draft SHA256:
`696710072198f22bbffddbe6bc762883e97277f5667759f674a5750a529aab27`.
Scope: конечный discovery/probe путь и сборка существующих AI-компонентов. Никаких
изменений правил дела, экономики, провайдерских платежей или новой авторизации.
Режим остаётся `Game.mode='night_case'`. Здесь нет разрешения на реальные ключи,
платные запросы, изменение rehearsal/production или системных настроек.

Основание: [AI_ACCESS](NIGHT_CASE_AI_ACCESS.md), [T](NIGHT_CASE_TRANSPORT_DRAFT.md),
[application contract](NIGHT_CASE_APPLICATION_CONTRACT.md), принятые HTTP/views R2.
Проверены owning `config/night_case_ai.py`, `storage/night_ai.py`, AI control/repository,
gateway/adapters и текущие signatures `application/night_case_ai_dispatch.py`.
**T stage3 ещё не frozen:** его текущие имена — ориентир для seams, не новая спецификация
его внутренностей. До реализации этого draft согласовать seams с принятой финальной T.

## 1. Граница результата

Администратор сохраняет профиль, выбирает его ревизию, получает ограниченный список
моделей либо вводит ID вручную, отдельно выполняет синтетический probe. Запускающий
игрок может делать то же только со своим staged/active BYOK данной партии.
BYOK активируется сразу по существующему control API, **без обязательного probe,
discovery или admin approval**. Неудача/отсутствие проверки означает `unverified`
или bounded error, а не дополнительный gate для cloud BYOK.

Нельзя изображать models/probe игровыми intent/render jobs. Новый control attempt
не имеет `NightRenderJob`, `NightAIIntentRequest`, AP, knowledge, narrative context
или binding gameplay slot. Успешный probe не выдаёт grant, не меняет эпоху и не
разрешает чужие private jobs. Admin AI и Night narrator credentials остаются раздельны.

Один результат discovery — максимум один GET и до 500 моделей; один probe — максимум
один inference POST с лимитом 64 output tokens. Giga может предварительно потребовать
один OAuth POST. Нет автоматического retry, pagination loop или фонового probing всех
моделей. При частичном каталоге есть `truncated`; ручной ID сохраняет рабочий путь.
Отдельно разрешён demand-driven inventory refresh действующего pinned local binding
перед игровой AI-задачей (§4.1). Это metadata GET без игрового контекста и без probe.

## 2. Runtime registry: ручной ID не равен доказанной capability

Существующие `ProfileRegistry.models` и `ModelCapabilities` требуют известную пару
`(preset,model_id)`. Их нельзя наполнять произвольными capabilities из браузера или
ответа `/models`. Минимальное расширение:

- Добавить один pure resolver контракта внутри registry, используемый **одинаково**
  `build_profile`, `ProfileRevision.decode`, views, control, dispatcher и adapters.
  Сначала explicit operator entry, затем разрешённый conservative manual contract.
  Старый конструктор по умолчанию сохраняет strict behavior; runtime factory явно
  включает manual admission для разрешённых presets. Не создавать второй codec.
- Manual model ID: строка 1..256 UTF-8 bytes, без управляющих символов, NUL и внешних
  пробелов. Это opaque ID, не URL для перехода. Сохраняются ограничения Yandex folder
  URI и HF/OpenRouter explicit routing; `auto` и provider fallback запрещены.
- Manual contract: `json_output='prompt'`, `supports_temperature=False`, generation
  `temperature=null`, output 1..800. Limit field выбирается существующим конечным
  adapter contract: Responses=`max_output_tokens`, Messages/Giga/прочий Chat=
  `max_tokens`; отдельный заранее протестированный operator override может выбрать
  допустимый `max_completion_tokens` для Chat. Не угадывать поле по имени модели.
  Неизвестная модель/несовместимое поле может дать fallback; `unverified` честно это
  сообщает. Ни модели, ни capabilities не выбираются автоматически по первой строке.
- Для Anthropic API `2026-10-21` sampling override запрещён безусловно, включая
  explicit operator entry: `temperature/top_p/top_k` не отправляются. API этой версии
  отклоняет эти поля, независимо от модели. [Официальная migration](https://platform.claude.com/docs/en/api/migration-2026-10-21).
- `ProfileRevision.config/config_hash` остаются неизменяемым snapshot выбранных
  settings/capabilities; probe не переписывает их. Более сильный JSON contract требует
  нового явно проверенного operator contract и новой profile revision. Ответ списка
  моделей и единичный успешный probe не являются доказательством поддержки JSON schema.
- Допуск local ID в **конфигурацию** разрешает discovery профиля до выбора модели.
  Его inference/probe отдельно требует local-execution evidence (§4). Поэтому нет
  цикла «чтобы запросить inventory, сначала нужно доказать выбранную модель».

Новая таблица моделей не нужна. `unverified|probe_ok|probe_failed` — безопасная проекция
последнего terminal control receipt именно для текущих config/credential/policy pins;
время `checked_at` обязательно. Исторический успех не становится live readiness.
Capability и local-admission evidence — разные вещи. Успешный probe не повышает права.

## 3. Операторский каталог endpoint policies

Для первого среза **server-config + read-only admin catalog**, без web CRUD сетевых
политик. Администратор в UI выбирает существующие `policy_id/version`; новый адрес,
CIDR или CA добавляется оператором в versioned deployment manifest с проверкой и
перезапуском процессов. Это явное ограничение первого UI, не обещание редактирования
любой локальной машины из браузера.

Manifest — отдельный конфигурационный JSON, не общий mutable state игры. Фиксирует:
`manifest_version=1`, `environment_id`, policies с immutable `policy_id/version`,
base_url/network_class, exact allowed CIDRs, named CA reference, label, поддержанные
presets, `inventory_route` из закрытого enum, optional exact `local_model_allowlist`.
Существующий gateway `OperatorPolicy` остаётся владельцем SSRF/TLS validation. Новый
manifest переводится в его types; это не второй URL validator. Смена тех же id/version
с другим canonical hash отвергается. Старые профили не переводятся на новый URL молча;
удалённая policy даёт `config_unavailable`, snapshot/receipt остаются читаемыми.

Cloud origins остаются из 18-preset каталога. BYOK не принимает policy, URL, CA,
CIDR или custom headers. Local/generic — только admin. Catalog admin DTO содержит
`policy_id,version,label,presets,network_class,inventory_supported`; полный адрес/CA
не попадает в игровые DTO. CA reference разрешается в отдельный read-only bundle,
создаёт проверяющий SSLContext; нет `verify=False`, изменения глобальной ОС или SDK.

`localhost` означает host/network namespace серверного executor, не браузера игрока.
Для минимального среза API/admin control executor и game worker должны видеть один
операторский endpoint (один host/network namespace либо общий явный адрес). Factory
получает общий manifest; deployment acceptance проверяет этот факт. Раздельные loopback
пространства с одинаковой строкой URL не считаются одной policy. Worker RPC/новая
распределённая auth-система сюда не входят; неподходящую topology не включать.

## 4. Discovery: закрытые routes и локальность

Первый проверяемый inventory catalog:

| Preset | Разрешённый read-only route | Нормализация и граница |
|---|---|---|
| openai | GET fixed base + `/models` | `data[].id`; advertised, не capability. [API](https://developers.openai.com/api/reference/resources/models/methods/list). |
| anthropic | GET `/v1/models?limit=500` | `data[].id`, `has_more`; без follow cursor; auth/workspace/version как pinned profile. [API](https://platform.claude.com/docs/en/api/models/list). |
| gemini | GET compatibility base + `/models` | `data[].id`, тот же Bearer. [Compatibility](https://ai.google.dev/gemini-api/docs/openai#list-models). |
| gigachat | GET fixed Giga base + `/models` | Bearer из bounded OAuth cache; Giga response codec. [API](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/get-models). |
| ollama | GET operator-declared same-origin `/api/tags` | native model/name/digest/remote metadata; не путать с `/v1/models`. [API](https://docs.ollama.com/api/tags). |
| lmstudio | GET operator-declared same-origin `/api/v1/models` | только type=llm; key, installed, loaded_instances → loaded. [Native API](https://lmstudio.ai/docs/developer/rest/list). |
| vllm, llama_cpp | GET pinned base + `/models` | server-advertised/served ID, без reload query. [vLLM](https://docs.vllm.ai/en/latest/serving/online_serving/), [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). |
| остальные presets + generic_openai | в первом срезе `discovery_unsupported` без network | inference уже использует 4 принятых families; manual model ID доступен. Добавление models route требует primary API fixture и finite catalog entry, а не предположения «всё совместимо с /models». |

Таким образом все 18 presets сохраняют настройку/ручной ID и bounded inference/probe;
этот срез не объявляет native discovery каждого провайдера проверенным. Никакого SDK
или отдельного универсального HTTP клиента на preset. Native inventory — небольшой
read-only decoder рядом с существующими adapters, не новая inference family.

Native route может отличаться от inference base path, но **только заранее заданным
same-origin абсолютным path** в operator catalog. Не выводить его из returned URL,
не разрешать браузеру arbitrary path. Reverse-proxy prefix должен быть указан заранее;
если его нет, `discovery_unsupported`. Нет pull/download/load/unload/delete, `/show`,
`reload=1`, tools, web search или файловых endpoint. Обычный inference local server
может загрузить уже установленную модель в память; это объясняется оператору.

Ollama local API умеет делегировать в cloud — это документировано; одного адреса
127.0.0.1 и присутствия ID в списке недостаточно. [Cloud API](https://docs.ollama.com/cloud).
Официальный server заполняет `remote_model/remote_host` из manifest модели:
[model_list.go](https://github.com/ollama/ollama/blob/main/server/model_list.go).
Нормализатор известной native schema отвергает remote entries, cloud aliases и
неподтверждённые/неполные записи. Для `installed` нужны положительные native признаки
локальных весов: bounded digest, положительный size, поддержанный local format и
отсутствие remote linkage в поддержанной версии схемы. Это утверждение доверенного
операторского сервера, не криптографическое доказательство физического исполнения.
Неизвестная версия/shape → `unknown`, без inference; допустим только explicit exact
operator local-model allowlist. Known remote linkage запрещён и при совпавшем allowlist.
Оператору можно рекомендовать отключить cloud в Ollama; приложение не меняет его
настройки само. [Официальный envconfig](https://github.com/ollama/ollama/blob/main/envconfig/config.go).

Local execution допускается при exact server allowlist либо свежем (≤5 min) успешном
inventory receipt для тех же owner/preset/credential/policy pins с выбранным ID:
Ollama/LM Studio — installed/loaded, vLLM/llama.cpp — served. `generic_openai` без
native evidence требует operator allowlist. Receipt может относиться к прежней
profile revision, только если **все** перечисленные pins совпадают; смена model ID
сама по себе не инвалидирует список. Ни чужой BYOK, ни другая policy не делятся cache.
Просроченный evidence сам не разрешает inference: отдельный bounded refresh (§4.1)
может получить новое доказательство. При неуспехе — fallback/`local_model_unverified`.
GET никогда не выполняется из gameplay transaction. Ручной discovery остаётся доступен,
но не требуется перед каждым новым окном недели. Cloud BYOK этой проверкой не связан.

Нужен один application helper `verify_local_execution(profile, owner_scope, now,
session, policies)` для control probe и **T gameplay authorize**. Он читает только
безопасный receipt/evidence и policy, не ходит в сеть. Это narrow seam после freeze T;
его нельзя заменить динамическим доверенным добавлением ID в pure registry. Admission
ref/hash и valid_until входят в private grant; deadline не выходит за срок evidence.
Models GET не требует admission выбранной модели и потому может получить первый список.

### 4.1. Refresh только по действующему игровому demand

У принятого T checkpoint1 `dispatch()` начинает с `reserve()`, а `_validate()` вызывается
внутри коротких reserve/authorize/complete transactions. Сейчас local-evidence helper
там отсутствует. Минимальный seam — внешний application coordinator
`ensure_local_admission(dispatch_source, actor, worker_id, transaction_factory=None)`
**до** вызова T.reserve; `_validate` получает только read-only admission check. Не
встраивать network callback в `_validate`, не перезапускать неудачный T permit.

1. Короткая tx: fresh действительная identity исходного T caller, operation fence,
   own terminal intent/render replay **до refresh**, затем AI advisory → Game/control →
   pinned binding/profile/credential → source. Проверить исходную intent/assignment ACL,
   mode/audience (включая BYOK), current epoch, running/non-interrupted game, participating
   starter, flags и source TTL. Job без assignment, ghost private job, source с готовым
   rendering/proposal либо закрытый source не создаёт inventory traffic. При cloud,
   allowlist или свежем admissible evidence refresh не нужен.
2. Если source ещё допускает не менее24s до исходного expiry, нет evidence, policy local
   и native inventory supported, координатор создаёт internal `ActiveLocalBindingSource`
   через trusted `WorkerPrincipal` из T. Account/Admin identity не подделывается; у worker
   отдельное право читать metadata **текущего** binding. Сохраняется только digest
   неизменной identity demand, не его текст/факты/меню. Затем tx закрывается.
3. Reserve/send/complete control flow (§5–7) выполняет максимум один фиксированный
   inventory GET, со своим12s budget, без SQL/HTTP principal context вокруг network.
   Local bearer использует ровно pinned credential; anonymous не требует vault/external.
   Никаких inference/OAuth/probe из этого worker-source и новых grants/epochs.
4. После completed inventory новая tx снова проверяет local admission. При успехе
   обычный T.reserve заново выполняет свои ACL/pins/TTL/quota checks; actual inference
   получает отдельный reviewed T permit и12s budget. Время metadata не продлевает
   original source TTL: если для T осталось недостаточно времени, authored fallback.
   Control GET не занимает gameplay slot и не списывает game inference/token caps.
   Refresh не даёт права повторно создать job или перерисовать first-shown rendering.

Это один запрос по потребности, не scheduler, heartbeat либо обход всех профилей.
Терминальный replay исходного T source не инициирует refresh даже через10h/после рестарта.
UI/HTTP не получает internal worker source. Exact allowlist остаётся альтернативой
metadata GET (кроме ранее установленного latest exact-scope remote evidence).

Refresh subject стабилен: `worker-profile:` + profile UUID, не process/worker instance,
binding UUID, epoch или revision. Immutable `demand_hash` = SHA256 compact canonical JSON
`['night-local-demand/1',game_id,source_kind,source_id,binding_id,epoch,config_hash,policy_hash]`;
kind/id берутся из реально прочитанного T source, не browser input. Request ID =
`local-refresh:` + demand_hash; сохранённый attempt уникален по subject/request ID.
Re-entry того же demand получает тот же pending/terminal receipt, без нового nonce/send.
Другие demands того же профиля используют свежий scoped cache; partial active profile
slot допускает только один refresh/check одновременно. `busy` даёт fallback текущему
demand, без ожидания под lock и без создания второго outbound разрешения.

Unknown/crash не переигрывает этот demand, даже после истечения его lease. Новый игровой
source может создать новый inventory attempt только после cooldown5min от последнего
failed/expired/uncertain automatic refresh того же профиля; это новая bounded проверка
для нового demand, не retry старого HTTP. Таймер сам её не запускает. Текущий demand
получает fallback при cooldown/limit/unknown/unsupported/remote/unknown locality.
Так следующий job через10h обновляет inventory без ручного admin refresh; если local
сервер недоступен или модель стала remote, игра продолжает authored fallback.

Cache ownership отделено от worker quota subject. Scope доказательства берётся из
профиля: environment + profile owner/scope/game + preset + credential UUID (либо null)
+ policy hash + native route/decoder version. Admin ручной inventory и worker refresh
могут делить evidence только при совпадении этого полного scope; worker не становится
владельцем профиля. Pins текущего active binding всё равно перепроверяются отдельно.
Local admission valid_until≤checked_at+5min должен покрывать весь выдаваемый T network
deadline; истёкший/отозванный evidence запрещает send/complete. Negative remote evidence
нельзя обойти старым positive receipt. Для native admission проверяется последний
completed inventory полного matching scope, а не поиск любой старой записи с нужным ID:
absent/unknown ID в последнем списке не подтверждён (включая truncated result).
Cache не переносит никакой gameplay context.

## 5. Control source и авторизация

Закрытый input union, caller не задаёт owner/config/credential values отдельно:

```
AdminProfileSource {kind:'admin_profile', profile_id:UUID, revision:int32>=1}
StagedByokSource   {kind:'staged_byok', game_id:String64, staged_credential_id:UUID}
ActiveByokSource   {kind:'active_byok', game_id:String64, binding_id:UUID, expected_epoch:int32>=0}
ActiveLocalBindingSource {kind:'active_local_binding', game_id:String64, binding_id:UUID,
                          expected_epoch:int32>=1, demand_hash:SHA256, demand_expires_at:UTC}
ControlRequest    {purpose:'models'|'probe', source:human-source-union, client_request_id:ASCII[8..96]}
LocalRefreshRequest {purpose:'models', source:ActiveLocalBindingSource, client_request_id:derived}
```

Администратор — existing live AdminAuth session/CSRF + server-created deployment
AdminPrincipal. Доступ к admin profile только его `created_by_subject`; существующий
disabled profile разрешён для models/probe перед enable, но credential должен быть
usable. Source pin включает observed enabled/current_revision; изменение любого из
них отменяет незавершённый результат. Admin binding не требуется.

Staged: живой start-authorized lobby owner, его game-scope credential status=staged,
не истёкший срок; единственная соответствующая current profile revision. Несколько
несогласованных ссылок — fail closed, не выбирать первую. Active: original starter
из control/proven receipt, live Game ACL, участие active/fog/ghost, running game,
точный current active BYOK binding/epoch. Не использовать Room.owner как fallback
для начавшейся игры. Probe допускается при health=auth_error/config_error для
диагностики, но сам не очищает health и не оживляет revoked grant. Ghost не получает
новых private narrative jobs из-за права управлять собственным ключом.

Четвёртый source internal-only: exact trusted T `WorkerPrincipal`, только models и
только current active **admin local** binding (BYOK arbitrary/local endpoint запрещён).
На reserve/send/complete нужны running Game + sealed lifecycle, current control
binding/epoch, active unexpired binding, health=ok, enabled profile, точная pinned
revision/config/caps, credential usable/unexpired либо auth_mode=none, participating
original starter active/fog/ghost с живым не blocked/archived/merged Account, enabled
runtime и та же разрешённая local policy/route. External flag не требуется local GET;
vault нужен только bearer. Нельзя пользоваться current default вместо pinned revision.
Game end/interruption, departure/moderation, revoke/rebind, credential/policy replacement
между фазами отменяют результат. Worker не читает admin session, не выдаёт approval,
не чинит health и не запускает probe. Demand expiry ограничивает attempt и также
перепроверяется; по возможности повторно проверяется исходная assignment/source currentness
в coordinator перед inference, всегда — обычным T.reserve.

Blocked/archived/merged-away principal запрещён на всех фазах. Исторический retry
может использовать только доказанную merge ancestry, как существующие own receipts;
никогда caller-provided aliases. В read receipt — fresh principal + source ownership
и game history ACL; terminal receipt можно вернуть после source expiry, но нельзя
запустить сеть снова. Ни admin, ни новый room owner не читают чужие BYOK results.

## 6. Одна новая durable таблица

Нужна `night_ai_control_attempts`: existing operation receipts не умеют owned lease,
send-CAS и pending result; игровые FK намеренно не подходят. Номер migration —
**0051 после 0050, если это всё ещё единственный head на старте реализации**. Не
переписывать 0045–0050. Одна таблица совмещает attempt и terminal safe receipt.

| Поля | Тип/constraint |
|---|---|
| id; principal_subject; principal_account_id | UUID PK; bounded server subject≤128; nullable Account UUID FK (RESTRICT), global admin без fake account |
| client_request_id; request_hash | ASCII8..96; lowercase SHA256 canonical purpose+input source+principal domain `night-ai-control/1`; UNIQUE(principal_subject,client_request_id) |
| purpose; source_kind | enum models/probe; admin_profile/staged_byok/active_byok/active_local_binding; последний только models |
| profile_id, profile_revision, config_hash | composite FK на immutable revision; int32>=1; SHA256; обязательны всем sources |
| credential_id | nullable FK RESTRICT; null только admin_profile/active_local_binding с auth_mode=none; нигде key/nonce/ciphertext |
| game_id, binding_id, epoch | admin: все null; staged: game nonnull, binding null, epoch nonnull; оба active kinds: все nonnull, FK binding; Game String64, epoch int32>=0 (worker>=1) |
| starter_subject_account_id | nullable Account FK RESTRICT; nonnull для BYOK и worker sources; active/worker: original starter из control/proven receipt; staged: immutable credential owner, проверенный по правам текущего lobby starter; не Room.owner для начавшейся игры |
| demand_hash, demand_expires_at | только worker source: оба nonnull immutable SHA256/UTC; остальные null; no Case/text/source payload |
| source_hash; policy_hash; registry_contract | hash immutable normalized pins; hash exact operator policy; bounded server contract version |
| observed_profile_revision, observed_profile_enabled | current profile identity/enabled на reserve; не подменяют выбранную historical revision |
| created_at, expires_at | UTC; expires=min(created+30s, source credential/binding expiry, worker demand expiry если есть); immutable |
| executor_id, lease_nonce | String96 и UUID; immutable, серверные; не выдаются клиенту |
| status | reserved / sending / completed / failed / cancelled / expired / uncertain |
| network_started_at, network_deadline | оба null до first outbound authorization; потом immutable UTC, deadline≤expires и ≤started+12s |
| oauth_claimed_at, operation_claimed_at | nullable, write-once; main operation только один раз, OAuth только Giga один раз |
| quota_debits | closed bounded JSON ≤4096, phase-tagged ссылки на counter scopes/periods; append-once для reserve_probe/oauth/operation, прежние записи immutable |
| completed_at, safe_result | оба null для reserved/sending; terminal timestamp + closed purpose-specific JSON ≤1MiB |
| local_evidence | nullable JSONB≤256KiB; только completed models: `{version:1, records:[{id,locality:'local'|'remote'|'unknown',availability,digest:null|bounded_string}]}`;≤500 records, остальные scope/policy/credential pins берутся из row |

SQL CHECK закрывает shape/nullability/times/terminal forms; INSERT trigger проверяет
source/profile/credential/game/epoch consistency (не только наличие отдельных FK).
Update trigger запрещает изменение pins, nonce, deadline, сброс claimed markers и
terminal rewrites/deletes. Для active source binding должен совпасть с profile,
credential и Game, staged credential принадлежит principal/game; admin scope — admin.
Worker source имеет principal_account_id=null, subject=`worker-profile:<profile_id>`,
admin-scope local profile и matching current control original starter/binding/epoch;
SQL guards не позволяют probe, cloud policy/config, BYOK или чужой profile/credential.
Active game source starter pin сверяется с authoritative control; staged owner — с
credential и start-authorized lobby ACL (control.starter может ещё быть null).
Account merge не переписывает сохранённый pin. Worker request ID обязан совпасть с
`local-refresh:` + сохранённым demand_hash.
Partial unique(profile_id) для reserved/sending ограничивает параллельные control
проверки одного профиля; это **не** `NightAIBinding.inflight_permit_id`.
Перед новым reserve истёкший active attempt этого профиля можно CAS-завершить под тем
же lock order; не удалять его ради освобождения slot. Local evidence — immutable
часть terminal result, заполняется только checked native decoder. Latest exact-scope
remote evidence запрещает ID даже при allowlist; новый positive inventory может
доказать изменившееся состояние. Другие результаты/ошибки не выдают local admission.

Проверка ACL/expiry/currentness в application остаётся обязательной: FK не заменяет
модерацию. Переходы repo CAS проверяют id+nonce+executor+status+deadline. Direct SQL
негативы должны проверять cross-game/profile pins, повтор sent, terminal mutation.
No raw provider response, prompt, headers, credential material или plaintext key.

Downgrade: lock новой таблицы и соответствующих counters до проверки; отказ ДО DROP,
если есть любой attempt/receipt либо ненулевой новый daily probe namespace. Общие
`nai:control:*:minute` принадлежат также T и не удаляются/reset. Empty upgrade/down/up
и retained receipt refusal проверяются на own-schema PG; публичную БД не мигрировать
ради теста. Account merge классифицирует новый FK как immutable history, не переписывает
subject/pins задним числом; RESTRICT сохраняет историю.

## 7. Lifecycle, quotas и реальная граница транзакции

Единый порядок каждой короткой tx: shared operation_fence → fresh principal/ACL →
own receipt lookup → AI config advisory → Game/sealed/control (только game source) →
profile/revision/credential → control attempt → sorted counter rows. Исторический
terminal replay идёт до clock/expiry/decrypt, но после fresh auth/fence. Одинаковый
ID+fingerprint возвращает тот же receipt, иной payload —409 idempotency_conflict.

1. `reserve`: проверить source и runtime/policy/registry; вставить immutable attempt,
   зарезервировать daily probe quota (если probe), commit. Если disabled/unsupported/limit/busy — сохранить
   собственный terminal safe outcome (после ACL), без выдачи outbound ticket.
2. `authorize_oauth` при cache miss: новая tx с тем же порядком, повторить auth/source,
   атомарно списать minute quotas для OAuth, поставить write-once marker и общий deadline, расшифровать локально только нужный
   credential, подготовить private DTO. **Только после успешного commit** выдаётся
   одноразовый `ControlOAuthTicket` и выполняется network.
3. `authorize_operation`: новая tx, fresh auth/source/expiry, проверка exact cached
   token pins, атомарное списание minute quotas основной операции,
   CAS operation_claimed_at/status=sending, commit; затем `ModelsTicket`
   или `ProbeTicket`. Если OAuth не требовался, здесь начинается общий12s budget.
4. `exchange` вне session/transaction. OAuth + основной запрос делят один monotonic
   budget; последующие tx не обнуляют его. UTC используется для durable fences,
   rollback wall clock не добавляет elapsed budget. Рестарт не воссоздаёт budget.
5. `complete`: новая tx, fresh auth/current pins/nonce/deadline. Сохраняется только
   validated safe result. Revoke/replace/moderation/expiry побеждают поздний результат:
   raw result уничтожается, attempt cancelled/expired; grant/профиль не восстанавливается.

Для HTTP обязательно закончить **внешний** principal/database context до exchange;
недостаточно назвать метод orchestrator. AdminAuth/session проверяется до каждой
reserve/send/complete фаз и непосредственно перед commit, как в принятом HTTP adapter.
Для этого control facade выполняется в процессе текущего authenticated request;
`reauth` — trusted existing session callback, не пользовательский claim. Worker завершает
зависшие attempts безопасной ошибкой; отдельно разрешён только internal source §4.1/5
со свежей worker/binding authority. Он не продолжает human attempt и не переигрывает
чужую admin-сессию. Refresh выполняет те же независимые transactions и send CAS.
Shared environment/policy topology оговорена §3. Disconnect/cancel не отменяет уже
выполненный provider request; завершение receipt может отсутствовать, но retry не шлёт
его повторно. Защищённый cleanup выполняется после закрытия сетевого ресурса.

Неизвестный исход после send/crash → `uncertain`, никаких hidden retries. Даже reserved
attempt не подхватывается новым executor: после30s expires; пользователь может явно
создать новую проверку с новым ID и новой квотой. Получение одного receipt повторно
не расходует квоту. Для automatic refresh новый demand/cooldown определён §4.1;
executor не меняет request ID старого demand для обхода terminal outcome.
Remote billing exactly-once не обещается.

Квоты используют `NightNarratorLimit`, транзакционные locks в одинаковом порядке с T:

- Существующие `nai:control:global:minute`≤30 и `nai:control:<subject>:minute`≤5;
  UTC minute buckets. Все новые control calls **делят их с OAuth игрового T**.
- Каждая outbound authorization списывает1 request в **текущей** UTC minute:
  основная операция и отдельный OAuth при cache miss. Cache hit не требует OAuth
  authorization. Counter debit и соответствующий claimed marker — одна tx; повторный
  CAS не списывает снова. Ожидание после reserve не обходит новую минуту. Лимит означает
  число выданных сетевых разрешений за минуту, не измерение remote billing/wall clock.
- Probe дополнительно `nai:probe:day:<sha256(quota_identity)>`≤2/day UTC. Canonical
  compact UTF-8 JSON identity для admin = `['night-probe-day/1','admin',created_by_subject,profile_id]`;
  для staged/active BYOK = `['night-probe-day/1','byok',game_id,original_starter_subject]`.
  Original starter running game берётся из authoritative control/proven receipt.
  Actual lobby `_ensure_control` ещё допускает starter=null: staged identity использует
  immutable credential.owner_subject, совпадающий с current start-authorized lobby owner.
  Это будущий starter subject, а не выдуманное заполненное поле control. Stage→start
  с тем же организатором попадает в тот же bucket; после start credential owner обязан
  совпасть с original starter. Смена lobby owner не даёт новому владельцу доступа к
  старому staged credential/receipt; его проверки собственного нового ключа принадлежат
  его subject. Нельзя заменить pin receipt текущим principal alias или Room.owner.
  Unprovable ownership/original starter → отказ до quota/send.
  В BYOK identity **нет** profile/credential UUID, revision, epoch, nonce или model ID:
  actual `stage_or_activate_byok` создаёт новый profile UUID при каждой rotation, но
  две проверки той же партии/исходного организатора остаются общим лимитом. ≤128 chars scope.
  Первый reserve списывает daily probe резерв, no refund; OAuth failure тоже считается.
- Worker models использует тот же global30/min и principal5/min с subject
  `worker-profile:<stable profile UUID>`; все процессы/игры/ревизии этого профиля делят
  bucket. Профиль берётся из binding, не из worker input. Смена executor/binding/epoch
  не сбрасывает его. Прямой контроль admin остаётся в его principal bucket; оба пути
  делят global30, partial profile slot и scoped cache, без отдельного unlimited namespace.
- У probe фиксированный input≤1KiB и output cap64, models не тратит игровые token caps.
  Control traffic не обнуляет gameplay circuit и не имеет retry после429/5xx/401.
  Safe cooldown/code отражается в receipt; текущий game health не объявляется исправленным.

Quota/circuit/readiness не являются доступом к сети: только committed send CAS выдаёт
ticket. Disabling flags после reserve проверяется перед выдачей. Как в T, commit
authorization — linearization point: уже выданные байты нельзя отозвать, но поздний
результат не применится. Не обещать невозможную атомарность DB с внешним провайдером.

## 8. Gateway и safe DTO

Новые закрытые private types `ControlAuthorization`, `ModelsTicket`, `ProbeTicket`,
`ControlOAuthTicket` с purpose/source/config/credential/policy pins и общим NetworkBudget.
Они не принимаются gameplay `TicketFactory.issue` через подделанный DispatchSource.
Gateway добавляет явные branches для этих exact types и сохраняет общий pinned
numeric-connect backend, original Host/SNI/TLS verification, no proxy/redirect,
mixed-DNS rejection, special-address policy и scoped log suppression. Не дублировать TLS.

Models: GET только из §4, no body, максимум1MiB wire bytes и500 normalized records,
deadline12s; те же bounded headers/identity encoding, запрет gzip/oversized/chunk flood.
Полный JSON разбирается strict decoder с depth/duplicate/numeric bounds. Более500
строк → первые500 в стабильном provider order, dedup IDs, `truncated=true`; превышение
1MiB → bounded oversize error, не частично доверенный JSON. Returned links игнорируются.
Anthropic has_more становится truncated, не следующим HTTP запросом.

Probe: существующий adapter codec и output cap `min(64,pinned max_output_tokens)`;
immutable synthetic template
`night-control-probe/1`: system требует только JSON, user просит ровно
`{"ok":true}`. Никаких Case/Game/account names, истории, tool calls или пользовательского
prompt. Success только exact decoded JSON object с boolean true и нормальным завершением;
refusal/truncation/reasoning-only/extra keys → probe_failed. Это connectivity + минимальный
text/JSON smoke, не доказательство качества/всех capability. Native structured JSON
опции берутся только из pinned проверенного profile contract; manual остаётся prompt.

Public-to-owner receipt DTO (закрытые поля):

```
{id:UUID, purpose:'models'|'probe', status:'pending'|'completed'|'failed'|'cancelled'|'expired'|'uncertain',
 created_at:UTC, expires_at:UTC, checked_at:UTC|null, code:SafeCode|null,
 result: null | ModelsResult | ProbeResult}
ModelsResult = {models:[{id:str, availability:'advertised'|'installed'|'loaded'|'served'|'unknown'}],
                truncated:bool}
ProbeResult = {ok:bool, contract:'night-control-probe/1'}
```

SafeCode конечный: `disabled,discovery_unsupported,local_model_unverified,source_stale,
expired,acl_denied,busy,quota_exhausted,auth_error,config_error,endpoint_denied,timeout,
oversize,invalid_response,probe_failed,provider_unavailable,network_uncertain`.
Нет source owner, token, header, provider error message, raw body/usage prose, key hash,
credential fields или DNS/IP в HTTP error. Storage может дополнительно хранить bounded
safe local evidence (digest/locality/route version) для §4; оно не переносится в public
game view. Model IDs остаются owner-scoped и выводятся UI только как escaped text.

## 9. API/factory seams и включение

Предлагаемые минимальные signatures (имена уточнить после freeze T, смысл обязателен):

```
NightAIControlChecks.reserve(principal, request) -> OwnReceipt | ReservedControl
NightAIControlChecks.authorize_oauth(id, nonce, executor, auth) -> private grant
NightAIControlChecks.authorize_operation(id, nonce, executor, auth, token_ref=None) -> private grant
NightAIControlChecks.complete(id, nonce, executor, auth, bounded_result) -> OwnReceipt
NightAIControlFacade.execute(principal_resolver, request) -> OwnReceipt
NightAIControlChecks.get_receipt(principal, id) -> OwnReceipt
NightAILocalAdmission.ensure_local_admission(dispatch_source, actor, worker_id,
                                            transaction_factory=None) -> Ready | Replay | Fallback
```

Facade — владелец отдельных transactions, не принимает открытую caller session на
время network. Session-bound сервисы получают реальные service factories. Token/raw
body существуют только в private in-memory ticket с repr=False. Межпроцессного secret
broker/RPC в этом срезе нет. Models/probe routes используют уже принятые HTTP auth,
CSRF/origin/expected-viewer pin/manual bounded JSON/safe error contracts.
LocalAdmission — composition facade §4.1, не HTTP endpoint. `Ready` не является send
ticket; `Replay` возвращает уже сохранённый source result; `Fallback` использует обычный
T/N authored completion без модели. Только trusted facade формирует worker-source;
human models/probe request decoder отвергает active_local_binding. Internal receipt
не открывает список моделей игрокам: read owner API по-прежнему допускает лишь три
human source kinds. Worker/cleanup читает только собственные служебные записи.

Admin: POST `/api/admin/night-case/ai/profiles/{id}/revisions/{rev}/models|probe`, body
`{client_request_id}`; GET own `/api/admin/night-case/ai/checks/{id}`. Game: POST
`/api/night-case/games/{game_id}/ai/models|probe`, body closed source selector
`{kind:'staged_byok',staged_credential_id,client_request_id}` либо
`{kind:'active_byok',binding_id,expected_epoch,client_request_id}`; GET own
`.../ai/checks/{id}`. Клиент не передаёт произвольный credential/profile чужого scope.
202 для pending,200 terminal safe receipt,403/404 ACL,409 conflict,422 invalid; все no-store.

Единый runtime builder, env читается только в composition root:
`build_night_ai_runtime(db, settings, deployment_manifest, clocks, auth_factories)`.
Создаёт registry resolver, SecretVault/ReceiptFingerprinter, pinned policy catalog,
gateway/OAuth cache, control factories, принятый T dispatcher и control facade.
API/admin/worker используют одинаковые environment_id, manifest hash и keyring versions.
`NIGHT_AI_MASTER_KEYS`, `NIGHT_AI_MASTER_ACTIVE_KEY_ID`, `NIGHT_AI_RECEIPT_HMAC_KEY`,
`NIGHT_AI_RECEIPT_HMAC_ACTIVE_KEY_ID` — существующие vault settings;
не обращаться к admin_ai. Старые ключи остаются для retained ciphertext/receipt verify.
Anonymous local допускает отсутствующий master key. Новый control request не содержит
key material и использует canonical SHA256 fingerprint; существующим key-bearing
stage/save по-прежнему нужен отдельный receipt HMAC keyring. Нельзя требовать новый
секрет ради anonymous models/probe. Стабильный deployment identity обязателен.
Missing secret key не превращает cloud key-bearing profile в anonymous.

Реальный deployment факт, переданный координатором после read-only проверки:
rehearsal API+worker читают `/etc/mqb/mini-app.env`, админка — project `.env`.
DATABASE_URL совпадает, но текущие Night enabled/cursor/readiness заданы только
первому набору. **Нельзя строить admin factory из пустого NightCaseSettings и делать
вид, что он общий.** Будущий authorized deployment должен явно подключить общий
private config/keyring к трём службам (или эквивалентно настроить их service env),
проверить environment/manifest/key IDs/cursor readiness без вывода значений секретов.
Этот документ не меняет env-файлы, сервисы или доступы. Отсутствующая конфигурация
даёт bounded unavailable/OFF, не generated-on-start secret и не fallback к admin_ai.

`NIGHT_NARRATOR_ENABLED=false`, `NIGHT_NARRATOR_EXTERNAL_ALLOWED=false` по умолчанию.
Первый требуется всем network purposes, второй — только cloud/OAuth. Auth secret требует
vault_ready; anonymous local — нет. `config_ready` не означает successful provider probe.
Factory не делает HTTP на import/startup, не перечисляет модели и не запускает polling
без запроса. Local refresh запускает лишь действительный pending source через §4.1,
включая первый job после старта/следующего окна; не process startup. Incomplete wiring
оставляет authored fallback; flags не выбирают test fake. В factory один gameplay
entry point вызывает LocalAdmission, затем принятую T orchestration/dispatcher;
direct T.reserve/authorize без evidence тоже отказывает, поэтому facade не safety bypass.

HTTP key form остаётся write-only password input до TLS submit, затем очищается;
GET только mask/configured. Не HTML attributes/DOM data/localStorage/telemetry. Этот draft
не включает большую вёрстку. API catalog/manual-ID/receipt достаточно для следующего UI.

## 10. Ownership и приёмка

Срезы после независимого review, без одновременных правок T-owned gateway до его freeze:

1. **Registry/factory contracts:** `config/night_case_ai.py` narrow resolver + новый
   runtime composition module; tests manual/old strict registry/retained config parity.
   Не менять profile hashes при чтении, не повышать capabilities из inventory.
2. **Control storage:** отдельный `storage/night_ai_checks.py`, owning AI model +0051,
   one-table retention/constraints/CAS/quotas. Shared metadata импорт только по договору.
3. **Control application + gateway delta:** новые control checks/facade; finite model
   codecs/tickets в existing gateway/adapters. Существующий T permit protocol не обходить.
   Сюда же bounded local admission coordinator + narrow read-only T check. Один metadata
   control attempt, без второго gameplay engine/lease/очереди и без фона всех профилей.
4. **HTTP/factory wiring:** narrow existing AI routes; реальные principal recheck и
   завершение outer transaction, flags OFF, no network in constructors. После общего
   local gate отдельная согласованная rehearsal проверка без реальных provider calls.

Обязательные tests до включения:

- PG own-schema actual migration0050→0051; composite source guards, wrong-owner/game/
  revision/credential, terminal immutability, retained downgrade refusal/counter-only
  refusal. Two sessions same ID/same fingerprint дают один send, changed payload409.
- Fresh moderation/session logout, source replace/revoke/expiry между reserve/OAuth/send/
  complete; terminal replay без повторного clock/vault/network, чужой receipt404.
- Actual outer SQL transaction закрыта во время blocked fake HTTP: другой connection
  меняет Game/profile; late result rejected. Admin session recheck перед каждым commit.
- Общая T OAuth/control quota гонка30/5, включая разные worker IDs/игры одного local
  профиля. Admin probe2/day/stable profile через revision/credential rotation.
  Actual PG: BYOK probe1 → stage_or_activate_byok создаёт новый profile/credential/epoch
  → probe2 → ещё rotation → probe3 отказ; stage→start сохраняет bucket. Same request
  replay (включая после rotation) не добавляет daily debit/nonce/send; concurrent новые
  IDs после двух probes не проходят. Changed fingerprint того же ID конфликтует.
  No refunds, crash after sent→uncertain без autoresend; own result survives restart.
- Models1MiB/500/truncated, malformed/deep/duplicate JSON, HTTP redirects/returned URLs,
  private DNS/mixed DNS/SNI/CA, false local cloud-delegation, unsupported schema, invalid
  inventory cache scope/expiry. Никаких load/download endpoints или настоящих провайдеров.
- Four inference families на synthetic probe64; Giga OAuth+models/probe общий12s при
  wallclock rollback,401 без retry; secret/rawerror canaries не попадают в logs/DTO/PG.
- Manual arbitrary cloud ID сохраняется/активирует BYOK без probe; unsupported response
  даёт fallback. Anthropic2026 sampling всегда omitted; HF/OpenRouter routing immutable.
- Local anonymous external=false/master absent работает; local bearer требует vault;
  cloud external=false не отправляется. Worker/API/admin policy topology проверяется.
- Weekly scenario с fake UTC+monotonic: discover local, +10h, новый действительный job
  получает один fixed metadata GET и затем отдельный T inference permit; новая authority/
  grant/epoch не создаётся. Inventory недоступен/remote/unknown → authored, ни inference,
  ни pull/load/probe. Anonymous local без vault/external повторяет этот путь успешно.
- Два concurrent demands одного pinned local профиля: один metadata attempt/send,
  второй cache либо bounded busy/fallback, без дубликата. Повтор того же demand после
  unknown/lease expiry не создаёт новый nonce/GET; новый demand после cooldown может
  обновить inventory. Positive cache всех matching pins не требует GET; чужой owner,
  policy/credential/route и stale receipt не подходят. Static allowlist без negative
  remote evidence работает без metadata. First-shown authored rendering не изменяется.
- Worker source wrong purpose/probe/cloud/foreign profile, stale epoch/revision,
  revoked/departed/blocked starter, interrupted/terminal game отвергается на каждой
  фазе. Revocation во время metadata GET отбрасывает result; другие Game transactions
  проходят (нет SQL locks/context вокруг HTTP). Game quotas/slot не меняются от metadata;
  actual inference списывает их только своим T permit. Inventory+inference не удлиняют
  исходный source deadline; evidence expiry перед authorize запрещает send.
- Existing HTTP7 tests/27subtests и N/views regressions остаются зелёными; выбранная
  модель/профиль не меняются от default или inventory refresh без новой команды.

## 11. Решения для review и явные остатки

Технически выбраны: одна таблица; один models GET без pagination; no retry; daily
reserve и minute authorize quotas без refunds; server-config policy catalog; manual baseline; local evidence TTL5min;
human control execution в текущем authenticated процессе при общей endpoint topology;
models-only worker refresh действующего local binding по pending demand, stable daily
BYOK scope game+original starter, stable worker quota scope profile. Для staged subject
проверяется по immutable credential ownership до появления original starter control.
Sol нужно проверить прежде всего пригодность topology для будущей deployment factory,
source SQL guards и точный общий lock order с frozen T stage3. Это не вопросы владельцу
об уже разрешённых функциях; если topology требует RPC, выделить отдельный reviewed
срез, не маскировать его открытой сессией/непроверенным worker admin principal.

Источники inventory проверены по primary docs/Context7 2026-11-16, не настоящими
provider calls. Упомянутые API model IDs намеренно не зафиксированы: provider может
изменить alias/доступ/контракт. Принятый config hash фиксирует наши параметры, не веса
или поведение модели. Single probe не доказывает истинность свободной прозы.

**Отдельный следующий N/UI срез:** безопасная cause→job projection, ACL discovery
pending/cached rendering, exact source blocks рядом с прозой, first-write fallback и
catalog alias→fresh quote. Сегодня immutable events сами не получают job_id. Этот
draft не обещает автоматически появившуюся narration в UI и не включает episodes
export: только позднее sanitized owner-reviewed drafts по прежнему контракту.
