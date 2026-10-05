"""Game content: explicit, deterministic recipes. No network or dependencies."""
from pathlib import Path
import json, re
ROOT=Path(__file__).parent
CATEGORIES=[
 ('basic','Стихии','#7e9da0'),('nature','Природа','#82b370'),('weather','Погода','#8fbac8'),
 ('life','Живой мир','#a1be72'),('materials','Материалы','#cfad80'),('science','Силы и вещества','#e1be67'),
 ('food','Кухня','#d89377'),('craft','Изобретения','#c7a379'),('space','Космос','#a29cdd'),('magic','Чудеса','#cda0bf')]
# id | Russian name | category | illustrated motif | short, fictional almanac entry
RAW='''water|Вода|basic|water|Всё начинается с капли. Даже океан когда-то был маленьким.
earth|Земля|basic|earth|Тихая опора для всего, что однажды вырастет.
fire|Огонь|basic|fire|Нетерпеливая стихия: ей всегда хочется что-нибудь изменить.
air|Воздух|basic|air|Его не видно, зато без него не взлетит ни одно приключение.
mud|Грязь|nature|mud|Земля после купания. Гораздо интереснее, чем кажется.
dust|Пыль|nature|dust|Маленькие путешественники, которых подхватил ветер.
sand|Песок|nature|sand|Камни, научившиеся проходить сквозь пальцы.
swamp|Болото|nature|swamp|Тихая лаборатория природы, где жизнь пробует первые рецепты.
forest|Лес|nature|forest|Когда деревья собираются вместе, у ветра появляются истории.
desert|Пустыня|nature|desert|Море песка, в котором волны не спешат.
grass|Трава|nature|grass|Мягкий ковёр для первого шага по новому миру.
mountain|Гора|nature|mountain|Камень, который слишком долго мечтал о небе.
sky|Небо|nature|sky|Самое большое полотно в мире. Каждый день новая картина.
night|Ночь|nature|night|Время, когда самые далёкие огоньки становятся заметны.
ocean|Океан|nature|ocean|Целый мир под поверхностью другого мира.
sea|Море|nature|sea|Большая вода с маленькими обещаниями дальних берегов.
river|Река|nature|river|Вода, которая выбрала дорогу и больше не передумала.
lake|Озеро|nature|lake|Кусочек неба, бережно положенный на землю.
island|Остров|nature|island|Земля, которой нравится иногда побыть одной.
beach|Пляж|nature|beach|Место встречи двух миров и бесконечных следов.
volcano|Вулкан|nature|volcano|Гора, у которой очень горячие мысли.
soil|Почва|nature|soil|Маленькая вселенная под корнями большого дерева.
steam|Пар|weather|steam|Вода решила подняться повыше и посмотреть вокруг.
rain|Дождь|weather|rain|Облака вспоминают, откуда они пришли.
cloud|Облако|weather|cloud|Коллекция капель с очень свободным расписанием.
smoke|Дым|weather|smoke|История огня, написанная в воздухе.
storm|Шторм|weather|storm|Погода перестала говорить шёпотом.
lightning|Молния|weather|lightning|Очень короткая подпись неба.
snow|Снег|weather|snow|Вода попробовала себя в бумажных кружевах.
fog|Туман|weather|fog|Облако вышло погулять по земле.
rainbow|Радуга|weather|rainbow|Свет разобрал себя на любимые цвета.
wind|Ветер|weather|wind|Воздух, у которого появились планы.
hurricane|Ураган|weather|hurricane|Когда ветер слишком увлёкся танцами.
dew|Роса|weather|dew|Украшения, которые утро оставляет на листьях.
blizzard|Метель|weather|blizzard|Снег отправился в дорогу раньше весны.
plant|Растение|life|plant|Первое маленькое «да» в ответ на пустую землю.
seed|Семя|life|seed|Внутри уже спрятан целый сад. Осталось начать.
tree|Дерево|life|tree|Медленно, зато сразу в двух направлениях: к солнцу и к воде.
algae|Водоросли|life|algae|Подводный сад, которому не нужна лейка.
bacteria|Бактерии|life|bacteria|Самые маленькие участники самых больших перемен.
bird|Птица|life|bird|Жизнь нашла способ попробовать небо на вкус.
fish|Рыба|life|fish|Плавники вместо крыльев. Тоже вполне хороший план.
animal|Животное|life|animal|У мира появился тот, кто будет его исследовать.
human|Человек|life|human|Сначала любопытство. Потом инструменты. Потом вопрос: а что ещё?
lizard|Ящерица|life|lizard|Маленький дракон, который пока не определился с огнём.
horse|Лошадь|life|horse|Ветер согласился ненадолго стать животным.
heart|Сердце|life|heart|Небольшой ритм, который делает огромную работу.
blood|Кровь|life|blood|Тёплая река внутри живого мира.
wound|Рана|life|wound|Напоминание: даже в лаборатории чудес нужна осторожность.
flower|Цветок|life|flower|Растение нашло красивый способ пригласить гостей.
mushroom|Гриб|life|mushroom|Лесной зонтик, который не советует верить всем зонтикам.
egg|Яйцо|life|egg|Самая компактная упаковка для нового начала.
insect|Насекомое|life|insect|Шесть ног, большие планы и целый мир травинок.
bee|Пчела|life|bee|Крохотный специалист по цветам и сладким результатам.
butterfly|Бабочка|life|butterfly|Удивительный ответ на вопрос, кем можно стать потом.
cat|Кот|life|cat|Считает себя заведующим лабораторией. Возможно, так и есть.
mouse|Мышь|life|mouse|Маленький исследователь с особым интересом к сыру.
dog|Собака|life|dog|Счастье, которое первым бежит к двери.
wolf|Волк|life|wolf|Лесной голос, который слышнее всего под луной.
turtle|Черепаха|life|turtle|Никуда не торопится: дом всегда рядом.
coral|Коралл|life|coral|Подводный город, построенный терпением.
whale|Кит|life|whale|Океан доверил ему свои самые глубокие песни.
dinosaur|Динозавр|life|dinosaur|Время иногда выращивает очень большие сюрпризы.
dragonfly|Стрекоза|life|dragonfly|Пилот болотных аэродромов с четырьмя прозрачными крыльями.
lava|Лава|materials|lava|Камень ещё не решил стать твёрдым.
stone|Камень|materials|stone|Надёжный ингредиент. Обычно никуда не убегает.
clay|Глина|materials|clay|Материал, который охотно слушается рук.
ice|Лёд|materials|ice|Вода взяла паузу и стала почти драгоценностью.
glass|Стекло|materials|glass|Позволяет видеть стену насквозь, не проходя через неё.
metal|Металл|materials|metal|Терпеливо ждёт, пока кто-нибудь придумает инструмент.
gold|Золото|materials|gold|Очень убедительный аргумент для алхимика.
wood|Древесина|materials|wood|Дерево готово начать вторую жизнь.
coal|Уголь|materials|coal|Старое тепло, которое ещё может пригодиться.
diamond|Алмаз|materials|diamond|Давление не всегда портит характер.
ash|Пепел|materials|ash|Конец одной истории и начало другой почвы.
mineral|Минерал|materials|mineral|Тихое сокровище горных недр.
crystal|Кристалл|materials|crystal|Природа однажды попробовала геометрию.
copper|Медь|materials|copper|Тёплый цвет для холодных проводов.
steel|Сталь|materials|steel|Металл, который стал серьёзнее относиться к нагрузкам.
paper|Бумага|materials|paper|Тонкий материал для очень толстых историй.
thread|Нить|materials|thread|Всё большое полотно начинается с тонкой линии.
fabric|Ткань|materials|fabric|Множество нитей договорились держаться вместе.
brick|Кирпич|materials|brick|Маленький прямоугольник с большими архитектурными амбициями.
obsidian|Обсидиан|materials|obsidian|Застывшая тёмная память вулкана.
oil|Нефть|materials|oil|Далёкое прошлое осталось под землёй в жидком виде.
rubber|Резина|materials|rubber|Материал с редким умением возвращаться в форму.
plastic|Пластик|materials|plastic|Почти любая форма. Поэтому ответственность особенно важна.
silicon|Кремний|materials|silicon|От песчинки до мысли компьютера — удивительно длинная дорога.
energy|Энергия|science|energy|Способность превратить «можно было бы» в «получилось».
life|Жизнь|science|life|Самое неожиданное свойство материи: ей стало интересно.
time|Время|science|time|Не торопится, но меняет абсолютно всё.
light|Свет|science|light|Первый инструмент для поиска потерянных вещей и новых идей.
darkness|Тьма|science|darkness|Не всё неизвестное страшно. Иногда там просто нет лампы.
sound|Звук|science|sound|Воздух научился передавать настроение.
thought|Мысль|science|thought|Самая лёгкая вещь, способная сдвинуть целый мир.
heat|Тепло|science|heat|Невидимый повод придвинуться ближе.
cold|Холод|science|cold|Мир немного замедляет шаг.
pressure|Давление|science|pressure|Когда обстоятельства становятся слишком тесными.
gravity|Гравитация|science|gravity|Невидимая причина, по которой всё стремится встретиться.
magnetism|Магнетизм|science|magnetism|У металлов тоже бывают необъяснимые симпатии.
explosion|Взрыв|science|explosion|Открытие, которое точно услышали в соседней комнате.
plasma|Плазма|science|plasma|Вещество перестало стесняться и начало светиться.
acid|Кислота|science|acid|Зелёная колба из сказочной лаборатории. Не пробовать!
base|Щёлочь|science|base|Вторая сторона старого алхимического спора.
salt|Соль|science|salt|Маленькие кристаллы с большим кулинарным влиянием.
alcohol|Спирт|science|alcohol|В этой лаборатории используется только как игровой реагент.
gas|Газ|science|gas|Вещество, которое не любит жёсткие границы.
radioactivity|Радиоактивность|science|radioactivity|Светящийся знак: изучать только издалека.
fruit|Фрукт|food|fruit|Дерево решило красиво упаковать свои семена.
vegetable|Овощ|food|Съедобная причина завести огород.
meat|Мясо|food|Ингредиент для тех, кто не ограничился салатом.
bread|Хлеб|food|Мука, тепло и немного домашнего счастья.
cheese|Сыр|food|Молоко научилось ждать с пользой.
soup|Суп|food|Целый огород собрался в одной миске.
cake|Торт|food|Доказательство того, что праздник можно собрать по рецепту.
wheat|Пшеница|food|Золотое поле будущих завтраков.
milk|Молоко|food|Белая отправная точка множества вкусных открытий.
flour|Мука|food|Зерно стало гораздо ближе к хлебу.
dough|Тесто|food|Пока ещё не завтрак, но уже обещание.
tea|Чай|food|Короткая пауза между двумя великими открытиями.
coffee|Кофе|food|Официальный реагент слишком поздних экспериментов.
honey|Мёд|food|Лето, которое пчёлы научились хранить.
chocolate|Шоколад|food|Маленькое открытие с большим количеством поклонников.
cookie|Печенье|food|Хрустящая награда за терпение.
pizza|Пицца|food|Круглое доказательство того, что сыр почти всегда помогает.
tool|Инструмент|craft|tool|Руки поняли, что не обязаны справляться в одиночку.
wheel|Колесо|craft|wheel|Некоторые хорошие идеи действительно ходят по кругу.
electricity|Электричество|craft|electricity|Невидимая доставка энергии прямо к идее.
computer|Компьютер|craft|computer|Очень быстрый помощник, которому всё равно нужны хорошие вопросы.
robot|Робот|craft|robot|Инструмент, которому захотелось выдать отдельный стол.
internet|Интернет|craft|internet|Компьютеры познакомились. Последствия оказались огромными.
smartphone|Смартфон|craft|smartphone|Маленькое окно, за которым помещается почти весь мир.
house|Дом|craft|house|Место, где приключение можно ненадолго отложить.
village|Деревня|craft|village|Несколько домов решили стать соседями.
city|Город|craft|city|Много историй, которые происходят одновременно.
farm|Ферма|craft|farm|Человек и природа пытаются составить общее расписание.
temple|Храм|craft|temple|Место для вопросов, которые больше повседневных забот.
pyramid|Пирамида|craft|pyramid|Каменная геометрия с очень длинной биографией.
castle|Замок|craft|castle|Дом, который слишком серьёзно отнёсся к безопасности.
ruins|Руины|craft|ruins|Архитектура после долгого разговора со временем.
religion|Религия|craft|religion|Попытка найти смысл за границей видимого.
knight|Рыцарь|craft|knight|Человек, который надел на себя очень много металла.
question|Вопрос|craft|question|Самый полезный инструмент в любой лаборатории.
boat|Лодка|craft|boat|Древесина получила разрешение путешествовать по воде.
sail|Парус|craft|sail|Ткань нашла общий язык с ветром.
pottery|Керамика|craft|pottery|Глина стала сохранять не только форму, но и истории.
book|Книга|craft|book|Чьи-то мысли получили обложку и шанс пережить автора.
music|Музыка|craft|music|Звук, который научился рассказывать без слов.
paint|Краска|craft|paint|Теперь цвет можно переносить с места на место.
art|Искусство|craft|art|То, что не обязано быть полезным, чтобы быть необходимым.
clock|Часы|craft|clock|Попытка договориться со временем на понятном языке.
engine|Двигатель|craft|engine|Энергия устроилась на работу.
car|Автомобиль|craft|car|Колесо наконец обзавелось собственным характером.
train|Поезд|craft|train|Дорога, которая точно знает, куда поворачивать.
airplane|Самолёт|craft|airplane|Человек решил не ждать, пока отрастут крылья.
rocket|Ракета|craft|rocket|Вопрос «что там наверху?» получил очень громкий ответ.
satellite|Спутник|craft|satellite|Маленькая техника на очень большой круговой прогулке.
printer|3D-принтер|craft|printer|Идеи становятся вещами. Слой за слоем, иногда после калибровки.
space|Космос|space|space|За пределами знакомого неба начинается всё остальное.
universe|Вселенная|space|universe|Самый большой результат из самых маленьких начал.
planet|Планета|space|planet|Дом, которому не понадобились стены.
star|Звезда|space|star|Далёкая печь, у которой когда-нибудь может появиться история.
comet|Комета|space|comet|Ледяной путешественник с роскошным шлейфом.
blackhole|Чёрная дыра|space|blackhole|Очень убедительная причина не подходить слишком близко.
galaxy|Галактика|space|galaxy|Миллиарды огней решили держаться одной компанией.
asteroid|Астероид|space|asteroid|Камень, которому не сиделось на планете.
alien|Инопланетянин|space|alien|Где-то кто-то тоже пытается смешать воду с огнём.
sun|Солнце|space|sun|Самая важная лампа в этой лаборатории.
moon|Луна|space|moon|Ночная спутница больших и маленьких мечтателей.
nebula|Туманность|space|nebula|Звёздная мастерская ещё не закончила уборку.
dragon|Дракон|magic|dragon|Ящерица прочитала слишком много легенд.
phoenix|Феникс|magic|phoenix|Птица, у которой окончание истории всегда временное.
unicorn|Единорог|magic|unicorn|Лошадь согласилась на один очень необычный аксессуар.
mermaid|Русалка|magic|mermaid|Море тоже умеет рассказывать сказки о людях.
centaur|Кентавр|magic|centaur|Удобный ответ на вопрос, кто поведёт лошадь.
elf|Эльф|magic|elf|Лес оставил для себя человеческий голос.
wizard|Волшебник|magic|wizard|Тот же исследователь, только с менее строгими ограничениями.
magic|Магия|magic|magic|Когда любопытство доходит дальше привычных объяснений.
joy|Радость|magic|joy|Результат, который хочется немедленно кому-нибудь показать.
sadness|Грусть|magic|sadness|Иногда миру нужен дождь даже без облаков.
anger|Гнев|magic|anger|Внутренний огонь, которому полезно дать остыть.
fear|Страх|magic|fear|Сигнал осторожности. Не всегда точный, но очень громкий.
love|Любовь|magic|love|Некоторые соединения не хочется разъединять.
curiosity|Любопытство|magic|curiosity|Главный двигатель этой игры и большинства открытий.
surprise|Удивление|magic|surprise|Момент, когда мир оказался чуть больше, чем ожидалось.
golem|Голем|magic|golem|Глина вспомнила, что когда-то хотела погулять.
fairy|Фея|magic|fairy|Магия решила попробовать маленький формат.
potion|Зелье|magic|potion|Неизвестный эффект в очень убедительной бутылочке.
portal|Портал|magic|portal|Дверь, у которой по-настоящему необычная вторая сторона.
philosopher|Философский камень|magic|philosopher|Великое делание завершено. Но любопытство на этом не заканчивается.'''
ELEMENTS=[]
for line in RAW.splitlines():
 parts=line.split('|')
 if len(parts)==4: i,n,c,d=parts; art=i
 else: i,n,c,art,d=parts
 ELEMENTS.append({'id':i,'name':n,'category':c,'art':art,'description':d})
E={e['id']:e for e in ELEMENTS}
# Each unordered pair has one result. All quantities are abstract game associations.
RECIPES=[]
def add(result, *pairs):
 for p in pairs:
  a,b=p.split('+'); RECIPES.append({'a':a,'b':b,'result':result,'key':'+'.join(sorted((a,b)))})
add('steam','water+fire')
add('mud','water+earth')
add('lava','earth+fire')
add('dust','earth+air')
add('energy','air+fire')
add('stone','earth+earth','lava+air')
add('rain','water+air','cloud+water')
add('wind','air+air')
add('heat','fire+fire','fire+energy')
add('pressure','earth+energy','air+airplane')
add('sand','stone+air','stone+wind')
add('clay','mud+sand','mud+fire')
add('cloud','steam+air','water+sky')
add('smoke','fire+wood','fire+coal')
add('seed','earth+rain','plant+wind')
add('plant','mud+seed','earth+seed','earth+life')
add('tree','earth+plant','plant+time')
add('algae','water+plant','plant+sea')
add('swamp','mud+plant','mud+lake')
add('bacteria','swamp+energy','life+mud')
add('life','water+energy','swamp+lightning')
add('bird','air+life','egg+air')
add('fish','water+life','egg+water')
add('animal','soil+life','life+stone')
add('human','animal+fire','animal+time')
add('time','sand+glass','sand+energy')
add('cold','rain+wind','night+wind')
add('ice','water+cold','lake+cold')
add('glass','sand+fire','sand+heat')
add('metal','stone+fire','mineral+fire')
add('gold','metal+light','metal+philosopher')
add('wood','tree+tool','tree+wind')
add('coal','tree+fire','wood+time')
add('diamond','coal+pressure','coal+time')
add('storm','rain+energy','cloud+wind')
add('lightning','storm+energy','cloud+electricity')
add('snow','rain+cold','cloud+cold')
add('fog','cloud+earth','steam+cold')
add('rainbow','water+light','rain+sun')
add('light','energy+energy','fire+glass')
add('darkness','light+time','night+night')
add('sound','air+energy','metal+wind')
add('space','sky+night','sky+star')
add('universe','galaxy+time','galaxy+galaxy')
add('fruit','tree+sun','tree+flower')
add('vegetable','plant+soil','plant+farm')
add('meat','animal+tool')
add('bread','dough+fire','dough+heat')
add('cheese','milk+bacteria','milk+time')
add('soup','water+vegetable','vegetable+heat')
add('cake','bread+fruit','dough+chocolate')
add('tool','human+stone','human+metal')
add('wheel','wood+stone','wood+tool')
add('electricity','energy+metal','metal+lightning')
add('computer','electricity+silicon','electricity+thought')
add('robot','computer+metal','computer+tool')
add('internet','computer+computer','computer+satellite')
add('smartphone','computer+glass','computer+sound')
add('dragon','lizard+fire','dinosaur+magic')
add('phoenix','bird+fire','bird+ash')
add('unicorn','horse+magic','horse+rainbow')
add('mermaid','human+fish','human+sea')
add('centaur','human+horse')
add('elf','human+forest')
add('wizard','human+magic','human+potion')
add('planet','earth+space','earth+star')
add('star','fire+space','energy+space')
add('comet','ice+space','ice+star')
add('blackhole','star+gravity','star+pressure')
add('galaxy','star+star','star+nebula')
add('asteroid','stone+space')
add('alien','life+space','life+planet')
add('joy','human+light','human+flower')
add('sadness','human+rain')
add('anger','human+fire')
add('fear','human+darkness')
add('love','human+heart','heart+heart')
add('curiosity','human+question','human+book')
add('surprise','human+explosion','human+alien')
add('village','house+house')
add('city','village+village','village+time')
add('farm','human+plant','house+wheat')
add('temple','stone+religion','house+religion')
add('pyramid','stone+desert','desert+human')
add('castle','house+knight','stone+knight')
add('ruins','time+city','castle+time')
add('acid','fruit+water','bacteria+water')
add('base','water+ash')
add('salt','acid+base','sea+heat')
add('alcohol','fruit+time')
add('gas','air+heat','oil+heat')
add('crystal','mineral+time','salt+pressure')
add('radioactivity','mineral+energy')
add('gravity','planet+planet','earth+planet')
add('magnetism','metal+pressure','electricity+copper')
add('explosion','fire+pressure','gas+fire')
add('plasma','gas+electricity','energy+heat')
add('sun','sky+fire','star+planet')
add('wheat','grass+human','grass+seed')
add('milk','water+animal','animal+farm')
add('lizard','animal+swamp','animal+stone')
add('horse','animal+grass','animal+wind')
add('magic','energy+curiosity','light+crystal')
add('forest','tree+tree')
add('heart','life+blood','life+human')
add('question','human+thought')
add('house','wood+clay','brick+wood')
add('religion','human+star')
add('desert','sand+sun','sand+sand')
add('knight','human+steel','human+castle')
add('ash','fire+plant','fire+grass')
add('mineral','stone+mountain','stone+pressure')
add('night','sky+time','sky+moon')
add('grass','plant+rain','plant+plant')
add('thought','human+energy','human+time')
add('blood','human+wound')
add('mountain','stone+stone','earth+pressure')
add('sky','air+cloud','cloud+cloud')
add('wound','human+tool')
add('sea','water+water')
add('ocean','sea+sea','sea+water')
add('lake','earth+sea','water+mountain')
add('river','mountain+rain','lake+water')
add('island','ocean+earth','sea+volcano')
add('beach','sea+sand','ocean+sand')
add('volcano','lava+mountain','lava+pressure')
add('soil','earth+ash','earth+mud')
add('hurricane','storm+wind','wind+wind')
add('dew','plant+cold','grass+fog')
add('blizzard','snow+wind','snow+storm')
add('flower','plant+sun','grass+rainbow')
add('mushroom','forest+rain','soil+bacteria')
add('egg','bird+bird','bird+life')
add('insect','grass+life','bacteria+air')
add('bee','insect+flower')
add('butterfly','insect+rainbow','insect+time')
add('cat','animal+house','animal+milk')
add('mouse','animal+cheese','cheese+life')
add('dog','animal+human','wolf+house')
add('wolf','animal+forest','dog+forest')
add('turtle','animal+sand','egg+stone')
add('coral','sea+life','stone+ocean')
add('whale','ocean+animal','fish+ocean')
add('dinosaur','lizard+time','lizard+earth')
add('dragonfly','insect+swamp','insect+wind')
add('copper','metal+earth','mineral+tool')
add('steel','metal+coal','metal+heat')
add('paper','wood+water','wood+pressure')
add('thread','grass+tool','plant+tool')
add('fabric','thread+thread')
add('brick','clay+fire','clay+heat')
add('obsidian','lava+water','lava+cold')
add('oil','algae+time','swamp+time')
add('rubber','tree+heat','oil+plant')
add('plastic','oil+fire','oil+pressure')
add('silicon','sand+electricity','sand+metal')
add('flour','wheat+stone','wheat+tool')
add('dough','flour+water','flour+milk')
add('tea','plant+heat','grass+heat')
add('coffee','seed+heat','seed+fire')
add('honey','bee+flower','bee+time')
add('chocolate','milk+seed','milk+honey')
add('cookie','dough+honey','bread+chocolate')
add('pizza','bread+cheese','dough+cheese')
add('boat','wood+sea','wood+river')
add('sail','fabric+wind','fabric+boat')
add('pottery','clay+human','clay+tool')
add('book','paper+thought','paper+paper')
add('music','sound+human','sound+wood')
add('paint','water+flower','water+mineral')
add('art','paint+paper','human+paint')
add('clock','time+tool','time+metal')
add('engine','metal+steam','metal+gas')
add('car','wheel+engine')
add('train','car+steel','engine+steel')
add('airplane','engine+air','car+bird')
add('rocket','engine+space','engine+explosion')
add('satellite','computer+space','rocket+computer')
add('printer','computer+plastic','robot+plastic')
add('moon','sky+stone','planet+stone')
add('nebula','dust+space','cloud+space')
add('golem','clay+life','stone+magic')
add('fairy','flower+magic','butterfly+magic')
add('potion','water+magic','plant+magic')
add('portal','space+magic','glass+magic')
add('philosopher','gold+magic','crystal+wizard')
# Integrity checks are deliberately part of the content build.
seen={}
for r in RECIPES:
 for x in (r['a'],r['b'],r['result']): assert x in E, ('unknown',x,r)
 assert r['key'] not in seen, ('conflicting or duplicated pair',seen.get(r['key']),r)
 assert r['result'] not in (r['a'],r['b']), ('unproductive recipe',r)
 seen[r['key']]=r
known=set(['water','earth','fire','air']); tiers={x:0 for x in known}
for step in range(len(E)):
 fresh={r['result'] for r in RECIPES if r['a'] in known and r['b'] in known}-known
 if not fresh:break
 for x in fresh:tiers[x]=step+1
 known|=fresh
assert set(E)==known, ('unreachable',set(E)-known)
for e in ELEMENTS:e['tier']=tiers[e['id']]
CHAPTERS=[
 {'id':'spark','title':'Первая искра','subtitle':'Каждое великое дело начинается с любопытства. Познакомь четыре стихии друг с другом.','goals':['steam','mud','lava','energy','stone'],'color':'#e3af72'},
 {'id':'world','title':'Мир просыпается','subtitle':'Добавь зелень, нарисуй берега и подними горы. Пустота постепенно становится домом.','goals':['plant','tree','ocean','mountain','flower'],'color':'#92bb7f'},
 {'id':'living','title':'Кто здесь живёт?','subtitle':'У нового мира появились обитатели. Одним нужны крылья, другим — просто немного заботы.','goals':['life','bird','animal','human','cat'],'color':'#a9c88a'},
 {'id':'home','title':'Дом для мечты','subtitle':'Построй уютное место, испеки хлеб и сохрани первые мысли на бумаге.','goals':['tool','house','bread','book','music'],'color':'#d1ae87'},
 {'id':'machine','title':'Сила изобретений','subtitle':'От первой искры до машины, которая создаёт новые вещи. Не забудь откалибровать стол.','goals':['electricity','engine','computer','robot','printer'],'color':'#86bab7'},
 {'id':'stars','title':'Выше знакомого неба','subtitle':'Подними голову: у этой лаборатории нет потолка. Дальше — только новые вопросы.','goals':['sun','moon','galaxy','rocket','alien'],'color':'#a6a1d9'},
 {'id':'wonder','title':'За гранью возможного','subtitle':'Некоторые открытия не объясняют мир. Они делают его чудеснее.','goals':['magic','dragon','phoenix','unicorn','fairy'],'color':'#c29ac4'},
 {'id':'great','title':'Великое делание','subtitle':'Собери три невозможных открытия. А потом продолжай: в атласе осталось ещё столько пустых страниц.','goals':['universe','portal','philosopher'],'color':'#e6c271'}]
ACHIEVEMENTS=[
 {'id':'first','name':'Эврика!','text':'Сделать первое открытие','type':'count','value':5,'art':'energy'},
 {'id':'explorer','name':'Уже не ученик','text':'Открыть 25 элементов','type':'count','value':25,'art':'tool'},
 {'id':'collector','name':'Коллекционер чудес','text':'Открыть 75 элементов','type':'count','value':75,'art':'book'},
 {'id':'master','name':'Мастер превращений','text':'Открыть 150 элементов','type':'count','value':150,'art':'wizard'},
 {'id':'complete','name':'Мир собран','text':'Заполнить весь атлас','type':'count','value':len(E),'art':'universe'},
 {'id':'pets','name':'Кошки-мышки','text':'Открыть кота и мышь','type':'elements','elements':['cat','mouse'],'art':'cat'},
 {'id':'maker','name':'Слой за слоем','text':'Открыть 3D-принтер','type':'elements','elements':['printer'],'art':'printer'},
 {'id':'dragon','name':'Welizard','text':'Найти ящерицу и её огненного родственника','type':'elements','elements':['lizard','dragon'],'art':'lizard'},
 {'id':'breakfast','name':'Перерыв на открытия','text':'Найти хлеб, сыр, чай и печенье','type':'elements','elements':['bread','cheese','tea','cookie'],'art':'tea'},
 {'id':'space','name':'Звёздный картограф','text':'Открыть галактику, комету и чёрную дыру','type':'elements','elements':['galaxy','comet','blackhole'],'art':'galaxy'},
 {'id':'persistent','name':'Терпеливый исследователь','text':'Проверить 50 разных сочетаний','type':'tried','value':50,'art':'question'},
 {'id':'recipes','name':'Новые пути','text':'Записать 100 работающих рецептов','type':'recipes','value':100,'art':'potion'}]
DATA={'version':1,'elements':ELEMENTS,'recipes':RECIPES,'categories':[{'id':i,'name':n,'color':c} for i,n,c in CATEGORIES],'chapters':CHAPTERS,'achievements':ACHIEVEMENTS}
(ROOT/'data.json').write_text(json.dumps(DATA,ensure_ascii=False,separators=(',',':')))
print(f'{len(ELEMENTS)} elements / {len(RECIPES)} recipes / {len(CHAPTERS)} chapters / all reachable / max depth {max(tiers.values())}')
