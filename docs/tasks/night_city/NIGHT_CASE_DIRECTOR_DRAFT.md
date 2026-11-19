# Night Case N: сценарный директор и адресный рассказ

Статус: **принят к реализации после независимого Sol review, 2026-11-16**.
Проверенный draft SHA256: `f559edb9ad739976aa760253d7614bc5ac572abe896c5e0f44fd5e88277fd66e`.
Первичный P2 с окнами исправлен; адресный повторный review — ACCEPT.
Это план ограниченного N, не описание уже работающего AI. Kernel, дело и арт
сохраняют прежнюю authority; runtime меняется только в назначенных ниже границах.

## 1. Authority и результат первого N

Основание: [runtime contract](../NIGHT_CITY_RUNTIME_CONTRACT.md),
[application contract](NIGHT_CASE_APPLICATION_CONTRACT.md),
[AI_ACCESS](NIGHT_CASE_AI_ACCESS.md), [принятый T](NIGHT_CASE_TRANSPORT_DRAFT.md).
Owning code: `domain/night_case_narrative.py`, `night_case_delivery.py`,
`night_case_delivery_state.py`, `night_case_projection.py`, `night_case_engine.py`,
`application/night_case.py`, `storage/night_cases.py` и AI assignment/control.
Старые заявления runtime doc о неподключённом PG не описывают текущий rehearsal.

Уже существуют четыре job kind: window_digest, npc_reply, scene_narration,
story_offer; pure narrative validator; реальные server-once NPC lines/slips;
RenderJob/Rendering, первый сохранённый текст и ACL history. N связывает эти части.
T отвечает за permit/quota/egress/retry; N не создаёт второй dispatcher.

Первый полезный результат: после применённой беседы/открытия окна/авторской сцены
появляется адресный рассказ или authored fallback. Он сопровождает неизменные
точные результаты и карточки. Скрипт предлагает доступный следующий шаг, но не играет
за человека. Free text→legal choice→player confirmation остаётся отдельным intent path.
Удерживать правила или UI до ответа модели запрещено.

Произвольные новые игровые события модель не исполняет. В N каталог ограничен
предложениями **уже существующих** действий и декоративными сценками без эффектов.
Новые значимые ветки сохраняются как draft для автора; автоматический apply новой
механики не является частью N. Это ограничение первого среза, не отказ от принятого
гибридного ведущего и свободной подачи.

## 2. Source → director → immutable assignment

```text
existing step → transition events/messages → persist в game tx
 → director: адресные source IDs + whitelist materialization
 → RenderJob + immutable AIJobBinding (или null+reason), та же tx
 → commit → T reserve/authorize/network → N result validation
 → T fresh fences + first-write Rendering → ACL history
```

Director hook идёт после start/control callback и persistence событий, до commit.
Он не делает HTTP, DNS, отдельный commit, chance reroll или игровую команду.
Вход не «пусть AI придумает, что случилось», а уже применённый источник.
Опциональная художественная ошибка/переполнение контекста даёт отсутствие job либо
authored-only job; не откатывает успешный игровой ход. Storage corruption/несовпадение
duplicate immutable row остаётся настоящей ошибкой, не подавляется как «AI недоступен».

| Job | Источник первого N | Адресат / обязательный exact вывод |
| --- | --- | --- |
| window_digest | committed private window_digest event, включая initial/wake по kernel правилам | ровно account event; рассказ об summarized_window из payload, job создан в action_window из envelope; точные карточки и список событий |
| npc_reply | accepted talk + его private action_result event | actor; exact composed_body и выданные claims/proofs |
| scene_narration | committed public scene event | public; exact authored scene Body |
| story_offer | первый private window_digest, emitted в данном action_window | его account; максимум одно предложение existing visible action текущего action_window, без apply |

У source/job два разных значения, которые нельзя восстанавливать из clock при чтении:
`action_window=Event.window_idx` — окно эмиссии события и предложения действия;
`summarized_window=Event.payload.window_idx` — только у digest source (включая job
story_offer от этого source), у npc_reply/scene_narration — null. Оба непустых номера
— exact int1..14. Это явные поля NSource/frozen DTO, не изменение Event/kernel.
При обычном открытии k>1 kernel `_digest` описывает k−1, а `_event` маркирует его k;
initial digest имеет оба номера1. Wake берёт эти значения из фактического события,
не вычисляет их заново по времени. Текст и exact blocks сводки относятся к первому,
assignment/job freshness, available_actions/quote и срок работы — ко второму.

`say`/square/whisper/ghost сообщения не запускают narrator автоматически.
Ни свободный chat, ни произвольная просьба NPC не обходят AP/talk/intent ограничения.
AFK notice остаётся exact system notice: это не window_digest и не новая presence.
Final/postmortem, наказания, голосование, promises, story_result и награды в первом N
показываются exact; отдельный AI пересказ не добавляется.

NPC trigger нельзя угадывать по тексту action_result. Сейчас transition hook получает
actor_key, но не нормализованный вид команды. Минимальный proposed seam:
`TransitionContext.command_summary=None | {kind, target_character_id}` из успешно
валидированной команды, только внутри application. Talk source сверяется с его
receipt result_ref и event audience. Нет source proof → нет npc_reply job.
Не расширять Event union и kernel state ради косметического рассказа.

Детерминированные caps: 1 digest + 1 story_offer/account/window; максимум2 npc_reply
jobs/account/window (последующие разговоры сохраняют полноценный exact авторский
ответ); максимум1 scene_narration/public/window. Счёт по уже созданным jobs и source
events той же scope/action_window под Game lock; summarized_window не ключ cap.
Результат выбора не зависит от чужих private
событий. Другие оплаченные AP не теряются из-за cap. Эти caps технические, не часть
RulesSnapshot; actual inference дополнительно ограничен T.

`job_id='nr_'+SHA256(canonical JSON ['night-director/1',game_id,cause_id,kind,
audience_key,template_hash])`. Никаких общих счётчиков. `template_version=template_hash`
(64hex). Source event ID и audience_seq берутся из уже стабильного отдельного stream.
`knowledge_revision` PG bigint = cause audience_seq; NarrationView.knowledge_revision
= hash frozen curated context, не public/global revision. Unique cause/kind/scope
не позволяет повторно enqueue после reconnect/повтора команды/worker restart.

TTL=min(source.created_at+5min, snapshot closes_at для source.action_window).
При enqueue source.action_window должен совпадать с открытым clock.window_idx;
закрытый/frozen/pending-open source не используется для нового предложения.
Закрытие summarized_window не истекает новый digest/offer: при открытии k2 срок
считается по close2, а не уже прошедшему close1. Early close или переход в другое
окно делает late result stale даже до сохранённого expires_at; срок не продлевается.
У initial/wake digest время источника реальное время применения, не прошедший срок
старого окна. Истёкший job не исчезает: authored история доступна. Никакой генерации
вновь при чтении и никакого backfill jobs из старой истории.

Assignment фиксирует current control snapshot в той же tx, без AI advisory из-под
Game. Допустимые reasons уже заданы AI_ACCESS. Нет binding/неизвестен policy/нет
разрешённого scope → null+reason. Profile/control меняются параллельно — T повторно
проверит current pins и при несовпадении даст fallback; director не повышает grant.
Jobs без assignment authored навсегда. Approve/rebind не переписывают старые jobs.

## 3. Отдельный curated context, не полная проекция

`project(..., PlayerActor)` содержит self.truth, secrets, faction и postmortem.
Его допустимость для игрока **не** делает его допустимым model context. Director
в application может пользоваться trusted state/case для вызова существующих
проекций/материализаторов; чистый context builder принимает только уже отобранные
типизированные records. Ни case.document(), ни state.document() ему не передаются.

| Аудитория | Разрешённый контекст | Запрещено / первый N |
| --- | --- | --- |
| public | только public authored scene/source + public authored observations и опубликованные authored cards в пределах этого source | любые private facts, объединение знаний участников, истинность claims, скрытые места/планы/вариант; admin binding не расширяет scope |
| account:A | public subset + private authored records, реально доступные A и необходимые именно для job | self.truth/secrets/faction/postmortem, другие goals/receipts/locations, сырой снимок всех собственных данных |
| NPC reply A | exact разрешённая реплика этого talk, выданные в этом talk карточки, имя роли NPC и безопасная style instruction | остальные знания A не становятся знаниями NPC; никакого «NPC прочёл личное досье», full NPC knowledge или hidden author alternatives |
| multi/whisper/ghost | первый N: нет AI job; exact сообщения с frozen recipients сохраняются existing ACL | нельзя заменить аудиторию union private знаний; нельзя размножить общий private summary по одному account и тем обойти BYOK |

Для будущего multi-context потребуется отдельный reviewed DTO с frozen recipients и
**пересечением разрешённых сведений**, а не union; нынешняя storage audience public/account
не притворяется такой поддержкой. Нынешний пользовательский chat≤3 и ghost канал остаются.

BYOK assignment/send допускает public либо ровно private A=credential owner=starter.
Чужой private job authored даже если админ или спонсор находится рядом. Проверяется
до body serialization и снова T перед reserve/send/complete. Менять provider на
другой binding ради обработки уже созданного private job нельзя.

Данные выбираются source-first, без полного history scan:

- Digest: только source.payload.event_ids/observation_ids, которые kernel уже отобрал
  для summarized_window; event refs относятся к нему, а сам digest envelope — к
  action_window. Source digest/notice не используются как повторный raw context.
  Проверяются own/public ACL, provenance и отсутствие forward refs; прочая история
  не добавляется «для полноты». Старые own/private показываются через existing history.
  Старый observation может быть опубликован в summarized_window: его исходное
  provenance не передатируется и не обязано иметь этот же номер; связь подтверждается
  разрешённым referenced event, как в kernel digest.
- NPC reply: точный применённый body + issued observation IDs, уже materialized для A.
  Полный body не меняется; если он составлен из line+outcome и длиннее1200, разбиение
  на contiguous chunks с same reference, без потери/перефразирования содержимого;
  лимит1200 включает typed prefix и номер части, а не только исходный текст.
- Scene: только source scene Body и прямо упомянутые публичные authored карточки,
  если нужны для подачи. Ни branch guard, ни почему выбрана сцена, ни unrevealed NPC.
- Story offer: до3 choices из existing available_actions для A в action_window по детерминированному
  публично объяснимому приоритету; full args/cost/revision остаются серверу. Условия
  выбора только visible eligibility. Не выбирать подсказку по hidden culprit/key path.

Own personal criteria/completed_steps не отправляются по умолчанию. Первый story_offer
может сослаться на already-visible label существующего personal action; секретную
формулировку цели и private work history NPC не получает. Private journal содержит
точную личную цель независимо от narrator. Расширение этого whitelist требует review.

Claim — «персонаж утверждает», proof — «полученная улика», result — «серверный итог»;
классификация не определяется моделью. `Body.mentions` не разрешает раскрыть facts[]:
IDs только для локальной валидации, truth-set/proves/asserts/true_in/exists_in не
сериализуются. Свободная запись board — тоже human claim, в model facts не включается.

В provider JSON нет Account UUID, player display_name, chat/message/thread ID,
game/case/variant IDs, внутренних action/observation IDs или вычисляемых из private
активности счётчиков. Используются authored role titles; если безопасной роли нет —
«участник», без автоматического переноса пользовательского имени. Из исторического
provenance остаётся разрешённая роль/место/окно находки; это не current location.
Public automatic source сохраняет прежнее redaction.

Не включаем raw chat (даже square), прежние AI renderings, свободный human board text
или модельные summaries как authority. Пользовательский free text есть только в
отдельном T intent path как untrusted request. Это ограничивает prompt injection и
накопление выдумок, но не доказывает семантическую безошибочность модели.

## 4. Frozen DTO и совместимость существующих codecs

Предложение: один closed `frozen_view.schema='night-director-view/1'` в existing
NightRenderJob; никаких новых PG таблиц для контекста и никаких изменений Case schema.

```text
{schema, narrative, reference_map, exact_blocks, offers,
 references, catalog_ids, summarized_window, action_window, context_hash}
narrative = exact поля NarrationView
reference_map[] = {alias,kind,source_id,body_hash}
  kind = observation | event; alias=r01..r64; source_id только internal
exact_blocks[] = {reference,kind,body,speaker_title:null|string}
  kind = proof | claim | result | scene
offers[] = {alias,selection_id,label,kind,target_id,cost,resource_id,resource_revision,params}
  alias=c01..c03; все поля кроме alias соответствуют серверному LegalAction+label
```

`narrative.window_idx=action_window` для всех четырёх job kinds: это binding/freshness
поля existing NarrativeJob и его request_token. summarized_window остаётся отдельным
метаданным и явно указан в digest facts/заголовке exact blocks; у offer label/facts
явно относятся к action_window. Не добавлять в NarrationView второе window поле.
Reference map сохраняет original source IDs/body hashes: digest event refs проверяются
против summarized_window, talk/scene source — против action_window. Alias не заменяет
номер окна и не даёт переиспользовать old source как current source. Оба поля входят
в frozen context_hash/input_hash; при decode сверяются с сохранённым cause Event.

`references`/`catalog_ids` top-level нужны совместимому authored fallback getter:
references — только разрешённые original source IDs, catalog_ids=[] в первом N.
Это не provider arrays. `narrative.references` — aliases reference_map;
`narrative.catalog_ids` — aliases offers. Source IDs при render validation разрешаются
назад **только через этот immutable map**, не lookup всего Case по AI-строке.
Один alias соответствует ровно одному source и body_hash, chunks могут ссылаться
на тот же alias. При использовании всех chunks исходный body восстанавливается точно.

`narrative.facts` — strings с явными typed prefixes и alias, например
`[r01; claim; садовник] «Я видел ...»`, не маскируемые под доказанную истину.
Для составного body prefix содержит `part i/n`, чтобы одинаковые куски не нарушали
existing unique-strings codec. Story_offer получает также safe labels своих choices
в facts вида `[c01; предложение; 1 AP] Осмотреть библиотеку`; provider видит связь
alias→label/точная цена, но не selection_id/params/resource_revision. Label берётся
из visible MenuChoice, не из внутренних идентификаторов. Эти строки тоже входят
в общий бюджет facts и не являются новой уликой или применённым действием.
Пределы существующего NarrationView:≤64 уникальных chunks,≤1200chars/chunk,
≤16000chars total; фактический provider payload≤32768 UTF-8 bytes.
Также ограничить entire frozen_view≤64KiB canonical JSON. Нельзя обрезать critical
body/превратить конец claim в иной смысл ради лимита: опциональные records исключаются
целиком по стабильному source order; source-critical overflow→authored-only.

context_hash вычислен по curated DTO без context_hash и без
`narrative.knowledge_revision`; затем knowledge_revision получает context_hash.
`input_hash=SHA256(canonical entire frozen_view)` после этого заполнения: нет hash cycle.
Case hash и ruleset version входят в narrative internal metadata; template hash
остаётся в existing PG template_version и job_id, без выдуманного поля NarrationView.
NarrativeJob request_token строится existing pure helper; worker восстанавливает job
из сохранённого DTO и проверяет input_hash, не пересобирает его из текущего знания.
Reference IDs и типы доступны игроку через ACL history; provider видит только aliases.

Контрактные файлы заранее сравниваются parity tests: actual field limits, PG int revision
против narrative string revision, sources candidate/fallback против PG ai/authored.
Нельзя записать source='candidate' в Rendering или принять old frozen_view={} за новый
validated context. Old job получает прежний authored-only path, без миграции контекста.

## 5. Model result, exact блоки и честная граница проверки

Provider получает existing `NarrativeJob.provider_payload`:
`{request_token,kind,facts,references,catalog_ids}`. Trusted template описывает роль
и limits; не содержит скрытого Case. Result остаётся exact
`{request_token,kind,text,references,catalog_ids}` — без произвольных effects.

Pipeline: bounded strict JSON из T → exact keys/token/kind/expiry → existing
validate_narrative_result → N checks Unicode/NUL/control chars, plain text, bounded
refs/maps, catalog cardinality≤1 для story_offer и0 для остальных → T fresh fences
→ `commit_rendering` и возвращение фактического first-write winner.
Freshness сверяет именно action_window с открытым current window и saved expires_at;
summarized_window не сравнивается с текущим clock как будто это окно команды.
Late response не получает новый window/token/map: он отклоняется, а source history
с authored fallback остаётся датированной прежними сохранёнными двумя номерами.
Не принимать HTML/markdown links/URLs как executable UI. Приложение выводит textContent,
технические ограничения не превращаются в обещание распознавать любую ложь.

Ненулевые catalog_ids у story_offer только выбирают existing offer. Их нельзя хранить
как будто это уже применённый gameplay event. В Rendering.catalog_ids сохраняются
только выбранные job-local aliases (0..1), не global gameplay catalog IDs;
выбранный offer обслуживает отдельная safe UI projection через frozen job map и
fresh available_actions/quote в том же action_window, не скрытый эффект commit_rendering.
В другом окне это исторический stale offer, не автоматически обновлённое предложение.
Исторический текст не
меняется, stale offer показывается недоступным, старая цена не становится новой командой.
Authored fallback сохраняет catalog_ids=[]; UI может показать исходные до3 предложений
без AI-highlight. Alias interpretation допустима только при new frozen_view schema;
исторические records не получают новый смысл молча.

Exact blocks всегда берутся из saved source и показываются рядом с живым рассказом.
Модель не переписывает результат, обещание NPC, оговорку, proof/claim карточку, AP,
цель, голосование или концовку. Свободный narrator text может варьировать интонацию,
паузы, образность и несущественную бытовую сценку в допустимом мире.
Игрок видит краткое различие «Слова ведущего» и реальные карточки/итоги; без названий
validators/permits. Факт, значимое обещание и доступное действие имеют точный блок/кнопку.

Структурная проверка доказывает IDs/ACL/сроки/форму, **не** истинность свободного текста.
Prompt запрещает новые алиби, намёки на скрытого виновного, неизвестные улики, обещания
ресурса/движение/NPC knowledge. Однако модель может нарушить это даже с допустимыми refs
или пустым references. Нет «LLM проверил LLM — значит доказано». Авторская оценка,
privacy canaries, отрицательные fixtures и live feedback проверяют качество, не теорему.
Strict assembly владельцем отвергнута: не заменяем всё свободное оформление шаблонами.
Подозрительный ответ можно отклонить/fallback, но невозможно полно перечислить ошибки.

## 6. NPC, предложения и проактивность без второго engine

`resolve_dialogue` уже выбирает authored line и once slip в kernel, записывает scope
и бюджеты, а `_grant` выдаёт claim перед action_result. N не читает seed/decisions для
выбора подсказки, не вызывает decide_slip повторно и не получает unrevealed slip pool.
Author line/outcome/выданная claim — exact. Повторный job/модель/формулировка не reroll.
Essential proof не становится случайной оговоркой. Former-player NPC не получает AI
реплики вместо ушедшего человека; live PC никогда не озвучивается моделью.

NPC может приглашать продолжить уже доступную authored тему. Exact текущий node prompt
и options показываются сервером; AI не создаёт новую обязательную кнопку или таймер.
Если игрок отвечает своими словами, existing intent выбирает только материализованный
legal choice; затем игрок подтверждает конкретное действие/цену. Свободное обещание
в чате не завершает personal goal и не считается передачей предмета/доли/письма.

Optional catalog первого N — finite `offer_existing_action` из current menu (до3),
никакого new effect grammar. Для выбора берутся только concrete choices с неизменяемым
params, не бесконечные claim text/vote citation combinations. Формы остаются обычным
UI вводом→quote→confirm. Список безопасен даже при rejected AI result.

Если позже понадобится значимое scripted optional event, необходим **отдельный**
authored catalog с executable guards/effects, stable candidate ID, TTL, budget и
идемпотентной системной командой через existing step. Принятие model text не может
само его применить; `scene` event сейчас допускает только authored scheduled source.
В N неизвестный event/effect/target отклоняется и может стать draft, не расширяет Case.

Clock/window/scene jobs проактивны независимо от модели. Hint «нет прогресса» в первом N
только по собственному source и available menu, никогда по скрытому правильному пути.
Director не изменяет quiet hours/AFK/freeze/wake и не создаёт presence. Уведомления
используют existing pointer outbox и ACL; задержка Telegram не переносит игровые сроки.

## 7. История, first-write и reusable episodes

Existing events/cards/messages сохраняют свои ACL; Rendering — annotation source,
не запись в каноническом chronicle вместо результата. `get_rendering` проверяет cause
и departure cutoff как сейчас. No direct job-ID access без game/source ACL.
Public/own streams отдельны; точный общий wall-clock порядок не выдумывается.

Читатель может раньше модели сохранить fallback. И AI, и fallback проходят один
`commit_rendering` first-write; отдаётся committed winner. first_shown_at монотонно
заполняется при чтении. После этого не переписывать текст, refs, source или стоимость.
Re-render кнопки/автоперегенерации после approve в первом N нет.

`EpisodeCandidateDraft` уже только draft; это не accepted event и не опубликованный
контент. Для reuse первого N: явное действие авторизованного владельца создаёт новый
sanitized template draft; приватная партия не экспортируется автоматически.
Source job может быть указан только если действующий actor имеет ACL этого source.
Админское право approve модель не даёт читать private исходник другого участника.
Public исходник тоже не означает отсутствие персональных данных в свободной прозе.

До сохранения portable candidate убираются actual game/account/message/source refs,
user names, private claims, разгадка исходной партии, quoted chat; роли/места заменяются
объявленными placeholder parameters. Автоматическая замена имён не считается доказанной
анонимизацией. Если безопасный draft нельзя получить без спорных деталей — decline,
оставить только ACL историю исходной партии. Owner review отдельно от source ACL;
проверяет текст, conditions/effects и отсутствие приватных следов. Approved draft ещё
нужно включить в новое авторское content version и пройти format/simulation gates.
Ни raw chat, ни old rendering не становятся published Case по одному флагу в БД.

## 8. Предложенные seams и приёмка

Предлагаемое владение реализации после review:

- Pure `domain/night_case_director.py`: closed safe-record/context DTO, alias mapping,
  build/render checks. Existing narrative helper переиспользуется; допустимы только
  адресные codec parity additions, без изменения игровых правил.
- `application/night_case_director.py`: hook/source mapping/selection caps/frozen enqueue
  и assignment. Минимальный command_summary seam в A. Нет AI advisory под Game.
- T dispatcher получает уже frozen assigned render job, вызывает N validator перед
  existing first-write. T stage1/storage/gateway ownership сейчас не пересекается;
  дальнейшая интеграция по согласованному API после его freeze/review.
- Rendering getter/HTTP DTO: safe exact blocks + optional fresh offer, старый history
  ACL сохраняется. UI позже отдельной задачей, никакой новой вёрстки в этом draft.
- Episode export/service — отдельная небольшая задача N после основного live story
  цикла; existing draft storage используется, а не автоматический export всех jobs.

Минимальные acceptance tests:

1. Actual talk/line/slip→exact source + private job; replay/worker retry не меняют
   line/slip/AP/issued claim. No NPC impersonation PC/former PC. No new proof из prose.
2. Private/public canaries во всех variants и roles, включая self.truth shadow:
   identical visible source→identical serialized context/job selection независимо
   от скрытого варианта/чужого AP/private moves. Public ID и количество jobs не зависят
   от чужих private событий. Alias не раскрывает author ID вроде variant_b.
3. NPC context не включает actor secret, personal criterion и чужую комнату;
   опубликованный claim сохраняет speaker/provenance и не превращается в proof.
   Multi whisper/ghost не отправляются ни admin model, ни BYOK.
4. Source record body не совпал/hash изменён/forward reference/foreign audience или
   reference window не соответствует роли source: fail closed. Digest refs k−1 при
   action_window=k допустимы; это не ошибочный «old window». Long composed Body сохраняется точно либо authored-only;
   truncation не создаёт нового смысла. События с null redacted source не deanonymize.
5. Assignment absent/pending→authored навсегда; approve×enqueue, rebind×render,
   reader fallback×late AI дают один immutable winner. New jobs после approve получают
   binding; старые — нет. Полный shown text/history не требует повторного model call.
6. BYOK public+own private допускаются; чужой private body не достигает fake transport.
   Admin model public job не получает combined private context. T revoke/epoch/expiry
   fences остаются обязательными независимо от valid narrative JSON.
7. Model token/kind/ref/catalog/Unicode/size mismatch → fallback; valid fabrication
   fixture демонстрирует остаточный semantic risk, не помечается «truth verified».
   Catalog selection никогда не вызывает step; stale UI choice проходит новый quote
   и explicit confirm. Freeform→intent→proposal→confirm тратит AP один раз.
8. Начальное/новое/wake окно создают bounded proactive jobs из actual events;
   downtime/freeze не порождают retroactive jobs/уведомления; no progress hint не
   выбирается по keyproof/culprit. Model failure не останавливает таймеры.
   Обязательный open k2: digest рассказывает об окне1, NarrationView/assignment job
   и валидный offer относятся к окну2, deadline рассчитан по close2, не close1.
   Initial:1/1; wake сохраняет actual envelope/payload. После close2/early transition
   ответ от этого job не применяется к k3, не передатирует digest и не получает новый TTL;
   позднее чтение возвращает неизменную историю, а не заново выбранный offer.
9. History после departure/merge соблюдает existing cutoffs. Private source→public
   episode export запрещён; sanitized draft остаётся draft до отдельного owner review
   и content admission. Source ACL нельзя заменить админским grant.

Для review открыты технические choices: достаточность source-first контекста без raw
чата; whitelist personal action labels без personal secret bodies; alias mapping при
существующем Rendering.references; ограничение multi narration до отдельного DTO;
finite offer-only catalog первого N. Это не вопросы повторного разрешения разработки.
Владельцу понадобится смысловой вопрос только при реальном изменении роли/цели/канона;
в данном draft такого изменения нет.
