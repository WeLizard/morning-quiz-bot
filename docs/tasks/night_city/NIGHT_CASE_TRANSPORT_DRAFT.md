# Night Case T: durable dispatch и ограниченный outbound gateway

Статус: **принят к реализации после независимого Sol review, 2026-11-16**.
Проверенный draft SHA256: `33f4d4b0dc07b596e435239eca65401c725de3eab12948c5a340c0fa6326253e`.
Вердикт: ACCEPT, P1/P2 нет; body контракта после review не изменён.
Это план следующего среза, не свидетельство включённого AI.
Владение документа: архитектура T. Runtime/БД/rehearsal будут меняться только в
назначенных ниже границах с отдельными проверками.

## 1. Исходные границы и результат T

Источники: [AI_ACCESS](NIGHT_CASE_AI_ACCESS.md), прежде всего §4–6;
[ORCHESTRATION_PLAN](NIGHT_CASE_ORCHESTRATION_PLAN.md), прежде всего §6–7
(в текущем файле нет §12); `config/night_case_ai.py`,
`application/night_case_orchestrator.py`, `application/night_case_ai.py`,
`storage/night_ai_models.py`, `storage/night_ai_control.py`, `storage/night_cases.py`.

Сейчас живой intent transport запрещён проверкой exact `TestOnlyIntentTransport`.
Durable `NightAIIntentRequest` уже сохраняет prepare/token/choices/expiry120s и
terminal replay. `NightAIBinding.inflight_job_id` — FK только на render job.
`NightNarratorLimit` уже существует, но сам по себе не является permit.
`claim_render_jobs` сначала блокирует job; его нельзя вызывать перед новым общим
порядком Game→source. Старые jobs без immutable AI assignment остаются authored.

Результат T: один работающий путь reserve→authorize→network→finalize для существующего
prepared intent и для существующего assigned render job. Проверка через fake HTTP и
локальный TLS server, реальный PG. Director/новая генерация jobs, экраны управления,
discovery/probe orchestration и реальные платные вызовы не входят. Gateway может иметь
внутренние read-only model codecs, но без отдельного разрешённого control-plane вызова
их никто не вызывает. Authored игра/дедлайны не ждут AI. `Game.mode='night_case'`.

Runtime construction только через explicit reviewed dispatcher/gateway factory;
`NIGHT_NARRATOR_ENABLED=false` и `NIGHT_NARRATOR_EXTERNAL_ALLOWED=false` по умолчанию.
Первый флаг нужен также local; второй нужен cloud и Giga OAuth. Exact test-only
injection остаётся отдельным тестовым путём, env не может выбрать fake transport.
Нельзя снять прежний exact-TestOnly guard до готовности permit и acceptance gates.

Принятые решения сохраняются: старт сразу authored; admin approve влияет только на
новые jobs; BYOK без admin approval, только public и собственный private контекст
starter. При BYOK чужие private jobs остаются authored; второго admin binding
одновременно нет. Endpoint/key/profile IDs не выходят в model JSON или публичный DTO.
`store=false` не означает отсутствия provider observability.

## 2. Закрытые API и ответственность

Предлагаемые внутренние типы, не browser DTO:

```python
Source = IntentSource(intent_id: UUID) | RenderSource(job_id: str)  # str 1..96
reserve(source: Source, *, actor: VerifiedPrincipal | WorkerPrincipal,
        worker_id: str) -> ReservedPermit | Deferred | Authored
authorize_oauth(permit_id: UUID, lease_nonce: UUID) -> OAuthTicket | CachedTokenRef | Denied
authorize_inference(permit_id: UUID, lease_nonce: UUID) -> SendTicket | Denied
gateway.exchange(ticket: OAuthTicket | SendTicket) -> BoundedResponse | TransportFailure
complete(permit_id: UUID, lease_nonce: UUID, outcome) -> ExistingSafeResult | Applied | Discarded
expire_due(*, limit: int = 20) -> CleanupCounts
```

`Deferred` — только допустимый retry после сохранённой failed attempt1 с retry_after,
не новая попытка на каждый poll. Busy/quota/circuit/disabled первого reserve дают
terminal clarification/authored без ожидания освобождения слота. Existing active permit
при replay возвращает безопасный pending, никогда повторный SendTicket.

`reserve/authorize/complete/expire_due` — application methods с собственными короткими
tx; repository не commit-ит. Facade закрывает реальный HTTP principal context до
network await, затем заново аутентифицирует браузер при возврате/finalize. Worker не
подделывает пользовательскую сессию: отдельный trusted worker principal + live ACL
источника. `Source`/IDs от клиента никогда не заменяют ACL.

Ticket — неперсистентный frozen dataclass `repr=False` для credentials/body, с
permit ID/nonce, deadline, точной EndpointPolicy, transport-contract version,
фиксированными method/path, bounded headers/body. Выдаётся только trusted application;
gateway не принимает raw URL, arbitrary headers, ORM Session, callback на БД или
сырой `PreparedIntent`. Внутри процесса ticket одноразовый. Повторная выдача inference
ticket запрещена durable CAS. Python-тип не защищает от злонамеренного кода сервера:
граница доверия — проверенный dispatcher, не криптографическая capability в браузере.

Intent использует существующий exact response `{request_token,kind,selection_id}`,
whitelisted `choices[{selection_id,kind,label}]`; labels только `MenuChoice.label`.
Render использует existing narrative codec/token/refs/catalog. Source-specific
finalize остаётся единственным владельцем ordinary proposal / first-write rendering;
transport не применяет команды, AP, knowledge, эпизоды или игровые эффекты.

Точный orchestration seam: `prepare_intent` сохраняет prepared при configured T
dispatcher+fresh eligible binding+legal choices, затем commit; отдельный reserve не
растягивает исходный120s срок. Без dispatcher остаётся сегодняшняя finalized clarification.
`propose_intent` вызывает dispatcher по ID, не `gateway.exchange(PreparedIntent)`.
Prepared replay не создаёт attempt повторно; pending наблюдается/дозавершается через
existing source row. Старый complete helper используется внутри общей complete tx,
без вложенного commit/нового независимого обхода permit.

## 3. PG delta 0050: одна таблица попыток и общий binding slot

Предложенное имя migration `20261116_0050_night_ai_dispatch`, down_revision=0049.
Перед реализацией проверить фактический single head. 0045–0049 не переписывать.

`night_ai_dispatch_attempts` (одна строка = максимум один inference HTTP):

| Поле | Тип / ограничения |
| --- | --- |
| id | UUID PK |
| source_kind | text enum `intent,render` |
| intent_id / job_id | UUID FK / varchar(96) FK; XOR по source_kind |
| game_id, binding_id, epoch | varchar(64), UUID, int≥1; composite FK binding(id,game_id,epoch) RESTRICT |
| attempt_no | int 1..2; UNIQUE(intent_id,attempt_no) WHERE intent_id NOT NULL; аналогично job_id |
| config_hash, caps_hash, payload_hash | 64 lower hex; неизменяемые |
| contract_version | varchar(32), ровно `night-ai-transport/1` |
| source_expires_at | timestamptz; immutable deadline исходного prepare/job |
| worker_id, lease_nonce | varchar(96), UUID; immutable; worker_id не секрет и не fence сам по себе |
| reserved_at, lease_until | timestamptz; reserved_at < lease_until ≤ min(reserved_at+30s,source_expires_at) |
| network_deadline | timestamptz; immutable reserved_at+12s ≤ lease_until; source должен оставлять полные12s при reserve |
| status | `reserved,sending,succeeded,failed,cancelled,expired` |
| oauth_claimed_at, sent_at, finished_at | timestamptz nullable, только монотонное заполнение |
| reserved_input_units, reserved_output_tokens | bigint≥0 / int1..800 |
| quota_debits | JSONB≤4096 bytes: массив 4 closed `{scope,period_start,requests,tokens}`; scopes §5 |
| retry_after | timestamptz nullable, только terminal failed transient |
| error_code | nullable bounded enum §7, без provider body/exception |
| response_hash | nullable64hex, hash bounded response; без raw response |
| usage | null или closed `{input_tokens:int≥0,output_tokens:int≥0}`; bool/float запрещены |

Immutable все поля до status включительно, кроме status; pins/lease/debits нельзя
«обновить под новую модель». CHECK: source XOR; `reserved` требует sent_at=NULL,
`sending` требует sent_at NOT NULL; оба active требуют finished_at=NULL; terminal
требуют finished_at NOT NULL; succeeded требует sent_at/response_hash; timestamps
не раньше reserved_at. oauth_claimed_at может быть только у GigaChat, один раз.
Response hash/usage допустимы только terminal и не означают принятия игрового результата.

Дополнительные composite UNIQUE на parents:
intent `(id,game_id,binding_id,epoch)` и job assignment
`(job_id,game_id,binding_id,epoch)`. Соответствующие composite FK attempt связывают
**реальный** source той же игры/assignment, не просто существующий UUID.
У render FK ведёт к `night_ai_job_bindings`, оттуда к настоящему job. Trigger проверяет
same game самого job, assignment, status source, source deadline и pins при INSERT;
prepared intent с binding NULL и authored job не допускаются. Parent state может
позже стать terminal, исторический attempt при этом сохраняется.

Partial UNIQUE(binding_id) WHERE status IN ('reserved','sending') — общий слот обоих
видов. В binding добавить `inflight_permit_id UUID NULL`, composite FK
`(inflight_permit_id,id,game_id,epoch)`→attempt `(id,binding_id,game_id,epoch)` DEFERRABLE;
`inflight_lease_until` остаётся. Старый `inflight_job_id` оставить nullable deprecated,
CHECK требует его NULL; новая пара permit/lease либо оба NULL, либо оба nonnull.
Deferred trigger: pointer указывает active attempt с тем же lease_until, и любой active
attempt имеет этот pointer. Terminal cleanup очищает только собственный id+nonce.
Никакого intent→fake render job.

0050 preflight: если legacy inflight_job_id/lease заполнены, явно отказать до ALTER:
сначала штатно drain старый dispatcher (по принятому scope live T ещё не было).
Обновить существующие mutable-column triggers binding/job под новый slot, не отключать
immutable pins/control guards. Render source lease/attempts при резервировании отражают
тот же permit; T не использует старый independent `claim_render_jobs` как authority.
Все изменения source+attempt+slot+quota атомарны.

Transitions: reserved→sending→succeeded/failed/cancelled/expired;
reserved→failed/cancelled/expired тоже допустимы. Terminal→что-либо запрещено.
Указатель очищается только вместе с terminal transition. Сохраняются attempt1 и
attempt2; retry не возвращает старую строку в reserved.

Upgrade не трогает sealed kernels/receipts/shown text. Downgrade блокирует наличие
любых dispatch rows или ненулевых counters новых namespaces; никаких DELETE истории.
Metadata FK classification новых столбцов — history; merge не переписывает исходного
actor/recipient. Новые tables отсутствуют в generic serializers.

## 4. Tx ordering, авторизация и crash/revoke

Единый порядок: shared operation_fence → fresh principal/Account ACL → own source
terminal replay → `night_ai_config` advisory → Game/sealed/control → binding →
profile/revision/credential → source/assignment/attempt → budget rows по sorted scopes.
Не брать AI advisory после Game. Worker discovery читает bounded candidate IDs без
FOR UPDATE и без удержания tx; затем один candidate через этот порядок. Не держать
source lock во время ожидания Game. Existing operation receipts не используются
как semaphore. Никаких DNS/HTTP/OAuth/model calls под tx.

Reserve требует active unexpired current binding/epoch, enabled profile, usable
credential и starter, permitted egress, live source ACL, отсутствие rendering/terminal
intent, immutable pins/token/body hash и remaining TTL≥12s. Private recipient должен
оставаться допустимым получателем; departed/blocked/archived/merged identity не
получает новый private вызов. BYOK: credential owner ровно starter этого game;
private audience ровно owner, никаких combined/multi-recipient/private чужих людей.
Admin trusted binding тоже получает только whitelist audience, не sealed truth.
Исторический ACL replay не даёт нового dispatch права.

После reserve commit gateway может resolve DNS без secret. Перед выдачей любого
OAuth/inference ticket — новая authorize tx с тем же порядком и всеми fresh guards.
Ciphertext читается/расшифровывается только локально; vault — AEAD, не внешний сервис.
Secret не сохраняется в permit/result/log; ticket выдаётся после commit.
`authorize_inference`: CAS reserved→sending + sent_at, только прежний nonce, неизменный
network_deadline и остаётся≥1s; второй вызов не возвращает повторно credential/ticket.
Gateway заново проверяет истечение непосредственно перед socket write; authorization
не бессрочна. DNS pin относится к точной policy/host/port и этой попытке.

После network — новая complete tx; повторяет binding/epoch/flags/credential/source
guards. Intent дополнительно fresh actor/window/choices/resource validation существующей
orchestration, срок остаётся prepare+120s. Confirm только ordinary existing flow.
Render публикуется только если source/assignment live и rendering ещё отсутствует;
existing authored/AI победитель неизменяем. Late revoked/stale ответ отбрасывается.
Reader может первым сохранить authored; T не «улучшает» его задним числом.

Revoke linearization = committed control/config mutation. Reservation после неё
невозможна; authorize после неё запрещён, результат после неё не принимается.
Revoke/disable/close той же tx сначала terminal-cancel active attempt и очищает
его binding pointer, затем завершает binding. Это обязательно: existing0049 trigger
запрещает любые дальнейшие UPDATE terminal binding. Поздний complete не пытается
очистить уже terminal binding; только читает прежний outcome и отбрасывает ответ.
Уже выданный ticket может уйти одновременно с revoke: обещать отмену переданных данных
нельзя. Best-effort cancellation не заменяет проверку на complete. Profile disable,
binding change, Account moderation работают так же; destructive erase ключа не
«отзывает» bytes, которые уже были в памяти другого worker.

Crash до/после send различить достоверно нельзя. Просроченный attempt CAS→expired,
резерв сохраняется; source завершает authored/clarification. **В T нет автоматического
resend после worker crash/неизвестного исхода.** Новая попытка допустима только после
наблюдаемого transient ответа/timeout своего worker (§7), не из-за replay HTTP-клиента.
Lease не продлевается и не resurrect-ится. Максимум1 active durable permit/binding;
это не доказательство прекращения удалённого вычисления после потери процесса.

## 5. Квоты и breaker

Использовать existing `NightNarratorLimit`, без новой экономики. Atomic debit:
`nai:global:minute`=10/min; `nai:actor:<UUID>:minute`=4/min;
`game:<id>:day`=min(binding caps,60 requests/120000 units) UTC;
`game:<id>:total`=min(binding caps,420 requests/840000 units), period_start epoch.
Actor публичного render — starter; private — recipient; intent — requester.
Game scopes общие для intent/render и всех bindings: смена ключа не сбрасывает расход.
Period_start=floor UTC minute/day либо UTC epoch; read+insert conflict+lock в одном
порядке. Quota_debits содержит точные строки/числа, чтобы завершение не списало повторно.

Unit reserve = UTF-8 bytes всех serialized prompt strings + trusted template/format
overhead + output cap; conservative quota units, не обещание точной provider tokenization
или цены. Body budget проверяется до reserve. В T резерв не возвращается даже при
известном usage: проще честный жёсткий предел разрешённых попыток; usage только metadata.
Output cap=min(profile generation,grant max,800). Ни retry, ни OAuth401 не обходят caps.

Breaker row `nai:circuit:<profile UUID>:<revision>`, period_start epoch:
existing failures/circuit_open_until. 5 последовательных provider transport failures
по порядку committed completion → open5min; валидный успешно принятый provider envelope
reset0. После истечения5min обычный reserve снова допустим под прежними
global/actor/game caps.
Отдельного half-open semaphore/probe в T нет: circuit timestamp не заменяет permit.
Stale/revoked/source conflict не считается provider failure.
401/403/unsupported config помечают binding health auth_error/config_error; нужны
control-plane исправления, не бесконечный retry. Raw response/log не хранить.

OAuth quota отдельно existing limit scopes `nai:control:global:minute`30/min и
`nai:control:<owner subject>:minute`5/min. Для admin owner subject из profile; BYOK —
credential owner. Authorize OAuth атомарно проверяет caps, ставит oauth_claimed_at;
один OAuth exchange/permit, не circuit timestamp как разрешение на сетевой вызов.
Discovery/probe UI пока закрыты: для них нужен собственный reviewed control-ticket
путь, лимиты из AI_ACCESS сохраняются, но не подменяются игровым fake job.

## 6. Gateway: DNS/IP/TLS без самописного TLS

Выбор T: `httpcore==1.0.9` (уже pinned через httpx0.28.1) напрямую, объявить direct
dependency без добавления нового SDK. `AsyncConnectionPool(network_backend=...)`
с small policy backend, делегирующим настоящий TCP/TLS библиотечному `AnyIOBackend`.
API custom backends и `start_tls(server_hostname=...)` документированы:
[HTTP Core backends](https://www.encode.io/httpcore/network-backends/).
Pinned implementation сохраняет origin host для TLS даже при ином connect target:
[connection.py 1.0.9](https://github.com/encode/httpcore/blob/1.0.9/httpcore/_async/connection.py).

Пул на один exchange: max_connections1, keepalive0, http1=True, http2=False,
retries0, proxy=None, uds=None. Не httpx env proxy/SDK retries. URL **не переписывать**
на IP: origin/Host остаются исходными; backend получает ожидаемый host/port, проверяет
их и передаёт delegate только canonical numeric selected IP. TLS выполняет обычный
stream.start_tls с исходным hostname. Никаких private monkeypatch глобального DNS,
ручного TLS handshake или verify=False. AnyIO literal IP path не требует нового DNS:
[pinned sockets implementation](https://github.com/agronholm/anyio/blob/4.14.2/src/anyio/_core/_sockets.py).

Operator registry, отдельно от ProfileRegistry: `(policy_id,version)`→exact origin,
base path, network_class, allowed CIDRs для local, CA reference→trusted SSLContext.
Данные инжектируются worker при старте; browser/admin profile может выбрать только
зарегистрированную policy, не расширить CIDRs/ports/CA. Отозванная policy fail closed.
Cloud presets используют только фиксированные origins; OAuth Giga — отдельная policy
для https:9443. generic/local доступны только admin, не BYOK.

Перед **каждым** новым соединением resolve A/AAAA AF_UNSPEC/SOCK_STREAM, максимум32
уникальных адреса, timeout≤3s в общем deadline. Пустой/слишком большой/mixed safe+unsafe
набор запрещается целиком. Cloud: каждый адрес public global unicast; дополнительно
запрет mapped IPv4, 6to4/Teredo/NAT64 transitional ranges, link-local, reserved,
multicast/unspecified/metadata. Не полагаться на один is_private: Python3.11/3.13
должны пройти одинаковую explicit deny matrix. Local: только exact allowlisted
host+port и каждый адрес в точном операторском CIDR; multicast/unspecified/link-local
и metadata запрещены также local. Никакого «весь RFC1918 разрешён» по умолчанию.

Canonical ASCII hostname; Unicode/admin host требует заранее нормализованной IDNA
operator policy, trailing dot/zone IDs/decimal-octal IPv4/encoded host/path отклоняются.
Среди всех разрешённых адресов выбирается один детерминированно; один connect на attempt,
без hidden address failover. В socket backend сверяется peer numeric address, если
библиотека предоставляет его; DNS validation→connect не делает повторного hostname
resolve. Тест должен доказать это, не просто mock `httpx.get`.

SSLContext: CERT_REQUIRED + check_hostname=True, platform/explicit trusted CA bundle,
без user CA path. Giga доверенный CA задаёт оператор; отсутствие CA — безопасная ошибка.
HTTP разрешён только explicit trusted_local. Никаких redirects (любой3xx error),
URL из response, proxy env, CONNECT/Upgrade/WebSocket, user-defined headers/cookies.
`Accept-Encoding: identity`; неожиданный Content-Encoding отклоняется без decompression.

Единый wall deadline12s включает DNS/TCP/TLS/OAuth/inference/body; connect≤3s,
write≤3s, read inactivity≤5s, плюс outer cancellation по monotonic deadline.
Отсчёт от reserved_at; network_deadline не сдвигается после OAuth/lock wait и повторного
authorize. Gateway преобразует оставшийся UTC интервал в monotonic budget один раз
и не увеличивает его при коррекции часов. Уже истёкший deadline не допускает send.
OAuth и inference не получают по12s каждый. Закрытие stream/pool гарантировано finally.
Request body≤64KiB, response raw body≤256KiB; OAuth body≤16KiB; decoded model text≤
16000 UTF-8 bytes и4000chars. Strict JSON: duplicate keys, NaN, invalid UTF-8,
trailing data, чрезмерная nesting depth>16 запрещены. Content-Length checked, но
chunked/small-read тоже считаются. Нет raw response в exception.
HTTP/1 parser h11 из pinned httpcore ограничивает incomplete event100KiB; после
headers дополнительный предел128 fields/32KiB. Это **не** обещание peak allocation32KiB:
library может прочитать chunk64KiB до application check. Oversize всегда отказ.

## 7. Четыре family adapters и bounded retry

Использовать фактические enum кода: `openai_chat`, `openai_responses`,
`anthropic_messages`, `gigachat_chat`. Суффиксы /1 в AI_ACCESS — описательная версия,
не мигрировать уже pinned profile config. Новое поле permit contract_version фиксирует
семантику wire codec. generic_openai сейчас разрешает только chat; Responses для него
не включать молча вопреки коду. Capabilities нельзя выводить из названия модели.

| Family | Exact минимальный request / response |
| --- | --- |
| openai_chat | POST base+/chat/completions; model, system/user messages только text, stream=false,n=1, разрешённое limit field, optional supported temperature/JSON format. Ровно одна choice, строка message.content, без tool_calls/refusal, finish_reason=stop. Usage prompt_tokens/completion_tokens иначе null. |
| openai_responses | POST base+/responses; model,instructions,input text,stream=false,store=false,output limit; без background/tools/previous_response_id. Только status=completed, message/output_text blocks; reasoning не выводится, tool/refusal/incomplete → failure. Usage input_tokens/output_tokens. |
| anthropic_messages | POST base+/v1/messages; system отдельно, user text,max_tokens,stream=false, pinned version header и workspace из profile; auth mode Bearer либо x-api-key как явно pin-нуто. Text blocks, stop_reason=end_turn, tool/refusal/thinking в разрешённый result не превращаются. Usage input_tokens/output_tokens. |
| gigachat_chat | POST base+/chat/completions, native model/messages/stream=false/max_tokens; Bearer access_token, choices text, completed normal finish. Никаких attachments/functions. OAuth flow ниже. |

Точные response wrappers могут иметь дополнительные provider metadata, но только
whitelisted поля становятся `BoundedResponse(text,usage,request_id?)`. Request ID
≤128 printable bytes только private diagnostics (в T можно вовсе не сохранять).
Игровой JSON result внутри text проходит отдельный existing exact codec.

Preset mapping сохраняет config registry: OpenAI organization/project headers;
Anthropic anthropic-version/workspace; Yandex OpenAI-Project=folder_id,
x-data-logging-enabled=false и model URI того же folder; OpenRouter provider.only=[pin],
allow_fallbacks=false без auto/model fallbacks; HF model:provider без :auto.
Остальные Chat presets используют свой fixed base/auth. Unsupported field/route
не удалять ради повторного запроса: config_error/fallback. Протокольная совместимость
не доказывает качество модели; unverified capabilities остаются честно unverified.

Giga OAuth: фиксированный POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth,
Basic authorization_key, RqUID=new UUID, form scope из closed registry enum;
expires_at — integer epoch milliseconds, future и≤now+31min, token bounded16KiB.
Memory cache `(credential_id,config_hash,scope)` с expiry margin60s, без PG/token logs;
cache никогда не заменяет live credential checks. После inference401 инвалидировать
cache; допускается **новый attempt_no2** с одним OAuth refresh и новым quota reserve.
Не внутренний невидимый retry внутри adapter. OAuth401/403 сразу auth_error.
Документы: [Giga token](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token),
[Giga chat](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat).

Outcome error enum: `disabled,stale,expired,acl_denied,quota_exhausted,binding_busy,
circuit_open,credential_unavailable,endpoint_denied,dns_failed,tls_failed,timeout,
network_error,rate_limited,provider_error,auth_error,config_error,oversize,
invalid_response,source_closed`. Ни body, ни credential, ни endpoint не входят в
публичный code. Intent fallback — существующий clarification; render — authored text.

Retry только attempt1→2 того же source/binding/profile/config/model/route. Причины:
observed timeout/network_error/429/5xx, либо описанный Giga token401. Минимум pause1s;
Retry-After только integer seconds, clamp1..30; без header pause2s. Если source TTL
не оставляет pause+12s — fallback. Reserve новой попытки вновь проходит ACL/квоты.
Нет SDK retries, перескока на другую модель или запроса «исправь JSON».
Provider мог обработать timeout-запрос: две оплаты допустимы; remote exactly-once
не обещается. До live enable UI/оператор видит этот факт. Собственный source result
и расход игровых AP остаются идемпотентными.

## 8. Проверки и предлагаемые ownership-срезы

Это границы для review, не разрешение параллельно менять все перечисленные файлы.

1. Storage: `storage/night_ai_dispatch.py`, модель attempt в owning AI models,
   0050 + узкие trigger updates; тесты migration/retained rows/slot/counters на PG.
2. Gateway/codecs: `infrastructure/night_ai_gateway.py`,
   `infrastructure/night_ai_adapters.py`; injected resolver/backend/clock, no DB.
   requirements: direct httpcore pin существующей версии, без нового SDK.
3. Application: `application/night_case_dispatch.py`, узкий seam orchestrator
   reserve/finalize, control revoke/cleanup CAS, render source path. A command API,
   rules/domain, admin AI и legacy OpenRouter клиент не переписывать.
4. Tests: pure provider fixtures + local TLS/DNS sockets + PG races + real facade
   principal tx lifecycle; затем независимое review. Live flags остаются false до
   отдельной завершённой интеграции. UI/discovery/director — следующий ограниченный срез.

Обязательные доказательства:

- 0049→0050 retained states/receipts unchanged, один head; bad XOR/cross-game FK,
  fake job, mutable pins/terminal row/nonce отказаны; downgrade не стирает permits.
- Два workers и intent×render одного binding: один slot/debit; разные games не
  конфликтуют по domain actor_seq; reserve replay не платит снова. Crash перед/после
  send, expiry cleanup×late complete не освобождают чужой новый slot.
- Revoke/profile disable/moderation/merge/epoch replacement до reserve, до authorize,
  во время HTTP и до complete; показанный authored никогда не заменяется. BYOK чужие
  private canaries отсутствуют в serialized body даже при проваленном результате.
- Во время blocked fake HTTP второй PG connection выполняет Game/control operation:
  никаких outer transaction/lock/connection, оставленных HTTP dependency. Проверить
  actual route principal lifecycle, не только название функции orchestrator.
- DNS mixed records/rebinding/public→metadata; IPv4 mapped/6to4/NAT64/zone/odd host;
  arbitrary admin URL без operator policy; env proxies; 3xx; TLS wrong-name/untrusted;
  локальный TLS server подтверждает **numeric connect + original SNI/Host/cert check**.
  No credential на неправильный IP. Тесты одинаковы на runtime Python3.11 и pinned3.13.
- Giga first OAuth/cache/401 refresh/restart/expired grant/cap; Basic не попадает на
  inference endpoint. Все families: exact request fields/headers, bad finish/JSON,
  401/429/5xx, compressed/oversize/chunked/slow trickle/cancel. Никаких платных calls.
- Day/minute boundaries/total после rebind; attempt2 отдельно списывается; breaker
  concurrency/expiry; ни source conflict, ни stale response не портят provider health.
- Intent получает ordinary proposal с original120s deadline, confirm через step
  тратит AP ровно один раз. Render assignment absent→authored, response first-write
  race→один immutable text. Полная история/episode review ACL не обходятся.

## 9. Источники, reuse и оставшиеся решения review

`modules/admin_ai.py` уже показывает text-only HTTPX streaming, no proxy/redirect,
bounded body и safe errors, но не имеет IP pinning, игровых ACL/permits/quotas.
`modules/openrouter_client.py` использует общий env key, fixed модель и SDK defaults.
Их clients/keys не переиспользуем; переносим только проверенный шаблон ограниченного
чтения/санитизации. Gateway использует готовые TCP/TLS библиотеки, policy-код наш.

Дополнительные официальные первоисточники, проверенные 2026-11-16:
[HTTP Core extensions](https://www.encode.io/httpcore/extensions/),
[HTTP/1 bounds](https://github.com/encode/httpcore/blob/1.0.9/httpcore/_async/http11.py),
[Responses](https://developers.openai.com/api/reference/resources/responses/methods/create),
[Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create),
[OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection).
Context7 `/encode/httpcore` использован для public backend API; version-specific
вывод сверён с tagged1.0.9 source, а не только latest docs.

Технические решения для независимого review: достаточно ли одного attempt table с
legacy slot preflight; устраивает ли conservative no-refund quota; достаточно ли отказа на mixed
DNS/одного IP без availability failover. Это trade-offs T, не новые обещания владельца.
Продуктового вопроса владельцу проекта для этого draft нет. Остаточные ограничения: provider
observability, неотменяемый already-sent request, неизвестная удалённая оплата,
качество свободной прозы. Ни gateway, ни валидатор не доказывают истинность prose.
