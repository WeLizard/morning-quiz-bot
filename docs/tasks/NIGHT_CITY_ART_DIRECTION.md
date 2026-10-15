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

### Сюжет 1 — карточка героя: Экономка

> Half-length portrait of a middle-aged housekeeper in a dark 1930s dress with a
> high collar, a heavy ring of keys at her belt, one hand resting on it, composed
> and watchful expression looking at the viewer, a dim manor corridor behind her
> with a single candle on a table.

Полный промпт A: сюжет + блок стиля A + общие ограничения.
Полный промпт B: сюжет + блок стиля B + общие ограничения.

### Сюжет 2 — карточка места: Библиотека ночью

> Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling
> ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out
> as if recently touched, snowy night visible through a tall window, nobody in the
> frame.

### Сюжет 3 — карточка улики: ключ и обрывок бумаги

> Top-down close-up still life on a worn wooden desk: a small antique key, a torn
> corner of an old document with a fragment of a cracked wax seal (no readable
> marks), a burnt match, a thin trail of ash, everything arranged to feel like
> evidence on a detective's table.

### Сюжет 4 — карточка призрака

> A translucent, calm and melancholic ghost of a person in old-fashioned clothes
> standing in a corridor, only partly visible, faint lantern glow passing through
> the figure, a window with falling snow behind, the mood is sad and mysterious
> rather than frightening.

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

Каждый блок — один запрос в imagegen. Файл сохраняется под указанным именем.

**a_1_character.png** — карточка героя: Экономка, стиль A

```text
Half-length portrait of a middle-aged housekeeper in a dark 1930s dress with a high collar, a heavy ring of keys at her belt, one hand resting on it, composed and watchful expression looking at the viewer, a dim manor corridor behind her with a single candle on a table. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**a_2_location.png** — карточка места: Библиотека ночью, стиль A

```text
Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out as if recently touched, snowy night visible through a tall window, nobody in the frame. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**a_3_evidence.png** — карточка улики: ключ и обрывок бумаги, стиль A

```text
Top-down close-up still life on a worn wooden desk: a small antique key, a torn corner of an old document with a fragment of a cracked wax seal (no readable marks), a burnt match, a thin trail of ash, everything arranged to feel like evidence on a detective's table. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**a_4_ghost.png** — карточка призрака, стиль A

```text
A translucent, calm and melancholic ghost of a person in old-fashioned clothes standing in a corridor, only partly visible, faint lantern glow passing through the figure, a window with falling snow behind, the mood is sad and mysterious rather than frightening. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**a_5_finale.png** — карточка финала: итоговое слушание, стиль A

```text
A long dining table in a candle-lit manor hall, many figures seated as simple silhouettes, one empty chair at the head of the table, a single sheet of paper in the centre of the table, the moment before a verdict, tense and quiet. vintage 1930s noir print illustration, linocut / woodcut feeling, deep ink black and midnight teal with a single warm amber lamp-light accent, visible paper grain and subtle halftone, bold readable silhouettes, strong chiaroscuro, hatching instead of smooth gradients, flat graphic shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_1_character.png** — карточка героя: Экономка, стиль B

```text
Half-length portrait of a middle-aged housekeeper in a dark 1930s dress with a high collar, a heavy ring of keys at her belt, one hand resting on it, composed and watchful expression looking at the viewer, a dim manor corridor behind her with a single candle on a table. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_2_location.png** — карточка места: Библиотека ночью, стиль B

```text
Interior of a manor library at night: floor-to-ceiling bookshelves, a rolling ladder, a desk with a green-shaded lamp, one book on a shelf pulled slightly out as if recently touched, snowy night visible through a tall window, nobody in the frame. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_3_evidence.png** — карточка улики: ключ и обрывок бумаги, стиль B

```text
Top-down close-up still life on a worn wooden desk: a small antique key, a torn corner of an old document with a fragment of a cracked wax seal (no readable marks), a burnt match, a thin trail of ash, everything arranged to feel like evidence on a detective's table. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_4_ghost.png** — карточка призрака, стиль B

```text
A translucent, calm and melancholic ghost of a person in old-fashioned clothes standing in a corridor, only partly visible, faint lantern glow passing through the figure, a window with falling snow behind, the mood is sad and mysterious rather than frightening. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

**b_5_finale.png** — карточка финала: итоговое слушание, стиль B

```text
A long dining table in a candle-lit manor hall, many figures seated as simple silhouettes, one empty chair at the head of the table, a single sheet of paper in the centre of the table, the moment before a verdict, tense and quiet. painterly gouache storybook illustration, muted warm palette of ochre, brick red, sage green and dusty blue, soft edges with visible brush texture, gentle cinematic lighting, cozy mystery atmosphere, simplified friendly shapes. Vertical 2:3 composition, subject in the central 85% with calm margins, no text, no letters, no numbers, no logos, no watermark, no gore, suitable for ages 12+, original design, no real people.
```

