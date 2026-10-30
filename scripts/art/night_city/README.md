# «Ночной город»: оболочка и пакеты миров

Решение владельца 2026-10-29 ([NIGHT_CITY_OPEN_ROOMS](../../../docs/tasks/NIGHT_CITY_OPEN_ROOMS.md), «Замечание владельца»):
общий дизайн «Ночного города» не привязан к одному миру; сюжет комнаты или дела подставляет свой **пакет мира**.
Этап 1 — превью и схема (этот каталог + `.local/night-city-packs/`). В клиент ничего не подключено.

## Что где

| Файл | Что делает |
| --- | --- |
| `worlds.json` | источники 15 миров: папка стиля в `art_batch2`, канон, какие места заполняют слоты, базовая палитра, поправки кадрирования портретов, возрастная рамка `age` (по умолчанию 12; `deep_choir`, `dead_air` — 16; `velvet_circle`, `eternal_hotel` — 18), `ui` — имена файлов интерфейса, если в папке стиля они названы иначе (`role_deck_back` вместо `card_back_role` и т. п.) |
| `build_world_pack.py` | собирает пакет мира (`pack.json` + WebP) и `index.json`; `--inventory` — наличие арта по слотам без сборки |
| `build_music.py` | кодирует WAV из `docs/tasks/night_city/music_invoce` (имена `<Название> - <world_id> - <day\|night\|finale>.wav`, `<Название> - shell_theme.wav`) в AAC `.m4a` ~96 кбит/с: срезает тишину по краям, loudnorm в два прохода (−18 LUFS фон, −16 финал), пишет `worlds/<мир>/music_<слот>.m4a`, `shell/music_shell_<n>.m4a` и `.local/night-city-packs/music.json` (длительности); печатает таблицу. Запускать до `build_world_pack.py` / `build_shell.py`: они подхватывают готовые файлы, нет слота — нет записи в пакете |
| `world_pack.schema.json` | формат `pack.json` (JSON Schema, все 13 собранных пакетов проходят проверку) |
| `build_shell.py` | нейтральная оболочка: векторная сцена `skyline.svg`, спрайт значков `icons.svg`, шрифт WeLizard Noir; `grain.webp` ещё собирается, но клиент его не использует — шумовое зерно на поверхностях убрано по решению владельца 2026-10-30 (ровные поверхности цветом палитры) |

```
python -I scripts/art/night_city/build_shell.py                  # → .local/night-city-packs/shell
python -I scripts/art/night_city/build_world_pack.py             # три мира превью → .local/night-city-packs/worlds
python -I scripts/art/night_city/build_world_pack.py --all       # все 13
python -I scripts/art/night_city/build_world_pack.py --inventory # inventory.md / inventory.json
python -I .local/night-city-packs/preview/shoot.py               # кадры, листы, проверки
```

## Пакет мира

Папка `worlds/<world_id>/` (в клиенте после подключения — `/app/night/worlds/<world_id>/`):

| Группа | Ключ в `pack.json` | Файлы | Источник в `art_batch2/<стиль>` |
| --- | --- | --- | --- |
| слоты сцен | `scenes.cover/title/lobby/night/day/vote/finale/out` | `scene_<slot>[_<время>].webp`, 600 px | `covers/<мир>.png`, `ui/screen_title|dossier|finale.png`, `locations/<место>_<время>.png` |
| время суток | `scenes.<slot>.times` + `default` | лобби: вечер, день; день: утро, день; ночь: ночь; вне игры: вечер | одна композиция в 4 состояниях |
| места недели | `places.<id>.times` | `place_<id>_<время>.webp` (только с `--places`) | все 8 мест × 4 состояния |
| портреты | `portraits[]` (`n`, `hero`, `sex`) | `portrait_NN.webp`, 128 px | `characters/c_*.png`, голова и плечи по маске |
| эмблемы фракций | `factions.shadow/investigation/independent` | `emblem_*.webp` | `ui/emblem_*.png` |
| рубашки | `backs.role/case/event` | `back_*.webp`, 480 px | `ui/card_back_*.png`; вырезка с прозрачностью кладётся на цвет `page` |
| рамки | `frames.hero/evidence/dossier` (+ `aspect`, `hole`) | `frame_*.webp` | `ui/frame_*.png`, окно считается по альфе |
| палитра | `palette` (+ `contrast`) | — | `worlds.json`, производные считает сборка |
| заголовочный шрифт | `font.display` | — | `null` = шрифт оболочки |
| обложка для списков | `thumb` | `thumb.webp`, 240 px | обложка мира |
| возрастная рамка | `age` (12, 16 или 18, есть и в `index.json`) | — | `worlds.json`; 12 и 16 — только пометка; для 18 игрок один раз отвечает «Мне есть 18», сервер без `age_ok` не пускает |

**Слоты, а не места.** Экран просит `lobby`, `night`, `day`, `vote`, `finale`, `out`, `title`, `cover` и время суток.
Нет точного времени — берётся ближайшее; нет слота — соседний (`vote → day → lobby`, `out → night → lobby`,
`finale → cover → title`); нет ничего — векторная сцена оболочки.

**Портреты за столом** — только ролево-нейтральные герои: детектив, врач, полиция, инспектор и т. п. исключаются
(`defaults.seat_exclude`), мужчины и женщины чередуются, не больше 17. Для недельного режима в `pack.json`
лежит id героя канона (`hero`), его пол и название роли.

**Палитра.** В `worlds.json` 11 базовых цветов; сборка выводит поверхности, оттенок выбора, градиент главной
кнопки, цвет текста на кнопке и значения контрастного режима и проверяет: текст ≥ 7:1, вторичный текст,
акцент, цвета фракций ≥ 4,5:1, кромка ≥ 3:1. Провал виден в `checks.contrast_failed`.

**Сжатие** (бюджеты v2): сцена ≤ 150 КБ, рубашка и рамка героя ≤ 90 КБ, рамка улики ≤ 60 КБ, значок, эмблема,
портрет ≤ 30 КБ, обложка списка ≤ 20 КБ. WebP; качество снижается шагом 4, пока файл не уложится.
Выбор исходника: файлы с `selected=false` в `manifest.json` пакета пропускаются, из `x`, `x_v2`, `x_v3` берётся
старшая версия.

## Оболочка

Вход, комнаты, открытые столы, приглашение, выбор сюжета и меню ⚙ — без мира: тушь, слоновая кость, один
красный «штамп», заголовки шрифтом WeLizard Noir (v1.1: строчные «ы» и «ъ» исправлены). Фоны оболочки — слоты
(вход, комнаты, приглашение, пусто, загрузка): сгенерированные картинки, запасной вариант — вектор `skyline.svg`
(решение владельца 2026-10-30); значки, кнопки и рамки — вектор и CSS, значки — один векторный спрайт
на все миры. Миры приносят арт и цвет, но не значки. Обложки миров появляются в оболочке только как
содержимое: чип сюжета у комнаты и стола, карточки выбора сюжета, карточка приглашения.

## Контракт: как клиент выбирает пакет

1. `GET /app/night/worlds/index.json` — список миров (`id`, `title`, `era`, `thumb`, `accent`, `age`, `default`).
2. У комнаты и стола есть поле `world` (id мира). Нет поля или мир неизвестен → `index.default` (`manor_lake`).
   У дела недели `world` берётся из `case.json` (`world`, `style_pack` уже есть в `case.schema.json`).
3. Клиент загружает `worlds/<world>/pack.json?v=<version>` при открытии комнаты, применяет палитру
   (`--nc-*` на `<html>`) и дальше разрешает слоты, портреты, рубашки и рамки через пакет. Оболочка
   (вход, списки, приглашение) пакет не применяет.
4. Номер портрета игрока (`portrait`, 1…N) — индекс в `pack.portraits`; при смене мира номер сохраняется.

Сервер (делает другой агент после одобрения):
- `rooms.world` — строка `^[a-z][a-z0-9_]{1,31}$`, по умолчанию `manor_lake`; в ответах комнаты, лобби мафии,
  открытых столов, приглашения (`room_title` + `world`) и групп Telegram;
- смена сюжета: `POST /api/guest/rooms/{id}/world` `{world, expected_revision}` — только хозяин и только до начала
  партии; значение проверяется по списку миров; ответ — комната с новым `revision`;
- дело недели задаёт `world` само, смена в комнате тогда закрыта.

Прототип клиентской части — `.local/night-city-packs/preview/nc-packs.js` + `packs.css`: превью запускает настоящий
`web/mini_client/night-city-ui.js` и ставит этот модуль поверх него.

## Фоны оболочки (`shell/shell.json`)

Клиент берёт фоны оболочки по слотам, как у миров: `web/mini_client/night/shell/shell.json` →
`{"schema": "nc-shell/1", "scenes": {"entry": "skyline.svg", "rooms": …, "invite": …, "empty": …, "loading": …}}`
(`entry` — вход, `rooms` — подложка списков комнат и столов на широком экране, `invite` — приглашение, `empty` — «нет столов»,
`loading` — открытие стола). Имя файла — `[a-z0-9_]+.(svg|webp)` рядом с `shell.json`. Нет слота, файла или самого
`shell.json` — показывается `skyline.svg`. Значки, кнопки, рамки оболочки остаются векторными и CSS.

## Музыка

`pack.json` мира: `music: {day, night, finale}` → `{file, duration}` (слот без дорожки отсутствует; у `neon_city` нет `night`);
`shell.json`: `music: [{file, duration}]` — темы оболочки, на сессию выбирается случайная. Файлы раздаются как `audio/mp4`
(`/app/night/...`, с Range), CSP — `media-src 'self'`. Плеер — `kit.music` в `web/mini_client/night-city-ui.js`: по умолчанию выключен,
пункты «Музыка» и «Громкость музыки» в ⚙, звук только после касания, лобби/день/голосование → `day`, ночь → `night` (нет — `day`),
итоги → `finale` один раз, потом тишина; петля — перекрёстное затухание 2,5 с, смена дорожки — 1,5 с. Копия в клиент: как у арта
(`web/mini_client/night/worlds|shell`, без `pack.js`, `index.js`, `icons.js`).
