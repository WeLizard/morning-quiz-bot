# Night City v2: исполнимое дело и чистое ядро

Дата: 2026-11-15. Статус: технический контракт следующего среза, **на независимом ревью**; код v2 ещё не реализован.
Основание: [runtime contract](../NIGHT_CITY_RUNTIME_CONTRACT.md), [MQB-010](../MQB-010-night-city-weekly-stages.md),
[weekly design](../NIGHT_CITY_WEEKLY_DESIGN.md), ответы владельца 15/28 октября и 15 ноября.
Это контракт pure kernel, не разрешение production и не описание уже работающего хранения.

## 1. Законченный первый цикл и границы

Первый результат: учебное дело на **каждый из составов 4, 5, 8, 12**, не копия усадьбы:
старт → личное досье → перемещение/осмотр/авторский NPC-диалог → личные находки →
доска → обвинение/слушание либо обязательное итоговое слушание → неизменяемый итог.
Параллельно проверяются уход, призрак, индивидуальный AFK, общий простой, восстановление
из строгого state codec, одинаковая команда и адресные проекции. Никаких БД, HTTP,
Telegram, provider calls, файлового журнала или второго симуляционного движка.

В первом kernel нет уничтожения улик, устранения Тенью, произвольных предметных обменов,
AI-эффектов и модулей из линейки дел. Это **не** приёмка полного недельного режима:
неподдержанные эффекты/модули отклоняются загрузчиком, а не игнорируются.
Фракции, авторские личные цели, ложные показания, ошибки обвинения и NPC уже существуют.
Подтверждённый свободный ввод позже выбирает те же команды из `available_actions`;
нового пути исполнения для AI не будет.

Решение владельца **2026-11-15**: при общем простое персонажи сохраняются.
Whole-table idle имеет приоритет над индивидуальным AFK4: детали в §8.

## 2. Версии, загрузка и обозначения

- Новый идентификатор документа: `schema: "night-city-case/2"`. Новый строгий state codec:
  `state_schema: "night-city-state/1"`. Первая поддерживаемая пара правил:
  `ruleset_ref: {"id":"night_case.core","version":1}`.
- Дело, rules snapshot, версия движка и варианты библиотечных эпизодов закрепляются при старте.
  В первом срезе библиотечные эпизоды отсутствуют: `episode_refs=[]`; непустой список отвергается.
- Везде `additionalProperties:false`. В описанных ниже объектах **все поля обязательны**,
  если рядом нет `?`. `?` означает только указанное значение по умолчанию; загрузчик
  материализует defaults в отдельном compiled-представлении, не переписывает исходный JSON.
- `ID`: ASCII `^[a-z][a-z0-9_]{1,31}$`; ссылки типизированы коллекцией. `AccountId`/`GameId`
  — непрозрачные платформенные строки, не Telegram IDs и не content IDs.
  Списки ID без повторов; числовые поля — exact integer, boolean числом не считается.
  `VariantSet` — `"all"` или непустой список существующих variant IDs.
- `Body={text:string[1..1200], mentions:FactId[]}`; `Label=string[1..80]`;
  подстановки только `{c:id}`, `{t:id}`, `{t:id|gen|dat|acc|ins|prep}`.
  `mentions` описывает затронутую пропозицию, **не** заверяет её истинность.
  `Art={asset_id:ID, alt:string[1..300]}`; `art?=null`. Asset разрешает каталог, не путь файловой системы.
- `Window=1..14`; историческое положение до начала — только `at.window=0`.
  Все runtime timestamps — aware UTC, JSON-форма RFC3339 с `Z`, точность микросекунд.
  `now == deadline` означает истечение; скрытых чтений часов нет.
- Ограничения v1 loader сохраняются: UTF-8, максимум 2 MiB, глубина 64, 100000 узлов,
  запрет повторных ключей, nonfinite, внешних schema refs и неизвестных версий.
  Collection limits: locations 4..10, characters 12..24, facts 6..120,
  observations 6..150, actions 1..200, dialogues 0..40, variants 2..5, events 0..40.
  Варианты, команды и дочерние узлы не могут вводить произвольный expression/string eval.

`content_hash` = SHA-256 исходного принятого документа: UTF-8 JSON, sorted object keys,
compact separators, порядок массивов сохранён. Это тот же алгоритм, что Task 1.
`rules_hash` считается отдельно по полностью материализованному снимку правил.
Воспроизводимость хранит также `compiler_version`; изменение defaults требует новой версии ruleset.

### Как использовать v1 без drift

`case.schema.json` и семантика `night-city-case/1` остаются неизменными. V1 — формат
авторского черновика, он **не** принимается `start`. V2 получает отдельный
`case.v2.schema.json`; исполнимая схема самодостаточна, без внешних `$ref`.
ID/Label/Body.text и формы героя повторяют ограничения v1 с parity-тестами на общих
валидных/невалидных значениях. Дополнительный `Body.mentions` — явно новый v2-контракт.
`meta` сохраняет поля/типы v1, с ограничениями v2: `duration` отсутствует либо `week`,
`modules=[]`, `players={min:4,max:12}`. `compositions` ниже задаёт реальную поддержку;
диапазон `meta.players` не означает автоматически поддержку 6/7/9/10/11.

Перенос v1 → v2 — отдельная авторская операция, без silent coercion: `evidence.found`
превращается в доступное действие и результат, `testimony` — в claim, `requires` —
в guards знания, `key_for` исчезает в пользу одного `variant.key_proofs`.
Скрипт конверсии может подготовить **draft**, но не придумать входы диалогов, смысл
доказательства или цель героя. Оригинал/хеш сохраняются в отчёте происхождения вне runtime case.

## 3. Точный корень и узлы контента

Корень:

```text
schema, meta, ruleset_ref, setting, locations[], characters[], facts[],
observations[], actions[], dialogues[], variants[], compositions[],
flags[], initial, events[], endings, victory, episode_refs[], items[]?
```

`setting={blurb:Body, crime:Body, days:7}`. `flags[]={id:ID, initial:bool}` — максимум 64,
чтобы один batch всегда помещался в закрытый `world_changed` payload. Это технический
бюджет core/1. Флаги — только
**публичные** флаги сюжета; скрытых флагов в core/1 нет. `victory={framed_limit:int[1..12]|null}`,
`null` означает: ошибочное обвинение не завершает дело само по себе.
`initial={public_observations:ObservationId[], personal:[{character:CharacterId, observations:ObservationId[]}]}`.
Все начальные observations обязаны существовать во всех поддерживаемых вариантах.
Тайны, связанные с конкретным вариантом, задаются в досье героя, а не начальной публичной выдаче.

| Узел | Поля и смысл |
| --- | --- |
| `locations[]` | `{id, name:Label, body:Body, connects:LocationId[], art?}`. Граф симметричный, связный, без self-loop. Все связи публичны; тайные проходы в core не поддержаны. |
| `characters[]` | `{id, title:Label, title_forms:{gen,dat,acc,ins,prep}:Label, gender:"f"\|"m", bio:Body, can_be_player:bool, faction:"investigation"\|"shadow"\|"independent", home:LocationId, schedule:[{windows:Window[],location:LocationId}], secrets:[{variants:VariantSet,body:Body}], goal:{id,body:Body,when:VisiblePredicate[]}, ghost_memories:ObservationId[], art?, name?:Label, public?:Body, looks?}`. Нет имён игроков в контенте. `name` — имя героя по канону мира (правило П6), `public` — что о нём знают все; то же у каждого облика в `looks[]`, первый облик повторяет верхние поля. Имя носит один герой дела: любые облики могут встретиться в одной партии. `{c:id}` в тексте — имя облика партии, подпись игрока туда не попадает; персонаж игры носит имя облика, пул `npc_name_era` — запасной для дел без имён. |
| `facts[]` | `{id, body:Body, true_in:VariantSet\|"none", at?:{character:CharacterId,location:LocationId,window:0}}`. Пропозиции о мире; полный truth-set никогда не является клиентским полем. |
| `items[]` | `{id, title:Label, body:Body, location:LocationId\|null, art?}`. Ключевые предметы дела (правило П7): одно описание для ведущего, картинки и карточки улики. `location` — где предмет в начале, `null` — у героя или не на месте. |
| proof в `observations[]` | `{id,kind:"proof",title:Label,body:Body,proves:FactId[],exists_in:VariantSet,subject?}`. `subject` — ровно одно из `{item}`, `{location}`, `{character}`: о чём улика. `proves` непустой; каждый факт истинен во всех вариантах существования proof. |
| claim в `observations[]` | `{id,kind:"claim",title:Label,body:Body,asserts:FactId[],speaker:CharacterId\|null,exists_in:VariantSet,subject?}`. `asserts` может быть пустым; содержание не обязано быть истинным. |
| `compositions[]` | `{id,players:4\|5\|8\|12,player_characters:CharacterId[]}`. Ровно N различных `can_be_player` героев; все остальные герои являются NPC. В первом мини-деле ровно одна composition на каждое N. |
| `variants[]` | `{id,culprit:CharacterId,accomplices:CharacterId[],motive:Body,method:Body,key_proofs:ObservationId[],min_key:int[1..8],composition_ids:CompositionId[],final_text:Body}`. Ключи — proof, не claim; `min_key<=len(key_proofs)`. |

`culprit` не входит в `accomplices`. Виновный и сообщники получают faction shadow
независимо от default героя. После этого для каждого варианта/composition должен
оставаться хотя бы один human investigation; NPC-противник допустим.
Распределение персонажей между Account выполняется детерминированной seed-перестановкой
отсортированного списка участников; выбранные имена и формы обращения — отдельный
утверждённый roster input. Не имитируем достижение полной UX-приёмки «досье» этой перестановкой.
Всем 12 людям нужны личные цели; goal проверяется при финале по собственным знаниям/доске.

Расписание действует только на NPC со статусом active. Для каждого окна берётся
единственный `schedule` override либо `home`, если override нет. Повтор окна внутри
одного списка и пересечение двух overrides запрещены даже при одинаковой location.
Полное покрытие 14 окон не требуется: home задаёт явный default. Все получившиеся
назначения проверяются против scheduled locks/unlocks до старта; PC ходит командами
и не телепортируется по авторскому расписанию.

Предмет и его надпись — разные факты. Proof может доказывать «найден документ с подписью»;
утверждение «подпись настоящая» остаётся claim, пока другое proof его не подтвердило.
Запись знания хранит observation ID и происхождение, а не автоматически присваивает
истинность всем `mentions/asserts`. V6 не запрещает ложные показания `exists_in=all`.

### Правила дизайна П1–П9

Компилятор принимает любое правильно собранное дело. Соблюдает ли оно правила дизайна для всех
миров ([проект меню §2.1](NIGHT_CITY_MENU_DESIGN.md)), показывает отдельный отчёт:
`scripts/validate_night_case_v2.py <дело> --scope rules` (`domain/night_case_rules.py`).
У каждого правила статус `passed`, `failed` со списком мест в деле или `not_checked`:

- П2 — у каждого игрового героя есть диалог;
- П4 — у игрового героя нет постоянной стороны `shadow`, и он не в Тени во всех вариантах;
- П5 — не меньше 5 вариантов правды, у каждого картинка финала;
- П6 — у каждого облика каждого героя есть имя, «что знают все» и возраст;
- П7 — в деле есть предметы, и каждая ключевая улика ссылается на предмет, место или героя;
- П1, П3 — `not_checked`, пока движок играет только составы 4/5/8/12;
- П8 (канон мира) и П9 (контекст ведущего) — не поле дела; проверяются ревью канона и тестами кода.

Отчёт `passed` только когда все девять правил `passed`. Пока этот отчёт не входит в условие
регистрации дела: регистрация потребует его, когда первое дело будет доведено до правил.

### Действия и диалоги

`actions[]`:

```text
{id, kind:"examine"|"interact", location:LocationId, label:Label,
 available_when:VisiblePredicate[], repeat:"player_window"|"player_game",
 outcomes:Outcome[], fallback:Body}
```

Стоимость — 1 AP из rules snapshot, а не присланное клиентом число. Действие требует
присутствия actor в `location`; осмотреть одну точку и осмотреть другую — разные IDs.
Повторный запуск по новому command ID после исчерпания repeat недоступен **независимо**
от того, была ли найдена улика. Replay прежнего command ID возвращает прежнюю receipt.

`dialogues[]`:

```text
{id, character:CharacterId, entry_node:NodeId,
 nodes:[{id:NodeId, prompt:Body,
         options:[{id:OptionId, label:Label, available_when:VisiblePredicate[],
                   outcomes:Outcome[], fallback:Body, next_node:NodeId|null}]}]}
```

Node/option IDs уникальны внутри диалога/узла. `next_node` остаётся в том же диалоге;
`null` завершает разговор и сбрасывает cursor на entry для следующего обращения.
Входы/связи/`prompt` общие для вариантов; prompt не раскрывает нового знания.
`talk(dialogue_id,node_id,option_id)` стоит 1 AP и выбирает результат реплики.
Нужен текущий cursor, живой NPC в одном месте; NPC-only и controller различаются.
Если персонажа играет человек, авторское меню NPC недоступно: с ним работает социальный канал.
У бывшего PC после ухода авторские ответы и AI-реплики **всегда запрещены**.
Проверка достижимости учитывает такую подстановку; ключевой proof не может зависеть
только от NPC-разговора с потенциальным человеком.

`Outcome={id, guard:{variants:VariantSet, when:VisiblePredicate[]}, body:Body, effects:Effect[]}`.
Не более 8 outcomes на действие/option. Все совпадения вычисляются **внутренне**:
ровно одно → применить; ноль → авторский fallback без эффектов; больше одного →
ошибка контента, переход атомарно отменён и внутренний diagnostic. Публикационный
валидатор обязан доказать непересечение для поддерживаемых состояний; первый набор
ограничивает outcomes одним branch на variant, без перекрывающихся VariantSet.
Outcome/body/effects целиком никогда не отправляются в список доступных действий.

## 4. Конечные predicates/effects и отсутствие утечек через меню

`VisiblePredicate` — один из объектов ниже; список означает AND, пустой список true.
Нет произвольных NOT/OR/вложенных выражений, callback или пути к state.

| Вид | Точные поля | Источник проверки |
| --- | --- | --- |
| `window_in` | `{kind,from:Window,to:Window}` | Открытое окно, `from<=to`. |
| `knows` | `{kind,observation:ObservationId}` | Личные observations actor **или** публичная доска/начальная публичная выдача. |
| `published` | `{kind,observation:ObservationId}` | На доске есть запись с этим observation; claim не становится proof. |
| `flag_is` | `{kind,flag:FlagId,value:bool}` | Публичный флаг. |
| `at` | `{kind,location:LocationId}` | Собственное место actor. |

Goals используют тот же язык; при финале `window_in/at` оцениваются по последнему
игровому состоянию владельца, а не по NPC, занявшему его персонажа после ухода.
Для departed сохраняется его последнее player snapshot. В ядре нет авторской
команды «назначить победителем»: цели вычисляет движок.

`Effect`:

| Вид | Точные поля | Разрешённый контекст |
| --- | --- | --- |
| `grant_observation` | `{kind,observation:ObservationId,audience:"actor"|"public"}` | Outcome; actor — человек, вызвавший команду. Scheduled event допускает только public. |
| `set_flag` | `{kind,flag:FlagId,value:bool}` | Outcome или event; изменение и имя флага публичны. |
| `lock_location` | `{kind,location:LocationId,through_window:Window}` | Только scheduled event; конец не раньше текущего окна. |
| `unlock_location` | `{kind,location:LocationId}` | Только scheduled event. |

`events[]={id,window:Window,body:Body,effects:Effect[]}`. Они публичны и без variant
guards в core/1. В одном окне выполняются в порядке массива; одно event ID один раз.
Нельзя одновременно lock/unlock одного места в одном окне; публикационный gate отклоняет
конфликт. Lock запрещает **вход**, не запирает уже находящегося там человека: выход
разрешён. NPC-расписание не может вести в закрытое место; конфликт — ошибка контента.

`available_actions(case,rules,state,viewer,*,now_utc)` использует только PublicView + SelfView
и явное время, одинаковое с последующим quote/step.
Оно не читает variant, outcome guards, key_proofs, чужие знания, тайны или чужие места.
Проверяются phase/controller/status, собственные AP/fence, видимые prerequisites,
место, общеизвестные lock и использованный repeat. `knows` допустимо, потому что
игрок уже получил это знание; угадывание отсутствующего observation ID не считается знанием.

Одинаковые разрешённые проекции → одинаковый список действий, цены и публичные причины
отказа, даже если скрытые варианты различаются. Не раскрываем «такой улики в варианте нет»
или «нужен настоящий виновник». Скрытая проверка выполняется **после** принятия действия:
тот же расход и repeat, затем законная новая находка либо нейтральный fallback.
Раскрытие различий через полученную улику — ожидаемый результат расследования;
различие до действия через ID меню/ошибку/счётчик — утечка.

### Меню, свободные параметры и конкретный quote (контракт Task C)

Меню не перечисляет все возможные тексты `claim` и комбинации citations. Оно возвращает
`tuple[MenuEntry,...]`, закрытый union из двух форм:

- `MenuChoice={kind:"choice",entry_id:string[1..128],label:Label,quote:LegalAction}` —
  конкретный конечный выбор для move/act/talk/pin/ghost_share/seen/finish_window/forfeit.
- `MenuForm={kind:"form",entry_id:string[1..128],label:Label,
  command_kind:"claim"|"accuse"|"vote"|"final_vote",cost:0,
  subject_ids:CharacterId[],board_ids:BoardId[],hearing_id:string[1..128]|null}`.
  Точная схема params выбирается по command_kind из §6, не передаётся как произвольная
  JSON Schema. Claim имеет пустые subject_ids/board_ids и hearing_id=null;
  accuse/final_vote перечисляют допустимых подозреваемых и public board IDs;
  vote имеет subject_ids=[], текущий hearing_id и public board IDs. Остальные формы
  имеют hearing_id=null. Повторы ID запрещены; references разрешаются в текущей проекции.

Для заполненной формы используется
`quote_action(case,rules,state,actor,intent:CommandIntent,*,now_utc)->LegalAction`,
где `CommandIntent={kind,params}` соответствует **ровно** одному player command из §6.
Сначала строгая проверка полей/типов/границ params, затем та же visible eligibility,
что использует step. Quote не списывает AP, не выдаёт знания и не вычисляет outcome.
Истёкший deadline/недоступная команда дают тот же публичный отказ; hidden variant не читается.

`LegalAction` из Task 2 не меняется. В его `params` попадает immutable canonical JSON
конкретных проверенных параметров; selection_id/target_id стабильны для этой операции.
Task 2 `propose_action` выбирает **только из сервером материализованных quotes**.
Ни AI, ни клиент не расширяют LegalAction произвольными аргументами после quote.
Подтверждение заново получает quote для того же intent и сравнивает с предложением;
принятая команда всё равно исполняется единственным step. Меню не является правом на действие.

`resource_revision` — хеш только релевантных **видимых** зависимостей конкретного quote:
game/actor/window fence, собственные actor_seq/AP/location, необходимый dialogue cursor/repeat,
только упомянутые prerequisites и нужные target status/lock/hearing ID+stage/citation IDs.
Не включаются общий public revision, чужие actor_seq/AP, чужие голоса, чужие диалоги,
не относящиеся к действию флаги и новые несвязанные записи доски. Проверка знания хранит
булевы значения нужных knows/published predicates, а не хеш всего private inventory.
Для citations достаточно существования выбранных неизменяемых board records и их IDs.
Изменение цены/цели/команды/params дополнительно сравнивается самими полями LegalAction.
Таким образом чужой независимый pin/ход не отменяет подтверждение, но закрытие нужного
места, смена своего cursor или исчезновение права голосовать отменяют устаревший quote.
Exact JSON/canonical hashing совпадает с §6; resource_id — стабильный собственный scope,
а не общий «ресурс всей партии». Это дополнение не меняет конструкторы Task A/B.

## 5. Снимок состояния, проекции и адресные события

Полный `KernelState` существует только внутри чистого вызова и защищённого codec.
Его нельзя сериализовать в HTTP или напрямую присвоить `games.state`.
Будущая PG-интеграция отдельно разделяет публичную и запечатанную части.

Точный state envelope:

```text
state_schema, game_id, case_ref{case_id,case_version,content_hash},
ruleset_ref, rules, rules_hash, compiler_version, engine_build,
sealed{variant_id,seed,composition_id,assignments:[{account_id,character_id}]},
clock{timezone,window_idx,window_seq,timer_seq,opened_at,closes_at,early_not_before,
      slot_cursor,phase,opening_pending,freeze_at,forget_at,resume_receipts[]},
players[], npcs[], public{flags,locks,observations,board,chronicle,revision,framed_count},
knowledge[], private_events[], dialogue_cursors[], action_uses[], event_uses[],
hearing|null, final_ballots[], receipts[], idle_windows, final|null
```

`phase=investigation|final_hearing|frozen|finished`; ordinary hearing — overlay.
Nullable времена представлены явным null. `slot_cursor` — последний потреблённый
регулярный local-date/time slot; не номер окна. Все maps в codec — массивы записей
с уникальным typed key, сортировка при кодировании, неизвестные поля отвергаются.
Для скалярных runtime полей: `*_seq`, `revision`, `knowledge_revision`, счётчики —
неотрицательные exact ints; `window_idx=1..14`, `last_seen_window=0..14`, `ap=0..3`;
`name=string[1..120]`, `finished_window/opening_pending/accepted/completed/met` — bool.
`slot_cursor={local_date:"YYYY-MM-DD",local_time:"HH:MM"}|null`;
`freeze_at/forget_at` и неоткрытые времена — UTC|null. Начальный state имеет
phase investigation, window_idx/window_seq/timer_seq=1, actor_seq/revisions/counters=0,
active players с AP=3, `last_seen_window=0`, пустые receipts/board/hearing/ballots/
event_uses/action_uses; затем применяет начальную выдачу и events окна 1 одним start batch.
Knowledge source и событие выдачи имеют стабильный детерминированный ID, даже на старте.
Старт не объявляет всех присутствующими: нужны реальный `seen` или принятое действие.

- `players[]`: `{account_id,character_id,name,status:active|fog|ghost|departed,
  location,ap,actor_seq,knowledge_revision,last_seen_window,missed_windows,
  finished_window,ghost_used_window|null,accusations_used,wrong_accusations,participated_windows[],
  departed_snapshot|null}`. Поля статуса не заменяют права аккаунта на Game.
- `npcs[]`: `{character_id,name,location,status:active|removed,origin:authored|former_player}`.
  Один персонаж управляется ровно одним PC либо NPC; former_player не наследует
  человеческие права, голос, награды или доступ к чужим знаниям.
  Removed NPC сохраняет запись/историю и последнюю location, но не перемещается,
  не разговаривает и не выполняет ghost actions; его статус публичен. NPC никогда не голосует.
- `knowledge[]`: `{account_id,observation_id,source:{kind:initial|action|dialogue|event|ghost,
  source_id,actor_character|null,location|null,window_idx}}`; append-only, повторная
  выдача того же observation не создаёт второе доказательство. Источники сохраняются.
- `board[]`: `{id,owner_account_id,kind:proof|claim,observation_id|null,text|null,source|null}`.
  Ровно две закрытые формы: authored запись имеет observation_id!=null, text=null,
  source!=null и kind, равный kind этого case observation (proof **или claim**);
  свободная заметка имеет kind=claim, observation_id=null, text:string[1..1200], source=null.
  Остальные сочетания запрещены. Авторская находка копирует неизменяемые kind/source,
  а её Body и speaker берутся из разрешённого observation, не из свободного text.
  owner_account_id — опубликовавший игрок; speaker авторского claim — исходный говорящий,
  и один не подменяет другого. Поэтому «NPC сказал» не становится заметкой от имени игрока.
  Для обоих authored kinds codec требует существующий источник того же observation:
  собственную knowledge владельца, public observation либо уже существующую authored
  public board запись; source должен совпадать с этим разрешённым источником.
  Self/forward board refs не обосновывают публикацию. Свободная заметка не может указать
  чужой source. Pin/ghost_share сохраняют эту форму; claim не становится proof и не
  увеличивает key count. Board ID детерминирован из команды.
- `dialogue_cursors[]`: `{account_id,dialogue_id,node_id}`;
  `action_uses[]`: `{account_id,action_key,window_idx|null}`;
  `event_uses[]`: EventId; `public.locks[]`: `{location,through_window}`.
- `public.observations[]`: `{observation_id,source}` с той же формой source, что knowledge;
  `public.flags[]`: `{id,value}`; `public.chronicle[]`: только Event с public audience.
  `final_ballots[]`: `{account_id,suspect:CharacterId|null,citations:BoardId[]}`.
  `clock.resume_receipts[]`: `{outage_id,payload_hash}`; тот же ID с другим interval — отказ.
  `departed_snapshot`: `{location,known_observations:ObservationId[],window_idx}` либо null.
- `receipts[]`: `{actor_key,command_id,payload_hash,accepted,code,actor_revision,result_ref:null|{kind:"event",event_id}}`.
  `result_ref` внутренний адрес личного результата, не вложенное содержимое.
- `final`: `{code,at,variant_id,culprit,key_proofs,goal_results[],reward_facts[]}`.
  Только после finish правду можно включить в разрешённую участнику postmortem-проекцию.
  `goal_results[]={account_id,goal_id,met:bool}`; все accounts — участники исходного roster.

Одинаковая форма source не означает одинаковую аудиторию его значений. При явном
`pin` владелец осознанно публикует неизменяемое **историческое** происхождение своей
находки: кто/где/в каком окне получил authored proof или claim. Это не текущая location персонажа;
подпись не обновляется после перемещения и не выдаёт последующие действия.
Для автоматического public grant/event source строится отдельным whitelist:
`actor_character=null, location=null`, кроме полей, которые само авторское публичное
событие явно объявляет публичными. В core/1 без такого объявления оба поля всегда null.
Нельзя автоматически копировать private source/current location из state в public grant.
Канонический источник уже опубликованной authored записи не переписывается при повторной выдаче;
исходный private source остаётся у владельца, явный pin переносит его без искажения.

`Event={event_id,window_idx:Window,audience_seq:int[1..2^63-1],kind,
audience:{kind:"public"}|{kind:"accounts",ids:[AccountId]},payload}`.
Все поля обязательны, extras запрещены; bool/float не заменяют integer.
`window_idx` — курсор игрового окна при эмиссии, а не время UTC и не окно исторического
source. События закрытия k (hearing/status/final) имеют window_idx=k; события открытия,
scheduled effects, digest и AFK notice следующего окна — k+1. Frozen header тоже
помечен pending cursor k+1, хотя это окно ещё не открыто. Terminal в окне 14 не создаёт
событий окна 15. Forgotten сохраняет pending cursor, не откатывает его ради статистики.

Общие exported helpers принадлежат `domain/night_case_state.py`:

- `event_scope(audience)->str`: строгий audience object преобразуется в `"public"`
  либо `"account:" + account_id`; private core audience содержит ровно один ID.
- `event_id_for(game_id,audience,seq)->str`: `"evt_" + sha256(raw).hexdigest()`, где
  raw — UTF-8 кодировка JSON-массива `["night-city-event/1",game_id,event_scope(audience),seq]`,
  `ensure_ascii=False`, `separators=(",",":")`, без BOM/перевода строки, без усечения хеша.
  seq проверяется как точное целое в указанном диапазоне.

Один engine emitter `_event` берёт следующий audience_seq только из своего stream.
В каждом полном stream последовательность непрерывна 1..N, `(scope,seq)` уникален,
а window_idx не убывает с ростом seq. Public IDs/seq не зависят от private событий;
личный stream не зависит от чужих private событий. Повтор команды останавливается
receipt до эмиссии и не создаёт новых событий. Codec проверяет scope/seq/ID и порядок;
public chronicle хранится по audience_seq, private_events — по `(event_scope,audience_seq)`,
а не по hash ID. Последовательности не обрезаются ради сводки.

Это уточнение ещё не выпущенного state-контракта перед совместной правкой B/C;
сигнатуры конструкторов не меняются. Оно не объявляет существование или миграцию PG states.

### Закрытый Event.payload core/1 — общий для engine и codec

`EventId`, `BoardId`, `HearingId`, source_id — непрозрачные строки 1..128; content IDs
остаются ID из §2. Все перечисленные поля обязательны, null указан явно, extras запрещены.
Body соответствует §2; timestamps — UTC/Z. Массивы reference IDs без повторов.
Для private kinds audience **ровно один** AccountId, принадлежащий исходному roster;
core/1 не выпускает групповых private events. Audience public не содержит ids.

| Event.kind | Точный payload | Audience и дополнительные инварианты |
| --- | --- | --- |
| `window` | `{window_idx:Window,phase:"investigation"|"final_hearing"|"frozen"|"finished",opened_at:UTC|null,closes_at:UTC|null}` | Public. Это состояние активного окна после перехода, не сообщение о private действии. Для investigation/final_hearing оба времени заданы и opened_at < closes_at; для frozen/finished оба null: активного окна нет. |
| `status` | `{character_id:CharacterId,controller:"player"|"npc",status:"active"|"fog"|"ghost"|"removed"}` | Public. Player допускает active/fog/ghost; NPC — active/removed. При forfeit/AFK4 событие сообщает npc/active; departed — состояние прежнего player record, не второго контроллера. Location/AccountId сюда не входят. |
| `hearing` | `{hearing_id:HearingId,suspect:CharacterId,stage:"opened"|"closed",resolution:null|"not_supported"|"not_proven"|"wrong"|"solved"|"cancelled",resolve_window:Window}` | Public. Opened требует resolution=null, closed — ненулевое. Cancelled означает прекращение overlay при другом terminal outcome. Нет key count, истинного виновника или чужих голосов. |
| `final` | `{code:"solved"|"shadow_framed"|"no_investigators"|"unresolved"|"forgotten",at:UTC}` | Public. Sealed поля, роли, goal/reward details здесь запрещены; postmortem формируется отдельной разрешённой проекцией. |
| `action_result` | `{body:Body,observation_ids:ObservationId[0..150]}` | Private, только actor. ID содержат только уже разрешённые этому адресату observations; fallback/служебный результат может иметь []. Body — разрешённый авторский или фиксированный системный текст, не весь Outcome. |
| `observation_granted` | `{observation_id:ObservationId,source:Source}` | Private для одной личной выдачи либо public для public grant. Source ровно из §5: kind, source_id, actor_character, location, window_idx; source.window_idx совпадает с envelope.window_idx выдачи. Public redaction ниже обязательна. |
| `window_digest` | `{window_idx:Window,observation_ids:ObservationId[0..150],event_ids:EventId[0..64]}` | Private, один адресат. Payload window_idx — суммируемое окно, envelope window_idx — окно эмиссии. Точные правила отбора ниже; self/future/чужие refs запрещены. Сводка не создаёт знаний. |
| `afk_notice` | `{window_idx:Window,missed_windows:int[1..14]}` | Private, один адресат. Payload window_idx=k — пропущенное закрытое окно; envelope window_idx=k+1 — следующее реально открытое окно. Не подменяет digest; никаких observation/event refs. |
| `board` | `{board_id:BoardId}` | Public. Ссылается на уже созданную public board запись, как для pin, так и для claim. Не копирует private исходник в payload. |
| `scene` | `{content_event_id:ID,body:Body}` | Public. Только авторское scheduled event: content_event_id ссылается на events[].id, а body равен разрешённому телу этого события. Не используется для private Outcome или AI-кандидата. |
| `world_changed` | `{flags:[{id:FlagId,value:bool}],locks:[{location:LocationId,through_window:Window|null}]}` | Public. Flags 0..64, locks 0..10, хотя бы один массив непустой; IDs внутри каждого уникальны. Это изменившиеся значения, не полный state. null снимает lock. Никаких actor/cause/private refs. |

Один world_changed после batch объединяет фактические set_flag/lock/unlock/истечение locks;
неизменившиеся значения пропускаются, списки сортируются по ID. Это единственный дополнительный
kind для видимых изменений мира: универсального effect payload нет. Всего в core/1
ровно 11 перечисленных kinds. Scheduled событие
может породить scene и world_changed; private действие с публичным set_flag — только
публичный world_changed плюс свой private action_result. Pin/claim представлены board,
а переход окна, персональная сводка и напоминание — window, window_digest и afk_notice.

### Отбор сводки и порядок истории

При каждом фактическом открытии окна k>1, после его opening batch, создаётся ровно
один window_digest каждому неушедшему человеку (active/fog/ghost): envelope.window_idx=k,
payload.window_idx=k-1. Кандидаты — уже существующие public и собственные private
события с envelope.window_idx=k-1. Window_digest и afk_notice исключаются. Никакие
события текущего/более старого окна или чужой аудитории не попадают в эту сводку.
Открытие после wake выполняет тот же отбор один раз; при входе в freeze opening_pending
не создаёт digest/notice pending-окна. Terminal не открывает дополнительное окно.

Порядок отбора детерминирован: сначала public stream по audience_seq, затем собственный
private stream по audience_seq; сохраняются последние 64 кандидата этого порядка.
Это технический приоритет групп при ограничении объёма, **не** сравнение реального времени
между streams. Внутри каждой группы сохраняются её самые поздние события; вся история
остаётся в state. event_ids выдаются в том же порядке, без повторов.

Observation_ids — отсортированное по ID объединение observations из выбранных
observation_granted, action_result.observation_ids и authored board записей выбранных
board events. Каждый observation реально доступен адресату через собственную knowledge,
public observations или public authored board (proof/claim). Свободный claim без
observation_id не выдумывает ссылку. Знание авторского claim не удостоверяет его истинность.
Старые знания не добавляются лишь потому, что остаются в inventory; для пустого отбора
оба списка пусты. Codec проверяет точное соответствие выбранным events и разрешения.

Исключение для старта: initial digest имеет envelope/payload window_idx=1 и создаётся
после всех initial grants. Его кандидаты — **только** public и собственные private
observation_granted с source.kind=initial, соответствующие initial выдаче этого дела.
Это явный снимок начальных знаний, а не полная публичная история окна 1; dynamic actions,
scene/world_changed/board и последующие выдачи не входят. Применяются те же предел и
порядок отбора. Личные referenced events имеют audience_seq меньше sequence сводки.

Codec отвергает self/forward refs: для обычной сводки refs относятся строго к прошлому
окну, private refs также имеют меньший audience_seq; неубывание window_idx в каждом
stream запрещает дописывание backdated событий. Для initial digest разрешено лишь
описанное происхождение initial, а не произвольное public событие того же окна.
Публичная и личная истории восстанавливаются раздельно по своим seq с группировкой
по игровому окну. Общий точный wall-clock порядок public/private streams не обещается.

Для **автоматического** public observation_granted Source имеет actor_character=null,
location=null; kind="event", source_id равен его собственному публичному event_id.
Начальная public выдача допускает kind="initial" с публичным start-event ID.
Таким образом даже source_id не раскрывает ID private dialogue/action и его место.
Явный pin не выпускает копию private source как observation_granted: provenance
сохраняется в публичной board записи по воле владельца и относится к прошлой находке.
Повторная выдача не переписывает существующий source. Codec проверяет audience/refs
по состоянию и отвергает частный event в chronicle, публичный — в private_events,
и digest с чужим event_id. Engine использует этот же закрытый union, а не свою схему.

Ни приватный event, ни его счётчик/время/ID не попадают в публичную chronicle.
Клиентская revision = public revision + собственная revision, не общий action counter.
`private_events` содержит адресные авторские результаты и их тексты для восстановления
result_ref после decode_state; `Transition.events` — только новые события текущего вызова.
Нельзя хранить историю лишь во внешнем in-memory списке теста и объявить codec полным.
Это описание pure snapshot; будущая PG-разбивка хранит такие записи отдельно с теми же ACL.

`project(...,viewer)` возвращает explicit whitelist: публичное состояние и доску,
свою роль/цель/тайну, собственные знания/AP/cursor/receipt references и замеченных
NPC/людей в **своей текущей локации**. Для `viewer=None` только публичная часть,
без списка всех реальных мест. Нельзя получить private snapshot «организатора» по умолчанию.
Свой faction shadow знает назначенную ему правду по правилу дела; narrator payload
всё равно не получает sealed целиком. Ghost видит свои сохранённые знания, public board,
но не новые чужие тайны. Departed не получает новые личные открытия.

## 6. Команды, отказы и replay

`Actor=PlayerActor(account_id)|SystemActor`; actor передаётся доверенным caller отдельно,
а не берётся из пользовательского JSON. Envelope игрока:
`{command_id:string[8..64],kind,window_idx,window_seq,actor_seq,params}`.
Системный envelope: `{command_id,kind,window_seq,timer_seq,params}`. Param union строгий:

| kind | params | Цена/эффект |
| --- | --- | --- |
| `move` | `{location}` | 1 AP; соседнее незакрытое место. |
| `act` | `{action_id}` | 1 AP; §3/4. |
| `talk` | `{dialogue_id,node_id,option_id}` | 1 AP; §3. |
| `pin` | `{observation_id}` | Бесплатно; только полученная actor находка. |
| `claim` | `{text:string[1..1200]}` | Бесплатная публичная неподтверждённая заметка. |
| `seen` | `{}` | Бесплатно; отмечает присутствие, возвращает fog в active. |
| `finish_window` | `{}` | Бесплатно; готовность закрыть окно; новый успешный ход снимает отметку. |
| `accuse` | `{suspect:CharacterId,citations:BoardId[0..5]}` | Один активный иск; правила §7. |
| `vote` | `{hearing_id,choice:"support"|"oppose",citations:BoardId[0..5]}` | Голос обновляем до закрытия, NPC/ghost не голосуют. |
| `final_vote` | `{suspect:CharacterId|null,citations:BoardId[0..5]}` | Только итоговое слушание; null — воздержаться. |
| `ghost_share` | `{observation_id}` | Один раз в окно, бесплатно; только заранее разрешённая ghost_memory, уже известная этому ghost; публикуется как прежнее знание. |
| `forfeit` | `{}` | PC → departed, персонаж → former_player NPC; явно необратимо в этой партии. |
| `system.tick` | `{expected_due_at}` | Только SystemActor; §8. |
| `system.resume` | `{outage_id,unavailable_from,resumed_at}` | Только SystemActor; подтверждённый caller простой, §8. |

Личные беседы/чат — часть будущего application с ACL; kernel принимает только
их подтверждённый presence через `seen`. Не добавляем незаявленное хранение свободной
переписки в pure state. Это не мешает первому циклу действий/доски; приёмка общения
остаётся незакрытым пунктом следующих срезов.

Порядок `step`:

1. Проверить codec/case hash/ruleset и trusted actor membership. Найти receipt по
   `(game,actor_key,command_id)` **до** fence/времени: тот же canonical payload hash →
   вернуть прежнюю receipt без events/расхода; другой payload → `command_id_conflict`.
2. Для нового player command проверять due time, phase, window fence и actor_seq.
   При наступившем deadline вернуть `deadline_pending`, не выполнять скрытый implicit tick;
   application сначала проводит SystemActor tick и возвращает свежую проекцию.
3. Проверить публичную доступность ровно теми же функциями, что меню; затем применить
   outcome/effects, AP, собственный actor_seq и private/public revisions атомарно.
4. Проверить терминальные условия в порядке §7; сформировать адресные events,
   receipt и следующий `due`. Входной state не мутировать.

Точный `payload_hash`: SHA-256 compact UTF-8 JSON, sorted object keys,
`ensure_ascii=false`, `allow_nan=false`, исходный порядок массивов. Для игрока
хешируется объект **ровно** `{kind,window_idx,window_seq,actor_seq,params}`;
для системы — `{kind,window_seq,timer_seq,params}`. `command_id` исключён: он часть
ключа receipt вместе с game и trusted actor_key. actor_key — `account:<AccountId>`
или `system`, game берётся из state. Схема команды/params проверяется до fingerprint:
неизвестные поля, некорректные типы, повторные JSON-ключи и неканонический timestamp
отвергаются; нет молчаливых defaults, преобразования boolean в int или удаления полей.
Перестановка ключей объекта не меняет hash, перестановка citations в массиве меняет.
Replay возвращает сохранённые code/accepted/actor_revision; не освежает их по текущему
state и не увеличивает ни actor_seq, ни public/private revision.

Обычные отказы: `not_participant`, `stale_context`, `deadline_pending`,
`action_unavailable`, `command_id_conflict`. Существование скрытого узла и его
вариантная принадлежность не уточняются. Отказ не расходует AP и не увеличивает actor_seq;
для вошедшего участника receipt отказа сохраняется как данные для replay.
Внешняя квитанция — только `{accepted,code,actor_revision}`, содержимое результата
перечитывается через авторизованную проекцию. Чужому аккаунту receipts недоступны.

Чистая функция доказывает последовательную идемпотентность только на переданном state.
PG-транзакции, уникальный command key и атомарный reserve в будущем обязательны;
две независимые копии state сами по себе не защищают от гонок.

## 7. Слушания, ошибочные обвинения и финал

Принятые правила: обвинение со второго дня, не более одного активного; proof важнее claim;
неверно обвинённый становится ghost; на седьмой день итоговое слушание обязательно.
Техническое разрешение недоопределённых деталей core/1:

- Обычный иск доступен в окнах **3..12**, один расход права обвинения на игрока.
  Иск, поданный в окне k, открывает слушание немедленно и закрывается **при закрытии k+1**:
  участники получают одно полное следующее окно. В окне 13 идёт сбор последних улик;
  окно 14 целиком отдано финальному голосованию. Это предотвращает наложение двух
  слушаний; cutoff/длина явно записаны в rules snapshot, а не спрятаны в коде.
- `hearing={id,accuser,suspect,opened_window,resolve_window,eligible_accounts[],
  initial_citations[],votes:[{account_id,choice,citations[]} ]}`.
  Список eligible фиксируется при создании: human active, не fog/ghost/departed.
  Для подсчёта исключаются ставшие ghost/departed/fog; возвращение не расширяет
  этот список до следующего слушания. Кворум: support > половины оставшегося eligible;
  N=0 или ничья — нет поддержки. Отсутствующий голос не считается support.
- Citation должен ссылаться на существующую public board запись. Для результата
  берётся объединение proof из initial citations и всех допустимых votes, без дублей;
  «oppose» не скрывает объективно опубликованное доказательство. Claims не дают key count.
- Нет поддержки → иск закрыт без отстранения. Поддержка + верный suspect + достаточные
  variant.key_proofs → `solved`. Поддержка + верный suspect + мало ключей → одинаковое
  сообщение «Обвинение не доказано», игра продолжается. Поддержка + неверный suspect →
  отстранение suspect, счётчик framed увеличен, игра продолжается, если не сработала
  явная victory-политика. Текст не раскрывает истинного виновника до финала.
  Для human отстранение означает player.status=ghost; для NPC — npc.status=removed.
  NPC не превращается в фиктивного игрока-призрака. Уже ghost/removed подозреваемый
  не может быть целью нового обычного обвинения; это публичная проверка доступности.
- `victory.framed_limit=null` разрешает противоречие старых §6.4/6.5 в пользу обычного
  продолжения. Ненулевой авторский лимит явно включает терминальную победу Тени на
  N-м ошибочном осуждении; первый учебный case имеет null. Дело не получает этот
  режим случайно из слова «ошибка» или названия ending.
- В начале окна 14 phase=`final_hearing`; у каждого active human отдельный
  `final_vote`, даже если он раньше потратил право обычного иска. На закрытии окна
  выбирается suspect со строгим большинством активных людей. Если он истинный и
  опубликованных cited keys достаточно — solved, иначе `unresolved`. Никаких
  дополнительных суток, NPC-голосов или бесконечного повторения финала.
  Считаются последние ballots тех людей, кто остаётся active к закрытию. Все их
  citations, включая голос за другого suspect или null, объединяются в один набор
  публичных proof по observation ID. Повторы и claims не повышают key count.
  При N=0 или отсутствии строгого большинства итог unresolved, без случайного tie-break.

После **одной** принятой команды/effect batch порядок терминальных причин:
`solved` → `shadow_framed` → `no_investigators` → `unresolved` (закрытие окна 14) →
`forgotten` (срок заморозки). Только первый итог применяется, награды/финальные события один раз.
`no_investigators` означает отсутствие оставшихся human investigation вследствие
отстранения/явного ухода/индивидуального AFK; общий простой сначала проходит политику §8.
Заморозка не финал. `accusation_unproven` не ending, а неокончательный результат слушания.

`endings` — объект с **ровно** ключами `solved,shadow_framed,no_investigators,unresolved,forgotten`,
значения Body. При solved/unresolved движок добавляет `variant.final_text` в postmortem;
само наличие authored ending не создаёт новый trigger.
`reward_facts` — вычисленные данные `{account_id,participated_windows,total_windows,
completed,goal_met,faction_won,wrong_accusations}`. Числовые награды в ядре пока не начисляются:
не вводим новые коэффициенты репутации вместо принятия соответствующего этапа.
`faction_won`: investigation при solved, shadow при shadow_framed/no_investigators/unresolved;
при forgotten никто. Independent получает только свой goal_met, не фиктивную общую победу.
`participated_windows` в reward facts — количество уникальных окон с presence;
`total_windows` — число фактически открытых окон до финала. Forgotten не создаёт штрафов.
Число открытых окон снимается до финализации: `window_idx - int(opening_pending)`;
pending cursor не уменьшается ради reward facts, иначе нарушится порядок event streams.

## 8. Время, DST, простой и AFK

Полный `rules` для `night_case.core@1`:

```text
{timezone:IANA,
 slots:["09:00","19:00"],quiet_start:"23:00",quiet_end:"08:00",
 window_count:14,ap_per_window:3,move_cost:1,act_cost:1,talk_cost:1,
 early_min_seconds:1800,outage_extension_min_seconds:3600,
 outage_extension_max_seconds:21600,afk_notice_windows:1,afk_fog_windows:2,
 afk_depart_windows:4,freeze_after_idle_windows:6,forget_after_days:14,
 first_accusation_window:3,last_ordinary_accusation_window:12,
 accusations_per_player:1,final_hearing_window:14,
 support_policy:"strict_majority",idle_policy:"table_idle_first"}
```

В первом profile числа фиксированы принятыми решениями и явно указанными выше
техническими выборами; будущий иной preset получает свой ruleset version.
`start` открывает окно 1 в заданный `now_utc`. Первый конец — ближайший регулярный slot
**не раньше** `opened_at+30min`; короткий старт перед границей не создаёт минутного окна.
Обычный следующий конец — первый slot после открытия, удовлетворяющий этому минимуму.
Сами 09/19 считаются локальными датами через `zoneinfo`, не прибавлением 10/14/24 часов UTC.

- DST: неоднозначный локальный slot выбирает более поздний UTC (`fold=1`);
  несуществующий slot переносится на первый существующий local instant после gap.
  Проверка round-trip local→UTC→local обязательна. При совпавших UTC slots оставить один.
  `next_slot` всегда строго после переданного UTC; quiet-hour конец вычисляется тем же способом.
- Тихие часы не блокируют действия. Дедлайн внутри quiet hours переносится на их конец.
  Notification due вычисляется отдельно; отсутствие Telegram не влияет на фазу.
- Раннее закрытие: все не ghost/departed/fog люди отметили finish, активных хотя бы один,
  `now>=early_not_before`. Система закрывает текущее окно, **открывает следующее сейчас**,
  но его регулярный конец всё равно привязан к следующему 09/19 slot. Каждый early close
  снова требует 30 минут. Поэтому 14 окон могут закончиться раньше семи календарных дней,
  как и разрешённые ранние развязки; номер игрового дня = `(window_idx-1)//2+1`.
- `system.tick` закрывает **только одно** открытое окно за вызов и открывает следующее
  в фактический now; не прогоняет пропущенные сутки циклом. AP не копятся; обнуляются
  до 3 для active/fog, ghost/departed имеют 0. Истёкшие locks снимаются, затем применяются
  события нового окна, NPC расписание и личные сводки. Все эти шаги один batch.
- Подтверждённый простой передаёт caller, а не угадывает движок по редкому ходу игрока.
  `system.resume` идемпотентен по `outage_id`; interval должен быть UTC,
  `unavailable_from<=resumed_at==now`. Если deadline попал в интервал, старое окно
  сохраняется: `closes_at=after_quiet(now+clamp(duration,1h,6h))`; одно окно, без
  ретроактивного AFK/голосования. В остальных случаях дедлайн не меняется.
  После продления следующий конец снова регулярный slot. Нельзя передавать resume
  из player command. Непроверенный длинный провал worker должен быть классифицирован
  будущим application до tick; pure kernel не может установить факт недоступности сервера.
- Presence — `seen` или любое принятое player действие, записанное в текущее окно;
  GET/project не меняет state. Missed counter увеличивается только на реально закрытом
  окне. 1 → адресное afk_notice при следующем фактическом открытии окна; 2 → fog;
  4 → бывший PC/NPC при индивидуальном отсутствии. Напоминание не является window_digest;
  его payload указывает пропущенное окно, envelope — открытое следующее, как в §5.
- Если **ни один неушедший человек** не присутствовал в закрываемом окне, увеличивается
  `idle_windows`; любое закрытое окно с presence сбрасывает этот счётчик в 0.
  Это шесть **последовательных** пустых окон. Пока общий простой продолжается,
  AFK4-конверсия откладывается для всех.
  При шести таких окнах, если есть следующее окно, последнее окно закрывается ровно один раз, затем phase=frozen:
  сохраняются PC/знания, `window_idx` уже указывает на следующее окно, `opening_pending=true`.
  Его события/AP ещё не открываются, `opened_at/closes_at/early_not_before=null`.
  Первое `seen` до `forget_at` открывает это окно обычным batch, без расхода, и обнуляет table idle;
  вернувшийся становится active. Дедлайн получает ближайший slot с минимумом 30 минут,
  остальные пропустившие получают одну возможность вернуться в этом окне;
  затем обычная индивидуальная AFK4-конверсия возобновляется. Никаких замен людей задним числом.
  Закрытие окна 14 всегда обрабатывает финальное голосование/terminal outcome раньше
  freeze: окна 15 не существует, даже если одновременно достигнут idle_windows=6.
- Freeze хранит остаток hearing в **игровых окнах**, а не истекающий фоновый wall clock.
  Через 14×24 часа UTC заморозки — forgotten без штрафов; `seen` на границе уже поздно.
  `forfeit` никогда не отменяется политикой общего простоя.

Ближайший `Due={kind:"phase",at:UTC,window_seq,timer_seq,reason}` — минимум phase deadline,
early-close-not-before (если все готовы) и forget_at. Изменение due увеличивает только
`timer_seq`; player `window_seq` меняется при смене окна/phase, не при готовности другого
игрока или продлении того же окна. Старый системный fence не применяет переход дважды.
SystemActor tick, вызванный раньше `due.at`, не меняет state. Случай broken state → domain error,
карантин/retries/уведомление оператора выполняет будущий application, не бесконечный pure tick.

## 9. API и владение файлами следующей реализации

| Файл | Ответственность и публичный API |
| --- | --- |
| `domain/night_case_v2_format.py` | `load_v2(raw:bytes)->CaseV2`; `compile_v2(case,ruleset_registry)->CompiledCase`. Строгая схема, refs, supported-module gate, хеш; никакой публикации из успешного parse. |
| `domain/night_case_state.py` | Строгие frozen types, `encode_state(state)->bytes`, `decode_state(raw,case,rules)->KernelState`; общие `event_scope(audience)->str`, `event_id_for(game_id,audience,seq)->str` по §5. Все вложенные snapshot immutable; проверить версии/хеши/инварианты, receipt/knowledge ID uniqueness, event streams и разрешённые digest refs. |
| `domain/night_case_time.py` | `next_slot(after_utc,tz,rules)->UTC`; `after_quiet(at_utc,tz,rules)->UTC`; `resume_deadline(clock,outage,rules,now)->Clock`; только явные часы/пояс. |
| `domain/night_case_engine.py` | `start(case:CompiledCase,rules,roster,*,game_id,seed,now_utc)->Transition`; `step(case,rules,state,actor,command,*,now_utc)->Transition`. Единственный исполнитель predicates/effects/времени/финалов. |
| `domain/night_case_projection.py` | `project(case,rules,state,viewer)->GameView`; `available_actions(case,rules,state,viewer,*,now_utc)->tuple[MenuEntry,...]`; `quote_action(case,rules,state,actor,intent:CommandIntent,*,now_utc)->LegalAction`. Меню/quote/step используют общую visible eligibility; quote не применяет переход. Конструкторы Task A/B не меняются. |
| `domain/night_case_simulation.py` | `find_witness(case,rules,composition,variant,*,seed,budget)->SearchResult`; генерирует legal commands и вызывает **тот же** `step`, включая system.tick. |

`Transition={state,events:tuple[Event,...],receipt|null,due:Due|null}`. `start` не принимает
variant из пользовательского ввода: выбирает допустимый вариант deterministic RNG.
Он вызывает общий внутренний initializer в engine:
`_initialize(case,rules,roster,*,game_id,seed,composition_id,selected_variant_id,now_utc)->Transition`.
Production-валидатор V4 вызывает **тот же** initializer для явного перебора вариантов;
initializer всегда проверяет совместимость состава/варианта и применяет все начальные
правила. Это доверенный verification path, не debug-команда и не поле HTTP/user input.
Production simulation не импортирует tests; tests пользуются этим же внутренним API.
Seed/RNG version фиксируются; нельзя использовать process-random
Python `hash()`. Никаких глобальных random/clock, IO или хардкода имён `manor_lake`.
CompiledCase содержит весь секретный контент только на серверной стороне; его тип не DTO.

`roster={players:[{account_id,display_name}],npc_name_pool:[string]}` — вход доверенного
caller, имена уже прошли общую проверку имён. Accounts/имена уникальны; pool достаточно
велик для NPC без совпадений с людьми. После раздачи pool сортируется и перемешивается
отдельным deterministic RNG stream; выбранные NPC names сохраняются в state.
Раздача/variant/name streams независимы: изменение числа выброшенных имён не меняет виновника.
Name-pool/input hash включается в свидетельство start вместе с roster, не читается из внешнего
сервиса внутри start. Подбор по форме обращения и приёмка UI-досье остаются отдельным шагом;
mini fixtures заранее задают совместимые участников/персонажей и проверяют механику раздачи.

## 10. Доказательства V4/V11 и этап усадьбы

V4 ищет **существующий** путь через реальные commands/transitions для каждого
допустимого variant × composition, включая PC вместо всех потенциальных NPC.
Сбор знаний столом не означает автоматическое объединение private inventories:
симулятор явно делает `pin`, переходы, голоса и платит AP каждым человеком.
Нельзя сократить путь, проверив только связанность графа prerequisites.

`SearchResult.status=found|exhausted|inconclusive`:

- `found`: witness `{case_hash,rules_hash,engine_version,composition_id,variant_id,
  seed,roster,input_hash,start_at,steps:[{actor,command,now_utc,expected_receipt,state_hash}],final_code}`.
  Повтор witness через доверенный `_initialize`/step обязан воспроизвести state hashes и solved.
- `exhausted`: только полностью перебранное конечное пространство объявленной модели
  без пути. Указать search assumptions; отсутствие случайно найденного пути недостаточно.
- `inconclusive`: исчерпан time/state budget; V4=`not_checked`, не failed и не passed.

V4 доказывает разрешимость при своей политике сотрудничества, не победу против любого
саботажа и не литературную честность загадки. V3 сравнивает наблюдаемые результаты,
а не скрытый truth-set одинакового показания. V11 запускает фиксированные policies/seeds
до terminal без аварий; «ленивый» policy должен получить unresolved/forgotten, не зависнуть.
Публикационный отчёт разделяет структурные проверки, проверку проекций, witness,
эвристики и человеческую содержательную приёмку. Одной отметки «schema valid» недостаточно.

Приёмка core: оба способа solved (ранний/итоговый), unresolved, ошибочное обвинение,
NPC/PC подстановка, 4/5/8/12, ghost/forfeit, duplicate/conflicting command ID,
параллельные независимые actor fences в последовательной модели, altered hash/state,
DST, 30-часовой outage, idle6/freeze/restart/wake/forget и canaries во всех проекциях/events.
PG-гонки и устойчивость реального сервиса к перезапуску здесь не заявляются.

После принятия core — отдельные детальные планы модулей усадьбы:

1. `archive_requests@1`: запрос за AP, persisted pending delivery на **следующее игровое
   окно**, адресат и once key; выдача через тот же step. Не sleep и не обещание AI.
2. `version_archive@1`: явные связи версий документов/гипотез, архивирование без потери
   proof/source, compare/unarchive commands. Связи не выводятся из свободной прозы.
3. `turning_point@1`: авторский одноразовый trigger раскрытия/смены разрешённых целей;
   фиксированная правда преступления не переписывается. Изменение целей — versioned data,
   не arbitrary effect. Проверить продолжение уже идущих диалогов/слушаний и V4.

Только после регистрации поддержанных контрактов непустой `meta.modules` принимается
новым ruleset; отсутствующий интерпретатор блокирует старт. Все три варианта усадьбы
превращаются в данные с proof/claim и независимыми путями; `photographer` не заменяет ID
улики. Тайный проход «библиотека → погреб» разрешён владельцем 2026-11-15;
он открывается по зацепкам. В core/1 скрытые связи пока не поддержаны: исполнимый
контракт этого открытия добавляется на этапе модулей, с регрессиями V4.
Текущий Markdown-черновик не runnable, не проходит V4 по факту существования и не
подменяется упрощённым мини-делом. Полный цикл общения, визуальная сцена и rehearsal
остаются следующими явно проверяемыми срезами.
