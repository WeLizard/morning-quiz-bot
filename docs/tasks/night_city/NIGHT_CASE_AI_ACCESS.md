# Night Case: доступ к моделям и ключам ведущего

Дата: 2026-11-16. **Принятый контракт для реализации; live-поддержка провайдеров ещё не подтверждена.**

Это дополнение к [application contract](NIGHT_CASE_APPLICATION_CONTRACT.md), прежде всего §9;
старый документ и migration `20261115_0045` здесь не изменяются. После принятия этого
дополнения одиночные `NIGHT_NARRATOR_PROVIDER/MODEL/API_KEY` заменяются binding resolver.
Запрет plaintext-ключей в PG сохраняется; допускается описанный ниже ciphertext.
Rules/kernel, `Game.mode='night_case'`, Account/Room/Game, ACL истории, immutable renderings
и авторские fallback остаются прежними. [Runtime](../NIGHT_CITY_RUNTIME_CONTRACT.md) и
[интеграционные факты](NIGHT_CASE_INTEGRATION_FACTS.md) задают границы приложения.

## 1. Принятый продуктовый смысл

Владелец явно выбрал два пути. При обычном старте игра **сразу работает на authored
fallback**, а администратор получает запрос на AI. Его approve включает выбранный
им профиль только для этой партии. Deny/ожидание/неисправность не останавливают игру.
Альтернатива — запускающий вводит свой ключ: этот ключ подключается к ведущему
**этой партии сразу, без admin approval**. Другие игроки его не видят и не используют.

Администратор выбирает доступные модели и подключения, включая локальные. Telegram
не владеет партией: запрос есть в in-app админке даже без чата/бота. Telegram-доставка
может быть подключена адаптером; эта работа не разрешает реальную рассылку или рабочий
bot token. Монетизация, подписки, кошелёк, загрузчик моделей, AI для других игр и общий
конструктор подключений вне scope.

Далее сроки/лимиты/форматы — технические решения первого среза, а не дополнительные
ответы владельца. Настройка профиля не гарантирует доступность любой модели, региона
или тарифа. Наличие provider preset означает проверенный адаптер и fake tests;
live connection имеет отдельный наблюдаемый результат с датой.

## 2. Четыре семейства транспорта и конечные presets

`adapter` — закрытый enum: `openai_chat/1`, `openai_responses/1`,
`anthropic_messages/1`, `gigachat/1`. Preset фиксирует API origin/base path,
разрешённые auth/project поля, методы discovery и безопасные опции. Это не возможность
передавать произвольные headers/body/URL из UI. SDK на каждую марку не требуется.

- Chat: текстовые `messages`, одна completion, без streaming/tools/images/audio;
  извлечение только `choices[0].message.content`. Отсутствие ожидаемой строки — error.
- Responses: текстовые input/instructions, `store=false`, без previous_response_id,
  background/tools; извлечение только завершённых output_text message blocks.
- Anthropic: native Messages, отдельный system, обязательный max_tokens;
  объединяются text blocks, tool/thinking blocks не выдаются игроку.
- GigaChat: OAuth плюс native chat contract. OAuth credential не подставляется как
  inference bearer. Token refresh и body/usage extraction — часть этого адаптера.

Общий выход — `{text, usage:{input_tokens,output_tokens}|null, provider_request_id|null}`;
request ID только в закрытой диагностике. Проверка игрового результата — прежний Task2
codec с exact token/kind/refs/expiry. JSON output schema включается только при известной
capability модели; иначе JSON в plain text и та же строгая проверка. Нельзя незаметно
перейти на другую модель или снять validator после ошибки.

Каталог ниже проверен по официальным страницам 2026-11-15. Идентификаторы моделей
намеренно не зашиты: discovery/manual ID → явный выбор → immutable profile revision.
В таблице `key` — отдельный secret API key; `B` — Bearer auth. Для BYOK доступны только
cloud presets, не `generic`/local. Строки catalog version/adapter version pin-ятся.

| preset | Семейство / base URL | Credentials и дополнительные поля | Первичный источник |
| --- | --- | --- | --- |
| openai | Responses по умолчанию, Chat — явная capability; `https://api.openai.com/v1` | key/B; optional organization_id/project_id → одноимённые OpenAI headers | [API overview](https://developers.openai.com/api/reference/overview) |
| anthropic | Messages; `https://api.anthropic.com` | key/B; pinned anthropic-version; workspace_id обязателен для ключа без workspace scope. Legacy x-api-key — отдельный auth mode preset, не произвольный header | [Overview/auth](https://platform.claude.com/docs/en/api/overview) |
| gemini | Chat; `https://generativelanguage.googleapis.com/v1beta/openai` | Gemini API key/B; без service-account JSON, Vertex ADC и project impersonation | [Official compatibility](https://aistudio.google.com/docs/openai) |
| openrouter | Chat; `https://openrouter.ai/api/v1` | key/B; route/provider policy pin-ится, automatic provider/model fallback выключен | [API](https://openrouter.ai/docs/api_reference/overview) |
| deepseek | Chat; `https://api.deepseek.com` | key/B | [API](https://api-docs.deepseek.com/) |
| xai | Responses; `https://api.x.ai/v1` | key/B; store=false, без встроенных search/tools | [Quickstart](https://docs.x.ai/developers/quickstart), [Responses](https://docs.x.ai/developers/rest-api-reference/inference/responses) |
| mistral | Chat; `https://api.mistral.ai/v1` | key/B | [API](https://docs.mistral.ai/api) |
| groq | Chat; `https://api.groq.com/openai/v1` | key/B; не посылать unsupported logprobs/logit_bias/name; n=1 | [Compatibility](https://console.groq.com/docs/openai) |
| together | Chat; `https://api.together.ai/v1` | key/B | [Compatibility](https://docs.together.ai/docs/inference/openai-compatibility) |
| fireworks | Chat; `https://api.fireworks.ai/inference/v1` | key/B; полный provider model ID, account/deployment часть ID при необходимости | [Compatibility](https://docs.fireworks.ai/tools-sdks/openai-compatibility) |
| huggingface | Chat; `https://router.huggingface.co/v1` | User Access Token/B с Inference Providers permission; model:provider pin, не auto-route | [Chat API](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion) |
| yandex | Chat; `https://ai.api.cloud.yandex.net/v1` | API key/B для этого compatibility endpoint; обязательный folder_id → OpenAI-Project, model URI из этого каталога; x-data-logging-enabled=false | [Базовый запрос](https://aistudio.yandex.ru/ru/docs/ai-studio/operations/generation/completions-basic), [модели](https://aistudio.yandex.ru/ru/docs/ai-studio/operations/models/get), [logging](https://aistudio.yandex.ru/ru/docs/ai-studio/operations/disable-logging) |
| gigachat | GigaChat; `https://api.giga.chat/v1` | secret authorization_key (выданная console Base64 пара client_id:secret); scope=PERS/B2B/CORP, см. ниже; доверенный CA preset | [SDK/API](https://developers.sber.ru/docs/ru/gigachat/guides/using-sdks), [REST](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api) |
| ollama | Chat; admin URL, обычно `http://localhost:11434/v1` | none для обычного local server; Bearer только если явно настроен защищающий gateway | [Compatibility](https://docs.ollama.com/api/openai-compatibility) |
| lmstudio | Chat; admin URL, обычно `http://localhost:1234/v1` | none либо отдельный server API token/B | [Compatibility](https://lmstudio.ai/docs/developer/openai-compat), [REST](https://lmstudio.ai/docs/developer/rest) |
| vllm | Chat; admin URL | none либо server API key/B | [Online serving](https://docs.vllm.ai/en/latest/serving/online_serving/) |
| llama_cpp | Chat; admin URL | none либо server API key/B | [Server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) |
| generic_openai | Chat **или** Responses, выбор до probe; admin allowlisted URL | none либо key/B; никаких custom auth scripts/headers | Совместимость подтверждается probe именно этой ревизии; неизвестные варианты fail closed |

Yandex: выбран новый documented compatibility endpoint. Старый native SDK использует
другой endpoint/auth (`Api-Key`); это не основание смешивать их. IAM/OAuth Yandex,
AWS Bedrock, Vertex и Azure deployment auth в первый каталог не входят.

GigaChat: OAuth POST `https://ngw.devices.sberbank.ru:9443/api/v2/oauth`, Basic
authorization_key, новый RqUID UUID на попытку, form scope ровно
`GIGACHAT_API_PERS|GIGACHAT_API_B2B|GIGACHAT_API_CORP`; inference — Bearer access_token.
Adapter валидирует документированный `expires_at`, refresh с запасом 60s, максимум
один refresh+повтор после 401. Token cache только в памяти worker, по credential ID,
без raw auth в exception; после рестарта новый token. TLS verification обязательна,
оператор устанавливает доверенный CA bundle на worker, **никогда verify=False**.
Scope/account tier выбирается владельцем ключа; чужой scope не перебирается автоматически.

GET models выполняется adapter-specific read-only методом (обычно `/models` относительно
base, Anthropic `/v1/models`). Ollama дополнительно может читать `/api/tags`; LM Studio
native inventory только по поддержанному read-only endpoint. UI различает
`server-advertised`, `installed`, `loaded`: `/v1/models` не доказывает наличие всех весов.
Никаких pull/download/load/delete моделей. Ollama cloud-delegated models не считаются
local: local preset допускает только подтверждённые локальные модели. Обычная inference
может активировать уже установленную модель средствами сервера; это показывается админу.
Для server-advertised vLLM/llama.cpp достаточно уже обслуживаемого model ID.

Discovery ограничен 500 записями/1 MiB/12s, ID 1..256 UTF-8 bytes, plain text;
pagination/cursor обрабатывается preset, полученные URL не посещаются. Если list API
недоступен, manual model ID + отдельный probe; состояние `unverified` честно сохраняется.
Модель не выбирается автоматически по первому элементу списка. Полный список не обещает
chat/JSON поддержку; probe проверяет выбранный bounded text contract, не качество истории.

## 3. Профиль, binding и разрешение

`ProfileRevision/1` — immutable закрытый документ:

```text
{preset, preset_version:1, adapter, model_id,
 endpoint:{policy_id,policy_version,base_url,network_class,ca_ref:null|string},
 auth_mode, project_fields, api_version:null|string,
 capabilities:{json_output:"prompt"|"json_object"|"json_schema", output_limit_field:string},
 generation:{temperature:null|number, max_output_tokens:int},
 routing:null|PresetRouting, credential_id:null|UUID, config_hash:SHA256}
```

`project_fields` — закрытая форма соответствующего preset из §2, остальные `{}`;
output_limit_field (`max_tokens|max_completion_tokens|max_output_tokens`),
auth_mode/routing/API version разрешены только preset registry,
не произвольные strings во внешнем DTO. max_output_tokens=800, диапазон1..800;
temperature по умолчанию null (не отправлять), при поддержке0..1. Endpoint policy
immutable snapshot, содержит нормализованный base URL, network class и trusted CA reference.
Policy ID/version сверяется с server registry, а текущее ужесточение operator allowlist
может запретить старый endpoint, но не переписать его. Для Anthropic первая registry
revision pin-ит документированную API version `2026-10-21`; смена — новая revision.
Нет metadata keys от клиента. Hash — canonical JSON без config_hash; секрет не входит,
входит непрозрачный credential ID. Старый profile не редактируется; новая ревизия+CAS
current_revision. Модельные aliases у провайдера могут менять веса: pin гарантирует
нашу конфигурацию, не воспроизводимость генерации. Истина replay — сохранённый текст.

Для admin mode binding ссылается на profile revision, выбранную **при approve**.
Для BYOK создаётся game-scoped immutable revision той же формы, server builds preset
endpoint/options; нельзя сослаться на admin credential/profile. Такой профиль не
появляется в общем каталоге и не переиспользуется другой партией.

`GameAIControl` хранит monotonic epoch, immutable starter Account (зафиксирован успешным
start), current_binding_id|null. Approval request привязан к game_id+epoch+requester,
не ко всей Room/Telegram группе и не ко всем будущим стартам.

| Объект | Закрытые состояния и переходы |
| --- | --- |
| ApprovalRequest | pending → approved / denied / expired / cancelled; terminal неизменяем. Pending TTL24h. Approve привязывает одну profile revision и один binding; denied без свободного текста провайдера. |
| Binding | active → revoked / superseded / expired / closed; обратно нельзя. TTL30 суток от создания или до конца игры, что раньше. Для продления новый epoch и новое явное подключение. |
| Credential | staged / usable / revoked / erased; staged BYOK TTL1h; usable game key действует только в своём binding/lobby, окончание/revoke → erase ciphertext. Admin credential reusable только admin profiles. |
| Effective status (вычисляемый) | authored / pending_approval / ai_admin / ai_byok / fallback_unavailable. Это UI view, не ещё одна state machine в PG. |

Control создаётся вместе с lobby: epoch=0, starter=null. Start defaults to admin_request
(либо явно authored/BYOK). Commit игрового старта фиксирует starter и создаёт pending
request+уведомление в новой epoch; не вызывает HTTP. При выборе staged BYOK
той же учётной записи/lobby commit сразу создаёт active binding, pending не создаётся.
Ключ можно подключить после старта: только starter, usable Account и действующее
участие. Lobby staging доступен тому, кто имеет право start; если стартовал другой
Account, чужой staged key использовать нельзя. Staging не разрешает inference до start.

Каждое новое переключение `request_admin|activate_byok|use_authored|admin_rebind`
увеличивает epoch под row lock, supersedes прежний binding и cancels pending request.
Переход на admin с BYOK сразу включает fallback до approve; не продолжается старое
списание. Deny/expire/revoke не возвращают предыдущий ключ/модель. Повторный запрос
после отказа — новый client_request_id, не revival; cooldown5min, максимум3 новых
requests/game/UTC-day, стартовый считается. Retry с тем же ID не создаёт уведомлений.

Approve проверяет pending, тот же current epoch, now<expires_at, running game,
usable requester и profile/credential. Его grant фиксирует game, epoch, profile hash,
credential, deadline и квоты. Admin вправе выбрать свой профиль и лимиты ниже platform
caps. Смена default profile не меняет pending requests (они не выбирали профиль) или
active bindings. Изменение активной модели — явный admin_rebind с новой ревизией;
в mode BYOK администратор может revoke, но не заменить его своим профилем без нового
запроса starter. Одобрение старого pending после BYOK даёт request_stale, не отбирает ключ.

Revocation профиля/credential проверяется при каждом dispatch, поэтому отзывает все
связанные grants немедленно для новых запросов. Re-enable профиль не оживляет старые
bindings: нужны новые grants. Ошибка auth/config помечает binding unavailable до
явной замены/успешного probe; transient outage использует breaker, затем новые jobs
снова могут идти в той же активной привязке. Уже сохранённый fallback не перегенерируется.

## 4. Ключи, ACL и сеть

**Provider account — отдельная граница доверия.** Его владелец может включить
observability и читать prompts/completions: это прямо поддержано, например,
[OpenRouter Input & Output Logging](https://openrouter.ai/docs/guides/features/input-output-logging).
`store=false` регулирует конкретное API storage, а не все журналы/права владельца;
[OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data) отдельно
описывают application state и abuse monitoring. Нет универсальной гарантии zero logs.

Поэтому BYOK разрешён только если audience=`public` **или ровно один account:owner**
и весь context разрешён этому owner. Чужой private NPC reply/digest/intent запрещён
ещё ДО reservation/дешифрования/transport; multiparty private context тоже не допускается.
Такие jobs получают null binding+`byok_audience_denied` и authored fallback. Проверка
повторяется на dispatch, не полагается на корректность director. В этом первом срезе
не поддерживаются одновременно admin и BYOK bindings: чужие private jobs при BYOK
остаются authored. Для admin-only режима все разрешённые jobs обслуживает отдельно
одобренный trusted operator profile. Administrator provider account — доверенная
операторская инфраструктура, не способ игроку-спонсору получить роль оператора.

Правило распространяется и на отдельный intent parsing path: own actor only для BYOK,
immutable binding snapshot и повторная проверка перед принятием proposal. Внешняя
модель никогда не получает общую case truth. UI владельцу ключа явно объясняет:
«AI для общих сцен и твоих личных сцен; чужие личные сцены ведутся по авторскому тексту».
Это техническое сохранение уже принятой приватности, не новый approval для собственного ключа.

Секреты admin narrator отделены от admin_ai. Ни чтение старого admin_ai ключа, ни
`confirmed_external` не дают разрешение на игру. `NIGHT_NARRATOR_ENABLED` — общий
kill switch, `NIGHT_NARRATOR_EXTERNAL_ALLOWED` — разрешение cloud egress;
локальные allowlisted endpoints могут работать без external flag. BYOK не требует
approve, но не обходит выключенный сервис, запрет egress, блокировку Account и лимиты;
форма сообщает конкретную причину fallback до подтверждения. Flags default false.

Secret form — TLS POST, password input без автозаполнения/analytics/session replay,
не URL/query/localStorage/sessionStorage/HTML attributes. Request body этой группы
маршрутов не логируется. Допустимый secret 1..8192 bytes, без CR/LF/NUL; opaque bytes
не обрезаются silently. GET возвращает только `credential_configured:true|false`,
mask=`********` или null. Нет endpoint export/decrypt, даже в admin UI. Keys не входят
в kernel, jobs, context, outbox, public Game.state, errors, traces, metrics labels.
Auth header формируется в worker вне provider JSON. OAuth token response тоже secret.

PG хранит AES-256-GCM ciphertext+tag, случайный 96-bit nonce, key_id и AAD version.
Master key 32 random bytes — отдельный `NIGHT_AI_MASTER_KEYS` secretstore/env keyring,
active key ID отдельно; не БД, не Git, не frontend config и не обычный backup bundle.
AAD — canonical UTF-8 JSON `["night-ai-secret/1",environment_id,credential_id,
scope,owner_subject,game_id_or_null,preset]`. Уникальность `(key_id,nonce)` enforced;
новый nonce при каждом encrypt/rewrap. Используется готовый AEAD primitive, не своя
криптография ([официальная документация](https://cryptography.io/en/latest/hazmat/primitives/aead/)).
Ротация master key переупаковывает ciphertext, не меняет смысл credential/profile;
смена provider key всегда новый credential ID/revision. Старые key IDs удерживаются
до завершения проверенного restore/rotation; потеря master key → AI fallback, игра жива.

Key-bearing idempotency fingerprint — HMAC-SHA256 canonical validated request, отдельный
стабильный `NIGHT_AI_RECEIPT_HMAC_KEY` из secretstore (не raw SHA секретного ввода).
Остальные requests SHA256. В receipt хранится только digest, never body. HMAC rotation
требует versioned retained verification key для retained receipts; не перезаписывать
ключ при каждом deploy. Plaintext доступен коротко trusted application/worker в памяти;
не обещаем защиту от администратора ОС, memory dumps или скомпрометированного worker.

Окончание/stop/interrupted игры, уход/блокировка starter немедленно делают binding
непригодным через обязательную live lifecycle/Account проверку; игра не ждёт AI cleanup.
В своей обычной tx они ставят deduplicated cleanup pointer на имеющийся binding (§5),
не берут AI locks в обратном порядке. Cleanup worker в порядке §6 закрывает binding
и erase game ciphertext; дополнительно проверяет eligible rows каждые60s и после restart,
включая staged credentials без binding. Недоступный worker может задержать erase, но не
разрешить новые dispatch. Use_authored/revoke в AI service erase в своей tx сразу.
Staged TTL1h/истёкшие grants также неиспользуемы независимо от задержки cleanup.
Interrupted не autoresume.
Terminal narration может быть authored: финал не ждёт последней платной генерации.
История/renderings не удаляются. В backup остаётся **зашифрованная** прежняя версия
до срока retention; purge live DB не обещает уничтожить старые backups. Restore в
rehearsal не активирует восстановленные credentials/grants автоматически: egress off,
восстановление требует явного решения по grants. Master-key backup хранится отдельно.

Usable Account/ACL проверяются под shared operation_fence **до** receipt lookup;
merge policy приложения сохраняется, active/interrupted participation блокирует merge.
Доказанная historical merge ancestry позволяет читать разрешённые прежние receipts,
но не воскресить erased key. AdminPrincipal — существующая admin session identity,
не Account/Telegram ID, выдуманный из строки. Текущая админка имеет общего оператора,
не per-Account RBAC: trusted adapter назначает stable subject
`admin:<deployment_id>:operator`, одинаковый для его сессий, не session token/CSRF.
Account subject=`account:<uuid>`. Это audit scope, не новая система авторизации.
Admin session+CSRF защищает управление;
owner game != site admin. Admin может менять собственные narrator profiles, approve,
deny/revoke и видеть диагностические метаданные; чужой BYOK не раскрывается.

Endpoint policy для cloud — только фиксированные HTTPS origins/paths из registry,
без user URL. Generic/local URL может добавить только admin, в пределах **операторского**
allowlist host+port+network ranges, который UI не расширяет. localhost означает worker
host/container, не компьютер игрока. HTTP допустим только явно разрешённому local
loopback/выделенному trusted LAN endpoint; cloud всегда TLS. GigaChat OAuth: отдельное
фиксированное разрешение HTTPS:9443. CA reference выбирается из server registry;
пользователь не передаёт CA path/certificate/verify flag.

Normalize URL один раз, reject userinfo/query/fragment, non-http(s), ambiguous encoded
path/host/IP и headers injection. Redirects выключены для discovery/probe/inference/OAuth.
Не доверять env proxies (`trust_env=false`). До каждого нового соединения resolve все
A/AAAA, validate все адреса, pin connect address с исходными Host/SNI и cert validation;
это исключает повторный бесконтрольный DNS resolve между check/connect. Cloud запрещает
loopback/private/link-local/metadata/multicast/unspecified/reserved и IPv4-mapped обходы.
Local разрешает только точные configured ranges/ports, не весь RFC1918. Переадресация
через DNS, провайдерский response URL или OpenAI baseURL из user prompt невозможна.
Если выбранная HTTP library не обеспечивает это, adapter не включается до решения,
а не объявляется SSRF-safe после строковой проверки URL.

## 5. PG delta после 0048

AI migration — `20261116_0049` после `20261116_0048_admin_audit_scope`, отдельного
совместимого audit hotfix. 0045/0047 и принятые S fixtures не переписывать; исправление
невыпущенной 0046 ограничено audit CHECK и fail-closed legacy accounts preflight.
Новые таблицы
размещаются в отдельном owning storage module; UUID PK, timestamptz UTC, FK RESTRICT.
JSONB документы закрыты codec/bounds; CHECK enums/nullability, unique indexes и tx ниже
обязательны. Конкретные таблицы первого среза:

| Таблица | Поля / ограничения |
| --- | --- |
| night_ai_credentials | id; scope=admin/game; owner_subject; game_id nullable (nonnull iff game); preset; status; key_id/nonce/ciphertext/AAD version nullable только erased; created_at/expires_at/erased_at. Staged/usable ciphertext required. UNIQUE(key_id,nonce). Секрет после erase не восстанавливается из audit. |
| night_ai_profiles | id; scope=admin/game; game_id nullable iff admin; label≤80; current_revision≥1; enabled; is_default=false; created_by_subject; created_at. is_default разрешён только enabled admin profile; partial unique на true. Политика disable revokes grants транзакционно и снимает default. |
| night_ai_profile_revisions | (profile_id,revision) PK; config JSONB≤16KiB, config_hash; credential_id nullable; created_at/by. Immutable, FK на credential; scope/game/preset проверяются service+codec, не только наличие FK. |
| night_ai_game_control | game_id PK/FK; starter_account_id nullable только lobby; epoch≥0; current_binding_id nullable; updated_at. Один сериализуемый control row на игру, не player/domain fence. |
| night_ai_requests | id; game_id; epoch; requester_account_id; status; created_at/expires_at; decided_at/by_subject nullable; binding_id nullable nonnull iff approved; reason enum nullable. UNIQUE(game_id,epoch), partial unique(game_id) WHERE status=pending. |
| night_ai_bindings | id; game_id; epoch; mode=admin/byok; (profile_id,profile_revision); config_hash; granted_by_subject; status; valid_until; caps JSONB; health=ok/auth_error/config_error; inflight_job_id/inflight_lease_until (оба null либо оба nonnull); created_at/closed_at. UNIQUE(game_id,epoch); partial unique(game_id) WHERE status=active. Credential через pinned revision. |
| night_ai_job_bindings | job_id PK/FK night_render_jobs; game_id; epoch; binding_id nullable; fallback_reason nullable; created_at. Immutable assignment, null binding требует reason, nonnull требует same game/epoch. Existing jobs без строки трактуются authored, никогда current binding. |
| night_ai_operations | (principal_subject,client_request_id) PK; operation; target_id; fingerprint; fingerprint_version; safe_result JSONB≤8KiB; created_at. Append-only аудит/idempotency, без secret body/provider response. |

Game/profile/binding FKs и cross-row invariants проверяются в одной tx; deferred FK
решает цикл control/request/binding, не отключение integrity. Game-scoped profile
и credential никогда не связываются с другой game. Config_hash recomputed при load;
несовпадение → unavailable/fallback, не новый snapshot по defaults.

Existing `night_narrator_limits` переиспользуется для global/account/game/profile/binding
reservations и circuits. `NotificationOutbox` сохраняет **ровно** закрытый pointer-only
envelope app contract §4: `{game_id,scope,cause_id,kind}`; extras запрещены, payload.kind
равен row.kind, payload.game_id равен row.game_id. Никаких expiry/reason/text/credentials
в payload. Два новых разрешённых сочетания:

| kind | scope | cause_id / dedupe | Единственный разрешённый consumer |
| --- | --- | --- | --- |
| night_ai_approval_requested | admin:night_ai | UUID night_ai_requests.id; dedupe=`night-ai-request:<request_id>` | Admin notification adapter: in-app; Telegram только после отдельного включения и только server-configured admin destination |
| night_ai_cleanup | system:night_ai_cleanup | UUID night_ai_bindings.id; dedupe=`night-ai-cleanup:<binding_id>` | Internal AI cleanup worker; никогда browser notification/Telegram/game broadcast |

Consumer allowlist проверяет **пару kind+scope** до claim, затем pointer принадлежит
указанной game. Admin adapter читает request/expires_at/status только через свой
авторизованный сервис; expired/denied/cancelled запрос не рассылается как новый pending.
In-app inbox — сама `night_ai_requests`, доступная после commit без Telegram. Уведомление
может повториться после crash: ссылка ведёт на admin UI, GET не одобряет; chat_id не
доказывает admin права. Первый rehearsal оставляет Telegram adapter выключенным.

Cleanup pointer — сигнал перепроверить **этот** binding, не команда безусловно удалить
текущий ключ игры. Worker под locks §6 читает AI rows и канонические lifecycle/Account,
выводит eligibility/reason=`terminal|interrupted|starter_unusable|expired`; чужой/новый
binding не затрагивает. Нет причины — безопасный no-op. Причина для аудита выводится
из прочитанного состояния, не доверяется outbox. Повторный pointer идемпотентен.
Periodic row scan остаётся обязательным для staged expiry, пропущенных wakeups и
последующих изменений eligibility; outbox не является единственным источником cleanup.
Generic dispatcher и любой Telegram consumer не claim-ят system scope или неизвестную
пару kind+scope. Ни admin pointer, ни cleanup pointer не превращается в broadcast.

`night_render_jobs`, `night_renderings` и их first-write-wins ключи не заменяются.
Job binding — отдельная таблица, поэтому существующий S schema API не меняется скрыто.
API migration downgrade отказывается удалять существующие AI control/audit данные;
rollback приложения — flags off + предыдущий build без исполнения новых bindings.

## 6. Транзакции, гонки и dispatch

Общий порядок mutation: shared operation_fence → проверка principal/ACL → lookup own
operation receipt → fingerprint equality → advisory `night_ai_config` → lock Game/control
→ проверить текущие state/epoch/expiry → необходимые profile/credential locks →
изменение+receipt+outbox → commit. Start с AI settings берёт этот advisory lock ДО
Game lock в общей start tx; создание request/binding остаётся частью start commit.
Равный ID с другим operation/target/body → idempotency_conflict, не новый вызов.
Historical retry после lifecycle/expiry возвращает прежний safe_result с отметкой replay,
но не активирует старый grant. Read ACL также под shared fence. Никаких shared→exclusive
upgrades в merge tx; порядок app contract неизменен.

Approve/deny в одной epoch конкурируют на control row: только один terminal winner.
Revocation всех profile grants и AI-настройки партии сериализуются коротким transaction
advisory lock `night_ai_config` для всех AI control mutations, dispatch reservation и
response commit, затем Game/control/profile. Он не охватывает HTTP и игровые команды,
не становится public revision; простота порядка важнее параллельности редких настроек.
Создание job assignment в игровой tx читает committed binding snapshot без advisory lock;
dispatch всё равно повторно проверяет grant. Обычные игровые команды не берут этот
lock; они могут committed менять lifecycle. Worker проверяет lifecycle после Game lock,
а cleanup closed grants выполняется отдельно в том же порядке, без upgrade lock order.

Worker claim lease30s → короткая dispatch tx: fence/usable requester/game state,
AI config lock, binding current epoch/active/unexpired, profile enabled, health, flags,
scope и все budgets. Reserve atomically в sorted scopes, commit ДО HTTP. Вне tx получить
secret по этому binding, ещё раз проверить revocation перед send. Не держать game locks
на сетевом запросе. После HTTP новая tx проверяет те же grants/epoch и job lease, Task2
validation; затем existing first-write-wins INSERT rendering. Revoked/expired/superseded
ответ не публикуется, сохраняется authored fallback. Reader по-прежнему может выиграть
гонку authored текстом ещё до ответа модели.

Вызов, уже допущенный dispatch reservation, может уйти наружу одновременно с revoke;
отменить уже переданные провайдеру данные невозможно. Гарантия: ни одной **новой**
reservation после revoke, никакого принятого late response; best-effort cancel in-flight.
Максимум1 in-flight/binding через lease reservation; bounded retry не бесконечен. Если
worker упал после send, неизвестно, списал ли провайдер деньги: бюджет не возвращается
автоматически, повтор расходует новый резерв. Exactly-once гарантируется rendering и
нашими control effects, не сторонним billing.
В dispatch tx binding.inflight_* заполняется только если пусто/lease истёк;
lease совпадает с текущим job lease. Response/expiry cleanup освобождает только свой
job+lease, не новую reservation другого worker. Это ограничение текущих leases;
network request старого умершего процесса нельзя объявить доказанно отменённым.

Jobs получают binding_id/epoch в момент создания: pending/off → null+reason и authored.
Approve не запускает задним числом старые jobs. После смены модели jobs старого binding
дают fallback, не отправляются новой модели с прежним token. Уже показанный AI/fallback
не меняется. Director передаёт только прежний privacy whitelist; ключ/endpoint/Room chat
не попадают в model payload. Имена реальных людей, sealed culprit и raw переписки не
добавляются ради лучшего результата. Episode drafts проходят прежний owner review.

Default quotas сохраняют §9: connect3s/total12s, TTL5min, максимум2 inference attempts/job,
output800 tokens/4000 chars; global10 requests/min, actor4/min, game60/day и120000 reserved
input+output tokens/day UTC. Public job actor scope — starter, private — его recipient.
Кроме daily cap, grant имеет total максимум420 inference attempts/840000 reserved tokens;
продление/смена ключа не обнуляет накопленные game totals. Admin может уменьшать limits.
Total counters имеют scope=`game:<id>:total`, period_start=UTC epoch, без daily rollover.
Reservations upper-bound UTF-8 bytes input + output limit, если нет надёжного tokenizer;
при неизвестном usage весь резерв остаётся. Это лимит запросов/токенов, не гарантия цены
в валюте: тарифы провайдера вне приложения.

Breaker per profile revision (5 consecutive errors →5min), не одна неисправная модель
на все партии. Binding auth/config error требует исправления, transient timeout/429/5xx
допускает один retry в TTL с bounded Retry-After≤30s; не retry invalid credentials или
invalid model response. OAuth calls/discovery/probe имеют отдельный control-plane cap
global30/min, principal5/min; probe максимум64 output tokens,2/day/principal/profile.
Эти вызовы не обходят consent/egress и не берут игровые факты. Все счётчики durable;
crash/restart/defaultprofile смена их не сбрасывают.

## 7. Минимальные application API и UI

Сервисы не зависят от HTTP/Telegram. Mutations используют `client_request_id` UUID,
admin/game replacements ещё `expected_epoch`/`expected_revision`; эти fences относятся
к AI settings, не к игровым AP/window/actor revision. Внешние DTO closed, secrets write-only.

| Метод / предлагаемый маршрут | Кто и результат |
| --- | --- |
| list_presets → GET /api/night-case/ai/presets | Authenticated Account; только enabled BYOK presets, public fields schema, capabilities; no endpoints/credentials/admin models. |
| get_ai_status(game) → GET /api/night-case/games/{id}/ai | Game ACL; `{status:"authored"|"pending"|"ai"|"fallback",model_label:null|string}` — оба внутренних ai_* отображаются как ai. Starter дополнительно `{mode:"authored"|"admin"|"byok",epoch,request_id,request_status,expires_at,credential_configured,can_configure,reason}`. Others не получают mode/byok owner/key/profile IDs/budgets. |
| stage_or_activate_byok(game,expected_epoch,preset,model_id,project_fields,secret,client_request_id) → POST …/ai/byok | Lobby start-authorized actor: staged ID/expiry; running starter: immediately active binding/status. Server-derived profile, без approval/probe requirement. Неверный рабочий ключ даёт последующий fallback, не hidden admin gate. |
| request_admin(game,expected_epoch,client_request_id) → POST …/ai/request | Starter; pending request view, TTL; first request также внутри start. |
| use_authored(game,expected_epoch,client_request_id) → POST …/ai/off | Starter; revoke own binding/cancel request/erase BYOK. |
| list/save_profile_revision; disable_profile → /api/admin/night-case/ai/profiles | Existing admin session+CSRF; profile schema, secret write-only, explicit model/adapter, revision CAS. Save не перебиндит партии. |
| discover_models(profile_revision); probe(profile_revision) → POST admin …/models, …/probe | Admin; bounded metadata или `{ok,code,checked_at}`; synthetic fixed prompt, не case context. Same actions для собственного staged/game BYOK через game route, только starter/owner credential. |
| list_requests → GET /api/admin/night-case/ai/requests | Admin inbox; pending plus bounded history, requester display name/game title, no roles/keys. |
| decide(request_id,decision,profile_ref|null,limits|null,client_request_id) → POST admin …/requests/{id}/decision | approve требует enabled profile revision; deny требует null refs. Expired/stale проверяются после own replay. |
| revoke_binding / rebind_admin → POST admin …/bindings/{id}/revoke, …/replace | Admin; revoke любого binding, replace только действующего admin mode и той же game; explicit profile revision/caps. |

`stage_or_activate_byok` не может передать клиентский credential_id чужой партии;
при start допускается только staged ID, проверенный по game+owner+TTL. Повтор secret
POST возвращает прежний safe receipt без echo; approve ID недоступен другой учётке.
Admin subject из проверенной сессии, client не задаёт `approved_by`/`starter`.
Model discovery для BYOK получает только собственный secret; не надо показывать его
браузеру или использовать выбранный пользователем base URL.

Ошибка DTO `{code,request_id,retry_after_seconds|null}`: auth_required(401), forbidden(403),
not_found(404, в том числе чужой game/credential), idempotency_conflict/stale_epoch/
request_stale/profile_disabled/game_not_running(409), invalid_config/unsupported_preset/
unsupported_model_contract(422), rate_limited(429), provider_unavailable(503 для probe).
UI не получает provider raw error, URL с credentials, тела HTTP или stack. Ошибка
inference не превращает успешный game command в HTTP500: ход принят, narration fallback.

Admin UI: отдельный раздел «AI ведущего», profiles/revisions, provider+model discovery,
поле ключа replace-only, project/scope по выбранному preset, testconnection и дата,
enabled/default выбор, inbox approve/deny, active bindings/revoke. Default профиль —
только preselection approve, не автоматическое разрешение. Для local явно написано
«адрес доступен worker на сервере», inventory не кнопка «скачать».

Starter UI до start: «Запросить AI у администратора» (default), «Мой ключ для этой
партии», «Авторский ведущий». Собственный ключ вводится в существующем lobby с game ID;
форма показывает provider/model и предупреждение о возможном списании самим провайдером,
никакой оплаты приложению. После старта pending badge не блокирует map/actions;
starter может заменить/удалить свой ключ. Other-player network/caches не содержат secret
или признак, кто оплачивает. История отображает сохранённый текст и источник authored/AI,
а не обещание повторить ответ той же моделью. Shell/noir kit и UI_RULES сохраняются.

## 8. Срезы и проверяемая приёмка

Сначала независимое review этого документа. После acceptance — адресная синхронизация
§9 app contract и плана, не переписывание core/schema/1. Реализация Sol/Luna с отдельным
ревью security/concurrency, не вторым игровым engine.

1. **AI-S:** новый storage module+models и migration после0045: таблицы, crypto vault,
   immutable config codecs, control service/idempotency. `cryptography` пока отсутствует
   в requirements: добавить одну проверенную stable pinned dependency/lock для AEAD,
   версию/совместимость выбрать при реализации по официальному registry; не dev release.
   Уже имеющийся httpx0.28.1 переиспользовать при доказанном network policy adapter.
   Ownership: новые
   storage/night_ai*.py, application/night_case_ai_access.py, migration; существующий S
   менять только явной интеграцией. Реальный PG tests — без ключей/внешней сети.
2. **AI-T:** infrastructure/night_case_providers/* (либо компактный equivalent module),
   preset registry, четыре adapter families, DNS/TLS policy, discovery/probe, fake
   transport matrix. Не добавлять vendor SDK без необходимости. Secrets helper не
   импортируется domain. No generic arbitrary request escape hatch.
3. **AI-W:** narrator binding resolver/jobs association/reservations/late result fence,
   outbox kind и expiry/credential cleanup в worker. Existing rendering winner protocol;
   game timers не ждут этот worker job. Отдельные transport/process restart tests.
4. **AI-U:** admin и starter HTTP/UI через те же services, CSRF, profile revisions,
   inbox и safe model selector. Telegram notification adapter тестируется fake и
   остаётся disabled. Затем local gate и data-preserving rehearsal по общему runbook.

Обязательные доказательства (fake secrets/canaries, никаких реальных токенов в fixture):

- PG: migrate0045→newhead на retained game/history; idempotent create/start request;
  approve×deny/approve×BYOK/replace×late-response/revoke×dispatch/expiry×retry races,
  same action ID после lostresponse возвращает winner; другой payload конфликтует.
  Outbox принимает только четыре pointer fields и точные kind/scope пары; foreign-game
  pointer rejected, cleanup не claim-ится Telegram, повтор cleanup не удаляет новый binding.
- BYOK: starter подключает без approve; чужой Account/room owner/admin GET не видит key;
  foreign game/profile/staged ID rejected; game end/interrupted/account blocked revokes;
  merge policy+historical receipt сохраняются. Нет inference другого game на этом key.
  В transport recording и fake provider-owner logs отсутствуют private canaries всех
  остальных игроков, в том числе intent/NPC/digest, даже при подделанном job assignment.
  Public+own private работают, чужие private — authored без сетевого вызова/списания.
- Crypto: ciphertext dump/log/error/outbox/provider JSON не содержит key canary;
  wrong key/AAD/nonce tamper fail closed; nonce uniqueness, master-key rewrap/restore,
  erased live secret не возвращается, missing masterkey не останавливает игру.
- Network: redirects, localhost cloud URL, metadata IPv4/IPv6/mapped, DNS rebinding,
  mixed DNS records, env proxy, URL credentials/path confusion; TLS invalidcert fails.
  Local exact allowlist работает из worker, не случайно из browser; discovery не pull.
- Provider family matrix: каждому preset проверены endpoint/auth/project fields,
  native response parser, usage absent/oversize/non-JSON/timeout/429/401; GigaChat OAuth
  scope/refresh/TLS, Yandex folder header+URI, Anthropic version/workspace, xAI store=false.
  Неудачный probe не считается live-supported; mock schema tests отдельно от live check.
- Budgets: два worker не превышают общий cap; retries и ambiguous timeout списывают
  резерв, смена binding/суток не обнуляет total; malformed output fallback; breaker
  одной модели не выключает другую. No credentials в metric labels/stack captures.
- Narration: start pending сразу даёт authored, approve влияет только на новые jobs;
  чужие private canaries не попадают в context; revoke после send отбрасывает ответ;
  reader/worker race и restart дают один текст; episode drafts не публикуются сами.
- Browser: admin login+CSRF и starter4-account cycle, deny/re-request/BYOK/replace/off,
  model selector/project fields, failed probe и fallback, два admin tabs racing;
  screenshots375×812,390×844,1280×800, day/night по UI_RULES; secret в DOM только
  редактируемого password input до submit, не persisted value/telemetry/screenshot.

Итог gate различает: implemented+fake-tested preset; configured connection;
live probe passed с датой; полноценный пользовательский сценарий rehearsal. Только
последний подтверждает работу UI игры. Provider off остаётся поддержанным режимом.
Исследование официальных docs не является сетевой проверкой ключа или разрешением
использовать платный API. Отдельный реальный provider smoke выполняется только с явно
введённым для этого credential/подключением и установленными лимитами; эта сессия его
не выполняет. Production, рабочие рассылки и массовые загрузки моделей не разрешены.
