#!/usr/bin/env bash
# DuckDNS: A-запись для cron и TXT-запись для ACME DNS-01.
#
# Токен берётся из $DUCKDNS_TOKEN или из файла (по умолчанию ~/.duckdns_token,
# права 600). Порт 80 для сертификата не нужен: DNS-01 подтверждает владение
# доменом через TXT-запись, а не через HTTP.
#
# Примеры:
#   ./scripts/duckdns.sh update morningquiz          # A-запись = текущий внешний IP
#   ./scripts/duckdns.sh update morningquiz 1.2.3.4  # A-запись = конкретный IP
#   CERTBOT_DOMAIN=... CERTBOT_VALIDATION=... ./scripts/duckdns.sh auth   # хук certbot
#   DUCKDNS_DRY=1 ./scripts/duckdns.sh update test   # показать запрос, не отправляя
set -euo pipefail

API="https://www.duckdns.org/update"
DRY="${DUCKDNS_DRY:-0}"
TOKEN=""

require_token() {
    if [ -n "${DUCKDNS_TOKEN:-}" ]; then
        TOKEN="$DUCKDNS_TOKEN"
        return
    fi
    # certbot запускает хуки от root, cron — от владельца: ищем в обоих местах.
    local file
    for file in ${DUCKDNS_TOKEN_FILE:-} "$HOME/.duckdns_token" /etc/mqb/duckdns_token; do
        [ -n "$file" ] || continue
        if [ -r "$file" ]; then
            TOKEN="$(tr -d '[:space:]' < "$file")"
            [ -n "$TOKEN" ] && return
            echo "Файл $file пуст." >&2
            exit 2
        fi
    done
    echo "Нет токена DuckDNS: положите его в /etc/mqb/duckdns_token, ~/.duckdns_token или задайте DUCKDNS_TOKEN." >&2
    exit 2
}

subdomain() {
    # morningquiz.duckdns.org -> morningquiz (DuckDNS не поддерживает вложенные имена)
    printf '%s' "${1%%.duckdns.org}"
}

wait_for_txt() {
    # DuckDNS отдаёт TXT и на _acme-challenge.<домен>, но подтверждаем факт, а не надежду.
    local sub="$1" expected="$2" deadline
    deadline=$(( $(date +%s) + ${DUCKDNS_PROPAGATION_TIMEOUT:-180} ))
    if [ "$DRY" = "1" ]; then
        printf 'DRY: ждали бы TXT=%s у %s\n' "$expected" "$sub" >&2
        return 0
    fi
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if dig +short +time=3 +tries=1 TXT "_acme-challenge.$sub.duckdns.org" @1.1.1.1 | grep -qF "$expected"; then
            echo "TXT подтверждён в DNS"
            return 0
        fi
        sleep 5
    done
    echo "TXT не появился в _acme-challenge.$sub.duckdns.org за ${DUCKDNS_PROPAGATION_TIMEOUT:-180}s." >&2
    exit 1
}

call() {
    local query="$1"
    local url response
    url="$API?$query"
    if [ "$DRY" = "1" ]; then
        printf 'DRY: %s\n' "$url" >&2
        return 0
    fi
    if ! response="$(curl -fsS --max-time 20 "$url")"; then
        echo "DuckDNS недоступен." >&2
        exit 1
    fi
    case "$response" in
        OK|UPDATED*) return 0 ;;
        *) echo "DuckDNS ответил: $response" >&2; exit 1 ;;
    esac
}

case "${1:-}" in
    update)
        [ -n "${2:-}" ] || { echo "Укажите субдомен: $0 update <субдомен> [ip]" >&2; exit 2; }
        require_token
        sub="$(subdomain "$2")"
        call "domains=$sub&token=$TOKEN&ip=${3:-}" >/dev/null
        echo "A-запись $sub.duckdns.org обновлена${3:+ на $3}"
        ;;
    auth)
        : "${CERTBOT_DOMAIN:?нужен CERTBOT_DOMAIN}" "${CERTBOT_VALIDATION:?нужен CERTBOT_VALIDATION}"
        require_token
        sub="$(subdomain "$CERTBOT_DOMAIN")"
        call "domains=$sub&token=$TOKEN&txt=$CERTBOT_VALIDATION" >/dev/null
        echo "TXT для $sub.duckdns.org добавлен"
        wait_for_txt "$sub" "$CERTBOT_VALIDATION"
        ;;
    cleanup)
        : "${CERTBOT_DOMAIN:?нужен CERTBOT_DOMAIN}"
        require_token
        sub="$(subdomain "$CERTBOT_DOMAIN")"
        call "domains=$sub&token=$TOKEN&txt=&clear=true" >/dev/null
        echo "TXT для $sub.duckdns.org очищен"
        ;;
    *)
        echo "использование: $0 update <субдомен> [ip] | auth | cleanup" >&2
        exit 2
        ;;
esac
