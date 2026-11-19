# Manor: проверяемые личные задачи

Дата: 2026-11-15. Статус: **контракт для независимого ревью; не реализовано**.
Источники: [канон](worlds/canon/manor_lake.md), [draft01](drafts/01_manor_lake_missing.md),
[авторская карта, §6–6.1](MANOR_AUTHORING_MAP.md), [core](EXECUTABLE_FORMAT_V2.md),
[три модуля](MANOR_MODULES_V2.md), [runtime](../NIGHT_CITY_RUNTIME_CONTRACT.md).
Авторская карта — вход проектирования, а не доказательство уже принятой/реализованной механики.
Ни одна из двенадцати целей не заменяется знанием карточки, если канон требует поступка.

Это отдельное расширение личных задач, не скрытый четвёртый module, не экономика,
универсальный inventory/trade или второй движок. Обычные технические и литературные
конкретизации ниже предложены для реализации в разрешённом scope; они не обозначены
как отдельные решения владельца. Game.mode остаётся `night_case`.

## 1. Граница правды и совместимость

Сервер подтверждает выполнение конечного authored действия: осмотр именно оригинала,
реальный возврат с принятием, этап работы, подписанное сюжетное обязательство.
Самостоятельные реплики человека и AI не создают этих результатов. Текст «я сжёг бумагу»
не меняет оригинал. Ни LLM, ни regex не доказывают «никому не рассказал» по свободному чату.

`goal.body` сохраняет литературное желание героя. Дополнительный обязательный для
расширенных целей `goal.criteria:Body` прямо показывает игроку критерий зачёта: какие
действия, карточки и формальные публикации учитываются. Скрытую текущую успешность
сравнения с чужой находкой/публикацией интерфейс не сообщает. Свободную речь можно
обсуждать внутри истории, но её семантика не входит в автоматический зачёт.

Новое optional поле корня case: `personal_tasks`. Оно допустимо только при
`ruleset_ref={id:"night_case.core",version:2}`; `personal_tasks.version` равно exact int 1.
`meta.modules` сохраняет ровно прежние три возможных имени. Это явная добавка к ещё
не выпущенному profile/2: после принятия нужно согласованно обновить schema/compile,
state codec, module spec и документацию профиля. Этот файл сам их не изменяет.
При отсутствии personal_tasks profile/2 не получает новые команды, goal predicates,
поля state или events; поведение трёх модулей остаётся прежним. Core/1 отвергает всё
расширение и сохраняет свои hashes, fixtures и `night-case-core/1`.

До первых реальных /2 партий окончательная семантика замораживается под
`night-case-core/2` и новой compiler version; field/capability включены в content_hash.
Если /2 успели выпустить раньше, эту добавку нельзя принять под прежним build: нужен
новый ruleset/build с явной миграционной политикой. Старые snapshot/witness не
переинтерпретируются. `engine_build_for(case.ruleset_ref)` остаётся единственной таблицей
build; сырой payload клиента не выбирает профиль. `parse_command` и
`Command.from_document(...,ruleset_version=1)` сохраняют согласованный module API;
дополнительный capability gate проверяет скомпилированный case в quote/step.

## 2. Точные узлы контента

Ниже поля обязательны, extras запрещены, nullable только по явной пометке.
ID/Body/Window/VariantSet и общие пределы файла — core; числа строго int, не bool/float.
ID уникальны внутри своего каталога; reference lists без повторов. Каталоги упорядочены;
порядок не задаёт скрытый приоритет. Никаких expression strings, путей к state или callbacks.

```text
personal_tasks = {
  version:1,
  originals:Original[0..4], caches:Cache[0..4], works:Work[0..4],
  commitments:Commitment[0..4], trips:Trip[0..4],
  topics:Topic[0..12], steps:PersonalStep[1..64]
}
Original = {
  id:ID, source_location:LocationId,
  initial_holder:CharacterId|null,
  sections:[{id:ID, observation:ObservationId, backup_proofs:ObservationId[0..8]}][1..4],
  destroy_locations:LocationId[0..4],
  return_to:CharacterId|null, return_location:LocationId|null, offer_body:Body|null
}
Cache = {id:ID, owner:CharacterId, location:LocationId, thaw_flag:FlagId}
Work = {id:ID, owner:CharacterId, location:LocationId, stages:ID[1..4]}
Commitment = {
  id:ID, kind:"recommendation"|"share", issuer:CharacterId,
  beneficiary:CharacterId, document:Body
}
Trip = {id:ID, traveler:CharacterId, work:WorkId, road_open_flag:FlagId, epilogue:Body}
Topic = {id:ID, subject:CharacterId, observations:ObservationId[1..12]}
PersonalStep = {
  id:ID, action:ActionId, actors:CharacterId[1..12],
  requires:PersonalStepId[0..8], choice_group:ID|null,
  operation:Operation,
  responses:[{variants:VariantSet, body:Body, observations:ObservationId[0..8]}][1..5]
}
```

Original sections — одна физическая связка, не независимые копии: уничтожение целого
уничтожает все sections. initial_holder=null означает бумагу в source_location, иначе
изначально удерживаемую названным героем. return_to/location либо оба null, либо оба
заданы; offer_body задан ровно при return_to!=null, иначе null; holder/recipient различны.
В Manor письмо удерживает butler; его адресат задаётся
автором дела явно. Для will_original return-поля null, sections — draft и rights.
Пустой destroy_locations запрещает уничтожение этой вещи. Это не правило удаления улик.

У уничтожаемого original каждая section требует хотя бы один backup proof. Для
неуничтожаемого письма список может быть пуст. Backup proofs существуют во всех
вариантах существования section, являются proof и
доказывают нужные расследованию статические факты независимо от оригинала. Для section
claim backup всё равно представляет отдельное проверяемое свидетельство, не превращает
исходную реплику в истину. Доступность backup проверяется witness, не обещанием schema.
Все обязательные ключи дела должны оставаться достижимы без любого personal action,
добровольной передачи PC или NPC-диалога с потенциальным PC.

Commitment.issuer — изначально NPC во ВСЕХ составах, не бывший PC. Для Manor это owner.
`share` — подписанное, уже вступившее в силу авторское дополнение, закрепляющее
именованное право на долю; не обещание в будущем, не баланс денег и не реальная юридическая услуга.
`recommendation` — адресный подписанный документ. Body не заявляет о совершённом
получении до операции выдачи. У works/trips/commitments owner/beneficiary один и тот же
персонаж, что единственный actor соответствующих шагов. Work.stages — строгий порядок.

PersonalStep.action ссылается на существующий actions[] узел с kind=`interact`.
При включённой capability он получает **единственное** дополнительное поле
`personal_step:PersonalStepId`; ссылка взаимно-однозначна. Такой action имеет
`outcomes=[]`, repeat=`player_window`, обычные location/label/available_when/fallback.
Обычные actions по-прежнему требуют свой непустой outcomes согласно core.
Стоимость personal act — обычный act_cost=1. После собственного успешного исполнения
шага он недоступен навсегда; неуспешная оплаченная попытка доступна в следующем окне.
Для return промежуточное offered также закрывает повтор навсегда: одна адресная попытка.

Original.sections.observation и Operation.deliver_card.observation существуют во всех
вариантах: операция имеет один фиксированный target. Response observations существуют
во всех вариантах своей ветки. Неполные exists_in/ref связи отклоняет compile.
Анонимные письма — claim со speaker=null; их Body не выдаёт автора, а source проходит
обычную публичную redaction. Литературное ревью проверяет эту анонимность отдельно.

Responses непересекающимся partition покрывают все варианты дела. Сначала сервер
проверяет физическую операцию, затем выдаёт её успешный ответ выбранного варианта.
Failure всегда использует action.fallback, без grants и без сообщения скрытой причины.
Здесь нет второй variant guard системы и нет конфликтующих core outcomes.
`requires` — DAG собственных успешно завершённых шагов, максимум глубина 8, все
prerequisites доступны тем же actors. Внутри непустой choice_group шаги имеют одинаковых
actors и prerequisites: завершение одного закрывает остальные для этого человека.
Группы конечны, 2..4 шага. В Manor это выбор cook silence/bargain.

## 3. Конечные операции

Operation — ровно один объект из таблицы. Клиент присылает только обычный
`act{action_id}`; object/section/receiver/stage/body/result не являются его параметрами.
Все ссылки, совместимость actor и location, профили и дополнительные поля проверяются compile.

| kind | Остальные поля | Реальный успешный переход |
| --- | --- | --- |
| `inspect_original` | `original:OriginalId, section:SectionId` | Actor лично осмотрел section в source_location, пока оригинал там, либо в своём удержании. Выдаётся section.observation плюс responses; записан его осмотр. |
| `take_original` | `original:OriginalId` | Единственный оригинал перемещён из source_location в удержание actor. В action.available_when требуется собственный story_done осмотра этого original. |
| `destroy_original` | `original:OriginalId` | Удерживаемый actor оригинал уничтожен в одной из destroy_locations. Необратимо; все sections атомарно недоступны для новых осмотров. |
| `offer_return` | `original:OriginalId` | Удерживаемое письмо оставлено адресату в фиксированном return_location; первоначально это предложение передачи, а не выполненная доставка. Правила принятия ниже. |
| `recover_cache` | `cache:CacheId` | При публичном thaw_flag=true в нужном месте owner извлёк единственный скрытый предмет; buried→recovered. |
| `advance_work` | `work:WorkId, stage:ID` | Owner в месте работы выполнил ровно следующий этап; отдельная оплаченная команда на каждый этап. |
| `record_deed` | нет | Actor выполнил явно названное authored действие с выполненными visible prerequisites, например сравнил известные бумаги или подал защиту. Пустая кнопка «получить цель» недопустима при авторском ревью. |
| `deliver_card` | `observation:ObservationId, recipient:CharacterId|null` | Доставлена фиксированная authored карточка названному адресату; null означает публичную публикацию. Это сообщение, а не согласие адресата или выплата. |
| `issue_commitment` | `commitment:CommitmentId` | Активный видимый изначальный NPC в одном месте с beneficiary подписал адресный document после её собственных prerequisites. |
| `book_departure` | `trip:TripId` | Traveler после полной своей work оформил заявку на последующий отъезд. road_open_flag не является guard заявки. Заявка не считается отъездом; результат завершает только §7. |

Исходный original может быть `at_source` или `held(character)`; далее допустимы только
`at_source→held→destroyed` либо `held→offered→delivered|declined|cancelled`.
Inspect состояния не меняет. Доставленное/уничтоженное/отклонённое письмо повторно
не циркулирует; общего drop/pickup/trade нет. Offered находится по адресу, а не одновременно
в руках отправителя; declined/cancelled означает оставленное неполученное письмо,
не обратную телепортацию. Повтор original-inspect того же actor/section через другой
step запрещён compile; разные actors могут осмотреть один оригинал независимо.

Compile требует inspect/take в source_location; destroy — в destroy_locations;
offer_return — в return_location; recover/advance — в соответствующем location каталога.
Для destroy/offer actor либо initial_holder, либо имеет свой обязательный take prerequisite.
Для recover/advance/commitment/trip actors — singleton соответствующего owner/beneficiary.
Responses issue_commitment имеют body, в точности равный Commitment.document: подписанный
результат нельзя заменить несвязанным обещанием из другого response. Остальные ответы
и references проверяются обычным Body/mentions/privacy контрактом.

Если адресат уже ghost/departed (в том числе его персонажем управляет former-PC NPC),
оплаченная попытка offer_return заканчивается нейтральным action.fallback и
`story_result(disposition="not_completed",observation_ids=[])`. Original остаётся held;
ни offered, ни story_offer, ни pending запись, ни step_done не создаются. Публичный
статус адресата остаётся доступен обычным способом; принятие за него не имитируется.

Для offered всегда создаётся личный `story_offer` адресату-PC и явное подтверждение
отправителю `story_result(disposition="offered",observation_ids=[])`.
Их body берётся из Original.offer_body, без содержания письма и утверждения о принятии.
Успешный PersonalStep.responses применяется только после принятия: до него не выдаются
success observations и не пишется step_done. При отказе остаётся только closed decision.
Получатель active/fog в return_location принимает или отклоняет через
`story_reply{offer_event_id:EventId,accept:bool}`, 0 AP, только свою ещё открытую доставку.
Эта команда проходит обычные deadline, actor/window/command fences и является presence.
Её конкретные quotes учитывают собственное положение и статус предложения.
Начальный NPC принимает сразу только если active, видим и находится в return_location;
otherwise попытка имеет нейтральный fallback без создания offered. Никакого ответа
от лица PC или бывшего PC. Принятие PC пишет completed исходного шага для отправителя
и даёт адресату sections.observations; before-проверка использует момент ПРИНЯТИЯ.
Отказ, terminal, уход отправителя/адресата или превращение адресата в ghost отменяют
открытую доставку; ghost отправителя также отменяет её. Завершённый возврат не отменяется.
Ответ после отмены — обычный невалидный видимый запрос, не повтор доставки.

Deliver_card — только конечное заранее написанное одноразовое сюжетное сообщение.
Получатель-PC получает его в private stream без сочинённого ответа, если active/fog;
изначальный active NPC может получить без автоматического встречного согласия;
former-PC NPC/removed/ghost/departed не служат подставным участником. Для NPC доставку
фиксирует личный receipt отправителя. Message body не доказывает утверждения claim.
Не нужны colocation/ответ, потому что это authored письмо, не обход цены whisper:
никаких произвольных слов, получателей, вложений или повторяемой общей переписки здесь нет.
Собственная отдельная коммуникация ≤3/whisper/group/ghost останется следующим контрактом.

Успешный record_deed всегда имеет содержательные authored prerequisites и response:
сравнение опирается на конкретные входные observations, защита — на published proof,
решение cook — на свой завершённый шаг выяснения. Compile проверяет refs/форму,
литературное ревью — смысл действия. Ни компилятор, ни LLM не доказывают смысл прозы.

## 4. Знание, результат и скрытые гонки

Original state и знания — разные сущности. Destroy не удаляет observations, knowledge,
board, facts, provenance, архивные версии или существующие receipts. Section observation
может уже быть известна через копию: успешный inspect всё равно записывает личное
физическое действие; одна лишь копия этого действия не создаёт. В authoring желательно
разделять карточки оригинала и реестровой копии, чтобы их provenance оставался понятен.

Личные результаты не записываются как статические `facts.true_in`, будто подпись уже
выдана/картина нарисована во всех таких вариантах. Их authority — typed receipt и журнал.
Responses могут выдавать обычные observations о предсуществующих фактах дела, но это
не носитель mutable achievement. Document commitment и progress work — typed story
result, не новая key proof. В accusation/hearing ничего из этого автоматически не цитируется.

Меню и quote используют только собственные prerequisites/progress, actor-character,
AP/location/window/repeat, публичные guards/locks и разрешённую видимость NPC.
Для personal_steps разрешены дополнительные visible predicates
`{kind:"story_done",step:PersonalStepId}` и
`{kind:"story_any_done",steps:PersonalStepId[1..4]}`: только собственные receipts.
Физическое отсутствие оригинала, чужой осмотр, скрытый cache state и чужая публикация
НЕ становятся hidden available_when, revision hash или подробным error.

Пример: quote на inspect выдан, затем другой PC забрал/сжёг оригинал. Старый quote
не отвергается по secret revision: законная оплаченная попытка проходит с обычной
accepted receipt и neutral fallback «В указанном месте бумаги не оказалось».
AP/repeat и факт попытки совпадают с успешной попыткой; различие допустимо только
в уже оплаченном личном результате. Нельзя отличать «сожжено» от «забрали» без
авторского разрешённого наблюдения. Неполученный secret goal milestone не выдаёт
диагностику «опоздал: её уже нашла дочь». Собственный статус holding известен actor,
но скрытая дополнительная история этого предмета в его revision не включается.

`resource_revision` включает конкретные видимые inputs действия, свои relevant
completed steps/choice/offer, а не общий story journal hash/length/seq, чужой work,
все public flags, общий timer_seq или current goal_met. Проверка и применение используют
одни helpers в существующих quote/step. Тестировать две сериализации race, не заявлять
готовой транзакционной защиты PostgreSQL до application среза.

## 5. Закрытый журнал для порядка и codec

Существующие Event.window_idx+audience_seq сохраняются. Они не задают общего порядка
двух чужих private streams и недостаточны для «уничтожил раньше чужого осмотра».
У snapshot при включённой capability появляется ровно одно поле:

```text
personal_story = {version:1, journal:StoryBatch[0..2048]}
StoryBatch = {
  seq:int[1..2048], window_idx:Window,
  cause: {kind:"command",account_id:AccountId,command_id:CommandId}
       | {kind:"system",transition_key:ID},
  entries:StoryEntry[1..128]
}
```

seq непрерывен, окна не убывают. Это SEALED chronology: сериализуется только в trusted
snapshot и state_hash для доверенного replay. Не отдавать в project, AI jobs, player
receipts, event IDs, лог клиента, ETag или quote. Межпоточная хронология публичного UI
по-прежнему не обещается. Все entries одного успешного step/tick находятся в одном batch;
разные записи того же command не получают искусственный порядок «раньше» внутри команды.
Batch появляется только при изменении story, не при каждом движении/сообщении.
System transition_key выводится из устойчивого источника (`close_<window>`,
`forget_<window>`), не часов/случайности; повтор terminal/tick не создаёт batch.

Закрытый StoryEntry union:

| kind | Остальные поля |
| --- | --- |
| `step_done` | `step_id:PersonalStepId,account_id:AccountId` |
| `return_offered` | `step_id:PersonalStepId,account_id:AccountId,offer_event_id:EventId,recipient_account_id:AccountId|null` |
| `return_answered` | `offer_event_id:EventId,decision:"accepted"|"declined"|"cancelled"` |
| `public_reveal` | `topic_id:TopicId,publisher_account_id:AccountId|null,event_id:EventId` |
| `actor_closed` | `account_id:AccountId` |
| `departed_epilogue` | `trip_id:TripId,account_id:AccountId` |

Parameters физических операций восстанавливаются только по immutable compiled step.
`step_done` уникален по (account,step); offer один на эту пару, answer один на offer;
accepted атомарно соседствует со step_done исходного offer_return. Изначальный NPC
имеет recipient_account_id=null и выполняет offered+accepted+done одним batch;
его offer_event адресован только отправителю. Для PC offer_event принадлежит адресату.
Public reveal сохраняется один раз на (topic,publisher_account|null), первый момент;
actor_closed один на account, epilogue один на (trip,account). Первый чужой осмотр
выводится из step_done inspect_original, а не из знания карточки. Work stage, original
custody, completion/choice, commitments и заявки выводятся из этого конечного журнала
и authored initial state; второй pending root или независимая изменяемая копия не нужны.

Нейтральный fold строит индекс, валидирует допустимые монотонные переходы, ссылки,
actor/action/character, уникальность, prior prerequisites, ordered stages и receipt events.
Он НЕ эмулирует AP, фазы, variant outcome или terminal engine: полноценную легальность
и hashes доказывает только replay через step. Нельзя назначать codec «доказательством
легальной игры» по одному структурно допустимому журналу. Объекты/индексы immutable,
наружу выдаются defensive copies.

Лимит достаточен по конструкции: ≤64×12 завершений, ≤4 физических предложения/ответов,
≤12×13 первых раскрытий, ≤12 закрытий actor и ≤4 эпилогов; batches не больше entries.
Безуспешные попытки остаются обычными command receipts, не раздувают story. Отдельный
runtime отказ из-за скрытого общего количества записей недопустим; compile bounds
гарантируют вместимость. Ни одна операция после actor_closed не засчитывается этому PC.

В Event union добавляются пять kinds, только с включённой capability:

| kind | payload | audience |
| --- | --- | --- |
| `story_result` | `{step_id:PersonalStepId,disposition:"completed"|"not_completed"|"offered",body:Body,observation_ids:ObservationId[0..12]}` | Только инициатор. Не содержит seq, чужой goal result, скрытую причину провала. |
| `story_offer` | `{step_id:PersonalStepId,from_character:CharacterId,original_id:OriginalId,return_location:LocationId,body:Body}` | Адресат-PC; для изначального NPC — отправитель. Body — Original.offer_body, не содержимое ещё не принятого письма. |
| `story_return_closed` | `{offer_event_id:EventId,decision:"accepted"|"declined"|"cancelled"}` | Отдельные singleton events отправителю и адресату-PC; NPC собственного account не имеет. |
| `story_epilogue` | `{trip_id:TripId,body:Body}` | Только traveler; явно последующая сцена после игрового финала. |
| `authored_card_delivered` | `{observation_id:ObservationId,body:Body}` | Public. Body в точности равен case.observations[id].body. Нет publisher, account, character, action/step ID, topic, journal seq или private event ID. |

При accepted отправитель дополнительно получает story_result completed, адресат —
обычные observation_granted с неизменяемым source. Source.kind остаётся action;
source_id — action предложения, actor_character — отправитель, location — адрес возврата,
window — принятие. Для адресного deliver_card source аналогично фиксирует действительного
автора доставки. Публичный deliver_card использует отдельный путь ниже: личность
действительного отправителя связывается только в sealed journal, не через public source.
Обычные grants от personal action имеют прежний source action/actor/location/window.
Digest включает разрешённые новые личные result/grant events по своим/публичным streams
и прежнему bounded64 правилу; никаких чужих story entries, документов или source.

Каждый успешно выполненный `deliver_card(recipient=null)` ВСЕГДА создаёт ровно один
public authored_card_delivered с текущими window_idx и public audience_seq, даже если
карточка давно публична. Replay той же команды возвращает старые events без нового
события. Это публикация authored карточки, а не free board claim и не повторный вызов
дедуплицирующего core `_grant` в надежде получить событие. ObservationId и Body прежние;
повтор не создаёт новый экземпляр proof и не удваивает количество ключей.

Если public.observations ещё не содержит этот ID, добавляется одна row с обычным source
`{kind:"event",source_id:<этот public event_id>,window_idx:<текущее окно>,
actor_character:null,location:null}`. Событие создаётся раньше ссылки на него.
Уже существующая board-карточка не меняется и не заменяет проверку наличия именно
public.observations row; её собственное первоначальное происхождение сохраняется.
При повторной доставке public.observations не меняется: прежний source неизменяем,
второй row/новый ложный provenance не появляются. Новое событие свидетельствует именно
о повторной доставке, а не переопределяет первоначальную находку. Дополнительный
observation_granted для этого пути не создаётся. В публичном event нет ссылки на шаг
автора; публикуются только разрешённые ObservationId/Body, а не весь каталог операций.

Codec/resolver profile/2 с capability принимает этот конкретный runtime event source
при первой выдаче: public stream, совпадающие observation_id/window, точное Body,
null actor/location, prior event reference. Остальные правила source не ослабляются.
Повторные authored_card_delivered разрешены для уже публичного ID, но не дубли row.
Digest выводит observation_id из этого kind по прежнему own/public-window cutoff и
bounded64 правилам, с дедупликацией списка observations; саму историю не удаляет.
Hook public_reveal ссылается на реально созданный authored_card_delivered, а publisher
берёт из исполняемой команды в sealed batch. Так by=self различает нового публикатора,
by=any использует самое раннее допустимое раскрытие; оба ограничены своим goal cutoff.
Ни board.by_account, ни секретный author/action ID не нужны для этого свидетельства.

## 6. Явные раскрытия и goal predicates

Topic связывает конкретные authored карточки с секретом subject. Учитывается первая
формальная ПУБЛИКАЦИЯ одной из этих карточек: pin, ghost_share, public grant или
deliver_card с recipient=null. Private finding/receipt, адресное письмо, обычная реплика,
free board claim и initial own secret не являются публикацией. Публикация уже известной
публичной карточки новым человеком тоже фиксирует его самостоятельное раскрытие.
Карточки Topic не могут находиться в initial.public_observations. Для каждого способа
публикации используется общий hook, событие-свидетель обязано реально содержать этот ID.
События postmortem не участвуют. Никаких сканирований prose или доступа к чужому чату.

Scoring scope осознанно уже бытового слова «секрет»: «до первой формальной публичной
публикации перечисленных карточек». Игрок видит это в criteria, в том числе что адресное
письмо/свободная речь не оцениваются этим предикатом. Авторская приёмка проверяет,
что Topic содержит все предусмотренные делом карточки, раскрывающие данный секрет;
schema не может семантически найти пропущенную перефразировку.

К существующему goal.when AND добавляются только следующие конечные predicates:

| kind | Остальные поля | Значение |
| --- | --- | --- |
| `story_done` | `step:PersonalStepId` | Есть успешный шаг именно оцениваемого account до его cutoff. |
| `story_any_done` | `steps:PersonalStepId[1..4]` | Хотя бы один собственный указанный шаг завершён. Не произвольный вложенный OR. |
| `story_before` | `step:PersonalStepId,boundary:Boundary` | Собственный успешный step существует и его batch.seq строго меньше первого boundary; если boundary отсутствует, условие выполнено. |
| `story_unexposed` | `topic:TopicId,by:"self"|"any"` | До cutoff нет формального public_reveal этого topic указанной группой. |
| `story_departed` | `trip:TripId` | Есть собственный departed_epilogue, а не только заявка. |

`Boundary` — `{kind:"public_reveal",topic:TopicId,by:"self"|"any"}` либо
`{kind:"foreign_inspection",original:OriginalId}`. Foreign — другой human account,
успешно осмотревший любую section оригинала; собственный первоначальный осмотр адвоката
не портит ему цель. Изначальные NPC не выполняют personal steps за кадром. Для by=self
сравнивается publisher account, для any также системная публикация publisher=null.
Boundary и step в одном batch НЕ удовлетворяют strict before. Эти три исторических
предиката доступны только goal.when, никогда available_when/quote/NPC guards.
story_done/any_done доступны в visible prerequisites только для своего actor.

## 7. Финал и конкретное соответствие двенадцати ролям

Результат игры/приоритеты endings, hearing, AFK и заморозки остаются core+modules.
При final сначала фиксируются все реальные последствия завершающей команды/закрытия,
затем cutoff раскрытий ДО postmortem, затем единственный детерминированный epilogue,
затем вычисляются goal_results/reward_facts. Все действия завершающей команды находятся
в одном story batch. Никаких повторных наград/переоценки после финала.

Для departed cutoff — его actor_closed (при forfeit/AFK4); бывший NPC ничего не доделывает.
Для остальных — final cutoff. Раннее ошибочное обвинение создаёт ghost, а не смерть;
готовая работа и уже поданная заявка могут завершиться эпилогом, новые personal acts
для ghost запрещены. Исторически завершённый поступок сохраняется после ухода, но
неполученный ответ/недописанная картина после ухода успехом не становятся.

Выбор реализации для первого тестового дела, не отдельный ответ владельца проекта и не обязательный
канон всего мира: «уехать» может завершаться заранее детерминированным эпилогом.
Book_departure доступен после полной картины,
может быть подан до открытия дороги и прямо называется заявкой на последующий отъезд.
При любом terminal кроме forgotten, для не-departed traveler с полной work и заявкой
записывается departed_epilogue: фактический сюжетный отъезд после открытия дороги.
Если road_open_flag ещё false, Body явно описывает более позднее время «когда метель
стихла и открыли дорогу». Это заранее определённая финальная сцена, не утверждение,
что дорога была открыта в текущем runtime window. Новое игровое окно/таймер/clock IO
не создаются. Эпилог не рисует этапы, не выдаёт новые clues, AP или main-case победу.
При forgotten не обещается будущий отъезд. Criteria художницы раскрывает это правило
до игры; это сохраняет само действие отъезда, а не подменяет его заявкой.

| PC | Авторские шаги и точный зачёт |
| --- | --- |
| housekeeper | Авторский выбор этого дела: «своя девочка» — daughter; это не отдельный ответ владельца проекта и не обязательное отношение во всех историях мира. Личная подача защиты в hall после published rights/alibi → record_deed; goal story_done этого шага AND оба published AND character_active(daughter). Публикация другими без её поступка не достаточна. |
| lawyer | Свой осмотр original draft в library → take_original → destroy_original у камина. Goal story_before(destroy,foreign_inspection(will_original)). Собственный осмотр разрешён, чужой — нет; позднее уничтожение реально, но цель проиграна. |
| doctor | Собственное сравнение двух разрешённых образцов даёт автора правок и личный record_deed. Goal story_before(compare,public_reveal(regimen_inquiry,by=self)). Criteria говорит именно о её формальном раскрытии до установления руки. |
| butler | offer_return удержанного письма → реальное принятие адресатом. Goal story_before(return,public_reveal(opened_correspondence,by=any)). Отправка предложения не завершает цель. |
| maid | Лично подать проверяемое свидетельство (record_deed с конкретными входами), затем issue_commitment recommendation от найденного owner. Goal story_done(issue). Здесь «доверие» означает подписанную им адресную рекомендацию за её помощь; сам отъезд не требуется. |
| gardener | recover_cache в winter_garden после thaw_flag; goal story_before(recover,public_reveal(cache_secret,by=any)). Другой герой не выкапывает предмет за него; публичный флаг «выкопал» не нужен. |
| cook | Своя сверка двух источников о первоначальных посвящённых → record_deed. Затем одна exclusive ветка: record_deed «решила молчать» или deliver_card фиксированного предложения одному установленному посвящённому. Goal story_done(compare) AND story_any_done(silence,bargain). Чужое текущее знание не читается, оплату/согласие не выдумываем. |
| companion | Два личных authored deliver_card шага создают интригу: анонимное письмо и противоречивые документы наследникам; затем owner issue_commitment share. Goal story_before(issue,public_reveal(intrigue_authorship,by=any)). Адресаты не обязаны реально ссориться в чате: зачёт требует её конкретных интриг и полученного права, не оценки эмоций. |
| niece_artist | Три advance_work в tower_room: underlayer→likeness→finish, затем book_departure. Goal story_departed(trip) AND story_unexposed(sitter_identity,by=any). Личность натурщика заранее authored; эпилог не называет её. |
| nephew_gambler | Собственный осмотр источника наличных, record_deed с точной находкой. Goal story_before(find,public_reveal(cash_search_or_debt,by=any)). Получение денег и погашение долга не добавляются. |
| daughter | Свой inspect_original секции rights will_original в library. Goal story_done(inspect_rights). Take/destroy раньше осмотра не даёт находку, чтение backup или чужой board её не подменяет. |
| investigator | Прежний AND knows invitation_sender + invitation_purpose соответствует именно познавательной цели; нового personal step не требуется. |

Это конкретизация счётных критериев, не заявление о том, что сервер гарантирует
бытовую скрытность, доверие, эмоциональный хаос или тайну произвольных сообщений.
Дочь и адвокат намеренно конкурируют: не требуется одновременное выполнение всех goals.
Каждая цель должна иметь собственный достижимый witness при кооперативных остальных
игроках для каждого состава, где роль PC; это не гарантия против саботажа адресата.

## 8. Реализация и приёмка следующего среза

| Слой | Ответственность |
| --- | --- |
| case.v2.schema.json / night_case_v2_format.py | Capability, closed unions, refs/actors/partition/DAG/limits, source/backup checks и запрет ложных пустых outcomes вне personal action. |
| night_case_state.py | story_reply parser /2, capability-aware state/events codec, sealed journal constraints и прежний build/hash binding. |
| новый domain/night_case_personal.py | Чистый индекс/fold и конечные story predicates/operation helpers; только данные, без своего start/step/таймеров или решений terminal. |
| night_case_engine.py | Вызвать операции внутри существующего act; hooks публикации/ухода/final; append batch и обычные events/grants атомарно с AP/receipt. |
| night_case_projection.py | Собственный progress/criteria/предложения; общий eligibility/quote, никакого journal/globalseq/hidden state. |
| night_case_simulation.py | Конечные personal act/reply кандидаты через тот же menu/quote/step; goal witnesses отдельно от main-case V4 и без обещания полного поиска. |

Публичная проекция не получает personal_tasks каталог. Собственная проекция получает
`personal:{criteria:Body,completed_steps:PersonalStepId[],pending_returns:EventId[],
booked_trips:TripId[],work_progress:[{work:WorkId,completed_stages:ID[]}]}` только для
своих steps/work/trips и адресованных открытых offers. Completed steps отсортированы
по ID, не secret chronology. Самые body/results доступны через собственный stream.
goal.criteria отсутствует в старом profile/1 и в старых нерасширенных goals; при наличии
personal predicates обязателен. Для персонажа без personal predicates self.personal.criteria
использует goal.criteria, если задан, иначе goal.body; массивы progress пусты, если его
шагов нет. Provider whitelist не расширяется автоматически.

Минимальные внутренние API: `story_index(case,state)->StoryIndex` (immutable derived data),
`story_predicate(predicate,index,account_id,cutoff_seq)->bool` и
`validate_story(case,state)->None`. Исторические predicates используют один evaluator
при финале/проверке; видимые story_done/any_done используют его же с own scope.
Исполнение операции — один dispatch из существующего act/step; private helper может
готовить конечные typed deltas, но не принимать command в обход step, проверять свой
таймер или назначать final. Публичные start/step/project/available_actions/quote_action
сохраняют свои signatures. State codec не импортирует engine, а нейтральный story helper
не импортирует state codec обратно: case/state передаются как валидированные read-only data.

Минимальная проверка до приёмки:

1. Core/1 hashes и replay прежние; /2 без capability отвергает story commands/events/
   fields; unknown op/version/extras/bool-int/плохие refs/cyclic prerequisites fail closed.
2. Две сериализации inspect→destroy и destroy→inspect; take на пути тоже физически
   исключает библиотечную находку. Уже выданные cards/board/source неизменны. Дочь не
   получает цель из копии, адвокат не побеждает после чужого осмотра; своё обнаружение допустимо.
3. Скрытые canary states дают одинаковые menu/quote/доступные metadata до оплаченного
   результата. Чужие story actions не меняют независимый quote/публичные event IDs.
4. NPC acceptance, PC accept/decline, чужой offer ID, отказ после ухода/ghost/terminal,
   replay каждого command. Уже ghost/departed адресат даёт not_completed без pending;
   offered отправителю появляется только для active/fog PC адресата, без success grants
   до принятия. Нельзя дважды доставить или подписать за человека.
5. Три реальных этапа картины, out-of-order отказ, отсутствие instant completion;
   ранний recovery до finish не даёт успех, после finish+booking даёт явный эпилог,
   forgotten/departed не создают отъезд. Отсутствующая поездка не подменяется knows.
6. Commitment только после своих prerequisites у active visible original NPC;
   чтение чужой рекомендации не даёт личный зачёт. Никакой money delta и key proof.
7. Card publication hook покрывает pin/ghost_share/public grant/deliver_card, включая
   повтор известной публичной карточки другим actor: новый redacted authored_card_delivered,
   прежний единственный public.observations row/source, новый sealed publisher для by=self,
   прежний первый момент для by=any; codec/replay/digest согласованы, publisher не утёк.
   Private card и произвольная фраза
   не дают ложного public_reveal; same-batch before=false; postmortem не портит цели.
8. Journal codec запрещает подменённые actors/params/порядок/duplicate/receipt refs,
   replay проверяет actual state_hash. Private seq/length никогда не покидают trusted
   snapshot. Digest содержит свои новые результаты, не чужую работу или документы.
9. Для Manor 3 варианта × разрешённые compositions: main-case witness остаётся после
   максимально раннего законного уничтожения оригинала; budget exhaustion = inconclusive.
   Отдельно по каждой личной цели — positive/negative replay при роли PC. Не требовать
   невозможного общего witness, где одновременно выиграли конкурирующие оригинал-цели.
10. В живой обкатке отдельно проверить понятность criteria до старта: что считается
    публичным раскрытием, чем offered отличается от возврата, почему копия не равна
    личной находке оригинала и когда именно происходит эпилог отъезда. Зелёные unit
    tests сами по себе эту понятность не доказывают.

Остаётся авторинг точных ID, текстов response/fallback/criteria, recipient письма и
предложения cook, входных proof/backup и ратифицированного дополнения; затем независимое
ревью и реализация. Это разрешённая работа, а не повторный запрос права добавить каждую
бумагу. Выбор daughter, конкретного натурщика и материалов проверяется на соответствие
канону, не выдаётся за найденный в источнике факт. Конкретного неизбежного противоречия,
требующего сейчас менять канон, этот контракт не вводит. PG/application/UI/provider,
живые диалоги и выпуск остаются отдельными срезами.
