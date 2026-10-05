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
    local file="${DUCKDNS_TOKEN_FILE:-$HOME/.duckdns_token}"
    if [ ! -r "$file" ]; then
        echo "Нет токена DuckDNS: задайте DUCKDNS_TOKEN или создайте $file с правами 600." >&2
        exit 2
    fi
    TOKEN="$(tr -d '[:space:]' < "$file")"
    if [ -z "$TOKEN" ]; then
        echo "Файл $file пуст." >&2
        exit 2
    fi
}

subdomain() {
    # morningquiz.duckdns.org -> morningquiz (DuckDNS не поддерживает вложенные имена)
    printf '%s' "${1%%.duckdns.org}"
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
        # Даём записи разойтись: проверяющие Let's Encrypt серверы видят её не мгновенно.
        if [ "$DRY" != "1" ]; then sleep "${DUCKDNS_PROPAGATION_WAIT:-15}"; fi
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
