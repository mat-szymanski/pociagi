"""Sprawdza klucz do API Otwarte Dane Kolejowe (PKP PLK) i pobiera próbkę danych.

Klucz czytany jest z pliku .env (PKP_PLK_APIKEY=...) albo ze zmiennej środowiskowej.
Użycie: python check_api.py
"""
import json
import sys

from plk import get, load_key


def main():
    key = load_key()
    if not key or "wpisz" in key:
        sys.exit("Brak klucza: utwórz plik .env na wzór .env.example.")

    status, info, _ = get("/api/v1/apikey/info", key)
    print(f"[apikey/info] HTTP {status}")
    if status != 200:
        sys.exit(f"Klucz nie działa (może jeszcze nieaktywny): {info}")
    # pomijamy pola, które mogłyby zawierać sam klucz
    print(json.dumps({k: v for k, v in info.items() if "key" not in k.lower() or "id" in k.lower()},
                     ensure_ascii=False, indent=2))

    status, usage, _ = get("/api/v1/apikey/usage", key)
    print(f"\n[apikey/usage] HTTP {status}")
    print(json.dumps(usage, ensure_ascii=False, indent=2)[:1500])

    status, stations, _ = get("/api/v1/dictionaries/stations?pageSize=10000", key)
    print(f"\n[dictionaries/stations] HTTP {status}, stacji: {stations.get('totalCount') if status == 200 else stations}")

    status, ops, limits = get("/api/v1/operations?withPlanned=true&pageSize=10000", key)
    print(f"\n[operations] HTTP {status}, limity: {limits}")
    if status != 200:
        sys.exit(ops)
    trains = ops.get("trains", [])
    print(f"Pociągów w odpowiedzi: {len(trains)} (łącznie: {ops.get('pagination', {}).get('totalCount')})")
    if trains:
        sample = dict(trains[0])
        sample["stations"] = sample.get("stations", [])[:3]
        print("Przykładowy pociąg (3 pierwsze stacje):")
        print(json.dumps(sample, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    main()
