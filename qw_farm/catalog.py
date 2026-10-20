"""Versioned original game content. No player data or network access."""
from copy import deepcopy
import math
from .projects import HOME_PROJECTS


def tick(now):
    """The one time normalisation: farm time is whole Unix seconds (floor). Wall clocks are float (time.time()); every entry
    point (service clock, apply, settle, project, new_farm) passes ``now`` through here, so range()/indices/JSON ints/validators
    never see a fraction. Legacy saved float deadlines stay valid: they are only compared and added to, never used as counts."""
    return math.floor(now)

VERSION = 'farm-2026-10-r9'
CROPS = {}
# id, title, seed cost, seconds, yield, unit NPC value, XP, level, tint
for row in [
    ('wheat','Пшеница',2,30,3,2,1,1,'#e4b746'),
    ('carrot','Морковь',4,120,3,5,3,1,'#e99248'),
    ('corn','Кукуруза',7,360,3,8,5,1,'#edcf58'),
    ('clover','Клевер',5,240,3,6,4,2,'#ce8cba'),
    ('strawberry','Клубника',12,1200,3,16,8,3,'#da6e69'),
    ('potato','Картофель',16,2700,4,14,12,4,'#c69f72'),
    ('sunflower','Подсолнух',22,3600,3,24,16,5,'#eeb744'),
    ('pumpkin','Тыква',32,10800,4,35,26,6,'#d88c40'),
    ('lavender','Лаванда',25,7200,3,28,22,7,'#a698cf'),
    ('tomato','Томаты',18,1800,3,19,10,4,'#d96d56'),
]:
    i,n,c,t,q,p,x,l,color=row
    CROPS[i]=dict(id=i,name=n,cost=c,seconds=t,yield_qty=q,price=p,xp=x,level=l,color=color)
ITEMS={k:dict(id=k,name=v['name'],price=v['price'],color=v['color'],kind='crop') for k,v in CROPS.items()}
for i,n,p,col in [('flour','Мука',10,'#e8daba'),('feed','Зерносмесь',8,'#ccb977'),('hay','Сено',12,'#bdd17b'),('egg','Яйца',11,'#f0dfc1'),('milk','Молоко',18,'#e3edf0'),('wool','Шерсть',25,'#dcd6ce'),('honey','Мёд',46,'#d6a83a'),('bread','Хлеб',29,'#ca8a50'),('bun','Булочка',39,'#d99b58'),('jam','Варенье',53,'#c56e7d'),('cheese','Сыр',53,'#efd05c'),('oil','Масло',64,'#c0b15c'),('soup','Овощной суп',57,'#bf805d'),('pie','Тыквенный пирог',175,'#dc9f62'),('yarn','Пряжа',67,'#c796b0'),('bouquet','Букет',99,'#b297c7'),('pancake','Оладьи',69,'#ca9457'),('salad','Дачный салат',70,'#7cab65')]:
    ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
BUILDINGS={}
for i,n,c,l,w,h in [('mill','Мельница',100,1,2,2),('feedmill','Кормоцех',80,2,2,2),('bakery','Пекарня',150,2,2,2),('kitchen','Летняя кухня',240,3,2,2),('dairy','Сыроварня',320,4,2,2),('loom','Мастерская',380,5,2,2),('coop','Курятник',100,1,2,2),('cowshed','Коровник',300,4,2,2),('sheepfold','Овчарня',420,5,2,2),('apiary','Пасека',500,7,2,2),('flowerbed','Клумба',35,1,1,1),('bench','Скамейка',45,1,1,1),('lantern','Фонарь',55,2,1,1),('scarecrow','Пугало',60,2,1,1)]:
    BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=w,h=h,decor=i in {'flowerbed','bench','lantern','scarecrow'})
BUILDINGS['road']=dict(id='road',name='Грунтовая дорога',cost=5,level=1,w=1,h=1,decor=True,ground=True)
RECIPES={}
for i,n,b,ingredients,out,t,l in [
 ('flour','Смолоть муку','mill',{'wheat':2},{'flour':1},60,1),
 ('feed','Смешать корм','mill',{'wheat':2},{'feed':2},45,1),
 ('mixedfeed','Зерносмесь','feedmill',{'corn':1,'wheat':1},{'feed':3},90,2),
 ('hay','Заготовить сено','feedmill',{'clover':2},{'hay':2},120,2),
 ('bread','Испечь хлеб','bakery',{'flour':2},{'bread':1},150,2),
 ('bun','Румяная булочка','bakery',{'flour':1,'egg':1},{'bun':1},180,2),
 ('pancake','Дачные оладьи','bakery',{'flour':1,'milk':1,'egg':1},{'pancake':1},480,4),
 ('jam','Клубничное варенье','kitchen',{'strawberry':2},{'jam':1},420,3),
 ('soup','Овощной суп','kitchen',{'potato':2,'carrot':2},{'soup':1},600,4),
 ('salad','Дачный салат','kitchen',{'tomato':2,'carrot':2},{'salad':1},300,4),
 ('cheese','Домашний сыр','dairy',{'milk':2},{'cheese':1},720,4),
 ('oil','Подсолнечное масло','mill',{'sunflower':2},{'oil':1},600,5),
 ('pie','Тыквенный пирог','bakery',{'flour':1,'pumpkin':3,'egg':1},{'pie':1},1200,6),
 ('yarn','Мягкая пряжа','loom',{'wool':2},{'yarn':1},900,5),
 ('bouquet','Ароматный букет','loom',{'lavender':3},{'bouquet':1},600,7),
 ('honeybun','Булочка с мёдом','bakery',{'flour':2,'honey':1},{'bun':3},900,7),
]:
    RECIPES[i]=dict(id=i,name=n,building=b,inputs=ingredients,outputs=out,seconds=t,level=l,xp=max(1,t//45))
ANIMALS={}
for i,n,b,inputs,out,t,l,c in [('chicken','Курочки','coop',{'feed':1},{'egg':2},240,1,65),('cow','Бурёнки','cowshed',{'hay':1},{'milk':2},900,4,180),('sheep','Овечки','sheepfold',{'hay':1},{'wool':2},1200,5,200),('bees','Пчёлы','apiary',{'lavender':1},{'honey':2},1800,7,220)]:
    ANIMALS[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,cost=c)
LEVELS=[0,20,65,135,240,400,650,1000,1500,2200,3100,4300,5800,7800,10300]
QUESTS=[
 dict(id='q1',name='Знакомство с землёй',text='Собери урожай с четырёх грядок. Он уже ждёт тебя — и никуда не убежит.',stat='harvests',goal=4,coins=45,xp=12),
 dict(id='q2',name='От зерна до дела',text='Получи три партии продукции. Мельница умеет не только красиво крутиться.',stat='crafts',goal=3,coins=70,xp=20),
 dict(id='q3',name='Первые поставки',text='Выполни три заказа для жителей. Филиныч обещал не съесть всё по дороге.',stat='orders',goal=3,coins=90,xp=25),
 dict(id='q4',name='Соседство начинается с тебя',text='Помоги соседу. Хорошие дела не требуют присутствия хозяина.',stat='helps',goal=1,coins=0,xp=15),
 dict(id='q5',name='Маленькая фабрика',text='Получи десять партий продукции и наладь собственные цепочки.',stat='crafts',goal=10,coins=140,xp=35),
 dict(id='q6',name='Свой уголок',text='Поставь три новых объекта: мастерскую, декор или ещё одну грядку.',stat='builds',goal=3,coins=110,xp=30),
 dict(id='q7',name='Завтрак для деревни',text='Доставь десять заказов. Здесь уже узнают твою тележку.',stat='orders',goal=10,coins=180,xp=50),
 dict(id='q8',name='Большой урожай',text='Собери урожай пятьдесят раз. Никаких обязательных серий заходов.',stat='harvests',goal=50,coins=250,xp=70),
 dict(id='q9',name='Ферма, которая дружит',text='Помоги соседям пять раз. Благодарность остаётся в журнале.',stat='helps',goal=5,coins=0,xp=45),
 dict(id='q10',name='Мастер хозяйства',text='Выполни двадцать пять заказов и оставь себе время на отдых.',stat='orders',goal=25,coins=400,xp=100),
]
NPCS=[('Филиныч','Для вечернего чаепития'),('Агата','На маленький деревенский праздник'),('Почтальон Ёж','В корзинку для дальней дороги'),('Механик Крот','Обед мастерской'),('Кошка Кая','К чаю и мурлыканью'),('Кошка Соня','Для сладкой дремоты на печке'),('Суслик Игорь','В запас на долгую зиму'),('Неведома Зверушка','Угощение для загадочного гостя'),('Медведь Пух','Для бодрости перед работой')]   # Frozen legacy order pool: rng % len(NPCS) must stay stable.
VILLAGE_QUESTS={
 'Лиса Даша':dict(item='carrot',qty=2,coins=12,xp=4,title='Морковка для тайника'),
 'Петух Олег':dict(item='wheat',qty=4,coins=12,xp=4,title='Завтрак перед рассветом'),
}

# Expansion r2. Stable IDs; existing crops/recipes retain their original values.
for row in [
 ('oat','Овёс',5,1800,4,6,5,1,'#cbb56e'),
 ('beet','Свёкла',9,600,3,11,6,2,'#bc667e'),
 ('cucumber','Огурцы',12,900,3,14,7,2,'#75a264'),
 ('cabbage','Капуста',15,2400,3,18,10,3,'#9bbb80'),
 ('peas','Горох',16,1500,4,15,9,3,'#86b56b'),
 ('rye','Рожь',14,7200,5,14,14,3,'#bca471'),
 ('raspberry','Малина',20,3600,4,22,15,4,'#c96785'),
 ('basil','Базилик',14,1800,3,18,10,4,'#83a47b'),
 ('blueberry','Голубика',26,10800,6,25,24,5,'#818bb6'),
 ('flax','Лён',26,14400,5,24,28,6,'#a6bad0'),
 ('rice','Рис',30,21600,6,25,34,7,'#bdd4aa'),
 ('watermelon','Арбуз',45,28800,5,42,42,8,'#659269'),
]:
 i,n,c,t,q,p,x,l,color=row
 CROPS[i]=dict(id=i,name=n,cost=c,seconds=t,yield_qty=q,price=p,xp=x,level=l,color=color)
 ITEMS[i]=dict(id=i,name=n,price=p,color=color,kind='crop')
for i,n,p,col,kind in [
 ('mushroom','Белые грибы',18,'#bc9e79','forest'),
 ('chanterelle','Лисички',23,'#e3b26f','forest'),
 ('wildberry','Лесная земляника',17,'#c56e7d','forest'),
 ('blackberry','Ежевика',24,'#82799e','forest'),
 ('herbs','Душистые травы',14,'#8aaa79','forest'),
 ('wood','Древесина',8,'#a77c52','forest'),
 ('hazelnut','Лесной орех',21,'#b69468','forest'),
 ('duck_egg','Утиные яйца',14,'#d8e3d3','product'),
 ('goat_milk','Козье молоко',24,'#e8e3d1','product'),
 ('rabbit_fluff','Кроличий пух',28,'#e1d6cf','product'),
 ('alpaca_fiber','Волокно альпаки',36,'#ceb797','product'),
 ('feather','Гусиные перья',22,'#deded5','product'),
 ('mushroom_soup','Грибной суп',83,'#b6926e','product'),
 ('berry_jam','Лесной джем',66,'#a4687f','product'),
 ('tea','Травяной чай',53,'#aeb47a','product'),
 ('pickles','Хрустящие огурчики',58,'#99b87f','product'),
 ('goat_cheese','Козий сыр',72,'#dfd09d','product'),
 ('linen','Льняное полотно',94,'#d3c8af','product'),
 ('forest_pie','Пирог лесника',96,'#c8915e','product'),
 ('oat_cookie','Овсяное печенье',65,'#ceac72','product'),
 ('pillow','Пуховая подушка',100,'#d7cbd7','product'),
 ('scarf','Шарф из альпаки',96,'#b49bb6','product'),
 ('vegetable_stew','Рагу с горошком',132,'#aca16d','product'),
 ('berry_milk','Ягодное молоко',117,'#c18ba8','product'),
 ('rice_pudding','Рисовый пудинг',125,'#d9d5b9','product'),
]:
 ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind=kind)
for i,n,c,l,w,h,decor in [
 ('duckpond','Утиный пруд',220,3,2,2,False),
 ('goatshed','Козий домик',340,4,2,2,False),
 ('rabbit_hutch','Крольчатник',270,3,2,2,False),
 ('alpaca_pen','Домик альпак',650,7,2,2,False),
 ('goose_house','Гусиный двор',300,4,2,2,False),
 ('teahouse','Чайная беседка',260,3,2,2,False),
 ('garage','Гараж механика',90,2,2,2,True),
 ('basket','Корзины лесника',40,1,1,1,True),
 ('alchemist_table','Стол алхимика',65,1,1,1,True),
 ('night_lantern','Фонарь Ночного города',65,1,1,1,True),
 ('elements_stone','Камень четырёх стихий',65,1,1,1,True),
 ('detective_scarecrow','Пугало-детектив',65,1,1,1,True),
]:
 BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=w,h=h,decor=decor)
for i,secret in [('alchemist_table','atlas'),('night_lantern','night'),('elements_stone','elements'),('detective_scarecrow','detective')]:
 BUILDINGS[i]['secret']=secret
for i,n,b,inputs,out,t,l,c in [
 ('duck','Уточки','duckpond',{'feed':1},{'duck_egg':2},600,3,120),
 ('goat','Козочки','goatshed',{'hay':1,'carrot':1},{'goat_milk':2},1500,4,180),
 ('rabbit','Пушистые кролики','rabbit_hutch',{'carrot':2},{'rabbit_fluff':2},1800,3,130),
 ('alpaca','Альпаки','alpaca_pen',{'hay':2},{'alpaca_fiber':2},3600,7,280),
 ('goose','Домашние гуси','goose_house',{'feed':1},{'feather':2},1200,4,150),
]: 
 ANIMALS[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,cost=c)

for i,n,b,inputs,out,t,l in [
 ('mushroom_soup','Грибной суп','kitchen',{'mushroom':2,'potato':2},{'mushroom_soup':1},600,4),
 ('berry_jam','Лесной джем','kitchen',{'wildberry':3},{'berry_jam':1},420,3),
 ('tea','Заварить лесной чай','teahouse',{'herbs':2,'wildberry':1},{'tea':1},240,3),
 ('pickles','Маринованные огурчики','kitchen',{'cucumber':3},{'pickles':1},600,3),
 ('goat_cheese','Нежный козий сыр','dairy',{'goat_milk':2},{'goat_cheese':1},900,4),
 ('linen','Соткать полотно','loom',{'flax':3},{'linen':1},1500,6),
 ('forest_pie','Пирог лесника','bakery',{'flour':2,'chanterelle':2,'egg':1},{'forest_pie':1},900,4),
 ('oat_cookie','Овсяное печенье','bakery',{'oat':3,'egg':1,'flour':1},{'oat_cookie':1},360,2),
 ('pillow','Набить подушку','loom',{'rabbit_fluff':2,'feather':1},{'pillow':1},1500,5),
 ('scarf','Связать тёплый шарф','loom',{'alpaca_fiber':2},{'scarf':1},1800,7),
 ('vegetable_stew','Рагу с горошком','kitchen',{'cabbage':2,'peas':2,'carrot':2},{'vegetable_stew':1},900,3),
 ('berry_milk','Ягодное молоко','dairy',{'milk':2,'raspberry':2},{'berry_milk':1},600,4),
 ('rice_pudding','Нежный рисовый пудинг','kitchen',{'rice':3,'milk':1},{'rice_pudding':1},1200,7),
 ('duck_bun','Булочки на утиных яйцах','bakery',{'flour':2,'duck_egg':1},{'bun':2},600,3),
]:
 RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=max(4,t//90))
# Expansion r3: crops for levels 9-20 and their first products (additive; r1/r2 rows untouched).
# Slow, low-attention crops: profit per hour ~21 -> ~26 and XP per hour ~5.3 -> ~6.3, i.e. the same
# class as rice/watermelon (21 and 5.2 per hour at level 8), so none of them outbids the older rows.
for i,n,c,t,q,p,x,l,color in [
 ('pepper','Перец',50,32400,5,48,48,9,'#d9553f'),
 ('eggplant','Баклажаны',58,36000,5,55,55,10,'#6f5a8c'),
 ('buckwheat','Гречиха',40,39600,6,46,60,11,'#a58f6e'),
 ('mint','Мята',60,43200,5,66,68,12,'#5fae8f'),
 ('grape','Виноград',64,46800,5,72,76,13,'#7b5f9a'),
 ('chamomile','Ромашка',62,50400,6,64,84,14,'#efe3b0'),
 ('hops','Хмель',78,54000,5,86,92,15,'#9fc06a'),
 ('garlic','Чеснок',72,57600,6,74,100,16,'#e6e0cf'),
 ('poppy','Мак',84,64800,6,86,112,17,'#c4506b'),
 ('melon','Дыня',100,72000,5,116,124,18,'#e4c26b'),
 ('cranberry','Клюква',100,79200,6,104,136,19,'#b83f4f'),
 ('saffron','Шафран',96,86400,5,140,150,20,'#9a62b5'),
]:
 CROPS[i]=dict(id=i,name=n,cost=c,seconds=t,yield_qty=q,price=p,xp=x,level=l,color=color)
 ITEMS[i]=dict(id=i,name=n,price=p,color=color,kind='crop')
for i,n,p,col in [
 ('porridge','Гречневая каша',205,'#b79c78'),
 ('mint_tea','Мятный чай',230,'#78b59b'),
 ('grape_roll','Виноградный рулет',230,'#8b6aa5'),
 ('hop_wreath','Хмелевой венок',340,'#a3bf72'),
]:
 ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,b,inputs,out,t,l in [
 ('porridge','Гречневая каша','kitchen',{'buckwheat':3,'milk':1},{'porridge':1},900,11),
 ('mint_tea','Мятный чай','teahouse',{'mint':2,'honey':1},{'mint_tea':1},480,12),
 ('grape_roll','Виноградный рулет','bakery',{'flour':2,'grape':2,'egg':1},{'grape_roll':1},1200,13),
 ('hop_wreath','Сплести хмелевой венок','loom',{'hops':3},{'hop_wreath':1},1500,15),
]:
 RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=max(4,t//90))
# Expansion r4: second-circle livestock for levels 8-22 (additive; older rows untouched).
# Each animal earns ~100-130 coins per hour net of feed, the same class as cow/sheep/bees/goose (74-128);
# only the first, short-cycle animals (chicken, duck) are higher because they need constant attention.
for i,n,p,col in [
 ('truffle','Трюфели',60,'#8d7a66'),
 ('turkey_egg','Яйца индейки',38,'#e6d3b4'),
 ('quail_egg','Перепелиные яйца',24,'#d9cdb4'),
 ('peacock_feather','Павлиньи перья',66,'#5f9a96'),
 ('mohair','Мохер',108,'#d9c9d6'),
 ('swan_down','Лебяжий пух',130,'#f1efe9'),
]:
 ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,p,col in [
 ('truffle_tart','Трюфельный тарт',150,'#b79672'),
 ('truffle_soup','Крем-суп с трюфелем',170,'#b9a68b'),
 ('omelet','Пышный омлет',230,'#e9cc72'),
 ('sponge_cake','Бисквит с мёдом',230,'#e3b86c'),
 ('quail_salad','Салат с перепелиными яйцами',215,'#9bbd83'),
 ('feather_fan','Перьевой веер',280,'#5f9a96'),
 ('plume_bouquet','Букет с перьями',330,'#8aa7b8'),
 ('mittens','Тёплые варежки',190,'#cba0b6'),
 ('mohair_plaid','Мохеровый плед',460,'#cdb3c9'),
 ('down_blanket','Пуховое одеяло',700,'#e9e3ee'),
 ('gingerbread','Медовый пряник',110,'#b9854f'),
]:
 ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,c,l in [
 ('pigsty','Свинарник',900,8),
 ('turkey_yard','Индюшатник',1100,10),
 ('quail_house','Перепелиный домик',1400,12),
 ('peacock_aviary','Павлиний вольер',2000,15),
 ('angora_pen','Ангорский загон',2800,18),
 ('swan_lake','Лебединая заводь',4000,22),
]:
 BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=2,h=2,decor=False)
for i,n,b,inputs,out,t,l,c in [
 ('pig','Поросята-трюфелисты','pigsty',{'feed':1,'potato':1},{'truffle':2},3600,8,360),
 ('turkey','Индюшки','turkey_yard',{'feed':2,'corn':1},{'turkey_egg':3},3000,10,420),
 ('quail','Перепёлки','quail_house',{'feed':1,'buckwheat':1},{'quail_egg':6},3000,12,520),
 ('peacock','Павлины','peacock_aviary',{'hay':1,'grape':1},{'peacock_feather':3},3600,15,800),
 ('angora','Ангорские козочки','angora_pen',{'hay':2,'mint':1},{'mohair':2},3900,18,1100),
 ('swan','Лебеди','swan_lake',{'rice':2,'peas':1},{'swan_down':2},5400,22,1800),
]:
 ANIMALS[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,cost=c)
for i,n,b,inputs,out,t,l in [
 ('gingerbread','Медовый пряник','bakery',{'flour':2,'honey':1,'oat':1},{'gingerbread':1},900,7),
 ('truffle_tart','Трюфельный тарт','bakery',{'flour':2,'truffle':1,'egg':1},{'truffle_tart':1},1200,8),
 ('truffle_soup','Крем-суп с трюфелем','kitchen',{'truffle':1,'potato':2,'milk':1},{'truffle_soup':1},900,9),
 ('omelet','Пышный омлет','kitchen',{'turkey_egg':3,'milk':1,'herbs':1},{'omelet':1},900,10),
 ('sponge_cake','Бисквит с мёдом','bakery',{'flour':2,'turkey_egg':2,'honey':1},{'sponge_cake':1},1500,10),
 ('quail_salad','Салат с перепелиными яйцами','kitchen',{'quail_egg':4,'cucumber':2,'basil':1},{'quail_salad':1},1200,12),
 ('feather_fan','Перьевой веер','loom',{'peacock_feather':3},{'feather_fan':1},1800,15),
 ('plume_bouquet','Букет с перьями','loom',{'peacock_feather':2,'bouquet':1},{'plume_bouquet':1},1500,16),
 ('mittens','Тёплые варежки','loom',{'rabbit_fluff':2,'yarn':1},{'mittens':1},1500,6),
 ('mohair_plaid','Мохеровый плед','loom',{'mohair':3},{'mohair_plaid':1},2400,18),
 ('down_blanket','Пуховое одеяло','loom',{'swan_down':3,'linen':1},{'down_blanket':1},2400,22),
]:
 RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=max(4,t//90))
EQUIPMENT={
 'tractor':dict(id='tractor',name='Трактор «Росток»',cost=120,level=2,role='sow',icon='tractor',
   description='Засевает выбранной культурой все свободные грядки одной командой. Семена оплачиваются по обычной цене.'),
 'harvester':dict(id='harvester',name='Комбайн «Колос»',cost=280,level=3,role='reap',icon='harvester',
   description='Убирает созревшие зерновые и сохраняет схему посева для повторного рейса.'),
 'robot':dict(id='robot',name='Робот-сборщик Р-01',cost=440,level=4,role='harvest',icon='robot',
   description='Сам собирает готовые культуры во время оплаченной смены — даже при закрытой игре.'),
}
HELPERS={
 'rabbit_gardener':dict(id='rabbit_gardener',name='Заяц Поливай',cost=65,level=2,role='water',icon='helper_rabbit',
   description='Поливает каждую новую посадку один раз: она созревает на 15% быстрее. Не заменяет помощь соседа.'),
 'mole_gardener':dict(id='mole_gardener',name='Крот Корнеич',cost=90,level=3,role='roots',icon='helper_mole',
   description='Собирает созревшие морковь, свёклу и картофель. Другое не трогает.'),
 'raccoon':dict(id='raccoon',name='Енот Кладовщик',cost=100,level=3,role='production',icon='helper_raccoon',
   description='Забирает готовые партии из мастерских и освобождает очереди.'),
 'shepherd':dict(id='shepherd',name='Пёс Пастушок',cost=110,level=3,role='animals',icon='helper_dog',
   description='Собирает продукцию животных и кормит их из твоего склада. При нехватке корма спокойно ждёт.'),
 'hedgehog':dict(id='hedgehog',name='Ёж Лесовичок',cost=60,level=2,role='guide',icon='helper_hedgehog',specialty='mushrooms',
   description='Проводник по грибным тропам: вылазка быстрее на 20%, грибов в корзине немного больше.'),
 'squirrel':dict(id='squirrel',name='Белка Орешка',cost=80,level=2,role='guide',icon='helper_squirrel',specialty='berries',
   description='Проводник по ягодникам и ореховым рощам: быстрее на 20% и дополнительная лесная находка.'),
}
SHIFTS={
 'short':dict(id='short',name='На полчаса',seconds=1800,actions=12,cost=4),
 'day':dict(id='day',name='На два часа',seconds=7200,actions=36,cost=10),
 'night':dict(id='night',name='На восемь часов',seconds=28800,actions=96,cost=22),
}
ROUTES={
 'timber_path':dict(id='timber_path',name='Лесная тропа',description='Собери древесину для причала.',level=1,seconds=300,cost=4,inputs={},outputs={'wood':4},xp=6,specialty='wood',icon='wood'),
 'mushroom_wood':dict(id='mushroom_wood',name='Грибная опушка',description='Мягкий мох, пеньки и первые белые грибы.',level=1,seconds=300,cost=4,inputs={},outputs={'mushroom':3,'chanterelle':1},xp=8,specialty='mushrooms',icon='mushroom'),
 'berry_edge':dict(id='berry_edge',name='Ягодная поляна',description='Земляника на солнышке, ежевика у старого забора.',level=1,seconds=600,cost=6,inputs={},outputs={'wildberry':4,'blackberry':1},xp=10,specialty='berries',icon='wildberry'),
 'herb_meadow':dict(id='herb_meadow',name='Луг четырёх стихий',description='На тропинке кто-то оставил страницу необычного атласа.',level=2,seconds=1200,cost=8,inputs={'carrot':1},outputs={'herbs':4,'wildberry':2},xp=15,specialty='herbs',icon='herbs',secret='atlas'),
 'old_grove':dict(id='old_grove',name='Ореховая роща',description='Долгая спокойная прогулка с корзиной орехов и грибов.',level=3,seconds=7200,cost=14,inputs={'bread':1},outputs={'hazelnut':6,'mushroom':4,'blackberry':3},xp=28,specialty='berries',icon='hazelnut'),
 'night_glade':dict(id='night_glade',name='Тропа Ночного города',description='Город спит. У калитки — конверт с совиной печатью. Без опасностей и потерь.',level=3,seconds=3600,cost=12,inputs={'oat_cookie':1},outputs={'chanterelle':8,'herbs':3},xp=22,specialty='mushrooms',icon='night',secret='night'),
}
# Fishing shares the two activity slots and guide rules with woodland trips.
# Its own category and completion counter keep fish out of the forest quest.
FISHING_LEVEL = 3
for route in ROUTES.values():
    route.update(kind='forest', category='forest')
for i,n,p,col in [
 ('crucian','Карась',18,'#c1a86c'),
 ('perch','Окунь',26,'#93ad82'),
 ('pike','Щука',44,'#839c89'),
]:
    ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='fish')
ROUTES.update({
 'pond_bank':dict(id='pond_bank',name='Тихий пруд',description='Караси у камышей. Возьми немного зерна для прикормки.',kind='fishing',category='fishing',level=3,seconds=600,cost=6,inputs={'wheat':1},outputs={'crucian':3},xp=10,specialty='fishing',icon='crucian'),
 'lake_inlet':dict(id='lake_inlet',name='Озёрная заводь',description='Окуни и караси в спокойной воде. Хлеб пригодится для прикормки.',kind='fishing',category='fishing',level=5,seconds=1800,cost=10,inputs={'bread':1},outputs={'perch':3,'crucian':2},xp=16,specialty='fishing',icon='perch'),
 'river_bend':dict(id='river_bend',name='Речной поворот',description='Долгая рыбалка на щуку и окуня. Не забудь кукурузную прикормку.',kind='fishing',category='fishing',level=8,seconds=3600,cost=14,inputs={'corn':2},outputs={'pike':2,'perch':3},xp=24,specialty='fishing',icon='pike'),
})


def route_level(route):
    """The same unlock threshold is used by starting trips and generating orders."""
    return max(route['level'], FISHING_LEVEL) if route.get('kind') == 'fishing' else route['level']


def trip_kind(trip):
    """Legacy trips have no kind; derive it from their unchanged route IDs."""
    return trip.get('kind', ROUTES.get(trip['route'], {}).get('kind', 'forest'))


SECRETS={
 'elements':dict(id='elements',name='Четыре стихии — одна грядка',world='Алхимия',hint='Вырасти и собери четыре разных культуры.',text='Земля, вода, воздух и огонь солнца. Филиныч называет это агрономией, а атлас — первым рецептом.',decor='elements_stone',icon='elements'),
 'atlas':dict(id='atlas',name='Страница маленьких чудес',world='Алхимия',hint='Вернись с Луга четырёх стихий.',text='Между травами нашлась страница Атласа маленьких чудес. На полях приписка: «Гриб плюс чайник — ещё не рецепт».',decor='alchemist_table',icon='alchemy'),
 'night':dict(id='night',name='Город спит — фермер не спит',world='Мафия',hint='Прогуляйся по тропе Ночного города.',text='В конверте — приглашение в Ночной город. Никаких настоящих ролей: только фонарь и подозрительно вежливый гусь.',decor='night_lantern',icon='night'),
 'detective':dict(id='detective',name='Дело о пропавшей булочке',world='Мафия',hint='После трёх заказов выполни поручение в кабинете находок.',text='Детектив допросил пугало. Оно молчало, но на шляпе обнаружилась крошка. Дело закрыто: завтрак доставлен.',decor='detective_scarecrow',icon='detective'),
}
LEVELS += [13500,17200,21600,26600,32400,39000,46500,55000,64500,75000,86600,99400,113500,129000,146000]
# r9 (stage 12): levels 31-50 are appended on top; thresholds of levels 1-30 never change, so level(xp) never drops.
LEVELS += [165600,188100,214000,243700,277900,313500,350500,389000,429000,470600,513900,558900,605700,654400,705000,757600,812400,869300,928500,990100]
QUESTS += [
 dict(id='q11',name='Корзинка лесника',text='Вернись из трёх лесных вылазок.',stat='forages',goal=3,coins=55,xp=20),
 dict(id='q12',name='Работа спорится',text='Пусть помощники выполнят двенадцать полезных действий.',stat='automation',goal=12,coins=45,xp=20),
 dict(id='q13',name='Механизация с душой',text='Соверши три рейса на тракторе или комбайне.',stat='machine_runs',goal=3,coins=65,xp=25),
 dict(id='q14',name='Небольшие чудеса',text='Открой две пасхалки соседних миров.',stat='secrets',goal=2,coins=0,xp=30),
 dict(id='q15',name='Первый улов',text='Забери улов с трёх законченных рыбалок.',stat='fishing_trips',goal=3,coins=55,xp=20),
]

# Land expansion: every step opens two more rows and columns. LAND_STEPS[i] is the step that grows the
# plot FROM the previous size TO step['size']; first two steps keep the original prices and need no level.
# Owner decision 2026-10-14: no hard limit of expansions - beyond 20 x 20 a step only gets dearer (until the farm is turned
# into an "agroholding": a separate future transition, NOT implemented - see docs/tasks/FARM_LAND_PROGRESSION.md, variant A).
LAND_START=8
LAND_TABLE=(
 dict(size=10,cost=300,level=1),
 dict(size=12,cost=600,level=1),
 dict(size=14,cost=2500,level=6),
 dict(size=16,cost=6000,level=9),
 dict(size=18,cost=14000,level=13),
 dict(size=20,cost=25000,level=18),
)
LAND_TABLE_END=LAND_TABLE[-1]['size']   # the saved table never changes: prices of sizes 10..20 are fixed
LAND_CEILING=60                         # technical sanity bound (rendering, state size), not a game rule

def _nice(v):
    """Round a positive integer to 3 significant digits (half up) so tail prices look designed."""
    step=10**max(0,len(str(v))-3)
    return (v+step//2)//step*step

def _tail_step(size):
    n=(size-LAND_TABLE_END)//2
    # cost = 25000*(s/20)^6 in exact integers; the gate climbs 5 levels per step and stops at the last level (50)
    return dict(size=size,cost=_nice(LAND_TABLE[-1]['cost']*size**6//LAND_TABLE_END**6),level=min(len(LEVELS),LAND_TABLE[-1]['level']+5*n))

LAND_TAIL=tuple(_tail_step(sz) for sz in range(LAND_TABLE_END+2,LAND_CEILING+1,2))
LAND_STEPS=LAND_TABLE+LAND_TAIL
LAND_SIZES=frozenset({LAND_START,*(s['size'] for s in LAND_STEPS)})
LAND_MAX=LAND_STEPS[-1]['size']

# Everything that depends on "which sizes exist" goes through land_step / is_land_size / land_bound / plot_upkeep / plot_limit /
# object_limit. After LAND_MAX land_step() is None ('max_land'): that is the hook for the future agroholding transition.
def land_step(size):
    """The step that expands a plot of ``size``, or None when it is already the maximum (or size is invalid)."""
    return next((s for s in LAND_STEPS if s['size']==size+2),None) if size in LAND_SIZES else None

def is_land_size(size):
    return size in LAND_SIZES

def land_bound():
    return LAND_MAX

def level(xp):
    return max(i+1 for i,x in enumerate(LEVELS) if xp>=x)

# Expansion r6: building upgrades 1 -> 3 (additive; no existing row changes).
# Production workshops: -15% recipe time per level (x1 / x.85 / x.70) and the queue keeps its older
# "2 + level" slots (3 / 4 / 5). Animal houses: capacity x1 / x2 / x3 (feed and product both scale) while the
# cycle grows only x1 / x1.6 / x2.2, i.e. +25% / +36% net per hour and far fewer visits. The barn (склад) has
# no capacity limit, so its upgrades raise the price of «Продать» by +5% / +10%.
# Upgrade price = coins (share of the building price, with a floor) + a few farm goods, level-gated.
MAX_BUILDING_LEVEL = 3
UPGRADE_BASE_COST = 400  # for the barn, which cannot be bought and has no BUILDINGS row
UPGRADES = {
    2: dict(level=4, coin_factor=.5, coin_min=200, items={'hay': 4, 'flour': 4}),
    3: dict(level=8, coin_factor=1.0, coin_min=500, items={'cheese': 2, 'linen': 2}),
}
RECIPE_SPEED = {1: 1.0, 2: .85, 3: .70}
ANIMAL_CAPACITY = {1: dict(mult=1, time=1.0), 2: dict(mult=2, time=1.6), 3: dict(mult=3, time=2.2)}
BARN_SELL_BONUS = {1: 0, 2: 5, 3: 10}  # percent on top of the item price


def upgrade_kind(building_type):
    """'workshop' | 'animals' | 'barn' | None (not upgradable)."""
    if building_type == 'barn':
        return 'barn'
    if any(r['building'] == building_type for r in RECIPES.values()):
        return 'workshop'
    if any(a['building'] == building_type for a in ANIMALS.values()):
        return 'animals'
    return None


def upgrade_cost(building_type, to_level):
    """Coins, goods and player level needed to raise a building to ``to_level`` (2..3), or None."""
    spec = UPGRADES.get(to_level)
    if spec is None or upgrade_kind(building_type) is None:
        return None
    base = BUILDINGS[building_type]['cost'] if building_type in BUILDINGS else UPGRADE_BASE_COST
    coins = max(spec['coin_min'], int(round(base * spec['coin_factor'] / 10.0)) * 10)
    return dict(coins=coins, items=dict(spec['items']), level=spec['level'])


def effective_level(raw):
    """Objects saved before r6 have no level (= 1); a legacy level 4 keeps the top effects."""
    return max(1, min(MAX_BUILDING_LEVEL, raw if type(raw) is int else 1))


def queue_slots(raw):
    return min(6, 2 + (raw if type(raw) is int and raw >= 1 else 1))


def animal_batch(spec, raw_level):
    """(inputs, outputs, seconds) of one feeding for a house of this level."""
    cap = ANIMAL_CAPACITY[effective_level(raw_level)]
    m = cap['mult']
    return ({k: q * m for k, q in spec['inputs'].items()}, {k: q * m for k, q in spec['outputs'].items()},
            spec['seconds'] * cap['time'])


ANIMAL_XP_LEGACY = 5  # reward of a batch that was started before r9 stage 13 (no 'xp' in animal_job)


def animal_xp(spec, raw_level):
    """XP of one collected batch: a quarter of the added value of the base batch, times the house multiplier."""
    v_out = sum(ITEMS[k]['price'] * q for k, q in spec['outputs'].items())
    v_in = sum(ITEMS[k]['price'] * q for k, q in spec['inputs'].items())
    return max(2, (v_out - v_in) // 4) * ANIMAL_CAPACITY[effective_level(raw_level)]['mult']


# Expansion r7: helpers and automation for a big farm (additive; no existing row changes).
# A helper does exactly what the owner could do by hand (same transitions, same yields, no bonuses) in a rectangular
# zone, one action per 30 seconds, until the paid time or quota ends. The wage per action is a few coins: it buys
# taps and offline continuity, never extra income. A paid shift never renews and never takes coins by itself.
HELPERS.update({
 'fox_picker':dict(id='fox_picker',name='Лиса Урожайка',cost=150,level=5,role='harvest',icon='helper_fox',
   description='Собирает любые созревшие культуры в своей зоне и складывает урожай на склад. Заново не сажает.'),
 'hamster_reaper':dict(id='hamster_reaper',name='Хомяк Жнец',cost=260,level=11,role='harvest',icon='helper_hamster',
   description='Второй сборщик урожая: назначь ему другой край фермы, и две зоны убираются одновременно.'),
 'cat_keeper':dict(id='cat_keeper',name='Кошка Хозяюшка',cost=160,level=7,role='animals',icon='helper_cat',
   description='Кормит животных в своей зоне и забирает их продукцию. Без корма на складе спокойно ждёт.'),
 'beaver_artisan':dict(id='beaver_artisan',name='Бобёр Мастер',cost=170,level=6,role='craft',icon='helper_beaver',
   description='Забирает готовое в мастерских своей зоны и ставит прежний рецепт заново, если хватает сырья.'),
 'badger_artisan':dict(id='badger_artisan',name='Барсук Подмастерье',cost=240,level=10,role='craft',icon='helper_badger',
   description='Второй мастер для другой части фермы: повторяет последний рецепт каждой мастерской.'),
})
SHIFTS.update({
 'estate':dict(id='estate',name='На восемь часов · большая ферма',seconds=28800,actions=240,cost=48,level=8),
 'manor':dict(id='manor',name='На восемь часов · поместье',seconds=28800,actions=480,cost=90,level=14),
})
MAX_SHIFT_ACTIONS=max(p['actions'] for p in SHIFTS.values())
SHIFT_INTERVAL=30  # seconds between two actions of one worker
ROLE_LABELS={'water':'поливает','roots':'корнеплоды','production':'забирает из мастерских','animals':'кормит и собирает',
             'harvest':'собирает урожай','craft':'мастерские: забрать и повторить'}
GROUPS=('plots','animals','workshops')
# Bigger land earns more beds and objects. The old fixed caps (24 beds / 80 objects) fit the 8 x 8 start only.
PLOT_LIMITS={8:24,10:32,12:42,14:54,16:68,18:84,20:120}
OBJECT_LIMITS={8:80,10:92,12:108,14:126,16:146,18:168,20:200}
# Beyond 20 x 20 land is room for buildings, decor and fields rather than for beds (more beds would shorten the ~90-day
# game by ~40%): +5 beds per step, objects keep growing with the area (+0.4 per new cell).
for _s in range(LAND_TABLE_END+2,LAND_CEILING+1,2):
    PLOT_LIMITS[_s]=PLOT_LIMITS[LAND_TABLE_END]+5*((_s-LAND_TABLE_END)//2)
    OBJECT_LIMITS[_s]=OBJECT_LIMITS[LAND_TABLE_END]+2*(_s*_s-LAND_TABLE_END**2)//5


def plot_limit(size):
    return PLOT_LIMITS.get(size,24)


def object_limit(size):
    return OBJECT_LIMITS.get(size,80)


# Expansion r8: residents' reputation, the caravan (big order) and daily contracts. Additive only.
# Extra income of all three systems stays below ~25% of a lower-bound active player's income (see qw_farm/market.py).
REP_NAMES=['Прохожий','Знакомый','Приятель','Друг','Близкий друг','Лучший друг']
REP_POINTS=[0,2,5,10,18,30]          # delivered orders needed for each level
REP_BONUS=5                          # percent of coins/XP per level (max 25)
REP_SPECIAL_LEVEL=2                  # from «Приятель» a resident asks for favourite goods
NPC_TASTES={
 'Филиныч':('tea','mint_tea','jam','honey','pie'),
 'Агата':('bouquet','pie','gingerbread','berry_jam','bread'),
 'Почтальон Ёж':('mushroom_soup','chanterelle','hazelnut','wildberry','pancake'),
 'Механик Крот':('soup','potato','vegetable_stew','bread','pickles'),
 'Кошка Кая':('milk','cheese','omelet','berry_milk','goat_cheese'),
 'Кошка Соня':('pillow','down_blanket','scarf','mohair_plaid','mittens'),
 'Суслик Игорь':('sunflower','oat_cookie','porridge','corn','pumpkin'),
 'Неведома Зверушка':('truffle','saffron','lavender','peacock_feather','truffle_tart'),
 'Медведь Пух':('berry_charge','honey_charge','forest_charge','honey','gingerbread'),
}
# Residents who order a themed product most of the time (only goods reachable for the player count; see domain.make_order)
NPC_SIGNATURE={'Медведь Пух':('berry_charge','honey_charge','forest_charge')}
SIGNATURE_PCT=70
MARKET=dict(
 rep_names=REP_NAMES,rep_points=REP_POINTS,rep_bonus=REP_BONUS,special_level=REP_SPECIAL_LEVEL,special_bonus=20,
 tastes={k:list(v) for k,v in NPC_TASTES.items()},
 village_quests=VILLAGE_QUESTS,
 caravan=dict(level=10,min_hours=12,max_hours=24,cooldown_hours=24,premium=45,xp_div=5,decor_chance=15,
              decor=['flowerbed','bench','lantern','scarecrow','basket'],value_share=12,rep_points=3),
 contracts=dict(count=3,level=2,streak_step=4,streak_max=5,tz_offset=10800),
)

def public_catalog():
    return deepcopy(dict(home_projects=HOME_PROJECTS,version=VERSION,economy=dict(income_ref=INCOME_REF_BANDS,upkeep_level=UPKEEP_LEVEL,plot_upkeep=PLOT_UPKEEP,upkeep_pct=UPKEEP_PCT,field_upkeep=FIELD_UPKEEP,debt_slow=[DEBT_SLOW,DEBT_SLOW_DEN],fund_level=FUND_LEVEL,season_days=SEASON_DAYS,fund_tiers=FUND_TIERS,tier_text=FUND_REWARD_TEXT,markup=FUND_MARKUP,min_share_pct=MIN_SHARE_PCT,discount_pct=TIER_DISCOUNT_PCT,feast=[FEAST_DAYS,FEAST_PCT],decor_tiers=DECOR_TIERS,decor_shop=DECOR_SHOP,reward_decor=REWARD_DECOR),invite=INVITE,market=MARKET,crops=CROPS,crop_classes=dict(slow=CROP_CLASS_SLOW,long=CROP_CLASS_LONG),items=ITEMS,buildings=BUILDINGS,recipes=RECIPES,animals=ANIMALS,levels=LEVELS,quests=QUESTS,equipment=EQUIPMENT,fields=field_catalog(),helpers=HELPERS,shifts=SHIFTS,automation=dict(roles=ROLE_LABELS,groups=list(GROUPS),interval=SHIFT_INTERVAL,plot_limits=PLOT_LIMITS,object_limits=OBJECT_LIMITS),routes=ROUTES,secrets=SECRETS,land=dict(start=LAND_START,max=LAND_MAX,steps=LAND_STEPS),upgrades=dict(max=MAX_BUILDING_LEVEL,levels=UPGRADES,recipe_speed=RECIPE_SPEED,animal=ANIMAL_CAPACITY,barn_bonus=BARN_SELL_BONUS,base_cost=UPGRADE_BASE_COST,costs={t:{str(n):upgrade_cost(t,n) for n in UPGRADES} for t in {*(r['building'] for r in RECIPES.values()),*(a['building'] for a in ANIMALS.values()),'barn'}},kinds={t:upgrade_kind(t) for t in {*(r['building'] for r in RECIPES.values()),*(a['building'] for a in ANIMALS.values()),'barn'}})))

def validate():
    for r in RECIPES.values():
        assert r['building'] in BUILDINGS and r['seconds']>0
        assert set(r['inputs'])|set(r['outputs']) <= set(ITEMS)
        assert all(type(n) is int and n>0 for n in [*r['inputs'].values(),*r['outputs'].values()])
        assert sum(ITEMS[k]['price']*q for k,q in r['outputs'].items()) >= sum(ITEMS[k]['price']*q for k,q in r['inputs'].items()), r['id']
    for a in ANIMALS.values():
        assert a['building'] in BUILDINGS and set(a['inputs'])|set(a['outputs']) <= set(ITEMS)
    for r in ROUTES.values():
        assert r['seconds'] > 0 and set(r['inputs'])|set(r['outputs']) <= set(ITEMS)
        assert all(type(q) is int and q>0 for q in r['outputs'].values())
        assert r['kind'] in {'forest', 'fishing'} and r['category'] == r['kind']
        if r['kind'] == 'fishing':
            assert r['level'] >= FISHING_LEVEL and not r.get('secret')
            assert all(ITEMS[k]['kind'] == 'fish' for k in r['outputs'])
    assert all(h['role'] in ROLE_LABELS or h['role']=='guide' for h in HELPERS.values())
    assert all(p['actions']>0 and p['seconds']>0 and p['cost']>0 for p in SHIFTS.values())
    assert len(LEVELS)==50 and LEVELS==sorted(set(LEVELS)) and LEVELS[29]==146000
    assert all(x['decor'] in BUILDINGS for x in SECRETS.values())
    assert set(NPC_TASTES)=={n for n,_ in NPCS} and all(i in ITEMS for v in NPC_TASTES.values() for i in v)
    assert len(REP_NAMES)==len(REP_POINTS) and REP_POINTS==sorted(set(REP_POINTS)) and all(d in BUILDINGS and BUILDINGS[d].get('decor') for d in MARKET['caravan']['decor'])
    return dict(crops=len(CROPS),items=len(ITEMS),recipes=len(RECIPES),buildings=len(BUILDINGS),animals=len(ANIMALS),quests=len(QUESTS),equipment=len(EQUIPMENT),helpers=len(HELPERS),routes=len(ROUTES),secrets=len(SECRETS))
# Expansion r5: second-circle production chains for levels 10-23 (additive; older rows untouched).
# Six new workshops, 21 recipes in 2-3 stage chains (raw -> intermediate -> luxury). Every recipe earns
# roughly 170-430 coins per hour of workshop time (the existing crafts: 48-390), the top luxury tier stays
# below 1.1x the best existing recipe. A whole chain pays ~250-330 per hour of workshop time overall.
for i,n,p,col in [
 ('butter','Сливочное масло',57,'#f0d878'),
 ('nut_paste','Ореховая паста',197,'#a9825a'),
 ('poppy_oil','Маковое масло',341,'#6b5a73'),
 ('grape_juice','Виноградный сок',91,'#7b5f9a'),
 ('melon_nectar','Дынный нектар',169,'#e4c26b'),
 ('cranberry_morse','Клюквенный морс',209,'#b83f4f'),
 ('ajvar','Баклажанная икра',155,'#8b5a4c'),
 ('marinated_mushrooms','Маринованные грибы',92,'#a98b64'),
 ('preserves_set','Набор домашних заготовок',513,'#c9885a'),
 ('smoked_cheese','Копчёный сыр',95,'#c99a57'),
 ('smoked_quail','Копчёные перепелиные яйца',72,'#a9743f'),
 ('smoke_platter','Фермерская тарелка',546,'#b98a58'),
 ('dyed_linen','Крашеное полотно',252,'#8190b8'),
 ('sundress','Льняное платье',746,'#9fb4d6'),
 ('alpaca_coat','Пальто из альпаки',881,'#a9887f'),
 ('croissant','Масляные круассаны',49,'#dca85d'),
 ('grape_jelly','Виноградное желе',157,'#8d6aa8'),
 ('poppy_roll','Маковый рулет',294,'#6f5a6f'),
 ('praline_cake','Ореховый торт',934,'#8a6244'),
 ('pastila','Ягодная пастила',279,'#b4506a'),
 ('saffron_cake','Шафрановый кекс',702,'#e0a93f'),
]:
 ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,c,l in [
 ('oil_press','Маслобойня',1500,10),
 ('juicery','Соковарня',2100,13),
 ('cannery','Консервный цех',2600,14),
 ('smokehouse','Коптильня',3200,15),
 ('tailor','Швейная мастерская',3800,17),
 ('confectionery','Кондитерская',4800,19),
]:
 BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=2,h=2,decor=False)
for i,n,b,inputs,out,t,l in [
 ('butter','Сбить масло','oil_press',{'milk':4},{'butter':2},900,10),
 ('nut_paste','Растереть ореховую пасту','oil_press',{'hazelnut':4,'honey':1},{'nut_paste':1},1200,11),
 ('poppy_oil','Отжать маковое масло','oil_press',{'poppy':3},{'poppy_oil':1},1500,17),
 ('grape_juice','Отжать виноградный сок','juicery',{'grape':2},{'grape_juice':2},600,13),
 ('melon_nectar','Сварить дынный нектар','juicery',{'melon':2,'honey':1},{'melon_nectar':2},900,18),
 ('cranberry_morse','Клюквенный морс','juicery',{'cranberry':3,'honey':1},{'cranberry_morse':2},900,19),
 ('ajvar','Баклажанная икра','cannery',{'eggplant':2,'pepper':2,'tomato':2},{'ajvar':2},1200,14),
 ('marinated_mushrooms','Замариновать грибы','cannery',{'mushroom':4,'herbs':1,'pepper':1},{'marinated_mushrooms':2},900,15),
 ('preserves_set','Собрать набор заготовок','cannery',{'ajvar':1,'marinated_mushrooms':1,'pickles':2},{'preserves_set':1},1800,18),
 ('smoked_cheese','Копчёный сыр','smokehouse',{'cheese':2,'herbs':1},{'smoked_cheese':2},1200,15),
 ('smoked_quail','Копчёные перепелиные яйца','smokehouse',{'quail_egg':6},{'smoked_quail':3},1200,16),
 ('smoke_platter','Фермерская тарелка','smokehouse',{'smoked_cheese':2,'smoked_quail':1,'marinated_mushrooms':1},{'smoke_platter':1},2100,20),
 ('dyed_linen','Покрасить полотно','tailor',{'linen':1,'blueberry':3},{'dyed_linen':1},1500,17),
 ('sundress','Сшить льняное платье','tailor',{'dyed_linen':2,'yarn':1},{'sundress':1},2100,19),
 ('alpaca_coat','Сшить пальто из альпаки','tailor',{'scarf':1,'mohair':2,'dyed_linen':1},{'alpaca_coat':1},3000,22),
 ('croissant','Испечь круассаны','confectionery',{'flour':2,'butter':1,'egg':1},{'croissant':3},900,19),
 ('grape_jelly','Сварить виноградное желе','confectionery',{'grape_juice':2,'honey':1},{'grape_jelly':2},1200,20),
 ('poppy_roll','Маковый рулет','confectionery',{'flour':2,'poppy_oil':1,'butter':1,'honey':1},{'poppy_roll':2},1500,20),
 ('praline_cake','Ореховый торт','confectionery',{'nut_paste':2,'sponge_cake':1,'butter':1},{'praline_cake':1},2400,21),
 ('pastila','Ягодная пастила','confectionery',{'melon_nectar':1,'cranberry_morse':1,'honey':1},{'pastila':2},1500,21),
 ('saffron_cake','Шафрановый кекс','confectionery',{'saffron':2,'butter':1,'flour':2,'egg':2},{'saffron_cake':1},2700,23),
]:
 RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=max(6,t//80))

# ---- r9 stage 14: upkeep, village fund and paid decor (additive; no existing row changes) ----------------------------
# INCOME_REF: reference net coins per Moscow day of the "active" balance-simulator profile (scripts/farm_balance_sim.py
# --days 90 --profile active, before any sink; the L20-24 spike of the raw run is smoothed to keep the table monotone).
INCOME_REF_BANDS=((1,4,1100),(5,9,7000),(10,14,13000),(15,19,19000),(20,24,30000),(25,29,36000),(30,34,40000),(35,39,42000),(40,44,42000),(45,50,42000))

def income_ref(lv):
    lv=max(1,min(50,lv))
    return next(v for lo,hi,v in INCOME_REF_BANDS if lo<=lv<=hi)

# Invitations. INCOME_REF at L1-4 is 1100 coins/day, so the inviter reward is ~1.1 days of early income and the invitee bonus
# ~0.4 day on top of the 250 starter coins. The reward needs a real player: the invited farm must reach INVITE['level'].
INVITE=dict(level=3,reward=1200,bonus=400,per_day=3,total=20,fresh_hours=24)

UPKEEP_LEVEL=10                 # upkeep starts here
PLOT_UPKEEP={8:0,10:0,12:2,14:5,16:10,18:18,20:30}   # coins per bed per bill, by land size
for _s in range(LAND_TABLE_END+2,LAND_CEILING+1,2):  # 30*(s/20)^2, rounded
    PLOT_UPKEEP[_s]=(3*_s*_s+20)//40
def plot_upkeep(size):
    return PLOT_UPKEEP.get(size,0)

UPKEEP_PCT=100                  # a building costs ceil(cost * level / 100) per bill
FIELD_UPKEEP=1500               # per hectare per bill (fields: stage 15)
DEBT_SLOW,DEBT_SLOW_DEN=6,5     # new timers take x1.2 while upkeep debt is open
FUND_LEVEL=8
SEASON_DAYS=28
FUND_TIERS=(5,15,30,50,80)      # personal scale thresholds in tenths of INCOME_REF(lv): 0.5 / 1.5 / 3 / 5 / 8
FUND_MARKUP=125                 # goods count at price x1.25 (percent)
MIN_SHARE_PCT=10                # minimal personal contribution (percent of INCOME_REF) for the common reward
MAX_CONTRIBUTION=10**9
TIER_DISCOUNT_PCT=25            # personal tier 3: upkeep discount until the season ends
FEAST_DAYS,FEAST_PCT=3,10       # "Праздник": +10% XP for 3 days
FUND_REWARD_TEXT={
 1:'Праздничная гирлянда (декор)',
 2:'«Праздник»: +10% опыта на 3 дня',
 3:'−25% содержания до конца сезона',
 4:'Вертушка — анимированный декор',
 5:'Кубок старосты: трофей и титул',
}
VILLAGE_GOAL_FLOOR=120000       # the common goal is never lower than this
VILLAGE_ACTIVE_DAYS=14          # an "active" farm acted within this many Moscow days
DECOR_TIERS={1:(8,1000,3000),2:(15,8000,20000),3:(25,40000,90000),4:(35,150000,300000),5:(45,400000,800000)}
DECOR_SHOP=[
 dict(id='dc_birdbath',name='Поилка для птиц',cost=1200,tier=1,w=1,h=1),
 dict(id='dc_hedge',name='Живая изгородь',cost=1800,tier=1,w=1,h=1),
 dict(id='dc_flowercart',name='Цветочная тележка',cost=2600,tier=1,w=1,h=1),
 dict(id='dc_fountain',name='Каменный фонтан',cost=9000,tier=2,w=2,h=2),
 dict(id='dc_gazebo',name='Садовая беседка',cost=14000,tier=2,w=2,h=2),
 dict(id='dc_toy_mill',name='Игрушечная мельница',cost=18000,tier=2,w=1,h=1),
 dict(id='dc_lily_pond',name='Пруд с кувшинками',cost=45000,tier=3,w=2,h=2),
 dict(id='dc_pergola',name='Увитая пергола',cost=65000,tier=3,w=2,h=2),
 dict(id='dc_garden_clock',name='Садовые часы',cost=88000,tier=3,w=1,h=1),
 dict(id='dc_obelisk',name='Резной обелиск',cost=160000,tier=4,w=1,h=1),
 dict(id='dc_crystal_house',name='Хрустальная оранжерея',cost=230000,tier=4,w=2,h=2),
 dict(id='dc_carousel',name='Карусель',cost=295000,tier=4,w=2,h=2),
 dict(id='dc_golden_scarecrow',name='Золотое пугало',cost=420000,tier=5,w=1,h=1),
 dict(id='dc_harvest_monument',name='Памятник урожаю',cost=600000,tier=5,w=2,h=2),
 dict(id='dc_aurora_tree',name='Дерево северного сияния',cost=780000,tier=5,w=2,h=2),
]
REWARD_DECOR=[   # earned, never sold: placed for free once unlocked by the fund
 dict(id='fd_garland',name='Праздничная гирлянда',w=1,h=1,source='Личная шкала фонда, 1-й порог'),
 dict(id='fd_pinwheel',name='Вертушка',w=1,h=1,source='Личная шкала фонда, 4-й порог (анимированный декор)'),
 dict(id='fd_cup',name='Кубок старосты',w=1,h=1,source='Личная шкала фонда, 5-й порог (трофей)'),
 dict(id='fd_banner',name='Знамя деревни',w=1,h=1,source='Общая цель деревни'),
]
for _d in DECOR_SHOP:
    BUILDINGS[_d['id']]=dict(id=_d['id'],name=_d['name'],cost=_d['cost'],level=DECOR_TIERS[_d['tier']][0],w=_d['w'],h=_d['h'],decor=True,tier=_d['tier'])
for _d in REWARD_DECOR:
    BUILDINGS[_d['id']]=dict(id=_d['id'],name=_d['name'],cost=0,level=FUND_LEVEL,w=_d['w'],h=_d['h'],decor=True,reward=True,source=_d['source'])

def validate_economy():
    assert [v for _,_,v in INCOME_REF_BANDS]==sorted(v for _,_,v in INCOME_REF_BANDS) and INCOME_REF_BANDS[0][0]==1 and INCOME_REF_BANDS[-1][1]==50
    assert all(INCOME_REF_BANDS[i][1]+1==INCOME_REF_BANDS[i+1][0] for i in range(len(INCOME_REF_BANDS)-1))
    assert len(FUND_TIERS)==5 and list(FUND_TIERS)==sorted(set(FUND_TIERS)) and set(PLOT_UPKEEP)==set(LAND_SIZES)
    for d in DECOR_SHOP:
        lv,lo,hi=DECOR_TIERS[d['tier']]
        assert lo<=d['cost']<=hi and BUILDINGS[d['id']]['decor'] and not BUILDINGS[d['id']].get('secret')
    assert {d['tier'] for d in DECOR_SHOP}==set(DECOR_TIERS) and len({d['id'] for d in DECOR_SHOP+REWARD_DECOR})==len(DECOR_SHOP)+len(REWARD_DECOR)
    return dict(decor_shop=len(DECOR_SHOP),reward_decor=len(REWARD_DECOR))

validate_economy()

# ---- r9 crops and production rebalance (docs/tasks/FARM_CROPS_R9_DESIGN.md) ---------------------------------------------------
# Prices of existing ITEMS never change; only seed cost, growth time, yield, XP and (lavender) the level of a crop do.
# Plantings, workshop jobs and animal batches store their own parameters and finish by the old ones.
CROP_TUNING_R9 = {   # id: (cost, seconds, yield_qty, xp, level)
 'wheat':(2,30,3,1,1),'carrot':(4,120,3,3,1),'corn':(9,300,3,4,1),'oat':(5,1800,6,8,1),
 'clover':(8,300,4,4,2),'beet':(9,900,3,6,2),'cucumber':(9,1800,3,8,2),
 'strawberry':(7,900,2,6,3),'peas':(10,1800,3,9,3),'rye':(20,3600,5,12,3),'cabbage':(14,14400,6,24,3),
 'basil':(9,900,2,7,4),'tomato':(18,1800,3,10,4),'potato':(17,3600,5,13,4),'raspberry':(15,7200,4,18,4),
 'sunflower':(16,3600,3,14,5),'blueberry':(23,7200,4,19,5),
 'lavender':(26,900,2,7,6),'pumpkin':(23,7200,3,20,6),'flax':(29,14400,6,29,6),
 'rice':(28,28800,8,43,7),'watermelon':(41,43200,6,53,8),'pepper':(26,3600,2,17,9),'eggplant':(58,28800,5,51,10),
 'buckwheat':(28,43200,6,63,11),'mint':(24,900,1,10,12),'grape':(25,7200,2,30,13),'chamomile':(90,43200,6,73,14),
 'hops':(60,28800,4,67,15),'garlic':(22,900,1,13,16),'poppy':(31,900,1,14,17),'melon':(76,7200,2,39,18),
 'cranberry':(43,7200,2,41,19),'saffron':(213,86400,5,122,20),
}
assert set(CROP_TUNING_R9)==set(CROPS)
for _i,(_c,_t,_q,_x,_l) in CROP_TUNING_R9.items():
    CROPS[_i].update(cost=_c,seconds=_t,yield_qty=_q,xp=_x,level=_l)
CROP_CLASS_SLOW=1800     # fast class: seconds < 1800
CROP_CLASS_LONG=14400    # long class (= field crop): seconds >= 14400

def crop_class(seconds):
    return 'fast' if seconds<CROP_CLASS_SLOW else 'medium' if seconds<CROP_CLASS_LONG else 'long'

for i,n,p,col in [
 ('rye_flour','Ржаная мука',34,'#b8a07c'),('borodinsky','Бородинский хлеб',85,'#7a5a3c'),('baton','Батон',65,'#d9a860'),
 ('bagels','Бублики',23,'#d8a466'),('rye_rusks','Ржаные сушки',26,'#a9855a'),('kvass','Хлебный квас',58,'#9a6a3a'),
 ('borscht','Борщ',103,'#b0453f'),('vinaigrette','Винегрет',123,'#a8506a'),('watermelon_jam','Арбузное варенье',138,'#c9566a'),
 ('watermelon_morse','Арбузный морс',61,'#e0707a'),('chamomile_tea','Ромашковый чай',107,'#e8dc9a'),
 ('barrel_pickles','Бочковые соленья',106,'#7a9a5a'),('adjika','Аджика',111,'#c8402f'),
 ('whey','Сыворотка',12,'#e6eadb'),('kefir','Кефир',39,'#eef2f0'),('curd','Творог',79,'#f5f0dc'),('yogurt','Йогурт',58,'#f1dfe6'),
 ('ryazhenka','Ряженка',63,'#e5c79a'),('smetana','Сметана',72,'#f6f1e2'),('whey_drink','Сывороточный напиток',58,'#e9a9b6'),
 ('brynza','Брынза',92,'#f2efe0'),('syrniki','Сырники',114,'#e2b66c'),('aged_cheese','Выдержанный сыр',254,'#d9a741'),
 ('meat','Мясо',100,'#d98a82'),('mince','Фарш',84,'#c9726a'),('sausages','Сосиски',88,'#d2837a'),
 ('mushroom_cutlets','Грибные котлеты',64,'#b5926a'),('doctor_sausage','Докторская колбаса',152,'#e3a0a0'),
 ('cabbage_rolls','Голубцы',168,'#a9bb7a'),('dumplings','Пельмени',102,'#efe3c4'),('cutlets','Котлеты',97,'#c08a5a'),
 ('servelat','Сервелат',165,'#a9553f'),('kulebyaka','Кулебяка',304,'#d9a05a'),
]:
    ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,c,l in [('creamery','Молокозавод',6000,21),('sausage_shop','Колбасный цех',9000,26),('cattle_barn','Хлев',5000,25)]:
    BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=2,h=2,decor=False)
# calves: hay + feed + a beet -> a batch of meat, like every other animal (~110 coins per hour of cycle net of feed)
ANIMALS['calf']=dict(id='calf',name='Бычки',building='cattle_barn',inputs={'hay':2,'feed':2,'beet':1},outputs={'meat':2},seconds=4800,level=25,cost=2600)

def _xp_r9(b,t):
    if b in ('creamery','sausage_shop','oil_press','juicery','energy_shop','cannery','smokehouse','tailor','confectionery','syrupery','soapery','noodle_shop'):return max(6,t//80)
    if b=='mill':return max(1,t//45)
    return max(4,t//90)

_R9_ROWS = [
 ('rye_flour','Смолоть ржаную муку','mill',{'rye':2},{'rye_flour':1},120,3),
 ('borodinsky','Бородинский хлеб','bakery',{'rye_flour':2},{'borodinsky':1},360,3),
 ('baton','Батон','bakery',{'flour':3,'milk':1},{'baton':1},360,4),
 ('bagels','Бублики','bakery',{'flour':2,'egg':1},{'bagels':2},300,4),
 ('rye_rusks','Ржаные сушки','bakery',{'rye_flour':1,'flour':1,'egg':1},{'rye_rusks':3},480,5),
 ('kvass','Хлебный квас','teahouse',{'borodinsky':1},{'kvass':2},600,5),
 ('borscht','Борщ','kitchen',{'beet':2,'cabbage':1,'potato':1,'carrot':1},{'borscht':1},900,4),
 ('vinaigrette','Винегрет','kitchen',{'beet':2,'potato':1,'pickles':1},{'vinaigrette':1},600,4),
 ('watermelon_jam','Арбузное варенье','kitchen',{'watermelon':1,'honey':1},{'watermelon_jam':1},900,8),
 ('watermelon_morse','Арбузный морс','juicery',{'watermelon':2},{'watermelon_morse':2},600,13),
 ('chamomile_tea','Ромашковый чай','teahouse',{'chamomile':2,'honey':1},{'chamomile_tea':2},600,14),
 ('barrel_pickles','Бочковые соленья','cannery',{'cucumber':3,'garlic':1,'herbs':1},{'barrel_pickles':2},1200,16),
 ('adjika','Аджика','cannery',{'tomato':2,'pepper':1,'garlic':1},{'adjika':2},900,16),
 ('kefir','Кефир','dairy',{'milk':3},{'kefir':2},480,6),
 ('curd','Творог','dairy',{'milk':4},{'curd':1,'whey':2},600,6),
 ('yogurt','Йогурт','creamery',{'milk':2,'strawberry':2},{'yogurt':2},600,22),
 ('ryazhenka','Ряженка','creamery',{'milk':3},{'ryazhenka':2},900,23),
 ('smetana','Сметана','creamery',{'milk':4},{'smetana':2},900,23),
 ('whey_drink','Сывороточный напиток','creamery',{'whey':3,'raspberry':2,'honey':1},{'whey_drink':3},600,24),
 ('brynza','Брынза','dairy',{'milk':4,'herbs':1},{'brynza':2},1200,24),
 ('syrniki','Сырники','kitchen',{'curd':2,'flour':1,'egg':1},{'syrniki':2},600,25),
 ('aged_cheese','Выдержанный сыр','dairy',{'cheese':3},{'aged_cheese':2},3600,33),
 ('mince','Фарш','sausage_shop',{'meat':2},{'mince':3},600,26),
 ('sausages','Сосиски','sausage_shop',{'mince':2,'milk':1},{'sausages':3},900,27),
 ('mushroom_cutlets','Грибные котлеты','sausage_shop',{'mushroom':3,'flour':1,'egg':1},{'mushroom_cutlets':2},600,27),
 ('doctor_sausage','Докторская колбаса','sausage_shop',{'mince':2,'egg':1,'milk':1},{'doctor_sausage':2},1200,28),
 ('cabbage_rolls','Голубцы','kitchen',{'mince':2,'cabbage':2,'rice':1},{'cabbage_rolls':2},1200,28),
 ('dumplings','Пельмени','sausage_shop',{'mince':2,'flour':2,'egg':1},{'dumplings':3},1200,29),
 ('cutlets','Котлеты','sausage_shop',{'mince':2,'bread':1,'egg':1},{'cutlets':3},900,30),
 ('servelat','Сервелат','smokehouse',{'sausages':2,'herbs':1},{'servelat':2},1500,31),
 ('kulebyaka','Кулебяка','bakery',{'flour':2,'mince':1,'cabbage':1,'egg':1},{'kulebyaka':1},1800,32),
]
R9_RECIPE_IDS=frozenset(r[0] for r in _R9_ROWS)      # recipes added by r9 (earlier-stage tests describe only their own rows)
R9_ITEM_IDS=frozenset(k for r in _R9_ROWS for k in r[4])|{'meat'}
for i,n,b,inputs,out,t,l in _R9_ROWS:
    RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=_xp_r9(b,t))
# recipe corrections: no recipe asks for more beds than a batch of the long crop gives
RECIPES['linen']['inputs']={'flax':2}
RECIPES['rice_pudding']['inputs']={'rice':2,'milk':1}
RECIPES['hop_wreath'].update(inputs={'hops':2},seconds=1800,xp=max(4,1800//90))

# ---- r9 stage 16: content of levels 17-50 (docs/tasks/FARM_R9_DESIGN.md section 2, FARM_CROPS_R9_DESIGN.md law) -------------
# Crop value law: up to L20 XP = 11 * 1.055^(L-1) * k(t), profit = 4 * XP.  From L21 the XP of NEW content may grow at most +2% per level and
# the profit at most +5% per level (the law is anchored at L20); the pace of the whole game is carried by PACE and the tail of LEVELS, not by crops.
CROP_K = {30: .091, 120: .183, 300: .289, 900: .5, 1800: .707, 3600: 1.0, 7200: 1.414, 14400: 2.0, 28800: 2.83, 43200: 3.3, 86400: 4.0}
CROP_XP_STEP, CROP_PROFIT_STEP = 1.02, 1.05


def crop_law(level, seconds):
    """(xp, profit) of one harvest of a crop of ``level`` that grows ``seconds`` by the corrected value law (the ceiling for L21+)."""
    k = CROP_K[seconds]
    if level <= 20:
        b = 11 * 1.055 ** (level - 1)
        return b * k, 4 * b * k
    b = 11 * 1.055 ** 19
    return b * CROP_XP_STEP ** (level - 20) * k, 4 * b * CROP_PROFIT_STEP ** (level - 20) * k


# <<R16 DATA>>
# Generated by the stage 16 content script; edit the numbers by hand only together with tests/test_farm_content_r9.py.
# id, name, seed cost, seconds, yield, unit value, xp, level, colour
R16_CROP_ROWS = [
 ('zucchini', 'Кабачок', 68, 28800, 5, 68, 68, 18, '#8fb86a'),
 ('beans', 'Фасоль', 76, 43200, 6, 62, 74, 19, '#a9c079'),
 ('currant', 'Смородина', 41, 7200, 2, 105, 42, 21, '#4b3f6b'),
 ('ginger', 'Имбирь', 122, 86400, 5, 123, 122, 22, '#d9b87a'),
 ('broccoli', 'Брокколи', 69, 28800, 5, 69, 68, 23, '#6fa65a'),
 ('turnip', 'Репа', 76, 43200, 6, 63, 74, 24, '#e6d9a8'),
 ('gooseberry', 'Крыжовник', 43, 7200, 2, 108, 42, 26, '#a8c96a'),
 ('barley', 'Ячмень', 125, 86400, 5, 126, 122, 27, '#d7bf74'),
 ('celery', 'Сельдерей', 72, 28800, 5, 71, 68, 28, '#8fc07a'),
 ('apple', 'Яблоня', 75, 43200, 6, 64, 74, 29, '#d9534f'),
 ('cherry', 'Вишня', 45, 7200, 2, 111, 42, 31, '#b3263e'),
 ('millet', 'Просо', 128, 86400, 5, 129, 122, 32, '#e2c35a'),
 ('leek', 'Лук-порей', 70, 28800, 5, 72, 68, 33, '#a7cf8a'),
 ('pear', 'Груша', 79, 43200, 6, 66, 74, 34, '#c6cf5a'),
 ('rosehip', 'Шиповник', 45, 7200, 2, 113, 42, 36, '#d0453c'),
 ('chickpea', 'Нут', 131, 86400, 5, 132, 122, 37, '#d8b878'),
 ('kohlrabi', 'Кольраби', 74, 28800, 5, 74, 68, 38, '#b7d68a'),
 ('plum', 'Слива', 84, 43200, 6, 68, 74, 39, '#6b4a8c'),
 ('sea_buckthorn', 'Облепиха', 46, 7200, 2, 116, 42, 41, '#f09a2a'),
 ('ginseng', 'Женьшень', 133, 86400, 5, 135, 122, 42, '#d8c49a'),
 ('asparagus', 'Спаржа', 77, 28800, 5, 76, 68, 43, '#9bc872'),
 ('apricot', 'Абрикос', 82, 43200, 6, 69, 74, 44, '#f0a64a'),
 ('viburnum', 'Калина', 46, 7200, 2, 118, 42, 46, '#c4232f'),
 ('pomegranate', 'Гранат', 136, 86400, 5, 138, 122, 47, '#b3262f'),
 ('artichoke', 'Артишок', 80, 28800, 5, 78, 68, 48, '#8fae6a'),
 ('peach', 'Персик', 87, 43200, 6, 71, 74, 49, '#f2a07a'),
]
# id, name, unit value, colour (animal goods and recipe outputs)
R16_ITEM_ROWS = [
 ('ostrich_egg', 'Страусиное яйцо', 268, '#efe3c4'),
 ('silk', 'Шёлковая нить', 235, '#efe6f0'),
 ('yak_wool', 'Шерсть яка', 341, '#8a6f5a'),
 ('golden_feather', 'Золотое перо', 185, '#e4b84a'),
 ('zucchini_fritters', 'Кабачковые оладьи', 100, '#cfa660'),
 ('bean_soup', 'Фасолевый суп', 223, '#c98a5a'),
 ('currant_morse', 'Смородиновый морс', 204, '#5a3f7a'),
 ('ginger_tea', 'Имбирный чай', 170, '#e6c27a'),
 ('broccoli_soup', 'Крем-суп из брокколи', 256, '#8fc27a'),
 ('turnip_pie', 'Пирог «Репка»', 318, '#d9a05a'),
 ('gooseberry_jam', 'Крыжовниковое варенье', 277, '#b6d27a'),
 ('barley_porridge', 'Перловая каша', 202, '#e6d29a'),
 ('celery_salad', 'Салат с сельдереем', 148, '#a7cf8a'),
 ('apple_pie', 'Яблочный пирог', 351, '#d9a05a'),
 ('giant_omelet', 'Гигантский омлет', 133, '#f0d060'),
 ('cherry_dumplings', 'Вареники с вишней', 149, '#f1e4c0'),
 ('millet_porridge', 'Пшённая каша с тыквой', 216, '#e8a94a'),
 ('leek_pie', 'Пирог с луком-пореем', 196, '#d9a05a'),
 ('silk_scarf', 'Шёлковый шарфик', 644, '#efd4e6'),
 ('cherry_syrup', 'Вишнёвый сироп', 289, '#9c1c34'),
 ('pear_compote', 'Грушевый компот', 133, '#dfe39a'),
 ('syrup_set', 'Набор сиропов', 776, '#d9475e'),
 ('rosehip_tea', 'Чай из шиповника', 280, '#e0603c'),
 ('hummus', 'Хумус', 248, '#e6cf9a'),
 ('felt_boots', 'Валенки', 1338, '#a98a6a'),
 ('lavender_soap', 'Лавандовое мыло', 81, '#b8a6dc'),
 ('kohlrabi_salad', 'Салат из кольраби', 146, '#d4e8aa'),
 ('plum_jam', 'Сливовое повидло', 189, '#6b4a8c'),
 ('chamomile_soap', 'Ромашковое мыло', 96, '#f4ecb0'),
 ('plum_cake', 'Сливовый пирог', 386, '#d9a05a'),
 ('honey_candle', 'Медовая свеча', 158, '#e8b84a'),
 ('sea_buckthorn_tea', 'Облепиховый чай', 288, '#f09a2a'),
 ('ginseng_tea', 'Женьшеневый чай', 192, '#c9a86a'),
 ('golden_fan', 'Золотой веер', 823, '#e4b84a'),
 ('noodles', 'Домашняя лапша', 40, '#efd89a'),
 ('asparagus_omelet', 'Омлет со спаржей', 147, '#f0d060'),
 ('noodle_soup', 'Суп с лапшой', 104, '#f0c070'),
 ('apricot_jam', 'Абрикосовое варенье', 196, '#f0a64a'),
 ('broccoli_pasta', 'Паста с брокколи', 206, '#efd89a'),
 ('viburnum_jelly', 'Калиновое желе', 312, '#c4232f'),
 ('pomegranate_juice', 'Гранатовый сок', 174, '#9c1c34'),
 ('artichoke_snack', 'Закуска из артишока', 166, '#b3c98a'),
 ('peach_tart', 'Персиковый тарт', 415, '#f2a07a'),
 ('harvest_cake', 'Торт урожая', 1247, '#f6d8a8'),
]
# id, name, cost, level (workshops, then animal houses)
R16_WORKSHOPS = [('syrupery', 'Сироповарня', 15000, 34), ('soapery', 'Мыловарня', 22000, 38), ('noodle_shop', 'Макаронная мастерская', 30000, 43)]
R16_HOUSES = [('ostrich_farm', 'Страусиная ферма', 9000, 29), ('silk_house', 'Шёлковый дом', 14000, 33), ('yak_pen', 'Горный загон', 22000, 37), ('pheasantry', 'Фазанник', 32000, 42)]
# id, name, house, inputs, outputs, seconds, level, cost
R16_ANIMAL_ROWS = [
 ('ostrich', 'Страусы', 'ostrich_farm', {'feed': 2, 'hay': 1}, {'ostrich_egg': 1}, 7200, 29, 3000),
 ('silkworm', 'Шелкопряды', 'silk_house', {'hay': 2, 'celery': 1}, {'silk': 2}, 10800, 33, 4500),
 ('yak', 'Яки', 'yak_pen', {'hay': 3, 'barley': 1}, {'yak_wool': 2}, 14400, 37, 7000),
 ('pheasant', 'Золотые фазаны', 'pheasantry', {'feed': 2, 'millet': 1}, {'golden_feather': 3}, 10800, 42, 10000),
]
# id, name, building, inputs, outputs, seconds, level
R16_RECIPE_ROWS = [
 ('zucchini_fritters', 'Кабачковые оладьи', 'kitchen', {'zucchini': 2, 'flour': 1, 'egg': 1}, {'zucchini_fritters': 2}, 600, 18),
 ('bean_soup', 'Фасолевый суп', 'kitchen', {'beans': 2, 'potato': 2, 'carrot': 1}, {'bean_soup': 1}, 900, 19),
 ('currant_morse', 'Смородиновый морс', 'juicery', {'currant': 3, 'honey': 1}, {'currant_morse': 2}, 600, 21),
 ('ginger_tea', 'Имбирный чай', 'teahouse', {'ginger': 2, 'honey': 1}, {'ginger_tea': 2}, 600, 22),
 ('broccoli_soup', 'Крем-суп из брокколи', 'kitchen', {'broccoli': 2, 'potato': 2, 'milk': 1}, {'broccoli_soup': 1}, 900, 23),
 ('turnip_pie', 'Пирог «Репка»', 'bakery', {'flour': 2, 'turnip': 3, 'egg': 1}, {'turnip_pie': 1}, 1200, 24),
 ('gooseberry_jam', 'Крыжовниковое варенье', 'kitchen', {'gooseberry': 4, 'honey': 1}, {'gooseberry_jam': 2}, 900, 26),
 ('barley_porridge', 'Перловая каша', 'kitchen', {'barley': 2, 'milk': 1, 'butter': 1}, {'barley_porridge': 2}, 900, 27),
 ('celery_salad', 'Салат с сельдереем', 'kitchen', {'celery': 2, 'cucumber': 2, 'smetana': 1}, {'celery_salad': 2}, 600, 28),
 ('apple_pie', 'Яблочный пирог', 'bakery', {'flour': 2, 'apple': 2, 'butter': 1, 'egg': 1}, {'apple_pie': 1}, 1500, 29),
 ('giant_omelet', 'Гигантский омлет', 'kitchen', {'ostrich_egg': 1, 'milk': 2, 'herbs': 1}, {'giant_omelet': 3}, 900, 29),
 ('cherry_dumplings', 'Вареники с вишней', 'kitchen', {'cherry': 3, 'flour': 2, 'egg': 1}, {'cherry_dumplings': 3}, 900, 31),
 ('millet_porridge', 'Пшённая каша с тыквой', 'kitchen', {'millet': 2, 'pumpkin': 2, 'milk': 1}, {'millet_porridge': 2}, 900, 32),
 ('leek_pie', 'Пирог с луком-пореем', 'bakery', {'flour': 2, 'leek': 2, 'smetana': 1, 'egg': 1}, {'leek_pie': 2}, 1500, 33),
 ('silk_scarf', 'Шёлковый шарфик', 'tailor', {'silk': 2}, {'silk_scarf': 1}, 1800, 33),
 ('cherry_syrup', 'Вишнёвый сироп', 'syrupery', {'cherry': 4, 'honey': 1}, {'cherry_syrup': 2}, 900, 34),
 ('pear_compote', 'Грушевый компот', 'syrupery', {'pear': 2, 'honey': 1}, {'pear_compote': 2}, 900, 34),
 ('syrup_set', 'Набор сиропов', 'syrupery', {'cherry_syrup': 1, 'pear_compote': 1, 'currant_morse': 1}, {'syrup_set': 1}, 1500, 35),
 ('rosehip_tea', 'Чай из шиповника', 'teahouse', {'rosehip': 4, 'honey': 1}, {'rosehip_tea': 2}, 600, 36),
 ('hummus', 'Хумус', 'kitchen', {'chickpea': 2, 'oil': 1, 'garlic': 1}, {'hummus': 2}, 900, 37),
 ('felt_boots', 'Валенки', 'tailor', {'yak_wool': 3, 'yarn': 1}, {'felt_boots': 1}, 2400, 37),
 ('lavender_soap', 'Лавандовое мыло', 'soapery', {'lavender': 3, 'oil': 1}, {'lavender_soap': 3}, 900, 38),
 ('kohlrabi_salad', 'Салат из кольраби', 'kitchen', {'kohlrabi': 2, 'carrot': 2, 'smetana': 1}, {'kohlrabi_salad': 2}, 600, 38),
 ('plum_jam', 'Сливовое повидло', 'kitchen', {'plum': 3, 'honey': 1}, {'plum_jam': 2}, 1200, 39),
 ('chamomile_soap', 'Ромашковое мыло', 'soapery', {'chamomile': 2, 'oil': 1}, {'chamomile_soap': 3}, 900, 39),
 ('plum_cake', 'Сливовый пирог', 'bakery', {'flour': 2, 'plum': 2, 'butter': 1, 'egg': 1}, {'plum_cake': 1}, 1500, 40),
 ('honey_candle', 'Медовая свеча', 'soapery', {'honey': 2, 'linen': 1}, {'honey_candle': 2}, 1200, 40),
 ('sea_buckthorn_tea', 'Облепиховый чай', 'teahouse', {'sea_buckthorn': 4, 'honey': 1}, {'sea_buckthorn_tea': 2}, 600, 41),
 ('ginseng_tea', 'Женьшеневый чай', 'teahouse', {'ginseng': 2, 'honey': 1}, {'ginseng_tea': 2}, 600, 42),
 ('golden_fan', 'Золотой веер', 'loom', {'golden_feather': 3}, {'golden_fan': 1}, 2400, 42),
 ('noodles', 'Домашняя лапша', 'noodle_shop', {'flour': 3, 'egg': 2}, {'noodles': 3}, 600, 43),
 ('asparagus_omelet', 'Омлет со спаржей', 'kitchen', {'asparagus': 2, 'egg': 2, 'milk': 1}, {'asparagus_omelet': 2}, 900, 43),
 ('noodle_soup', 'Суп с лапшой', 'noodle_shop', {'noodles': 2, 'carrot': 2, 'herbs': 1}, {'noodle_soup': 2}, 900, 44),
 ('apricot_jam', 'Абрикосовое варенье', 'kitchen', {'apricot': 3, 'honey': 1}, {'apricot_jam': 2}, 1200, 44),
 ('broccoli_pasta', 'Паста с брокколи', 'noodle_shop', {'noodles': 2, 'broccoli': 2, 'cheese': 1}, {'broccoli_pasta': 2}, 1200, 45),
 ('viburnum_jelly', 'Калиновое желе', 'confectionery', {'viburnum': 4, 'honey': 1}, {'viburnum_jelly': 2}, 900, 46),
 ('pomegranate_juice', 'Гранатовый сок', 'juicery', {'pomegranate': 2}, {'pomegranate_juice': 2}, 600, 47),
 ('artichoke_snack', 'Закуска из артишока', 'kitchen', {'artichoke': 2, 'cheese': 1, 'herbs': 1}, {'artichoke_snack': 2}, 900, 48),
 ('peach_tart', 'Персиковый тарт', 'confectionery', {'flour': 2, 'peach': 2, 'butter': 1, 'egg': 1}, {'peach_tart': 1}, 1500, 49),
 ('harvest_cake', 'Торт урожая', 'confectionery', {'peach_tart': 1, 'viburnum_jelly': 1, 'pomegranate_juice': 1, 'honey': 1}, {'harvest_cake': 1}, 2400, 50),
]
# id, name, cost, level, w, h, trophy
R16_DECOR_ROWS = [('dc_well', 'Деревенский колодец', 55000, 28, 2, 2, False), ('dc_weathervane', 'Флюгер-петушок', 48000, 30, 1, 1, False), ('dc_flower_arch', 'Цветочная арка', 160000, 36, 2, 2, False), ('dc_swing', 'Садовые качели', 190000, 38, 2, 2, False), ('tr_bronze_ear', 'Бронзовый колос', 240000, 40, 1, 1, True), ('tr_gold_sickle', 'Золотой серп', 380000, 43, 1, 1, True), ('tr_silver_plough', 'Серебряный плуг', 620000, 47, 2, 2, True), ('tr_gold_sheaf', 'Золотой сноп', 900000, 50, 1, 1, True)]
# <<END R16 DATA>>
for i,n,c,t,q,p,x,l,color in R16_CROP_ROWS:
    CROPS[i]=dict(id=i,name=n,cost=c,seconds=t,yield_qty=q,price=p,xp=x,level=l,color=color)
    ITEMS[i]=dict(id=i,name=n,price=p,color=color,kind='crop')
for i,n,p,col in R16_ITEM_ROWS:
    ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
for i,n,c,l in [*R16_WORKSHOPS,*R16_HOUSES]:
    BUILDINGS[i]=dict(id=i,name=n,cost=c,level=l,w=2,h=2,decor=False)
for i,n,b,inputs,out,t,l,c in R16_ANIMAL_ROWS:
    ANIMALS[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,cost=c)
for i,n,b,inputs,out,t,l in R16_RECIPE_ROWS:
    RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=_xp_r9(b,t))
# ---- energy corner: «Бодрильня» and the berry-and-honey charges (additive; ordered by Медведь Пух, see docs/tasks/FARM_PUKH_ENERGY.md) ----
# price = inputs + minutes * (2.5 + 0.1 * level), like the neighbouring workshops
for i,n,p,col in [('berry_charge','Ягодный энергетос',85,'#d9475e'),('honey_charge','Медовый энергетос',108,'#e0a93a'),('forest_charge','Лесной энергетос',79,'#6f9a55')]:
    ITEMS[i]=dict(id=i,name=n,price=p,color=col,kind='product')
BUILDINGS['energy_shop']=dict(id='energy_shop',name='Бодрильня',cost=1800,level=11,w=2,h=2,decor=False)
for i,n,b,inputs,out,t,l in [
 ('berry_charge','Ягодный заряд','energy_shop',{'raspberry':4,'honey':1},{'berry_charge':2},600,11),
 ('forest_charge','Лесной заряд','energy_shop',{'wildberry':4,'blackberry':1,'herbs':2},{'forest_charge':2},600,12),
 ('honey_charge','Медовый заряд','energy_shop',{'honey':2,'mint':1},{'honey_charge':2},900,13),
]:
    RECIPES[i]=dict(id=i,name=n,building=b,inputs=inputs,outputs=out,seconds=t,level=l,xp=_xp_r9(b,t))
ENERGY_ITEM_IDS=frozenset({'berry_charge','honey_charge','forest_charge'})
ENERGY_RECIPE_IDS=ENERGY_ITEM_IDS

# Paid decor and trophies that fill the levels between the five shop tiers (separate from DECOR_SHOP: its tier levels are pinned).
DECOR_EXTRA=[dict(id=i,name=n,cost=c,level=l,w=w,h=h,trophy=tr) for i,n,c,l,w,h,tr in R16_DECOR_ROWS]
for _d in DECOR_EXTRA:
    BUILDINGS[_d['id']]=dict(id=_d['id'],name=_d['name'],cost=_d['cost'],level=_d['level'],w=_d['w'],h=_d['h'],decor=True,extra=True,trophy=_d['trophy'])
R16_CROP_IDS=frozenset(r[0] for r in R16_CROP_ROWS)
R16_ITEM_IDS=R16_CROP_IDS|frozenset(r[0] for r in R16_ITEM_ROWS)
R16_RECIPE_IDS=frozenset(r[0] for r in R16_RECIPE_ROWS)
R16_BUILDING_IDS=frozenset(r[0] for r in [*R16_WORKSHOPS,*R16_HOUSES])|frozenset(d['id'] for d in DECOR_EXTRA)
R16_ANIMAL_IDS=frozenset(r[0] for r in R16_ANIMAL_ROWS)

# ---- r9 stage 15: fields and special machinery (additive; the minigame is replayed by the server, see fields.py) ----------
FIELD_MIN_LEVEL=22
FIELD_W=8                      # a hectare is an 8 x 8 grid; a field of N ha is 8 x (8 N)
FIELD_STEPS=(                  # buy_field {step}: index into this table, each step once
 dict(step=0,level=22,ha=1,cost=60000),
 dict(step=1,level=27,ha=1,cost=120000),
 dict(step=2,level=32,ha=2,cost=250000),
 dict(step=3,level=38,ha=2,cost=450000),
 dict(step=4,level=44,ha=3,cost=800000),
)
FIELD_MACHINES={               # three machines, one per operation; tier = width of the swath (1 -> 2 -> 3)
 'cultivator':dict(id='cultivator',name='Культиватор',op='cultivate',icon='cultivator',costs=(5000,30000,120000),levels=(22,27,38),
   description='Культивация: срезает сорняки, объезжает камни. Чем чище работа, тем быстрее растёт урожай (до -15% времени).'),
 'seeder':dict(id='seeder',name='Сеялка',op='sow',icon='seeder',costs=(7500,30000,120000),levels=(22,27,38),
   description='Посев по разметке рядов. От аккуратности зависит урожай.'),
 'combine':dict(id='combine',name='Комбайн',op='harvest',icon='combine',costs=(12500,30000,120000),levels=(22,27,38),
   description='Уборка полосами с выгрузкой бункера у края поля. Переполнение бункера — потери урожая.'),
}
FIELD_OPS={                    # operation -> (machine, state before, state after)
 'cultivate':dict(machine='cultivator',src='wild',dst='ready'),
 'sow':dict(machine='seeder',src='ready',dst='growing'),
 'harvest':dict(machine='combine',src='ripe',dst='wild'),
}
FIELD_FUEL=200                 # coins per hectare for every operation
FIELD_YIELD_MULT=16            # one hectare ~ 16 beds: yield_qty * 16, seeds cost * 16, XP crop.xp * 8
FIELD_SEED_MULT=16
FIELD_XP_MULT=8
FIELD_MIN_GROW=14400           # a field crop grows at least this long (catalog seconds)
FIELD_RUN_TTL=1800             # an unfinished run is closed by settle as the autopilot after this many seconds (runs opened before: 900, stored in expires_at)
FIELD_FULL_K=250               # percent of the autopilot time A = 90 s * ha / width: finishing within it keeps the whole manual bonus over the autopilot
FIELD_ZERO_K=600               # percent of A: from here on the manual bonus over the autopilot is 0; in between it falls linearly (docs/tasks/FARM_FIELD_TIME_QUALITY.md)
FIELD_STEP_CS=12               # honest play cannot be faster than 0.12 s per path character
FIELD_MAX_PATH=2000
FIELD_AUTO_S=90                # autopilot: 90 s * ha / width
Q_AUTO=950                     # permille: autopilot quality
Q_BASE,Q_SPAN=850,250          # permille: manual q = 850 + 250 * score (score 0..1000 permille) -> 0.85 .. 1.10
GROW_CUT=150                   # permille: best cultivation shortens growth by 15%
HOPPER=18                      # hopper capacity of the combine = 18 * width * ha cells (two lanes and a little slack)
for _c in CROPS.values():
    _c['field']=_c['seconds']>=FIELD_MIN_GROW

def field_catalog():
    return deepcopy(dict(min_level=FIELD_MIN_LEVEL,w=FIELD_W,steps=FIELD_STEPS,machines=FIELD_MACHINES,ops=FIELD_OPS,fuel=FIELD_FUEL,
        yield_mult=FIELD_YIELD_MULT,seed_mult=FIELD_SEED_MULT,xp_mult=FIELD_XP_MULT,min_grow=FIELD_MIN_GROW,run_ttl=FIELD_RUN_TTL,
        run_full_k=FIELD_FULL_K,run_zero_k=FIELD_ZERO_K,
        step_cs=FIELD_STEP_CS,max_path=FIELD_MAX_PATH,auto_s=FIELD_AUTO_S,q_auto=Q_AUTO,q_base=Q_BASE,q_span=Q_SPAN,grow_cut=GROW_CUT,
        hopper=HOPPER,upkeep=FIELD_UPKEEP,crops=sorted(k for k,c in CROPS.items() if c['field'])))

def validate_fields():
    assert [s['step'] for s in FIELD_STEPS]==list(range(len(FIELD_STEPS))) and [s['level'] for s in FIELD_STEPS]==sorted(s['level'] for s in FIELD_STEPS)
    assert FIELD_STEPS[0]['level']==FIELD_MIN_LEVEL and all(s['ha'] in (1,2,3) for s in FIELD_STEPS)
    assert {m['op'] for m in FIELD_MACHINES.values()}==set(FIELD_OPS) and all(FIELD_OPS[m['op']]['machine']==k for k,m in FIELD_MACHINES.items())
    assert all(len(m['costs'])==3 and len(m['levels'])==3 and list(m['costs'])==sorted(m['costs']) for m in FIELD_MACHINES.values())
    assert 100<=FIELD_FULL_K<FIELD_ZERO_K and FIELD_RUN_TTL>=FIELD_AUTO_S*max(s['ha'] for s in FIELD_STEPS)*FIELD_ZERO_K//100   # the slowest bonus still fits into a run
    assert any(c['field'] for c in CROPS.values())
    return dict(field_steps=len(FIELD_STEPS),field_machines=len(FIELD_MACHINES),field_crops=sum(c['field'] for c in CROPS.values()))

validate_fields()
