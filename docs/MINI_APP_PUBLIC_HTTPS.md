# Публичный HTTPS для Mini App без порта 80

Провайдер закрыл входящий 80, поэтому HTTP-01 отменяется. Это не проблема:
сертификат выпускается по **DNS-01** — подтверждение владения доменом идёт через
TXT-запись, порты для этого не нужны вообще. Входящий **443** остаётся обязательным
по другой причине: Telegram открывает Mini App только по HTTPS и только на 443
(это же проверяет `configured_url()` в `modules/mini_app_launch.py`).

## Что нужно от владельца

1. **Субдомен DuckDNS**, например `morningquiz.duckdns.org`: создаётся в кабинете
   <https://www.duckdns.org> (вход через GitHub/Google).
2. **Токен аккаунта DuckDNS** → в файл `~/.duckdns_token` с правами `600` (или в
   переменную `DUCKDNS_TOKEN`). Токен один на аккаунт: он подходит для любого числа
   субдоменов, и TXT-запись у DuckDNS тоже общая на домен.
3. **Решение по 443** — какой машине роутер отдаёт входящий 443 (см. таблицу).

## Варианты по 443

| Вариант | Что меняется | Плюсы и минусы |
|---|---|---|
| **A. Роутер → 192.168.0.33** | проброс 443 на наш сервер | наш nginx — входная точка; если 443 нужен ещё кому-то (home assistant, RustDesk), разводим по SNI (ниже) |
| **B. Соседний сервер как вход** | на нём проксируем наш домен на `192.168.0.33` (по SNI, TLS не трогаем) | роутер не трогаем совсем; зависим от чужой конфигурации |
| C. Туннель (cloudflared) | ничего | проверено: провайдер рвёт длинные соединения, не годится |

## Шаги (вариант A)

### 1. Сертификат без порта 80

```bash
# скрипт доступен и root-у (certbot запускает хуки от root), секретов в нём нет
sudo install -m 755 scripts/duckdns.sh /home/lizard/duckdns.sh

# токен: certbot ходит от root, cron — от lizard, поэтому файл общий на группу
sudo install -d -m 750 -o root -g lizard /etc/mqb
printf '%s' '<ТОКЕН>' | sudo tee /etc/mqb/duckdns_token >/dev/null
sudo chown root:lizard /etc/mqb/duckdns_token && sudo chmod 640 /etc/mqb/duckdns_token

sudo certbot certonly --manual --preferred-challenges dns \
  --manual-auth-hook "/home/lizard/duckdns.sh auth" \
  --manual-cleanup-hook "/home/lizard/duckdns.sh cleanup" \
  --non-interactive --agree-tos -m <ваш email> -d quizzywizzy.duckdns.org
```

Две грабли, на которые легко наступить (обе уже пройдены в репетиции):

1. **certbot вызывает хук без аргументов** — подкоманду (`auth` / `cleanup`) нужно
   указывать прямо в строке хука, иначе скрипт печатает «использование» и падает с кодом 2.
2. **certbot работает от root**, то есть `$HOME` у него `/root`; поэтому токен кладём по
   системному пути `/etc/mqb/duckdns_token`, а не в домашний каталог владельца.

Certbot вызывает хук как `duckdns.sh auth` и `duckdns.sh cleanup`, передавая
`CERTBOT_DOMAIN` и `CERTBOT_VALIDATION`. Скрипт ставит TXT-запись через API DuckDNS
(`domains=<домен>&token=<токен>&txt=<значение>`, очистка — `&txt=&clear=true`),
затем **сам проверяет**, что запись видна в `_acme-challenge.<домен>.duckdns.org`,
и только после этого возвращает управление (`DUCKDNS_PROPAGATION_TIMEOUT`, по умолчанию 180 с).

**Проверено на живом домене `quizzywizzy.duckdns.org`:** `certbot ... --dry-run`
(staging) → `The dry run was successful`. То есть вся цепочка DNS-01 работает **до**
любых изменений в роутере.

### 2. Проверка продления

```bash
sudo certbot renew --dry-run --cert-name quizzywizzy.duckdns.org
systemctl list-timers | grep certbot
```

Путь к хуку certbot запоминает в `/etc/letsencrypt/renewal/<домен>.conf`; если
скрипт переедет, поправить путь там.

Обновление A-записи (если адрес динамический) — своим cron, не трогая home assistant:

```bash
*/5 * * * * DUCKDNS_TOKEN_FILE=/etc/mqb/duckdns_token /home/lizard/duckdns.sh update quizzywizzy
```

### 3. nginx: домен → Mini App

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name morningquiz.duckdns.org;

    ssl_certificate     /etc/letsencrypt/live/morningquiz.duckdns.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/morningquiz.duckdns.org/privkey.pem;

    client_max_body_size 12m;          # фото до 10 МиБ плюс запас

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;                 # приложение сверяет origin с адресом
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

### 4. Если 443 нужно делить с другими сервисами (home assistant, RustDesk)

Сейчас модуль SNI не установлен, но доступен в apt (кандидат `1.26.3-2ubuntu1.2`):

```bash
sudo apt install -y libnginx-mod-stream
```

```nginx
# /etc/nginx/nginx.conf
load_module modules/ngx_stream_module.so;
load_module modules/ngx_stream_ssl_preread_module.so;

stream {
    map $ssl_preread_server_name $backend {
        morningquiz.duckdns.org   127.0.0.1:8443;    # наш nginx https (Mini App)
        ha.example.duckdns.org    192.168.0.X:443;   # home assistant, TLS без вмешательства
        default                   127.0.0.1:8443;
    }
    server { listen 443; proxy_pass $backend; ssl_preread on; }
}
```

Тогда https-сервер Mini App слушает `8443`, а `443` остаётся за мультиплексором.

### 5. Переменные приложения и кнопка в BotFather

```
MINI_APP_URL=https://morningquiz.duckdns.org/app
MINI_APP_ORIGIN=https://morningquiz.duckdns.org
```

Кнопку меню ставит **владелец бота**: BotFather → `/mybots` → бот → Bot Settings →
Menu Button → URL (`https://morningquiz.duckdns.org/app`).

### 6. Проверка

```bash
curl -sI https://morningquiz.duckdns.org/healthz | head -1
MINI_APP_BOT_TOKEN=... ./venv/bin/python scripts/smoke_mini_app.py \
    --base-url https://morningquiz.duckdns.org --user-id <тестовый id>
```

«Всё в порядке» = 16/16. Ответ 400 означает расхождение домена и
`MINI_APP_ORIGIN` — приложение сравнивает схему и хост запроса со своим origin.

## Что уже измерено на сервере

| Факт | Значение |
|---|---|
| Доступность ACME с сервера | `acme-v02.api.letsencrypt.org` → 200 за 0,86 с |
| Доступность DuckDNS | `www.duckdns.org` → 200 |
| nginx | 1.26.3, собран с `stream_ssl_preread`; пакет `libnginx-mod-stream` не установлен |
| Сертификаты Let's Encrypt | отсутствуют |
| 443 на нашем сервере | свободен (временный тестовый слушатель убран) |
| Внешний 443 | по сведениям владельца уходит на другую машину — нужно решение по варианту A/B |

## Про home assistant и DuckDNS

- Токен DuckDNS — на аккаунт: если HA уже обновляет свой адрес через
  DuckDNS-аддон, тот же токен годится для нашего субдомена, а TXT-запись (общая на
  домен) обеспечивает DNS-01.
- Наш адрес можно обновлять и своим cron (не трогая HA):
  `*/5 * * * * DUCKDNS_TOKEN_FILE=/home/lizard/.duckdns_token /home/lizard/duckdns.sh update morningquiz`
- Если 443 сейчас приходит на машину с HA, самый быстрый путь — **вариант B**: на
  ней включить SNI-проксирование нашего домена на `192.168.0.33:443`. Сертификат
  при этом остаётся наш (TLS завершается на нашем сервере), роутер не трогаем.

## Реализовано 2026-10-05: один домен для квиза и рабочей Библии

Владелец решил держать оба продукта на одном имени. Итоговая схема на сервере:

| Путь на `quizzywizzy.duckdns.org` | Куда |
|---|---|
| `/healthz`, `/app`, `/app/*`, `/api/mini/*` | Mini App квиза (127.0.0.1:8081, TLS наш) |
| всё остальное (`/`, `/login`, `/static/*`, `/vfx/*`, `/mocap/*`, `/files/*`, `/api/*`) | рабочая Библия проекта на `192.168.0.51:8765`, поверх обычного HTTP |

Конфиг: `/etc/nginx/sites-available/mqb-domain` (симлинк в `sites-enabled`), бэкап прежнего состояния — `~/backups/nginx-before-domain.tar.gz`. Mini App запускается с `--proxy-headers --forwarded-allow-ips=127.0.0.1` и `MINI_APP_ORIGIN=https://quizzywizzy.duckdns.org`, иначе приложение отвергнет запрос (400) из-за несовпадения схемы.

Проверено локально через `/etc/hosts`: `/healthz` 200, `/app` 200, `/app/app.js` 200 (наши), `/login` 200, `/` 303, `/api/documents` 401 (Библия), сертификат доверенный (`ssl_verify_result` 0). Старые vhost-ы (`quiz-web` на 8888, `mqb-miniapp` на 80) не затронуты.

Осталось от владельца: проброс входящего **443 → 192.168.0.33**. Порт 80 не нужен (DNS-01), другие порты не нужны.

**Побочный эффект для Библии, который стоит знать:** её защита от подбора пароля считает адрес клиента по `client_address` (`tools/bible_app/server.py`), а `X-Forwarded-For` не читает. Через обратный прокси все посетители выглядят как `192.168.0.33`, поэтому «пять неверных паролей → блокировка на 5 минут» станет общей для всех. Лечится одной правкой на стороне Библии: доверять первому значению `X-Forwarded-For`, когда прямой пир — наш nginx.
