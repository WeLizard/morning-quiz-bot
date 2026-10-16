# «Ночной город»: пробные арты — выбор направления

- **Статус:** `proposed` (набор промптов для генерации; арты ещё не сделаны)
- **Создан:** 2026-10-15
- **Связано:** [NIGHT_CITY_WEEKLY_DESIGN](NIGHT_CITY_WEEKLY_DESIGN.md) (§6, карточки), [MQB-010](MQB-010-night-city-weekly-stages.md) (этап 8)

## 1. Зачем и что делаем

Илья сгенерирует через imagegen около 10 пробных артов, чтобы понять, **в какую
сторону двигаться по дизайну** карточек. Это не финальные арты и не арты дела: они
только показывают стиль. Чтобы сравнение было честным, берём **5 одинаковых сюжетов
в двух стилях** (5 × 2 = 10).

Использованы шаблоны из библиотеки стилей GPT-Image2 (используется как
подсказка структуры промпта): `illustration-art-style`, `scene-storytelling`,
`character-design-sheet`. Библиотека — внешний справочник; её содержимое здесь не
проверялось на актуальность.

## 1а. Решения Ильи по стилю (2026-10-15)

- **Базовый стиль — A** («чернильный нуар-принт»). Эталон — готовый файл
  `art_samples/a_2_location.png` (библиотека ночью: тёмная тушь, сине-бирюзовый
  холод, янтарный свет лампы, фактура бумаги и штриховка). Стиль **единый для
  всех артов**, включая **карточки интерфейса, рамки, значки, кнопки** и
  прочее: одна палитра, одна манера линий и фактуры, одна логика света.
- **Границы единого стиля:** стиль единый **в пределах одного дела (сюжета)**. Если
  сюжет требует другого вида (например, дело-мистика), для него генерируется
  **немного другой пакет стиля** (близкая манера, другая палитра и фактура);
  пакет называется `style_pack` дела (по умолчанию `noir_print_a`) и включает
  палитру, рамки, подложки, значки и детали. Общие детали между делами можно
  переиспользовать, только если они подходят по пакету.
- **Форматы по типам** (не всё в 2:3): герой, место, призрак, финал — вертикаль
  **2:3**; **предметы, улики, символы — квадрат 1:1**; рамки — под формат своей
  карточки (2:3 или 1:1).
- **Состояния времени суток.** Для мест и сцен готовятся варианты одной и той же
  композиции: **утро, день, вечер, ночь** (меняются только небо, свет и палитра;
  композиция и предметы те же). Это добавляет эффект и «живость» партии.
  Предметы-вырезки не перерисовываются: тон при необходимости даёт верхний слой
  (см. [NIGHT_CITY_CARDS_DELIVERY §5.6](NIGHT_CITY_CARDS_DELIVERY.md)).

## 2. Общие правила для всех промптов

- **Без текста на картинке** (ни букв, ни цифр, ни вывесок): текст накладывает
  интерфейс, а генераторы плохо рисуют кириллицу.
- **Формат** 2:3 вертикально (например, 1024 × 1536) — формат карточки. Поля:
  важное — в центральных ~85 %, края спокойные, чтобы рамка карточки не резала.
- **12+**: без крови, ран, оружия крупным планом, откровенных сцен.
- **Оригинальность**: без имён художников, фильмов, игр, брендов и реальных людей
  в промптах; без узнаваемых персонажей.
- **Герой без имени**: портрет изображает роль, а не конкретного человека по имени
  (имя игрок вводит сам, дизайн §3.4).
- **Прозрачный фон (альфа-канал).** Сюжеты 1, 3 и 4 (герой, улика, призрак)
  делаются **вырезанными**: PNG с настоящим альфа-каналом, без фона, пола и
  шахматной клетки. Сюжеты 2 и 5 (место и финал) остаются цельными сценами с
  фоном: у сцены прозрачного фона быть не может.
- Один сюжет в двух стилях — **один и тот же текст сюжета**, различается только
  блок стиля (так видно разницу стилей, а не сюжетов).
- Сохраняйте результаты как `a_1_character.png`, `b_1_character.png` и т. д. (§5).

## 3. Два стиля для сравнения

**Стиль A — «Чернильный нуар-принт».**
> vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black
> and midnight teal with a single warm amber lamp-light accent, visible paper grain
> and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching
> instead of smooth gradients, flat graphic shapes

**Стиль B — «Гуашь, книжная иллюстрация».**
> painterly gouache storybook illustration, muted warm palette of ochre, brick red,
> sage green and dusty blue, soft edges with visible brush texture, gentle
> cinematic lighting, cozy mystery atmosphere, simplified friendly shapes

Что хочется проверить: читаемость в маленьком размере (карточка на телефоне),
уместность 12+, насколько стиль выдержит **единый вид** десятков карточек, и
подойдёт ли палитра к тёмной и светлой теме приложения.

## 4. Пять сюжетов и промпты

Формат одного промпта: `<сюжет> + <блок стиля> + <общие ограничения>`. Общие
ограничения (вставляются в конец каждого):

> Vertical 2:3 composition, subject in the central 85% with calm margins, no text,
> no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+,
> original design, no real people.

Для вырезанных сюжетов (1, 3, 4) к общим ограничениям добавляется:

> Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.

### Сюжет 1 — карточка героя: Экономка

> Half-length portrait cut-out of a middle-aged housekeeper in a dark 1930s dress with a high collar, a heavy ring of keys at her belt, one hand resting on it, composed and watchful expression looking at the viewer. Isolated figure only, no scenery, no floor, flat even lighting on the figure with no rim light.

Полный промпт A: сюжет + блок стиля A + общие ограничения.
Полный промпт B: сюжет + блок стиля B + общие ограничения.

### Сюжет 2 — карточка места: Библиотека ночью

> Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling
> ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out
> as if recently touched, snowy night visible through a tall window, nobody in the
> frame.

### Сюжет 3 — карточка улики: ключ и обрывок бумаги

> Top-down cut-out still life of evidence items: a small antique key, a torn corner of an old document with a fragment of a cracked wax seal (no readable marks), a burnt match, a thin trail of ash, arranged as one compact group. Items only, no desk, no background.

### Сюжет 4 — карточка призрака

> A calm and melancholic ghost of a person in old-fashioned clothes, standing, drawn as a pale desaturated silhouette in the same engraved hatching, with slightly broken hatching at the edges, no aura, no glow, no mist. Isolated figure only, no scenery. The sad and mysterious mood comes from the pose and the face, not from lighting effects.

### Сюжет 5 — карточка финала: итоговое слушание

> A long dining table in a candle-lit manor hall, many figures seated as simple
> silhouettes, one empty chair at the head of the table, a single sheet of paper in
> the centre of the table, the moment before a verdict, tense and quiet.

## 5. Как сохранить и что дальше

1. Папка для файлов: `docs/tasks/night_city/art_samples/` (создана заранее;
   **в git не добавляется**, решение о хранении картинок отдельное).
2. Имена: `a_1_character.png`, `a_2_location.png`, `a_3_evidence.png`,
   `a_4_ghost.png`, `a_5_finale.png` и те же с префиксом `b_`.
3. Если сервис выдаёт несколько вариантов — оставьте лучший, а в
   `art_samples/notes.txt` запишите сервис/модель и параметры (для воспроизведения).
4. Я посмотрю все 10, оформлю сравнение по критериям из §3 и предложу направление и
   стиль-гайд (палитра, рамка карточки, правила для героев, мест, улик, призраков,
   финалов). Если картинок не хватит для решения — в §6 дополнительные сюжеты.

## 5а. Детали-вырезки для сборки карточек

*(по предложению Ильи 2026-10-15)* Карточка собирается из слоёв (см.
[NIGHT_CITY_CARDS_DELIVERY §5.6](NIGHT_CITY_CARDS_DELIVERY.md)): подложка, рамка,
вырезки, значки, текст. Поэтому кроме 10 пробных артов понадобится **набор отдельных
деталей**: каждая вещь — один PNG с настоящей прозрачностью, один предмет на файл,
без фона и теней вокруг. Первая партия (после выбора стиля, в выбранном стиле):

| Группа | Детали |
| --- | --- |
| Предметы-улики | ключ старинный, ключ маленький, лупа, обрывок бумаги, письмо в конверте, сургучная печать целая и треснувшая, спичка, свеча, очки, перстень, карманные часы, блокнот |
| Следы | след сапога, пятно, отпечаток пальца, ключ в замке, дверной замок |
| Символы | луна, глаз, замок, треугольник «Тень», рука с лупой |
| Рамки | по одной на тип карточки (герой, улика, место, событие, призрак, финал), середина прозрачная |
| Подложки | бумага тёплая, бумага холодная, ночная ткань, пергамент |

Общие правила деталей: PNG с альфа-каналом, чистые края без ореола, один предмет на
файл, без текста, без реальных брендов, 12+. Для рамок — вертикальный формат 2:3 с
прозрачной серединой.

## 5б. Итоги первой партии (2026-10-15)

Сгенерировано Codex (до этого раздела готовы `a_1`–`a_5` и `b_1`, `b_2`; генерация
стиля B продолжалась, несмотря на просьбу её не начинать — просьба, вероятно, не
дошла до уже запущенной задачи). Проверено Pillow и просмотром.

| Что | Результат |
| --- | --- |
| Стиль A | совпадает с эталоном: гравюрная штриховка, холодная синева, янтарный свет; портрет и улики выглядят цельно |
| Размер и вес | 1024×1536, около 2,3–3,3 МБ каждый (PNG): без WebP в git не пойдут (§5.9 карточек) |
| Формат улики | `a_3_evidence` получился **2:3, а не 1:1**: просьба про 1:1 пришла уже после генерации |
| **Прозрачность** | альфа-канал есть (углы прозрачны), но **фон не вырезан чисто**: вокруг героя/улик остались тёмная виньетка и янтарное свечение с почти полной непрозрачностью (альфа 240–254), настоящей «вырезки» нет; полностью непрозрачных пикселей (255) тоже нет, значит альфу нужно нормализовать |
| Края | вокруг предметов видны ореол и контур света: промпт просил «clean edges without halo», но генератор добавил свечение |

**Обновление (агент Codex закончил, все 10 файлов созданы):**
- `a_3_evidence` пересоздан после уточнения: **1024×1024**, чистая вырезка — только
  ключ, обрывок бумаги с печатью и спичка с пеплом, без фоновой виньетки и свечения;
  стиль сохранён. Помогло сочетание «усиленный промпт + `a_2_location.png` как
  референс стиля» (генератор выдал 1254×1254, уменьшено до 1024×1024).
- Остальные вырезки (`a_1_character`, `a_4_ghost`, `b_1/3/4`) остаются со свечением и
  непрозрачным фоном; `b_*` созданы **до** решения «стиль A для всех» (стиль B
  не нужен, если Илья не передумает), `b_3_evidence` — 2:3.
- Альфа у всех вырезок почти полностью 240–254, а не 255 (у нового `a_3` — 0,2 % с
  255): при конвертации в WebP значения ≥240 нужно нормализовать до 255.
- Тест подтвердил рабочий рецепт для чистых вырезок (см. ниже, п. 1–2); `a_1` и `a_4`
  стоит переделать так же.

Выводы и предложения:
1. Для вырезок усилить промпт: «flat even lighting, no glow, no vignette, no rim
   light halo, no ambient backdrop light, isolated sprite with crisp edge».
2. Если «чистая» прозрачность недостижима, запасной путь — сгенерировать предмет на
   однотонном «ключевом» фоне и вырезать его, затем проверить края; требуется
   отдельный инструмент вырезания (**не выбран, не проверялся**).
3. После выбора границ — нормализация альфы (≥240 → 255) и конвертация в WebP при
   публикации, без изменения исходных PNG.
4. Предметы (улики) заказывать **по одному предмету на файл, 1:1**, а не группой:
   так их можно переиспользовать и собирать (см. §5а).

## 6. Дополнительные сюжеты (если останутся лимиты)

- **Эмблема фракции «Тень»** — треснувшая сургучная печать с символом луны, без
  текста, на тёмном фоне.
- **Рубашка карты** — симметричный повторяющийся узор из ключей и луны.
- **Карточка роли «Следствие»** — предмет-символ (лупа и блокнот) на нейтральном
  фоне, без людей.

## 7. Открытые вопросы

- Сколько вариантов стиля сравнивать: два (A и B) достаточно или добавить третий,
  например «минималистичная вектор-графика» (дешевле в производстве, лучше
  масштабируется)?
- Единый стиль для всех жанров (нуар, классика, мистика) или у каждого жанра
  своя палитра в рамках общего гайда?
- Кто и чем делает финальные арты (тот же imagegen, внешний художник): влияет на
  требование «единый вид» и на права; не решено.

## 8. Готовые промпты (копировать целиком)

Каждый блок — один запрос в imagegen. Файл сохраняется под указанным именем. Блоки 1, 3, 4 — с прозрачным фоном; блок 3 (улики) — квадрат 1:1. Эталон стиля — `a_2_location.png`. Стиль B (`b_*`) решением Ильи не нужен: его файлы перенесены в `art_samples/style_b/`, промпты оставлены для справки. Версия 2 промптов героя и призрака: без свечения и ореола.

**a_1_character.png** — карточка героя: Экономка, стиль A (прозрачный фон)

```text
Half-length portrait cut-out of a middle-aged housekeeper in a dark 1930s dress with a high collar, a heavy ring of keys at her belt, one hand resting on it, composed and watchful expression looking at the viewer. Isolated figure only, no scenery, no floor, flat even lighting on the figure with no rim light. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**a_2_location.png** — карточка места: Библиотека ночью, стиль A

```text
Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out as if recently touched, snowy night visible through a tall window, nobody in the frame. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**a_3_evidence.png** — карточка улики: ключ и обрывок бумаги, стиль A (1:1) (прозрачный фон)

```text
Top-down cut-out still life of evidence items: a small antique key, a torn corner of an old document with a fragment of a cracked wax seal (no readable marks), a burnt match, a thin trail of ash, arranged as one compact group. Items only, no desk, no background. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Square 1:1 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**a_4_ghost.png** — карточка призрака, стиль A (прозрачный фон)

```text
A calm and melancholic ghost of a person in old-fashioned clothes, standing, drawn as a pale desaturated silhouette in the same engraved hatching, with slightly broken hatching at the edges, no aura, no glow, no mist. Isolated figure only, no scenery. The sad and mysterious mood comes from the pose and the face, not from lighting effects. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**a_5_finale.png** — карточка финала: итоговое слушание, стиль A

```text
A long dining table in a candle-lit manor hall, many figures seated as simple silhouettes, one empty chair at the head of the table, a single sheet of paper in the centre of the table, the moment before a verdict, tense and quiet. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_1_character.png** — карточка героя: Экономка, стиль B (прозрачный фон)

```text
Half-length portrait cut-out of a middle-aged housekeeper in a dark 1930s dress with a high collar, a heavy ring of keys at her belt, one hand resting on it, composed and watchful expression looking at the viewer. Isolated figure only, no scenery, no floor, flat even lighting on the figure with no rim light. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**b_2_location.png** — карточка места: Библиотека ночью, стиль B

```text
Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out as if recently touched, snowy night visible through a tall window, nobody in the frame. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_3_evidence.png** — карточка улики: ключ и обрывок бумаги, стиль B (1:1) (прозрачный фон)

```text
Top-down cut-out still life of evidence items: a small antique key, a torn corner of an old document with a fragment of a cracked wax seal (no readable marks), a burnt match, a thin trail of ash, arranged as one compact group. Items only, no desk, no background. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Square 1:1 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**b_4_ghost.png** — карточка призрака, стиль B (прозрачный фон)

```text
A calm and melancholic ghost of a person in old-fashioned clothes, standing, drawn as a pale desaturated silhouette in the same engraved hatching, with slightly broken hatching at the edges, no aura, no glow, no mist. Isolated figure only, no scenery. The sad and mysterious mood comes from the pose and the face, not from lighting effects. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people. Output as PNG with a real transparent background (alpha channel), fully transparent outside the subject, no checkerboard pattern, no white or coloured backdrop, no ground shadow, no cast shadow outside the subject, no glow, no halo, no vignette, no light spill, no atmospheric haze, no semi-transparent aura around the subject, flat even lighting, crisp clean edges. Use the attached reference image only for the engraved noir print style.
```

**b_5_finale.png** — карточка финала: итоговое слушание, стиль B

```text
A long dining table in a candle-lit manor hall, many figures seated as simple silhouettes, one empty chair at the head of the table, a single sheet of paper in the centre of the table, the moment before a verdict, tense and quiet. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

## 9. Партия 2: персонажи, интерфейс, заготовки предметов (2026-10-15)

*(по поручению Ильи: ещё около 20 карточек персонажей, элементы интерфейса,
заготовки предметов в большом количестве; исполнитель — Codex, модель `gpt-6-sol`,
reasoning `medium`)*

### 9.1 Общие правила

- Стиль A, эталоны: `art_samples/a_2_location.png` (сцена) и
  `art_samples/a_3_evidence.png` (чистая вырезка). Блок «Для вырезанных сюжетов» из
  раздела 4 (версия 2: без свечения, ореола, виньетки) добавляется ко всем вырезкам.
- Без текста на картинках (ни букв, ни цифр), 12+, без оружия крупным планом,
  без реальных людей и брендов.
- Герои — **без имён** (роль и внешность), дизайн §3.4.
- Папка: `docs/tasks/night_city/art_batch2/` с подпапками `characters/`, `ui/`,
  `items/`; манифест `art_batch2/manifest.json` (файл, вид, размер, режим,
  номер промпта) и `notes.txt` (инструмент, **модель и reasoning**, параметры).
  В git не добавляется; позже — конвертация в WebP (§5.9 карточек).

### 9.2 Переделки (приоритет 0)

`art_samples/a_1_character.png` и `a_4_ghost.png` — заново по промптам версии 2
(раздел 8). Старые файлы сохранены в `art_samples/old_v1/`. Стиль B убран в
`art_samples/style_b/`.

### 9.3 Персонажи — 20 вырезок 2:3 (c_01 уже есть как `a_1_character.png`)

Состав соответствует делу «Зимнее завещание» ([CASE_SLATE §2.1](NIGHT_CITY_CASE_SLATE.md)); роли 15–19 заменены 2026-10-15 под усадьбу.

Половина фигуры, один герой на файл, прозрачный фон, взгляд на зрителя, поза
спокойная, одежда 1930-х. Разные возраст, телосложение и род.

| № | Файл | Роль | Пол | Деталь |
| --- | --- | --- | --- | --- |
| 01 | (готов `a_1`) | Экономка | ж | связка ключей |
| 02 | c_02_lawyer | Адвокат | м | круглые очки, портфель, бумаги |
| 03 | c_03_doctor | Домашний врач | м | чемоданчик, стетоскоп |
| 04 | c_04_butler | Дворецкий | м | белые перчатки, поднос |
| 05 | c_05_maid | Горничная | ж | фартук, тревожный взгляд |
| 06 | c_06_gardener | Садовник | м | рабочий плащ, кепка, секатор |
| 07 | c_07_cook | Повар | м | полный, белый фартук |
| 08 | c_08_companion | Компаньонка | ж | шаль, книга |
| 09 | c_09_artist | Племянница-художница | ж | пятна краски, шарф |
| 10 | c_10_gambler | Племянник-игрок | м | пёстрый жилет, карты в руке |
| 11 | c_11_daughter | Дочь от первого брака | ж | холодная, меховой воротник |
| 12 | c_12_hunter | Старый друг-охотник | м | твидовый пиджак, шляпа |
| 13 | c_13_watchman | Сторож | м | фонарь, тяжёлое пальто |
| 14 | c_14_owner | Владелец усадьбы | м, 70+ | трость, строгий костюм |
| 15 | c_15_chauffeur | Шофёр | м | кожаные перчатки, фуражка |
| 16 | c_16_governess | Гувернантка | ж | строгое платье, стопка тетрадей |
| 17 | c_17_student | Внучка-студентка | ж | берет, книги под мышкой |
| 18 | c_18_priest | Сельский священник | м | простая ряса, чётки |
| 19 | c_19_photographer | Фотограф-гость | м | складная камера, кепи |
| 20 | c_20_investigator | Следователь | ж | плащ, блокнот |

### 9.4 Интерфейс (стиль A)

| Группа | Файлы | Формат |
| --- | --- | --- |
| Рамки карточек, середина прозрачная | `frame_hero`, `frame_place`, `frame_event`, `frame_ending`, `frame_ghost` | 2:3 |
| Рамки 1:1 | `frame_evidence`, `frame_item` | 1:1 |
| Рубашка карты | `card_back` | 2:3, непрозрачная |
| Подложки | `plate_paper_warm`, `plate_paper_cool`, `plate_night_cloth`, `plate_parchment` | 2:3, непрозрачные |
| Кнопки без текста (основная, второстепенная, нажатая, недоступная) | лист `ui_buttons` | лист 3×3 |
| Панели, лента заголовка, разделитель, вкладка, подсказка-облачко, кольцо таймера, бейдж | лист `ui_panels` | лист 3×3 |
| Значки (24 шт.): типы улик (4), надёжность (2), фракции (3), действия (6: идти, осмотреть, говорить, приколоть, обвинить, закончить), время (3: солнце, луна, тишина), статусы (6: замок, метка места, реплика, призрак, колокол, печать) | листы `icons_01…03` | листы 3×3 (по 8–9) |

### 9.5 Заготовки предметов — 63 предмета на 7 листах 3×3

Каждый лист — одна картинка 3×3, предметы на прозрачном фоне, отдельно друг от друга
с запасом поля, одинаковый масштаб и один и тот же свет. После генерации лист
режется на отдельные PNG `items/i_<лист>_<номер>_<имя>.png` (1:1, прозрачные);
режем по связным областям альфа-канала с проверкой, что предмет целиком в своей
ячейке.

| Лист | Содержимое (9 предметов) |
| --- | --- |
| S1 ключи и замки | старинный ключ, малый ключ, связка ключей, навесной замок, дверной замок, ключ на бирке, накладка замочной скважины, шкатулка с замком, сейф с диском |
| S2 бумаги | обрывок бумаги, сложенное письмо, запечатанный конверт, лента телеграммы, газетная вырезка (без читаемого текста), страница бухгалтерской книги, билет, банкнота, фотография |
| S3 печати и следы | целая сургучная печать, треснувшая печать, обгоревшая спичка, коробок спичек, кучка пепла, след сапога, отпечаток пальца, пятно чернил, пуговица |
| S4 личные вещи | круглые очки, перстень-печатка, карманные часы, медальон, брошь, запонка, шпилька, перчатка, трубка |
| S5 свет и инструменты | свеча, подсвечник, масляная лампа, лупа, блокнот, перьевая ручка, чернильница, старинный фонарик, ножницы |
| S6 быт | чашка с блюдцем, бокал, графин, пузырёк без этикетки, коробочка для таблеток, портсигар, кошелёк, расчёска, ручное зеркало |
| S7 разное | зонт, шляпа, шарф, моток верёвки, небольшой чемодан, закрытая книга, дневник с замком, карманный компас, каминные часы |

Оружия среди предметов нет (12+).

### 9.6 Порядок и контроль

- **Этап 1 (проверка рецепта):** переделки a_1 и a_4, герои c_02–c_06, рамки
  `frame_hero` и `frame_evidence`, листы S1 и S2, лист значков `icons_01` — около
  12 изображений. После него проверка: чистые края, нет свечения, стиль совпадает,
  нарезка листов работает.
- **Этап 2:** остальное по спискам §9.3–9.5, если этап 1 принят.
- **Контроль качества каждого файла:** PNG, прозрачность по углам, непрозрачный фон
  не связан с границей, нет ореола (просмотр на ярком фоне контактным листом),
  нет текста, стиль совпадает с эталоном. Расхождения — переделка не более двух раз.
- **Время и лимиты:** прошлые 10 изображений заняли около часа; вся партия
  (около 45 запросов генерации) — несколько часов и заметный расход лимитов Codex;
  агент сообщает о лимитах и не подменяет модель молча.

## 10. Пакеты стилей и полный набор на пакет (2026-10-15)

*(по поручению Ильи: интерфейса «нужно намного больше», по 20 персонажей на каждый
стиль, лимиты не ограничивать)* Пакеты соответствуют шести делам из
[NIGHT_CITY_CASE_SLATE](NIGHT_CITY_CASE_SLATE.md). Стиль единый внутри пакета.

### 10.1 Блоки стиля для промптов

| Пакет | Дело | Блок стиля (вставляется вместо блока A) |
| --- | --- | --- |
| `noir_print_a` | Зимнее завещание | блок стиля A из раздела 3 |
| `art_deco_poster` | Ночной экспресс | 1930s art deco travel poster lithograph, bold geometric shapes and stepped ornaments, limited palette of black, metallic gold, deep burgundy and emerald, flat colour areas with soft print grain, elegant streamlined silhouettes |
| `eldritch_etching` | Туман над Чёрной бухтой | antique copperplate etching, fine cross-hatching, sepia ink with sea-green and murky teal tints, ornate nautical and occult ornaments, mysterious but not gory, aged paper texture |
| `newsprint_noir` | Пожар на Сенной | 1950s newspaper photo print, coarse halftone dots, black and white with a single red accent, rough newsprint texture, high-contrast flash lighting, clean readable shapes |
| `baroque_mask` | Последний вальс | 19th century engraved illustration with gold leaf accents, deep burgundy, gold, ivory and black, lace and filigree ornaments, candlelight, masquerade mask motifs, rich but readable silhouettes |
| `polar_lithograph` | Полярная звезда | early 20th century stone lithograph, cold palette of white, ice blue and graphite with a single warm amber kerosene-lamp accent, frost textures, compact solid shapes, subtle stone-print grain |
| `circus_lithograph` | Цирк «Балаган» | vintage 1900s circus poster lithograph, bold warm palette of tomato red, mustard yellow, cream and deep navy, striped tent motifs, sawdust texture, theatrical spotlight, playful but readable silhouettes |
| `campus_ink` | Кампус | contemporary ink-and-marker editorial illustration, clean confident linework, limited palette of charcoal, off-white paper and one electric teal accent, subtle paper grain, modern clothing without brand logos |
| `cosmic_engraving` | Песчаный город | 1920s scientific engraving and star-chart plates, fine ink linework on aged paper, palette of sand ochre, deep violet night and a pale sickly star-green, impossible geometry in architecture, dread through scale and emptiness, no gore, no monsters in close-up |
| `neon_noir` | Неон-Сити | rain-soaked neo-noir night city illustration, deep black and indigo with neon magenta and cyan accents, wet reflections, holographic signs with no readable text, cinematic noir lighting, modern clothing without brand logos |
| `prohibition_noir` | Сухой закон | 1929 gangster noir illustration in vintage sepia photo-print style with art deco gold accents, smoky speakeasy light, long black cars, fedoras and pinstripes, rain on cobblestones, guns only as holstered or carried props, never aimed at people, no blood |

Ограничения, правила вырезок версии 2 и запрет текста — общие (разделы 2, 4).
Эталон для каждого нового пакета: сначала одна сцена-эталон (место дела, как
`a_2_location.png`), затем всё остальное пакета генерируется с ней как референсом.

### 10.2 Набор на один пакет

| Группа | Состав | Кол-во |
| --- | --- | --- |
| Эталон | одна сцена-место дела | 1 |
| Герои | 20 ролей дела (список в CASE_SLATE), вырезки 2:3 | 20 |
| Места | 6–8 мест дела × 4 состояния (утро, день, вечер, ночь), 2:3, непрозрачные | 24–32 |
| Рамки | герой, место, улика, предмет, событие, призрак, финал, роль, цель, досье — середина прозрачная; 2:3, у улики и предмета 1:1 | 10 |
| Рубашки | колода дела, колода событий, колода ролей | 3 |
| Подложки | бумага тёплая, бумага холодная, ткань, пергамент, тёмная панель, светлая панель | 6 |
| Кнопки | листы 3×3: основная, второстепенная, иконочная — в состояниях обычная, нажатая, недоступная, выделенная | 3 листа |
| Панели и ленты | листы 3×3: ленты заголовков, разделители, вкладки, облачка подсказок, рамки полей ввода, плашки уведомлений, бейджи-счётчики | 3 листа |
| Значки | листы 3×3: типы улик, надёжность, фракции, действия, время суток и тишина, статусы, модули дела (рассудок, шифр, архив…), навигация (назад, карта, доска, блокнот, чат, профиль) | 6 листов |
| Эмблемы | фракции (Следствие, Тень, Независимые) 1:1 | 3 |
| Награды | медали и знаки репутации, лист 3×3 | 1 лист |
| Аватары | рамки аватаров игрока и NPC (с отметкой NPC), лист 3×3 | 1 лист |
| Карта | метки мест, пунктир пути, роза ветров, рамка карты, «туман» неоткрытого | 2 листа |
| Экраны | заставка дела, экран финала, фон досье | 3 |
| Карточки дел в меню | рамка карточки дела (лицо и оборот, места под значки), значки сложности, игроков, длительности, печать мира; **обложка 2:3 на каждое дело** | 4 + 1 на дело |
| Предметы | 63 базовых (листы S1–S7) + 18 «фирменных» предметов дела (2 листа) | 9 листов |

Итого на пакет около **110–120 изображений** (листы считаются одним запросом,
потом режутся). На шесть пакетов — около 700 запросов генерации: это **дни работы
агента**, поэтому порядок такой:

1. `noir_print_a` целиком (дело «Зимнее завещание» — первое).
2. Для пяти остальных пакетов сначала **эталон + 20 героев + рамки + рубашка** —
   чтобы оценить стиль; полный набор — когда дело пойдёт в работу.

### 10.3 Контроль на каждом шаге

Как в §9.6: прозрачность и чистые края у вырезок, контактный лист на ярком фоне,
сверка стиля с эталоном пакета, без текста, без повторов (одинаковые лица у разных
героев — переделка), манифест и `notes.txt` на каждый пакет
(`art_batch2/<пакет>/…`).
