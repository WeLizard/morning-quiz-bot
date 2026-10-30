# «Ночной город»: музыка для 13 миров и оболочки — заказ на генерацию

Статус: заказ составлен 2026-10-30. Музыку генерирует владелец проекта, затем подключаем в пакеты миров.
Арт и шрифты уже разнесены по пакетам (`scripts/art/night_city/README.md`), музыка ложится туда же.

## 1. Что нужно

На каждый мир — **три дорожки**:

| Слот | Где звучит | Длина | Характер |
|---|---|---|---|
| `day` | лобби, день, обсуждение, голосование | 2–3 мин, петля | фон под разговор: ровный темп, без резких пиков |
| `night` | ночь, ход ролей | 2–3 мин, петля | тише и напряжённее, больше пауз и низов |
| `finale` | экран итогов | 15–30 с, один раз | короткая развязка с внятным концом |

Плюс **оболочка** (вход, список комнат, приглашение) — одна дорожка `shell_theme`, 2–3 мин, петля, нейтральный
нуар без примет какого-либо мира.

Итого 40 дорожек (13 × 3 + 1). Минимум для первой версии — `day` и `night` у всех миров плюс оболочка (27);
`finale` можно добавить позже.

## 2. Общие требования

- **Без вокала и без слов**: игроки читают и переписываются, голос мешает. Допустимы вокализы без слов только там,
  где это прямо сказано ниже, и тихо.
- **Петля**: начало и конец в одной тональности и темпе, без затухания в конце и без вступления «из тишины», чтобы
  стык не был слышен. Если генератор делает затухание — отрежем по такту, но лучше без него.
- **Фон, а не концерт**: средняя громкость ровная, нет внезапных ударов, кульминаций и соло на первом плане.
- **Без имён реальных исполнителей и композиторов в промптах** — только жанр, эпоха, инструменты, настроение.
- Формат: лучше **WAV** — без потерь; в Opus мы сожмём один раз. Если генератор отдаёт только MP3 — бери 320 кбит/с. Сжатие (Opus ~96 кбит/с, ~1–1,5 МБ на петлю) и нормализация громкости
  (около −18 LUFS для фона) — наша часть.
- Имена файлов: `<world_id>_<slot>.mp3`, например `manor_lake_night.mp3`; оболочка — `shell_theme.mp3`.
  Если вариантов несколько — `_v2`, `_v3`, выберем при прослушивании.
- Складывать в `docs/tasks/night_city/music/<world_id>/` (в git не идёт, как и арт).

## 3. Промпты

Промпты на английском — генераторы музыки понимают его лучше. Русская строка — суть для нас.

### Оболочка — `shell_theme`
Нейтральный нуар: ночной город вообще, без эпохи и сюжета.
> Instrumental noir lounge, slow 70 bpm, upright bass walking softly, brushed drums, muted trumpet phrases far in the background, soft rain ambience, dark and elegant, seamless loop, no vocals, no build-ups

### Усадьба у озера — `manor_lake` (1930-е, зима, метель, отрезанная усадьба, без мистики)
- `day`: камерное, тёплое снаружи, тревожное внутри.
> Instrumental 1930s chamber music, solo piano and string quartet, slow waltz feel 80 bpm, wintry and intimate, creaking old house warmth with an undercurrent of suspicion, seamless loop, no vocals
- `night`: метель за окном, керосиновая лампа, кто-то ходит по коридору.
> Dark ambient chamber piece, low cello drones, sparse prepared piano notes, distant wind and snowstorm texture, ticking clock, slow and tense, seamless loop, no vocals, no percussion hits
- `finale`:
> Short orchestral resolution, piano and strings, 20 seconds, bittersweet final chord, 1930s drama, no vocals

### Ночной экспресс — `night_express` (1936, зима, поезд через перевал, ар-деко)
- `day`: вагон-ресторан, бархат и латунь, ритм колёс.
> Instrumental 1930s art deco swing, small salon band, clarinet and piano, gentle train rhythm in the percussion, elegant and slightly nervous, 100 bpm, seamless loop, no vocals
- `night`: тёмный тоннель, стук колёс, шорох в соседнем купе.
> Dark instrumental, steady train-wheel rhythm on low percussion, sustained low strings, muffled whistle far away, tension of a night train through mountains, seamless loop, no vocals
- `finale`:
> Short art deco orchestral sting, brass and strings, train arriving at a station, 20 seconds, decisive ending, no vocals

### Чёрная бухта — `black_bay` (1920-е, приморский городок, туман, колокол маяка, тихая мистика)
- `day`:
> Instrumental folk-noir, 1920s seaside town, accordion and fiddle played slowly and quietly, distant gulls and waves, melancholic and secretive, 75 bpm, seamless loop, no vocals
- `night`: туман, колокол маяка, что-то не так.
> Dark ambient, foghorn and distant lighthouse bell, low bowed bass, eerie harmonium chords, waves against wooden piers, slow creeping tension, seamless loop, no vocals
- `finale`:
> Short eerie resolution, harmonium and bell, 20 seconds, unresolved then settling chord, sea ambience fading in, no vocals

### Газетный город — `newsprint_city` (1950-е, ночной город, газета, телефонные станции)
- `day`: деловой нуар, пишущие машинки.
> Instrumental 1950s cool jazz, walking bass, vibraphone and muted trumpet, subtle typewriter clicks as percussion, smoky newsroom at night, 90 bpm, seamless loop, no vocals
- `night`:
> Dark 1950s film noir underscore, low saxophone lines, brushed snare, distant telephone ring and city hum, slow suspense, seamless loop, no vocals
- `finale`:
> Short film noir sting, brass hit and saxophone phrase, 20 seconds, headline-style ending, no vocals

### Дворец масок — `palace_masks` (1890-е, маскарад, люстры, зеркала, барочная роскошь)
- `day`: бальный зал, но чуть фальшиво.
> Instrumental baroque-style masquerade waltz, harpsichord and string ensemble, elegant yet slightly off-kilter, 1890s palace ball, 90 bpm, seamless loop, no vocals
- `night`: пустой зал, музыка там, где нет оркестра.
> Dark music-box waltz echoing in an empty palace hall, detuned celesta, slow strings, reverb of distant ballroom, unsettling elegance, seamless loop, no vocals
- `finale`:
> Short baroque orchestral reveal, harpsichord flourish and strings, unmasking moment, 20 seconds, final chord, no vocals

### Полярная звезда — `polar_star` (1912, экспедиция во льдах, полярная ночь, радио)
- `day`: суровый быт, лагерь, ветер.
> Instrumental ambient folk, solo cello and soft accordion, arctic wind, sparse and cold, 1912 polar expedition camp, slow 70 bpm, seamless loop, no vocals
- `night`: треск льда, радиопомехи, огни там, где их нет. Здесь допустим тихий вокализ без слов, далеко на фоне.
> Dark arctic ambient, cracking ice, distant radio static and morse fragments, low drones, very faint wordless voice far in the background, isolation and dread, seamless loop
- `finale`:
> Short cold orchestral resolution, cello and low brass, 20 seconds, wind dying down, no vocals

### Цирк «Балаган» — `circus` (1900-е, бродячий цирк, шатры, ярмарка)
- `day`: шарманка и ярмарка, но за кулисами.
> Instrumental vintage circus music, barrel organ and small brass band, playful but a little worn and melancholic, 1900s travelling circus backstage, 100 bpm, seamless loop, no vocals
- `night`: пустой шатёр, скрипит канат.
> Dark slow circus waltz, detuned calliope, low tuba, creaking ropes and wind in canvas, empty big top at night, eerie, seamless loop, no vocals
- `finale`:
> Short circus fanfare that slows and detunes at the end, 20 seconds, brass and drum roll, bittersweet, no vocals

### Кампус — `campus` (наши дни, университет, внутренняя «Сеть»)
- `day`: учёба, хакатон, лёгкая электроника.
> Instrumental lo-fi electronic, soft synth pads, mellow beat, modern university campus, focused and slightly uneasy, 85 bpm, seamless loop, no vocals
- `night`: пустые коридоры, мигающие лампы, Сеть отвечает не тем тоном.
> Dark minimal electronic, glitchy clicks, low sub bass pulse, flickering fluorescent hum, empty corridors at night, cold and watchful, seamless loop, no vocals
- `finale`:
> Short electronic resolution, synth swell and glitch cut, 20 seconds, clean ending, no vocals

### Песчаный город — `sand_city` (1920-е, пустыня, раскоп нечеловеческого города)
- `day`: лагерь экспедиции, жара, ветер.
> Instrumental desert ambient, oud and frame drum played softly, warm wind, 1920s archaeological camp, vast and quiet, 75 bpm, seamless loop, no vocals
- `night`: масштаб и пустота, геометрия, которая не сходится.
> Dark cosmic desert ambient, deep drones, sand hiss, slow dissonant bowed metal, sense of immense ancient scale, time feels wrong, seamless loop, no vocals
- `finale`:
> Short cosmic resolution, deep drone swelling to a single chord, 20 seconds, sandstorm fading, no vocals

### Неон-Сити — `neon_city` (2089, киберпанк, неон, дождь по расписанию)
- `day`:
> Instrumental synthwave noir, warm analog synths, steady mid-tempo beat, rain on glass, neon city 2089, cool and detached, 95 bpm, seamless loop, no vocals
- `night`:
> Dark cyberpunk ambient, deep bass pulses, distorted city hum, rain ambience, distant sirens filtered, slow tension, seamless loop, no vocals
- `finale`:
> Short synth sting, arpeggio rising to a held chord, 20 seconds, cyberpunk resolution, no vocals

### Сухой закон — `prohibition` (1929, портовый город, джаз в прачечных, длинные машины)
- `day`: подпольный джаз.
> Instrumental 1920s speakeasy jazz, honky-tonk piano, clarinet and banjo, quiet and smoky, 1929 port city, 110 bpm, seamless loop, no vocals
- `night`: туман над портом, мотор вдали.
> Dark 1920s noir underscore, low muted trumpet, slow double bass, foghorn and distant car engine, harbour at night, tense and hushed, seamless loop, no vocals
- `finale`:
> Short jazz band sting, brass stab and piano run, 20 seconds, case-closed ending, no vocals

### Глубинный хор — `deep_choir` (16+, 1930-е, шахтёрский город, пласт отвечает на стук голосами)
Самый мистический мир. Здесь допустим тихий хоровой вокализ без слов — он и есть «хор».
- `day`: город над шахтой, гудок смены, усталость.
> Instrumental industrial folk, 1930s mining town, slow heavy rhythm like distant machinery, low brass and harmonium, weary and grim, 70 bpm, seamless loop, no vocals
- `night`: глубина, стук в породе, голоса из камня.
> Dark chthonic ambient, deep subterranean drones, rhythmic knocking on rock, dripping water, very low wordless male choir far below, immense pressure and dread, seamless loop
- `finale`:
> Short dark choral resolution, low wordless choir and deep drone ending on one heavy chord, 25 seconds, rock settling

### Мёртвый эфир — `dead_air` (16+, конец 1990-х, ночная телестанция, кассеты с неснятыми кадрами)
- `day`: студия, мониторы, дежурный эфир.
> Instrumental late 1990s analog synth ambient, warm VHS-like detuned pads, soft drum machine, tape hiss, late-night TV station, uneasy calm, 80 bpm, seamless loop, no vocals
- `night`: помехи, обрывок сигнала, кадр, которого не было.
> Dark analog horror ambient, TV static swells, warped tape wow and flutter, low hum of CRT monitors, distorted broadcast tone fragments, slow creeping dread, seamless loop, no vocals
- `finale`:
> Short analog horror sting, signal cuts to static then a single warped synth chord, 20 seconds, broadcast ends, no vocals

## 4. Как подключим (после генерации)

- В `pack.json` мира появится группа `music` со слотами `day`, `night`, `finale`; у оболочки — `shell_theme`.
  Нет слота — тишина, игра не ломается.
- Музыка **по умолчанию выключена** и включается в меню ⚙ («Музыка: вкл/выкл» и громкость); в Telegram и
  браузерах звук может начаться только после первого касания.
- Дорожки грузятся лениво, только для мира текущей комнаты; между `day` и `night` — плавный переход 1–2 с.
- Выбор между вариантами `_v2`/`_v3` — при прослушивании вместе с владельцем.
