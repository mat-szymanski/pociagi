# Ile opóźnienia

Licznik łącznego opóźnienia pociągów w trasie i mapa z szacowaną pozycją pociągów,
na danych z API Otwarte Dane Kolejowe PKP PLK.

- `index.html` – licznik, wykres dnia, przewoźnicy, najbardziej opóźnione pociągi
- `mapa.html` – mapa pociągów w trasie z kolorem wg opóźnienia, trasą i tabelą stacji po kliknięciu

Strony są statyczne i czytają pliki JSON z `static/data/`, które tworzy `collect.py`.
Dzięki temu ten sam kod działa lokalnie i na GitHub Pages.

## Lokalnie
1. Skopiuj `.env.example` do `.env` i wpisz klucz z https://pdp-api.plk-sa.pl/
2. `python server.py` i otwórz http://127.0.0.1:8000

Serwer co 2 minuty (`POLL_SECONDS`) sprawdza `/data-version` (1 zapytanie) i dopiero przy nowych danych
pobiera migawkę (4–5 zapytań). PLK publikuje nowe dane nieregularnie, co kilka–kilkanaście minut.
Razem ok. 1500 zapytań na dobę przy limicie Standard 5000.

## Na GitHubie (bez własnego serwera)
Strona: https://mat-szymanski.github.io/pociagi/ (mapa: `mapa.html`).

Workflow `.github/workflows/collect.yml` co 5 minut uruchamia `collect.py` i przy nowych danych
publikuje katalog `static/` na GitHub Pages. Repozytorium musi być publiczne: wtedy minuty Actions są darmowe
(w prywatnym limit 2000–3000 min/mies. nie wystarczy na ok. 8600, a Pages wymaga planu Pro).

1. Wypchnij projekt do publicznego repozytorium (`.env` jest w `.gitignore`).
2. Settings → Secrets and variables → Actions → New repository secret: `PKP_PLK_APIKEY`
   (albo `gh secret set -f .env -R <właściciel>/<repo>`).
3. Settings → Pages → Source: **GitHub Actions**.
4. Actions → „Zbieranie danych” → Run workflow (pierwsze uruchomienie ręcznie).

Historia nie jest commitowana: przy każdym przebiegu `collect.py` dociąga ją z opublikowanej strony
(`HISTORY_URL`) i publikuje ponownie.

Ograniczenia GitHuba: zadania cykliczne co najmniej co 5 min, w godzinach szczytu bywają opóźniane
albo pomijane; w publicznym repo wyłączają się po 60 dniach bez aktywności w repozytorium.
GitHub Pages może cache'ować pliki do ok. 10 min.

## Pliki
- `plk.py` – klient API, czas warszawski, liczenie migawki i danych do mapy
- `collect.py` – jeden przebieg zbierania → `static/data/*.json`
- `server.py` – lokalnie: pętla `collect.py` + serwer plików
- `tools/build_stations.py` – buduje `static/data/stations.json` ze współrzędnymi stacji
- `tools/build_segments.py` – buduje `static/data/segments.json`: przebieg torów między kolejnymi stacjami
  (A* po sieci z `geo.osm`, pary stacji z rozkładu PLK na 31 dni); po zmianie rozkładu uruchom ponownie –
  dopisze brakujące pary
- `delay_now.py` – migawka w konsoli, `check_api.py` – test klucza

## Metodologia
- Opóźnienie pociągu = opóźnienie na ostatniej stacji potwierdzonej przez PLK (odjazd, a gdy brak – przyjazd).
- Przy zerowym opóźnieniu API pomija pola `adm`/`ddm` – traktujemy je jako 0.
- Pomijane są „widma” – pociągi ze statusem „w trasie”, których PLK nie zamknął lub przestał śledzić:
  wszystkie stacje potwierdzone; została tylko stacja końcowa, a prognozowany przyjazd minął > 15 min temu;
  prognozowany przejazd przez następną stację minął > 60 min temu; ostatnie potwierdzenie starsze niż 3 h.
- „Opóźniony” od 6 minut, jak w statystykach UTK.
- Pozycja na mapie: interpolacja liniowa między stacjami po czasach rzeczywistych (potwierdzone) i prognozowanych
  przez PLK. Jeśli w chwili publikacji danych pociąg powinien był minąć następną stację, a PLK tego nie potwierdził,
  reszta trasy jest przesuwana o tę różnicę. Pociąg porusza się wzdłuż torów (`segments.json`);
  dla par stacji bez wyznaczonego przebiegu zostaje prosta.

## Źródła i licencje
- Dane o ruchu: PKP Polskie Linie Kolejowe S.A. (API Otwarte Dane Kolejowe, regulamin wymaga podania źródła).
- Współrzędne stacji i sieć torów: `geo.osm` z https://github.com/JanKemnitz/PolishTrainsGTFS (CC0-1.0,
  migrowane z PLRailMap).
- Podkład mapy: © OpenStreetMap; tory: OpenRailwayMap.
