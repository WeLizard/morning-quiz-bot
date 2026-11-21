"""Static server for the Night Case mockups: the same /app/* addresses as the mini app.

    python docs/design/mockups/night-case/serve.py [port]   → http://127.0.0.1:4190/mock/index.html

/app/shell/* → web/shell/*, /app/* → web/mini_client/*, /mock/* → this folder. Read-only, loopback only.
"""
from __future__ import annotations

import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ROUTES = (('/app/shell/', ROOT / 'web' / 'shell'), ('/app/', ROOT / 'web' / 'mini_client'), ('/mock/', HERE))


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.webp': 'image/webp', '.woff2': 'font/woff2',
                      '.svg': 'image/svg+xml', '.js': 'text/javascript', '.css': 'text/css'}

    def translate_path(self, path):
        clean = path.split('?', 1)[0].split('#', 1)[0]
        for prefix, base in ROUTES:
            if clean.startswith(prefix):
                target = (base / clean[len(prefix):]).resolve()
                if target == base or base in target.parents:
                    return str(target)
        return str(HERE / '__missing__')

    def log_message(self, format, *args):  # noqa: A002 - the base class names it so
        return None


def start(port=0):
    server = ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=str(HERE)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == '__main__':
    server = start(int(sys.argv[1]) if len(sys.argv) > 1 else 4190)
    print(f'http://127.0.0.1:{server.server_port}/mock/index.html')
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
