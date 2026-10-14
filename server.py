"""Lokalny serwer: co POLL_SECONDS uruchamia collect.py (pobiera tylko, gdy PLK ma nowe dane)
i serwuje statyczne strony z katalogu static/ - te same, które mogą działać na GitHub Pages.

Użycie: python server.py  ->  http://127.0.0.1:8000
Zmienne: PORT (8000), POLL_SECONDS (120).
Budżet: sprawdzenie wersji = 1 zapytanie co 2 min, migawka = 4-5 zapytań przy nowych danych -> ok. 1500/dobę.
"""
import functools
import os
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import collect
import plk

STATIC = Path(__file__).with_name("static")
PORT = int(os.environ.get("PORT", 8000))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", 120))


def poller(key):
    while True:
        wait = POLL_SECONDS
        try:
            result = collect.run(key)
            if result != "bez zmian":
                print(f"[{plk.warsaw_now():%H:%M:%S}] {result}", flush=True)
        except Exception as e:  # sieć, 429, przerwa serwisowa PLK - spróbuj ponownie później
            traceback.print_exc()
            if "429" in str(e):
                wait = max(POLL_SECONDS, 600)
        time.sleep(wait)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def end_headers(self):
        # lokalnie zawsze świeże pliki - po edycji strony przeglądarka nie pokaże starej wersji
        self.send_header("Cache-Control", "no-store" if self.path.split("?")[0].endswith(".json") else "no-cache")
        super().end_headers()


def main():
    key = plk.load_key()
    if not key or "wpisz" in key:
        raise SystemExit("Brak klucza: utwórz plik .env na wzór .env.example.")
    threading.Thread(target=poller, args=(key,), daemon=True).start()
    print(f"Licznik: http://127.0.0.1:{PORT}  Mapa: http://127.0.0.1:{PORT}/mapa.html  "
          f"(sprawdzanie co {POLL_SECONDS} s)", flush=True)
    handler = functools.partial(Handler, directory=str(STATIC))
    ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
