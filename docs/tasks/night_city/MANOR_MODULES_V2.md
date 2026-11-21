# Manor: три модуля поверх исполнимого v2

Дата: 2026-11-15. Статус: реализовано (§1–8); §9 — модули выбывших игроков, добавлены 2026-11-21.
Это следующий pure-domain срез после A–D; не PG, UI, AI provider или разрешение публикации.
Канонический Game.mode будущего application adapter — `night_case`, не имя исторического UI.
Источники: [канон мира](worlds/canon/manor_lake.md), [draft01](drafts/01_manor_lake_missing.md),
[CASE_SLATE](../NIGHT_CITY_CASE_SLATE.md), [core](EXECUTABLE_FORMAT_V2.md),
[решения владельца](../NIGHT_CITY_RUNTIME_CONTRACT.md).

Владелец явно разрешил проход library↔cellar, обнаруживаемый по двум независимым зацепкам.
Хозяин этого дела — изначально NPC, а не отнятый у человека PC. Остальные решения ниже —
техническая конкретизация для реализации; не утверждение, что весь draft стал каноном.
Код, контент партии и арт этим документом не создаются.

## 1. Совместимость и конечный объём

Сохраняется `schema="night-city-case/2"`. Старый `ruleset_ref={id:"night_case.core",version:1}`
принимает ровно прежний контракт, `meta.modules=[]`, без новых полей и kinds.
Новое расширение явно выбирает `ruleset_ref={id:"night_case.core",version:2}`.
Его `meta.modules` — непустое множество из `version_archive`, `turning_point`,
`archive_requests`, `ghost_whisper`, `ghost_testimony`, `ghost_visions` (три последних — §9);
каждое имя обозначает **версию модуля 1** внутри ruleset/2.
Другие имена, лишние настройки и неподдержанный профиль отклоняются, а не игнорируются.

Для ruleset/2 единственное новое поле корня case — `module_data:object`.
Его ключи в точности совпадают с meta.modules; порядок массива modules не задаёт порядок
исполнения. Каждый модуль можно проверить отдельным fixture; Manor включает все три.
Schema остаётся самодостаточной: общие `$defs` переиспользуются локальными refs,
профильные ветки schema/compile запрещают расширения в core/1. Не копировать второй
набор типов core в отдельную почти такую же схему. Старые input hashes остаются прежними;
новые поля участвуют в полном canonical content_hash, не добавляются скрыто loader-ом.

RulesSnapshot с AP/slots/AFK не меняется: request стоит `act_cost=1`, ожидание ровно одно
игровое окно — константы нового profile. State/witness отдельно связывают ruleset_ref,
rules_hash, case_hash и compiler/engine build. Компилятор и engine явно регистрируют /2;
старые исполнимые witness не переименовываются в новый build задним числом.
Это один `_initialize`/`step`/`project`/`quote_action`, не второй движок для Manor.

Единый exported helper в `domain/night_case_state.py`:
`engine_build_for(ruleset_ref)->str`. Он строго принимает `{id:"night_case.core",version:1|2}`
(version — exact int) и возвращает соответственно `"night-case-core/1"` или
`"night-case-core/2"`; неизвестный id/version/extra field — ошибка. Нейтральное расположение
позволяет engine, codec и simulation использовать одну таблицу без циклического импорта.
Initializer записывает build для ruleset_ref **скомпилированного case**; state codec требует
совпадения case↔state ruleset_ref и engine_build_for этого профиля. Witness generation и
replay вычисляют ожидаемый engine_version тем же helper из переданного case, а не из
непроверенного witness/state. Существующий `ENGINE_BUILD` может остаться compatibility alias
для core/1, но новый код Task D не использует его как универсальную версию для обоих профилей.

Не добавляются инвентарь, экономика долей, уничтожение доказательств, обмен предметами,
смена фракций, произвольные скрипты или eval. Turning point /1 реализует сцену-перелом,
открытие пути и обнаружение скрытого NPC; это не все будущие возможности одноимённого
модуля из SLATE. Неподдержанные операции не маскируются литературным текстом.

Все ID/Body/Label/Window и strict JSON bounds — core. Ниже все поля обязательны,
nullable/default указаны явно, extras запрещены. Каталоги имеют уникальные ID;
ссылки проверяются до исполнения. Без дополнительной пометки массивы — упорядоченные,
reference lists без дублей. Лимиты действуют вместе с общими 2 MiB/64 уровнями.

## 2. `archive_requests`: отложенный личный ответ

```text
module_data.archive_requests = {
  queries: Query[1..12]
}
Query = {
  id:ID, label:Label, location:LocationId,
  available_when:VisiblePredicate[0..8],
  responses: [{variants:VariantSet, body:Body, observations:ObservationId[0..8]}][1..8]
}
```

Responses образуют непересекающееся полное покрытие variants. Это авторские ответы,
а не текст, добытый внешним сервисом. Observation существует во всех вариантах своего
response; claim не удостоверяет asserts. Допустим нейтральный ответ без observations.
В responses нет дополнительных runtime guards: результат определяется закреплённым
вариантом и query, поэтому не требуется сохранять секретный выбранный ответ при заказе.

Новая player-команда `archive_request`, params **ровно** `{query_id:ID}`.
Eligibility: active human, investigation, window 1..13, actor находится в query.location,
видимые prerequisites выполнены, AP≥act_cost, этот actor ещё не заказывал query в партии.
Граница доступности не читает response/variant. Меню выдаёт concrete MenuChoice;
quote target=query_id, cost=act_cost; resource_revision включает только собственные
ресурсы, данный repeat и используемые visible predicates. Скрытых цен/ETA нет.

Принятие списывает 1 AP, отмечает presence, увеличивает actor_seq и создаёт личный
`archive_requested`. Нельзя вручную передать observations, due_window или response.
Запрос в окне k приходит **при фактическом открытии k+1**, до его digest; не через
wall-clock таймер и не во время pending freeze. После wake доставка выполняется один раз.
Reply не отмечает presence и не расходует AP; knowledge_revision меняется при новой выдаче,
actor_seq от фоновой доставки не увеличивается. Изменение знания отражается в зависимых quotes.

Новые Event kinds (обычные window_idx/audience_seq/ID из core, только один адресат):

| kind | точный payload | правила |
| --- | --- | --- |
| `archive_requested` | `{query_id:ID,due_window:Window}` | envelope.window_idx=k, due_window=k+1. Один request на account/query/game. |
| `archive_response` | `{request_event_id:EventId,disposition:"delivered"\|"cancelled",body:Body\|null,observation_ids:ObservationId[0..8]}` | Ссылается на предшествующий request той же аудитории. Delivered: envelope.window_idx=due_window, body равен выбранному авторскому response, IDs равны его observations. Cancelled: body=null, IDs=[]; только если адресат уже ghost/departed к открытию due_window. |

Для active/fog запрос доставляется. Для ghost/departed новые личные знания не выдаются:
так сохраняется ограничение weekly §3.2 на знания призрака, даже если запрос был подан раньше.
Это явный технический выбор; AP за уже поданный запрос не возвращаются. При terminal
до due_window запрос имеет вычисленное состояние
`cancelled_terminal`; новых событий/окон после финала не создаётся.

Pending выводится из retained private history: requested без response, phase!=finished.
Один request имеет не более одного response. Отдельного state-root pending/второй очереди
нет. Допустимо локально индексировать history внутри одного вызова, не хранить другую истину.
Codec проверяет audience/refs/окна/repeat/response content и невозможность двойной доставки.
Отмена проверяется по состоянию адресата на границе открытия due_window, а не по его
возможному более позднему отстранению в этом же окне. События закрытия предыдущего окна
предшествуют opening delivery; последующий ghost status не делает задним числом доставленный
ответ отменённым. Полный replay остаётся доказательством истории переходов.

Delivered добавляет обычные observation_granted/knowledge. Source.kind="event",
source_id=request_event_id, actor_character=герой адресата, location=null,
source.window_idx=окно доставки. Это результат дистанционного запроса, не находка
в случайной текущей комнате. Source нельзя подменить клиентом; pin сохраняет его.
Digest извлекает observations и из archive_response(disposition=delivered), а прежний
request может войти как обычное личное событие. В ответе/проекции нет вариантов и чужих requests.

## 3. `version_archive`: документы и версии расследования

```text
module_data.version_archive = {
  documents: [{id:ID,family:ID,revision:int[1..16],observation:ObservationId}][2..16],
  comparisons: [{id:ID,left:DocumentId,right:DocumentId,action:ActionId}][1..16],
  theories: [{id:ID,title:Label,body:Body,
             links:[{observation:ObservationId,relation:"supports"|"contradicts"}][0..32]}][1..8]
}
```

Document — конкретная версия бумаги, не автоматически истинная гипотеза. У пары
family/revision ровно один document; observation у document уникален. Сравнение соединяет
разные версии одной family. Его action — обычный `interact`, visible prerequisites
содержат `knows` для обоих document observations. Output — обычные авторские outcomes
с proof/claim, не вычисленная моделью «истинность подписи». Cost/repeat/AP берутся из act.
Результат сравнения не обязан стать key, но все заявленные связи имеют явный author source.

Theories — публичные гипотезы, общие для вариантов. Их label/body не сообщают скрытые
улик/разгадку. Каждый link — авторское отношение к observation, а не импровизация.
Project показывает link только когда observation опубликован в public observations/board;
до публикации не отдаёт ни ID, ни relation, ни число скрытых связей. Document metadata
показываются только при известном viewer observation; comparison — когда известны оба.
Нельзя отдавать весь module_data как клиентский DTO.

Новая команда `version_mark`, params `{version_id:TheoryId,state:"active"|"archived"}`.
Любой active human может сделать её бесплатно в investigation/final_hearing. Начальное
состояние всех theories — active. Требуется реальное изменение; каждый account может
переключить конкретную theory не более одного раза в окно. Это явное техническое
правило совместной доски, не голосование о виновнике. Archived не означает «опровергнуто».
Запись не удаляет proof/claim/source, не меняет knowledge, citations или истинность.
UI позже сможет свернуть архивную группу; серверная доска и журнал остаются полными.

Public Event `version_marked` payload **ровно**
`{version_id:TheoryId,state:"active"|"archived",by_account:AccountId}`.
Account берётся из trusted actor. Текущее состояние — последнее такое событие по public seq;
отдельного mutable root не нужно. Codec проверяет reference/account/no-op/repeat-последовательность.
MenuChoice/quote привязаны к текущему состоянию и последнему событию именно этой theory,
собственному repeat/окну; чужая отметка другой theory не инвалидирует предложение.
Возврат из архива той же командой — полноценный предусмотренный путь.

## 4. `turning_point`: видимый перелом и скрытый NPC

`PublicPredicate` — только core `flag_is`, `published`, `window_in`; AND, максимум 8.
Нет `knows`, `at`, отрицания над чужими знаниями или variant в публичных guards.
Для ruleset/2 VisiblePredicate дополнительно допускает ровно
`{kind:"character_active",character:CharacterId}`: публичный статус текущего контроллера
персонажа active/fog, а не ghost/removed. Предикат не читает location/variant/knowledge.
Он допустим и в goal, но не добавляется молча в core/1.

```text
module_data.turning_point = {
  routes: [{id:ID,ends:[LocationId,LocationId],
            open_when:PublicPredicate[1..8],opened_flag:FlagId}][0..4],
  scenes: [{id:ID,not_before:Window,through_window:Window,
            when:PublicPredicate[0..8],body:Body,effects:PublicEffect[0..16]}][0..8],
  concealed_npcs: [{character:CharacterId,revealed_flag:FlagId,
                    placements:[{variants:VariantSet,location:LocationId}][1..8]}][0..2],
  recovery: {character:CharacterId,through_window:Window,requires_board_keys:true}|null
}
PublicEffect = grant_observation(audience="public") | set_flag
```

Routes добавляют двусторонние связи к обычному графу locations.connects. Ends различны;
дубли обычного ребра/другой route запрещены. Open_when содержит как минимум два разных
published proof, существующих во всех вариантах; независимость их смысла отдельно проверяет автор.
До открытия ребро не входит ни в project
connects, ни в move menu/quote. Базовый граф остаётся связным: скрытый проход не является
единственным способом попасть в cellar. Opened_flag объявлен в flags с initial=false,
принадлежит ровно одному route и не может изменяться обычными effects/сценами. Когда
open_when впервые выполнен, kernel ставит его true; повторно не закрывает. Это правило
включено в общий settle, flag попадает в один world_changed batch. Move сохраняет params
`{location}`, cost=1, locks/actor fences; отдельного teleport/pass-through исполнителя нет.

Scenes — публичные условные авторские события; not_before≤through_window. Проверяются
на старте, открытии окна и после принятого player action. Один scene ID исполняется один раз
через общий event_uses. Его ID не пересекается с core events[].id. Эмиссия — существующий
scene kind с content_event_id и точным авторским Body; codec знает оба каталога.
После through_window условие уже не проверяется. Сцены не читают variant и не двигают людей.
No generic script/callback. Locks оставлены только core scheduled events, чтобы не создавать
непроверяемые условные конфликты NPC-расписаний.

Settle: проверить routes в порядке массива; затем найти первую допустимую ещё не сыгранную
scene, применить её effects и повторить. Верхняя граница — число routes+scenes, каждый
срабатывает максимум один раз в партии. Обычные protected flags не могут быть сброшены.
Public effects сворачиваются в один world_changed на batch, как core. Нет второго tick.

Concealed NPC обязан быть can_be_player=false и отсутствовать во всех compositions.
Placements полностью и без пересечений покрывают variants. Его runtime npcs.location
инициализируется выбранным placement, а не публичным home; placement **статичен** до финала
этого среза. Для него schedule=[]; это не обычный NPC, гуляющий по открытому расписанию.
Скрытые переходы между убежищами пока не поддержаны и не выводятся из канонического события
о перемещении другого NPC. Location проверяется на существование. Static occupant может
оставаться за позднее закрытой дверью: lock запрещает вход, а не нахождение внутри.
Для concealed NPC проверяется placement, а не фиктивный маршрут home→home в каждом окне;
для остальных сохраняется обычная проверка schedule против locks.

Revealed_flag initial=false, принадлежит одному NPC; это защищённый флаг, не произвольный
set_flag. Новый Effect **ровно** `{kind:"reveal_npc",character:CharacterId}` разрешён только
в Outcome обычного examine/interact. Compile проверяет для каждого variant outcome:
action.location совпадает с placement NPC. Runtime повторяет проверку по настоящей location
**после** принятия и оплаты действия; эффект для другого/removed NPC — invalid content.
Чтобы законное ошибочное обвинение NPC не создавало этот invalid-content путь, compile
требует общий visible `character_active` guard для каждого target reveal_npc в данном action.
Статус target публичен и проверяется одинаково во всех вариантах; скрытое убежище — нет.
Обычные neutral fallbacks в неправильной комнате не меняют цену, repeat или причины отказа.
При reveal flag становится true и эмитируется public `npc_revealed` payload
`{character_id:CharacterId,location:LocationId}`. Это явное публичное обнаружение, не скрытая
утечка location через обычный roster. Повторный reveal не эмитирует дубль.

Пока flag=false, NPC не попадает в nearby и не даёт talk/menu/quotes, даже если человек
стоит в его комнате. Его существование и роль пропавшего публичны, поэтому roster и список
подозреваемых могут содержать его ID; там нет placement/schedule и признаков близости.
Для любого NPC dialogue availability использует один и тот же visibility gate в menu/quote/step.
Project показывает published discovery и видимые routes, но никогда placements/outcome guards.
Сравнение одинаковых public/self состояний в разных вариантах даёт одинаковые menus/errors.

### Доказанность и ранняя развязка

Только ruleset/2 расширяет каждый variant полем `required_key_proofs:ObservationId[0..8]`
(обязательно, можно []). Это subset key_proofs. Во всех способах solved требуется одновременно
count(distinct cited key proofs)≥min_key и включение всех required_key_proofs. Core/1 сохраняет
прежнюю формулу. Для обычного/final hearing набор — прежнее объединение допустимых citations;
claim никогда не входит в key count, архивирование theory не исключает доказательство.

Recovery, если задан, ссылается на concealed NPC. После settle он должен быть найден,
window_idx≤through_window, а **на публичной доске** уже должны быть min_key и required keys
выбранного варианта. Тогда обычный `_terminal(requested="solved")` завершает дело; никаких
AI-win/custom ending codes. При недостатке proof находка NPC сохраняется, игра продолжается;
поздний pin до cutoff может завершить начатое раннее раскрытие. Все свидетельства оплачены/
опубликованы реальными командами. Нельзя выиграть одним перебором пустых комнат.
Сохраняются обычные final.code=solved, endings.solved и выбранный variant.final_text;
публичная хроника discovery/board объясняет ранний путь. После cutoff остаются hearings.
Это техническая конкретизация ранней развязки draft в сочетании с требованием трёх ключей.

## 5. Порядок перехода и общие инварианты

Новых state-root полей нет: requests/version marks/discovery — retained events;
route/reveal flags — существующие public.flags; placement — существующий npcs.location.
Sealed.variant_id не меняется. Codec профильно проверяет новые kinds/refs/protected flags
и соответствие скрытого NPC selected placement. Project не возвращает sealed каталог.

Открытие окна: core AP/locks/scheduled events → NPC placement/schedule → ответы архива
с due_window=current (в стабильном порядке account_id, request audience_seq) → settle
routes/scenes → единый world_changed → window event → прежние digests/afk_notice.
Initial digest остаётся только initial grants. Archive events текущего окна попадут
в следующую сводку; чужие ответы никогда не входят в собственную. Terminal не открывает окно.

После player-команды: visible eligibility → один расход/repeat → авторский outcome/effects
→ settle → recovery/прочие terminal причины с прежним приоритетом → receipt/next due.
Нельзя между частями batch публиковать промежуточный state. Replay до fences/time возвращает
прежнюю receipt без новой заявки/публикации/обнаружения. Timer и player fences не смешиваются.
Freeze, подтверждённый outage, индивидуальный AFK и forfeit не заменяются модульной логикой.

Module APIs добавляются в существующие unions parse_command/quote/step. `version_mark`
и `archive_request` — concrete choices, не free-form provider commands. Proposal/confirmation
Task2 по-прежнему выбирают серверный LegalAction и сохраняют полный params/resource binding.
Для search/replay всё проходит через тот же kernel, никакой ручной выдачи результатов.

Точные codec API: `Command.from_document(raw,actor,*,ruleset_version=1)->Command` и
`parse_command(raw,actor,*,ruleset_version=1)->Command`. Второй передаёт keyword первому;
принимаются только exact int 1 или 2. Default сохраняет прежнее поведение и отвергает
archive_request/version_mark. Для /2 синтаксический union расширен; включённость конкретного
модуля дополнительно проверяет общая eligibility по compiled case. Выбор профиля не является
полем пользовательского envelope и не меняет состав canonical payload_hash.
Step и quote_action берут ruleset_version из case.ruleset_ref после проверки соответствия
state/case и явно передают его parser-у; quote intent materializer делает то же. Уже созданный
Command также перепроверяется для текущего профиля, не обходя /1 gate. Simulation создаёт
команды через эти же API/step; нигде не выбирает профиль по присланному kind.

Profile/2 имеет максимум 20 Event kinds: 11 core + два archive + version_marked + npc_revealed + пять из §9.
Каждый новый kind принимается codec только при включённом соответствующем модуле.
Имена protected route/reveal flags уникальны между всеми владельцами; посторонние writers
запрещены. Reference resolution использует один compiled registry, не догадки по префиксу ID.

### Явные дополнительные проекции /2

Core/1 сохраняет прежнюю форму GameView. У /2 добавляется публичный `locations[]`:
`{id,name,body,art,connects:LocationId[]}` — только разрешённые базовые места/рёбра плюс уже
открытые routes, без скрытых placements. В `modules` возвращаются только включённые
публичные части, в `self.modules` — только части для текущего участника:

Поле art обязательно в этом DTO: если optional art отсутствует в source, проекция выдаёт
null. Это материализация ответа, а не изменение старого loader или исходного content_hash.

- public `version_archive={theories:[{id,title,body,state,links:[{observation_id,relation}]}]}`;
  links отфильтрованы по публикации observation, state вычислен из version_marked.
- public `turning_point={routes:[{id,ends}],discoveries:[{event_id,character_id,location,window_idx}]}`;
  routes только открытые, discoveries — исторические npc_revealed, не скрытый current location.
- self `version_archive={documents:[{id,family,revision,observation_id}],comparisons:[{id,left,right,action}]}`;
  только известные документы и пары, где известны оба. Факт присутствия comparison не означает
  доступности act в текущей комнате: это по-прежнему проверяет quote.
- self `archive_requests={requests:[{request_event_id,query_id,due_window,
  status:"pending"|"delivered"|"cancelled"|"cancelled_terminal",response_event_id:EventId|null}]}`.
  Чужих requests и скрытых future response body/observations здесь нет. Полученные body и
  observations доступны через собственные события/knowledge. Меню содержит legal query choices.

Disabled/неприменимые module keys отсутствуют; viewer=None не получает self. Все списки
канонически упорядочены по ID, исторические discoveries — по public audience_seq.
Это read-only DTO, не дополнительный mutable state и не provider payload без отбора.

## 6. Перенос Manor: фиксированная правда и доступность

20 канонических героев сохраняются. 12 can_be_player из draft:
housekeeper, lawyer, doctor, butler, maid, gardener, cook, companion, niece_artist,
nephew_gambler, daughter, investigator. Остальные 8 — authored NPC во всех составах:
owner, hunter, watchman, chauffeur, governess, granddaughter, priest, photographer.
Не превращать photographer в observation ID: его реплика — отдельный authored claim со speaker.

Минимальные compositions (далее обычная seed-раздача между людьми):

| N | player_characters |
| --- | --- |
| 4 | housekeeper, lawyer, doctor, investigator |
| 5 | предыдущие + butler |
| 8 | предыдущие + maid, gardener, daughter |
| 12 | предыдущие + cook, companion, niece_artist, nephew_gambler |

Все три варианта совместимы со всеми четырьмя compositions: 12 witness-ячеек.
Канонические склонности сохраняются; culprit/accomplices переопределяют faction в shadow
как core. Не назначать всех невиновных Следствию: у gardener/companion остаются свои тайны.
Состав 4 в A всё равно содержит doctor/investigator из Следствия. Owner никогда не PC.

| Вариант | culprit / accomplice | скрытое убежище | что сохраняется |
| --- | --- | --- | --- |
| A | lawyer / housekeeper | cellar | Угроза разоблачения поддельной подписи, помощь экономки за долю, хозяин жив за подпёртой дверью. |
| B | hunter / watchman | cellar | Добровольная проверка семьи хозяином, маршрут через лодочный домик и обратно, прикрытие сторожем. |
| C | owner / никто | tower_room | Самостоятельная инсценировка, проход через погреб, свет наверху и подготовленный возврат. |

В C owner уже в tower_room на старте: переход до начала — факт метода, не runtime teleport.
Не подключать draft ev_cellar_knock как перемещение owner: в каноне оно относится к stranger.
Не подключать ev_extra_plate как обязательного нового NPC: draft задаёт ложный след ошибки
счёта, а core не поддерживает new_npc. События мира — каталог для отбора, не обязательный сценарий.

Базовый связный граф: main_hall↔library/kitchen_wing/winter_garden/tower_room;
kitchen_wing↔cellar/servants_quarters; winter_garden↔boathouse. Это техническая игровая
топология восьми канонических мест, не новый канонический интерьер. Скрытое ребро library↔cellar
добавляется отдельно. Обычный вход в cellar не обнаруживает человека за закрытым отсеком.

Passage открывается только после **двух опубликованных proof**: отдельный осмотр лишнего
ключа из housekeeper_keys и отдельный осмотр сдвинутой книги/механизма ev_swapped_book.
Оба доступны без NPC беседы и не требуют уже открытого passage. Book scene разрешается
с окна 7 (день 4), не выдаёт проход всем автоматически: он становится исследуемой точкой.
Два разных observation ID сами по себе не доказывают смысловую независимость; author review
и два независимых acquisition paths обязательны. Missing clue/единый скрытый подарок — отказ приёмки.

Case-local scene после открытия passage показывает переосмысление «исчезновения» и позволяет
сопоставить две версии завещания; не меняет ранее выбранного виновника. Обычные search cellar /
search tower доступны одинаково во всех вариантах после общих предпосылок. В правильной комнате
outcome даёт reveal_npc; в другой — нейтральный fallback. Меню не является детектором убежища.
Recovery cutoff=12 (до седьмого дня), min_key=3 и required distinctive proof обязательны.

Минимальный отбор канонических событий для первой версии данных (числа — техническое
расписание, все тексты остаются авторскими):

| Окно | событие | исполнимый результат |
| --- | --- | --- |
| 2 | ev_blizzard | boathouse закрыт на окна 2..4 включительно; потом обычное истечение lock. |
| 3 | ev_generator | tower_room закрыт на 3..4; скрытый owner C остаётся внутри, нового входа NPC нет. |
| 4 | ev_scarf | Публичная находка шарфа как след; принадлежность врачу устанавливается отдельной проверкой, не ложным proof. |
| 7 | ev_swapped_book | Публичный flag открывает осмотр механизма; никакой автоматической выдачи второй key улики. |
| 10 | ev_keys_found | Находка ключей в пальто как факт; версия о вине investigator остаётся claim. |
| 11 | ev_thaw | Публичная сцена/наблюдение об аллее без принудительного перемещения людей. |
| 13 | ev_object_on_table | Поздний альтернативный путь получить сведения о лишнем ключе, без перезаписи прежнего source. |

Расписания обычных NPC обходят locks. Ev_doctor_study не включён в этот отбор: не нужно
ради семи событий придумывать исключение «NPC входит в закрытую library».

### Ключи и документы — authoring map, не новые предметы мира

В каждом варианте ровно три минимальных key proof: два общих наблюдения о ключе и механизме
прохода плюс одно различающее сопоставление. required_key_proofs содержит это третье proof.
Такая конструкция не позволяет закрыть случайную версию тремя общими находками.
Дополнительные канонические предметы/показания дают контекст и проверки ложных следов.

| Вариант | различающее proof (case-local authoring requirement) | независимый путь при 12 людях |
| --- | --- | --- |
| A | Сопоставление will_draft с результатом архивного запроса устанавливает конкретную подделку адвоката; blurred signature сама этого не доказывает. | Осмотр бумаг + query об архивной регистрации + interact compare; не признание PC lawyer/housekeeper. |
| B | Физическое сопоставление rope_scrap/изменённого узла hunting_horn и возвратных wet_boathouse_tracks связывает подготовленный маршрут с hunter. | Осмотры общедоступных точек/сопоставление; watchman_testimony остаётся claim-подсказкой. |
| C | Сопоставление unaddressed_letter и архивного происхождения anonymous_invitation устанавливает подготовку инсценировки самим owner. | Бумаги + query об отправлении + сравнение; undeveloped_plate подтверждает свет/время, не выдуманную видимость лица. |

Это требования к новым **производным наблюдениям дела**, не заявление, что канон уже содержит
достаточный текст этих доказательств. При написании данных нужны конкретные совпадающие признаки
и три непротиворечивые fact tables. Нельзя заменить проверку фразой «сервер знает, кто виноват»
или объявить слух proof. Новые физические предметы/локации без отдельной пометки не добавляются.
Draft-списки ключей с testimony переводятся в clues/claims, не механически в key_proofs.

Version archive содержит документы черновика/«официальной» бумаги с явной family/revision,
comparisons через interact, и три theory A/B/C. Обнаружение, что «официальная» бумага тоже
черновик, — отдельный проверяемый результат, не retroactive rewrite уже выданного текста.
Theories можно архивировать/возвращать, но нельзя лишить обвинение уже опубликованных proof.
Archive queries: наследственный спор/регистрация и происхождение приглашения. Ответ в следующем
окне имеет понятный источник; телефон/дорога остаются закрыты. Канал получения сведений должен
быть объяснён авторским текстом дела (например, заранее доставленные архивные материалы,
которые разбираются за окно), а не внезапно работающей телефонной линией.

### Личные цели: отдельная обязательная проверка данных

Сохраняются public bio, голос, смысл секретов и личных целей канонических ролей.
Не менять условие «уничтожить черновик до обнаружения» на «узнать public_note» ради зелёного
goal_met. В текущем typed minimum нет уничтожения/экономики/рисования; это реальное ограничение.
Для каждого из 12 PC authoring map должен связать цель с поддержанной проверяемой развязкой
или явно отметить неподдержанную часть. Неподдержанная цель не получает passed/фиктивной награды.
Операционализации, меняющие смысл цели (например, для lawyer/companion/niece_artist), требуют
явного авторского решения до приёмки Manor. Реализация трёх модулей может быть принята отдельно;
игра Manor с подменёнными generic goals — нет. Не вводить через этот пробел четвёртый модуль
скрытого инвентаря/торговли без отдельного контракта.

## 7. Арт и существующий пакет

Используется noir_print_a. Уже есть library/cellar в четырёх временах суток и портреты;
текущее pack.json имеет пустые places, а build_world_pack.py --places умеет их экспортировать.
Это отдельная операция интеграции ассетов, не доказательство, что runtime art refs уже разрешаются.
Ключи/книга/тайник могут ссылаться через каталог на существующие i_S1_03_key_ring,
i_S1_01_antique_key, i_S7_06_closed_book, i_C2_05_secret_compartment_book; отдельные объекты
с альфой, фоны RGB. Asset IDs должны пройти обычные ID/catalog checks; имена файлов не
становятся произвольными путями в case. Отдельного open-passage арта нет: для первого UI
достаточно разрешённого ребра карты и существующих сцен. Генерация здесь не требуется.

## 8. Владение реализацией и приёмка

| Файл/слой | изменение следующего среза |
| --- | --- |
| case.v2.schema.json / night_case_v2_format.py | Профиль /2, module_data, required_key_proofs, refs/partition/limits/protected flags и compatibility gate. |
| night_case_state.py | Profile-aware Command.from_document/parse_command с ruleset_version=1 по умолчанию; общий engine_build_for; event unions/invariants, derived requests/version marks, hidden placement/board provenance; без второго pending root. |
| night_case_engine.py | Один start/step: запрос/доставка, version_mark, route/scene settle, reveal/recovery и прежние terminal rules. |
| night_case_projection.py | Общая NPC visibility/route eligibility, новые concrete quotes, whitelisted module views, скрытые каталоги не возвращаются. |
| night_case_simulation.py | Кандидаты новых concrete commands, шаги/время/requests через engine; generation/replay используют engine_build_for(case.ruleset_ref), не общий ENGINE_BUILD, для witness ruleset/build binding. |
| fixtures + case data | Независимые маленькие module fixtures, затем отдельный Manor JSON с source/authoring review; не помещать правила в fixture/validator. |

Никакой доменный импорт БД/Telegram/HTTP/provider. Time helpers без новых часов/очередей;
старые core/1 tests и hashes воспроизводимы. Не выдавать profile/2 compile за publication.

Минимальные тесты до приёмки:

1. Core/1 не принимает module_data/новые kinds; прежние cases/переходы не меняются. /2 неизвестный
   модуль/лишний config/неполное variant partition/плохой ref/неподдержанная операция fail closed.
   Direct parser default и передача Command(/2) в step(/1) не обходят gate; step/quote/parser
   согласованы для /2. Оба профиля дают свои build при start/witness/replay; подмена build/profile
   отклоняется codec/replay, прежняя core/1 строка неизменна. Optional source art даёт DTO art=null.
2. Request AP/repeat/ID replay, ответ ровно k+1, decode/replay между request и response;
   freeze→wake, outage, ghost и departed; terminal раньше доставки; окна13→14 и отказ в14.
3. Version compare только при обеих известных бумагах; archive/unarchive/no-op/repeat,
   независимые theory quotes; archived proof по-прежнему учитывается в hearings.
4. Hidden owner не виден в nearby/talk/quote при нахождении PC в его комнате. Одинаковый
   visible state разных вариантов имеет одинаковое меню/цены/отказы. Реальное reveal только
   после оплаченного поиска; fallback в неверной комнате, ID/stream без скрытых счётчиков.
5. Passage закрыт при 0/1 зацепке; при двух опубликованных независимых proof открывается
   симметрично один раз; AP=1 за переход, locks действуют. Scene late/expiry/цепочка bounded,
   effect batch атомарный, один world_changed, no duplicate recovery reward/final.
6. Две общие + чужая третья не solved; верная distinct третья обязательна в обычном hearing,
   final hearing и recovery. NPC found без ключей не даёт произвольную победу; cutoff12/13.
7. V4 witness и replay для всех 3×4 пар, включая12 людей: ключи без NPC-only PC-диалогов,
   оба способа solved, обычный unresolved, idle/freeze/forgotten, публичные и личные claims.
   Inconclusive budget остаётся not_checked; oracle-guided policy не доказывает баланс/догадливость.
8. Содержательная проверка трёх fact tables/производных proofs/ложных показаний/личных целей;
   несовпадения канона отмечены, не скрыты кодом или зелёной матрицей.

Порядок: сначала reviewed module fixtures/engine contracts, затем авторский Manor mapping,
потом полная матрица. PG, UI, рассказчик и первые тесты с людьми — следующие этапы.

## 9. Модули выбывших игроков: `ghost_whisper`, `ghost_testimony`, `ghost_visions`

Зачем: игрок, которого стол по ошибке отстранил на слушании (status `ghost`), остаётся
в игре и раз в окно влияет на неё (weekly §3.2). До этого среза было только core-действие
`ghost_share` — опубликовать на доске разрешённое воспоминание. Три модуля добавляют
остальные действия из §3.2. Старые дела их не включают, их партии не меняются.

Общие правила для всех трёх:

- Действие выбывшего бесплатно и одно на окно: `ghost_share`, `ghost_whisper`,
  `testimony_answer` и `ghost_sign` вместе записывают `ghost_used_window`. Фазы — те же,
  что у `ghost_share`: идущее окно investigation или final_hearing.
- Выбывший не получает новых знаний о мире (как с архивом). Передаёт он только то,
  что его персонаж уже знал.
- **Мистика — свойство дела, а не мира.** Включённый `ghost_visions` и означает «в этом деле есть
  мистика». Тогда экран называет выбывших «призраками». Без него — «отстранёнными»:
  человек жив, но отстранён от расследования, передаёт записки и отвечает на вопросы.
  Отдельного флага мистики нет, чтобы два источника не расходились.

### `ghost_whisper`: личная передача воспоминания

`module_data.ghost_whisper = {}` — настроек нет.

Команда `ghost_whisper`, params **ровно** `{observation_id:ID, recipient:CharacterId}`.
Eligibility: актор — ghost, `ghost_used_window != window_idx`; observation входит
в `ghost_memories` его персонажа и в **собственное** knowledge актора, но не публична
(нет в public.observations и на доске — передавать известное всем бессмысленно);
recipient — персонаж другого человека со status active или fog; этот же observation этому же
recipient актор ещё не передавал (второй раз — только потраченное окно). Знает ли получатель
это observation, eligibility не читает: меню выбывшего не раскрывает чужие знания, проверка
повтора смотрит только собственные `ghost_whispered` актора.

Принятие: `ghost_used_window = window_idx`, отмечается присутствие, actor_seq+1 у отправителя.
События (обычные envelope core, по одному адресату):

| kind | payload | правила |
| --- | --- | --- |
| `ghost_whispered` | `{observation_id:ID, recipient_character:CharacterId}` | Поток отправителя; receipt.result_ref ссылается на него. |
| `ghost_whisper_received` | `{from_character:CharacterId, observation_id:ID}` | Поток получателя, то же окно. Ровно одна пара на whisper. |

Если получатель ещё не знал observation, следом в его потоке идёт обычный
`observation_granted` и запись knowledge с source
`{kind:"ghost", source_id:<event_id ghost_whisper_received>, actor_character:<персонаж отправителя>,
location:null, window_idx:<окно>}`. Pin сохраняет этот source: на доске видно, что улика
пришла от выбывшего. Proof остаётся proof — его автор и вариант те же, меняется только путь.
У получателя не меняются AP, actor_seq и присутствие.

Codec: пары whispered↔received совпадают по окну, observation и персонажам; отправитель
к тому окну уже ghost (публичный status), observation есть в его ghost_memories и knowledge;
получатель — другой игрок. Source `kind:"ghost"` допустим только при этом модуле и только
со ссылкой на received того же потока плюс сохранённый grant с тем же source.
Self `modules.ghost_whisper = {sent:[{event_id,observation_id,recipient_character,window_idx}],
received:[{event_id,observation_id,from_character,window_idx}]}`.

### `ghost_testimony`: вопрос «да или нет»

`module_data.ghost_testimony = {}` — настроек нет.

Живой игрок спрашивает выбывшего; тот отвечает «да» или «нет». Вопрос и ответ публичны:
выбывший влияет на весь стол, а не на одного. Ответ — утверждение, не доказательство:
он не попадает на доску как proof и не считается ключом. Свободного текста от выбывшего нет,
поэтому он не может назвать роль или имя (§3.2).

- `testimony_ask`, params **ровно** `{ghost:CharacterId, text:string[1..200]}`. Eligibility:
  актор active (не fog), phase investigation, окна 1..13, AP≥act_cost; ghost — персонаж
  другого игрока со status ghost; у этого актора нет открытого вопроса к этому ghost.
  Стоит act_cost (1 ОД), отмечает присутствие. Событие public
  `testimony_asked {asker_character, ghost_character, text, answer_by}`, answer_by=window_idx+1.
  Вопрос открыт, пока нет ответа и текущее окно ≤ answer_by; потом он истёк без ответа,
  ОД не возвращаются.
- `testimony_answer`, params **ровно** `{question_event_id:EventId, answer:"yes"|"no"}`.
  Eligibility: актор — ghost этого вопроса, `ghost_used_window != window_idx`, вопрос открыт.
  Событие public `testimony_answered {question_event_id, answer}`.

Codec: asker был active, ghost — ghost на момент вопроса; без дублей открытого вопроса той же
пары; ответ один, не позже answer_by, от ещё не ушедшего ghost; текст 1..200 символов.
Public `modules.ghost_testimony = {questions:[{question_event_id, asker_character, ghost_character,
text, window_idx, answer_by, answer:"yes"|"no"|null, status:"open"|"answered"|"expired"}]}`
в порядке хроники. Текст вопроса — слова игрока, ведущему-ИИ он не передаётся.

### `ghost_visions`: явление (только дела с мистикой)

```text
module_data.ghost_visions = {
  signs: [{id:ID, character:CharacterId, location:LocationId, label:Label, body:Body}][1..48]
}
```

Character — can_be_player; ID уникальны. Знак — авторская подсказка, а не улика:
observations он не выдаёт.

Команда `ghost_sign`, params **ровно** `{sign_id:ID}`. Eligibility: актор — ghost,
`ghost_used_window != window_idx`, знак принадлежит его персонажу и ещё не показан в партии.
Событие public `ghost_sign {sign_id, character_id, location, body}`; body равен авторскому.
Codec: знак из каталога, один раз, поля равны авторским, персонаж к тому моменту ghost.
Public `modules.ghost_visions = {signs:[{event_id, sign_id, character_id, location, window_idx, body}]}`.

### Тесты среза

Модули выключены — команды отклоняются, старые kinds и hashes не меняются. Для каждого модуля:
eligibility (не ghost, повтор в окне, чужая или публичная память, ушедший получатель, AP,
окно 14), события и receipt, decode/replay, подмена истории отклоняется codec, меню и quotes
выбывшего и живого, проекция. Усадьба включает `ghost_whisper` и `ghost_testimony`,
`ghost_visions` — нет: в этом деле мистики нет. Знаки проверяются отдельной fixture.

### Экран (`web/mini_client/night-case-ui.js`)

- Выбывшему вкладка «Место» вместо ходов и действий показывает панель «Ты отстранён от
  расследования» (в деле с мистикой — «Ты — призрак дела»): вопросы к нему с кнопками «Да»/«Нет»,
  карточки воспоминаний с кнопками «На доску» и «Передать лично» и выбором получателя, знаки
  (только с `ghost_visions`) и список уже переданного. Подтверждение говорит «это твоё
  единственное действие в этом окне» вместо цены в ОД.
- Живому вкладка «Улики» показывает панель «Вопросы отстранённым» («Вопросы призракам»):
  все вопросы с ответом или сроком и форму «Кого спросить» + текст до 200 символов + «Спросить · 1 ОД»;
  в деле с мистикой ниже — «Явления».
- Личная находка, полученная шёпотом, подписана «Передано лично: <персонаж> — отстранённый игрок»
  («— призрак дела»). Чат выбывших называется по делу: «Отстранённые» или «Призраки».
- Выбор получателя и черновик вопроса переживают перерисовку экрана при опросе, как черновик беседы.
