# Черновики дел «Ночного города»

- **Статус:** `draft` — рабочий пакет для обсуждения, не канон и не игровые данные.
- **Дата:** 2026-10-23.
- **Основание:** запрос владельца проекта на черновики сюжетов без подключения к игре.
- **Что это:** одиннадцать черновиков дел — по одному для каждого мира. Ничего не добавлено в `case.schema.json`, не подключено к серверу, клиенту или админке.
- **Что это не меняет:** канон миров в [`worlds/canon/`](../worlds/canon/), [`NIGHT_CITY_CASE_SLATE.md`](../../NIGHT_CITY_CASE_SLATE.md) и [`MQB-010`](../../MQB-010-night-city-weekly-stages.md) остаются как есть.

## Состав

| Файл | Мир | Фабула | Модули | Статус |
|---|---|---|---|---|
| [`01_manor_lake_missing.md`](01_manor_lake_missing.md) | Усадьба у замёрзшего озера (`manor_lake`) | `missing` | `version_archive`, `turning_point`, `archive_requests` | черновик |
| [`02_night_express_extra.md`](02_night_express_extra.md) | Ночной экспресс (`night_express`) | `impostor` | `archive_requests`, `outsider`, `final_questions` | черновик |
| [`03_black_bay_returned.md`](03_black_bay_returned.md) | Чёрная бухта (`black_bay`) | `impostor` | `secret_identity`, `ghost_visions`, `final_questions` | черновик |
| [`04_newsprint_fire.md`](04_newsprint_fire.md) | Город газетного нуара (`newsprint_city`) | `sabotage` | `archive_requests`, `cipher`, `version_archive`, `efficiency` | черновик |
| [`05_palace_last_waltz.md`](05_palace_last_waltz.md) | Дворец (`palace_masks`) | `theft` | `expert`, `refutation`, `secret_identity` | черновик |
| [`06_polar_star_sabotage.md`](06_polar_star_sabotage.md) | Полярная звезда (`polar_star`) | `sabotage` | `survival_clock`, `victim_clock`, `final_questions` | черновик |
| [`07_circus_empty_pedestal.md`](07_circus_empty_pedestal.md) | Цирк «Балаган» (`circus`) | `hoax` | `turning_point`, `expert`, `version_archive` | черновик |
| [`08_campus_glass_archive.md`](08_campus_glass_archive.md) | Кампус (`campus`) | `forgery` | `archive_requests`, `expert`, `version_archive` | черновик |
| [`09_prohibition_rat.md`](09_prohibition_rat.md) | Сухой закон (`prohibition`) | `impostor` | `secret_identity`, `outsider`, `victim_clock` | черновик |
| [`10_sand_city_nameless.md`](10_sand_city_nameless.md) | Песчаный город (`sand_city`) | `sabotage` | `sanity`, `turning_point`, `cipher` | черновик |
| [`11_neon_city_erased_memory.md`](11_neon_city_erased_memory.md) | Неон-Сити (`neon_city`) | `exoneration` | `archive_requests`, `cipher`, `version_archive` | черновик |

Все 11 миров получили по одному черновику. Следующий шаг — выбрать дело и развернуть его в полный `case.schema.json` для валидатора; до этого тексты остаются черновиками.

## Правила черновиков

- Один тип фабулы на дело. Три варианта разгадки — альтернативные авторские версии, а не три виновника одновременно.
- Герои описываются ролями из канона, без имён. Имена игроков и NPC задаются партией, а не текстом дела.
- 12+. Без крови, ран, оружия в кадре, медикаментов как приёма и сцен насилия.
- Только реальные места, роли и предметы канона. Если для сцены нужен новый объект, он помечается `[предложение]` и не считается каноном.
- Никаких новых правил и модулей: используются только модули, уже перечисленные в каноне и `CASE_SLATE`.
- Числа окон, ходов, таймингов и AFK здесь не фиксируются. Для реализации они берутся из снимка `rules`, когда он будет утверждён.
- Черновик не является делом для валидатора: это сюжетный каркас, а не JSON. Превращать его в `case.schema.json` можно только после этапов 0–2 MQB-010.

## Как пользоваться

1. Владелец проекта выбирает один черновик и помечает, что в нём верно, а что переписать.
2. После решения по числам и модулям черновик переводится в структуру `case.schema.json`.
3. Валидатор V1–V11 проверяет достижимость, улики, составы 4/5/8/12 и отсутствие тупиков.
4. Только после этого дело попадает в игру. Сейчас — нет.

## Открытые решения

- Какой черновик считать первым: «Хозяин исчез из запертой библиотеки» или «Пассажир без билета».
- Может ли виновник быть играбельной ролью или в первых делах он всегда NPC.
- Нужен ли в первом деле владелец усадьбы как NPC (рекомендация черновика) или как играбельная роль.
- Реальная ли мистика в «Чёрной бухте» в этом конкретном деле (в черновике — да, но она не является виновником).
- Кто утверждает финальные тексты и формулировки обвинения.
