#!/usr/bin/env python3
"""Serve only the standalone game to a phone on a trusted local network.
Python 3.9+; standard library only. Stop with Ctrl+C. No directory listing.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import ipaddress
import socket
import sys
import webbrowser
from urllib.parse import urlsplit


def local_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            ip = ipaddress.ip_address(address)
            if not ip.is_loopback and not ip.is_link_local:
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses, key=lambda x: (not x.startswith('192.168.'), x))


def main() -> int:
    parser = argparse.ArgumentParser(description='Alchemia — локальный сервер для телефона')
    parser.add_argument('--port', type=int, default=8000, help='порт (по умолчанию 8000)')
    parser.add_argument('--no-browser', action='store_true', help='не открывать браузер автоматически')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Порт должен быть от 1024 до 65535.')
    path = Path(__file__).resolve().with_name('index.html')
    if not path.is_file():
        print('Не найден index.html рядом с serve.py. Распакуйте архив целиком.', file=sys.stderr)
        return 1
    content = path.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_HEAD(self) -> None:
            self._reply(False)

        def do_GET(self) -> None:
            self._reply(True)

        def _reply(self, send_body: bool) -> None:
            if urlsplit(self.path).path not in ('/', '/index.html', '/alchemia.html'):
                self.send_error(404, 'Not found')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if send_body:
                try:
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def log_message(self, format: str, *args: object) -> None:
            # The console is reserved for the address and launch instructions.
            return

    server = None
    for port in range(args.port, min(args.port + 11, 65536)):
        try:
            server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
            server.daemon_threads = True
            break
        except OSError:
            continue
    if server is None:
        print('Не удалось открыть порт. Попробуйте: python serve.py --port 8100', file=sys.stderr)
        return 1
    address = f'http://127.0.0.1:{server.server_port}/'
    print('\nALCHEMIA — атлас маленьких чудес\n', flush=True)
    print(f'На этом компьютере: {address}', flush=True)
    ips = local_addresses()
    if ips:
        print('\nНа телефоне откройте один из адресов:', flush=True)
        for ip in ips:
            print(f'    http://{ip}:{server.server_port}/', flush=True)
    else:
        print(f'На телефоне: http://<локальный IPv4 компьютера>:{server.server_port}/', flush=True)
        print('В Windows локальный IPv4 можно посмотреть командой ipconfig.', flush=True)
    print('\nКомпьютер и телефон должны быть в одной доверенной сети Wi-Fi.', flush=True)
    print('Если Windows спросит разрешение — разрешите доступ только для частной сети.', flush=True)
    print('При нескольких адресах нужен адрес Wi-Fi/Ethernet, а не VPN или Docker.', flush=True)
    print('Для остановки нажмите Ctrl+C. Не публикуйте этот сервер в интернете.\n', flush=True)
    if not args.no_browser:
        try:
            webbrowser.open(address)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print('\nЛаборатория закрыта. Прогресс остался в браузере.')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass
    raise SystemExit(main())
