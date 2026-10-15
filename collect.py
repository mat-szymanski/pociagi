"""Jeden przebieg zbierania: gdy PLK opublikuje nowe dane, zapisuje statyczne pliki JSON dla stron.

Pliki (w OUT, domyślnie static/data):
  now.json             - podsumowanie bieżącej migawki (licznik)
  trains.json          - pociągi w trasie z trasami i czasami (mapa)
  history/<dzień>.json - punkty wykresu dnia
  days.json            - lista dni z historią
  version.json         - wersja danych PLK, żeby nie pobierać tego samego dwa razy

Użycie: python collect.py [--force]
Zmienne: OUT (katalog wyjściowy), HISTORY_URL - adres katalogu data/ opublikowanej strony (GitHub Pages);
brakujące lokalnie pliki (wersja, historia) są z niego dociągane, więc niczego nie trzeba commitować.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

import plk

OUT = Path(os.environ.get("OUT", Path(__file__).with_name("static") / "data"))
HISTORY_URL = os.environ.get("HISTORY_URL", "").rstrip("/")
KEEP_DAYS = 31


def read_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if HISTORY_URL:
        rel = path.relative_to(OUT).as_posix()
        try:
            with urllib.request.urlopen(f"{HISTORY_URL}/{rel}", timeout=30) as resp:
                return json.load(resp)
        except Exception:  # pierwszy przebieg albo strona jeszcze nie istnieje
            pass
    return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)  # strona nigdy nie widzi pół zapisanego pliku


def run(key, force=False):
    """Zwraca opis wyniku; rzuca wyjątek przy błędzie API."""
    version, data_ts, _ = plk.data_version(key)
    # GITHUB_SHA: wersja kodu strony; gdy opublikowana jest starsza (np. anulowany przebieg po pushu),
    # publikujemy też bez nowych danych z PLK
    code = os.environ.get("GITHUB_SHA", "")
    published = read_json(OUT / "version.json", {})
    if not force and published.get("version") == version and published.get("code", "") == code:
        return "bez zmian"

    summary, map_data = plk.snapshot(key, data_ts=data_ts)
    day = summary["ts"][:10]
    history = read_json(OUT / "history" / f"{day}.json", {"day": day, "points": []})
    if not history["points"] or history["points"][-1]["ts"] != summary["ts"]:
        history["points"].append({"ts": summary["ts"], "total": summary["total"], "running": summary["running"],
                                  "delayed": summary["delayed"],
                                  "byCarrier": {c["code"]: c["total"] for c in summary["carriers"]}})
    days = read_json(OUT / "days.json", [])
    if day not in days:
        days = sorted(days + [day], reverse=True)[:KEEP_DAYS]
    if HISTORY_URL:  # wdrożenie Pages zastępuje całą stronę - przenosimy historię poprzednich dni
        for d in days:
            path = OUT / "history" / f"{d}.json"
            if d != day and not path.exists():
                old = read_json(path, None)
                if old:
                    write_json(path, old)

    write_json(OUT / "history" / f"{day}.json", history)
    write_json(OUT / "days.json", days)
    write_json(OUT / "trains.json", map_data)
    write_json(OUT / "now.json", summary)
    write_json(OUT / "version.json", {"version": version, "ts": summary["ts"], "code": code})
    return (f"dane {summary['ts']}: suma {summary['total']} min, w trasie {summary['running']}, "
            f"limit dobowy: {summary['limits'].get('Daily-Remaining')}")


if __name__ == "__main__":
    key = plk.load_key()
    if not key or "wpisz" in key:
        sys.exit("Brak klucza: utwórz plik .env na wzór .env.example albo ustaw PKP_PLK_APIKEY.")
    try:
        result = run(key, force="--force" in sys.argv)
    except plk.TransientError as e:
        # chwilowy problem z serwerem PLK mimo ponowień: nie oznaczamy przebiegu jako nieudany,
        # kolejne wywołanie z crona (za 5 min) spróbuje znowu; błędy 4xx (np. zły klucz) nadal przerywają
        print(f"::warning::Pominięto: serwer PLK nie odpowiedział poprawnie ({e})")
        result = "bez zmian"
    print(result)
    if os.environ.get("GITHUB_OUTPUT"):  # GitHub Actions: wdrażaj stronę tylko przy nowych danych
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"changed={'false' if result == 'bez zmian' else 'true'}\n")
