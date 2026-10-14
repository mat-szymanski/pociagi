"""Klient API Otwarte Dane Kolejowe (PKP PLK) i liczenie migawki opóźnień.

Opóźnienie pociągu = opóźnienie na ostatniej potwierdzonej stacji (odjazd, a gdy brak - przyjazd).
Koszt migawki: 1 /statistics + 2-3 /operations (PLK publikuje nowe dane co kilka minut);
trasy i przewoźnicy pobierani raz na dobę (cache w data/).
Czasy w API są lokalne (Europe/Warsaw) bez strefy - przeliczamy je sami, bo np. GitHub Actions działa w UTC.
"""
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://pdp-api.plk-sa.pl"
DATA = Path(__file__).with_name("data")
# PLK nie zawsze zamyka pociągi - status "w trasie" potrafi zostać na dni. Odrzucamy pociąg, gdy:
GHOST_AFTER = timedelta(hours=3)  # ostatnie potwierdzenie starsze niż 3 h
LOST_AFTER = timedelta(minutes=60)  # prognozowany przejazd przez następną stację minął ponad godzinę temu
FINISHED_AFTER = timedelta(minutes=15)  # została tylko stacja końcowa, a prognozowany przyjazd minął dawno
DELAYED_MIN = 6  # jak UTK: do 5:59 pociąg jest punktualny
BUCKETS = [("0–5", 0, 6), ("6–19", 6, 20), ("20–59", 20, 60), ("60+", 60, 10**6)]


def load_key():
    env = Path(__file__).with_name(".env")
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "PKP_PLK_APIKEY" and value.strip():
                return value.strip()
    return os.environ.get("PKP_PLK_APIKEY")


def get(path, key):
    req = urllib.request.Request(BASE + path, headers={"X-API-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            limits = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-ratelimit")}
            return resp.status, json.load(resp), limits
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300], {}


class ApiError(RuntimeError):
    pass


# --- czas warszawski bez zależności od strefy systemu (i bez pakietu tzdata na Windows) ---

def _last_sunday(year, month):
    d = date(year, month, 31)  # marzec i październik mają po 31 dni
    return d - timedelta(days=(d.weekday() + 1) % 7)


def warsaw_offset(utc):
    """CET/CEST: czas letni od ostatniej niedzieli marca do ostatniej niedzieli października, 01:00 UTC."""
    start = datetime.combine(_last_sunday(utc.year, 3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(_last_sunday(utc.year, 10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return timedelta(hours=2 if start <= utc < end else 1)


def warsaw_now():
    utc = datetime.now(timezone.utc)
    return (utc + warsaw_offset(utc)).replace(tzinfo=None)


def local_time(utc_iso):
    """'2026-10-14T18:54:14.6582106Z' -> '2026-10-14T20:54:14' (czas warszawski)."""
    utc = datetime.fromisoformat(re.sub(r"\.\d+", "", utc_iso).replace("Z", "+00:00"))
    return (utc + warsaw_offset(utc)).replace(tzinfo=None).isoformat(timespec="seconds")


def epoch(local_iso):
    """Czas warszawski z API -> sekundy Unix (dla przeglądarki w dowolnej strefie)."""
    if not local_iso:
        return 0
    t = datetime.fromisoformat(local_iso).replace(tzinfo=timezone.utc)
    return int((t - warsaw_offset(t - timedelta(hours=1))).timestamp())


# --- dane z API ---

def _cached(name, path, key):
    DATA.mkdir(exist_ok=True)
    cache = DATA / name
    if not cache.exists():
        status, body, _ = get(path, key)
        if status != 200:
            raise ApiError(f"{path}: HTTP {status} {body}")
        cache.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return json.loads(cache.read_text(encoding="utf-8"))


def routes_for(day, key):
    """(data kursowania, orderId) -> (kod przewoźnika, nazwa pociągu)."""
    body = _cached(f"routes_{day}.json", f"/api/v1/schedules/routes/{day}/shortened", key)
    return {(day, r["oid"]): (r.get("cc") or "?", r.get("nm") or "") for r in body.get("r", [])}


def short_name(name):
    """'„PKP Intercity” Spółka Akcyjna' -> 'PKP Intercity'."""
    name = re.sub(r"\s*\(.*?\)", "", name)
    name = re.sub(r"\s+(spółka akcyjna|s\.?a\.?|sp\. ?z ?o\.? ?o\.?|a\.s\.|s\.r\.o\.|gmbh)\s*$", "", name.strip(), flags=re.I)
    name = re.sub(r" - [A-ZŁ]+$", "", name.strip("„”\"' ")).strip("„”\"' ")  # '"Koleje Mazowieckie - KM"'
    return name


def carrier_names(key):
    body = _cached(f"carriers_{warsaw_now().date()}.json", "/api/v1/dictionaries/carriers", key)
    return {c["code"]: short_name(c["name"]) for c in body.get("carriers", [])}


def fetch_operations(key):
    trains, stations, page, limits, ts = [], {}, 1, {}, None
    while True:
        status, body, limits = get(f"/api/v1/operations/shortened?withPlanned=true&pageSize=10000&page={page}", key)
        if status != 200:
            raise ApiError(f"operations p{page}: HTTP {status} {body}")
        ts = body.get("ts")
        trains += body.get("tr", [])
        st = body.get("st") or {}
        stations.update(st if isinstance(st, dict) else {str(s["id"]): s.get("nm") for s in st})
        if not body.get("pg", {}).get("hn"):
            return ts, trains, stations, limits
        page += 1


def data_version(key):
    """Tanie sprawdzenie, czy PLK opublikował nowe dane wykonania."""
    status, body, limits = get("/api/v1/data-version", key)
    if status != 200:
        raise ApiError(f"data-version: HTTP {status} {body}")
    return body.get("operationsVersion") or body.get("dataVersion"), body.get("timestamp"), limits


def _delay(stop):
    # przy zerowym opóźnieniu API pomija pola adm/ddm
    return stop.get("ddm") if stop.get("ddm") is not None else stop.get("adm") or 0


def snapshot(key, top_n=15, data_ts=None):
    """Zwraca (podsumowanie, pociągi do mapy).

    data_ts: czas publikacji danych z /data-version (UTC); ts z /operations to tylko czas odpowiedzi.
    Na mapę trafiają pełne trasy z czasami rzeczywistymi (potwierdzone) i prognozowanymi (PLK przenosi
    opóźnienie na kolejne stacje), więc pozycję między stacjami liczy przeglądarka.
    """
    now = warsaw_now()
    routes = {}
    for d in (now.date() - timedelta(days=1), now.date()):  # nocne pociągi mają datę kursowania z wczoraj
        routes.update(routes_for(d.isoformat(), key))
    names = carrier_names(key)

    status, stats, _ = get("/api/v1/operations/statistics", key)
    stats = stats.get("data", stats) if status == 200 and isinstance(stats, dict) else {}
    api_ts, trains, station_names, limits = fetch_operations(key)

    data_now = datetime.fromisoformat(local_time(data_ts)) if data_ts else now  # prognozy są aktualne na ten moment
    running, map_trains, ghosts, finished = [], [], 0, 0
    for t in trains:
        if t.get("s") != "P":
            continue
        stops = sorted(t.get("st", []), key=lambda s: s.get("psn") or 0)
        done = [s for s in stops if s.get("cf") and not s.get("cn")]
        if not done:
            continue
        last = max(done, key=lambda s: s.get("asn") or s.get("psn") or 0)
        actual = last.get("ad") or last.get("aa")
        if not actual or now - datetime.fromisoformat(actual) > GHOST_AFTER:
            ghosts += 1
            continue
        rest = [s for s in stops if not s.get("cn") and (s.get("psn") or 0) > (last.get("psn") or 0)]
        if not rest:  # wszystkie stacje potwierdzone, tylko status nie zmienił się na "zakończony"
            finished += 1
            continue
        predicted = rest[0].get("aa") or rest[0].get("ad")
        late = data_now - datetime.fromisoformat(predicted) if predicted else timedelta(0)
        if len(rest) == 1 and late > FINISHED_AFTER:  # dojechał, PLK nie potwierdził stacji końcowej
            finished += 1
            continue
        if late > LOST_AFTER:  # PLK przestał śledzić pociąg
            ghosts += 1
            continue
        delay = _delay(last)
        carrier, name = routes.get((t["od"][:10], t["oid"]), ("?", ""))
        station = lambda s: station_names.get(str(s["id"]), str(s["id"]))
        running.append({"carrier": carrier, "name": name, "delay": delay, "at": station(last),
                        "from": station(stops[0]), "to": station(stops[-1])})
        map_trains.append({
            "id": f"{t['od'][:10]}_{t['oid']}", "c": carrier, "n": name, "d": delay,
            # [id stacji, przyjazd, odjazd (Unix s, 0 = brak), opóźnienie, 1 = potwierdzone, 1 = odwołany postój]
            "s": [[s["id"], epoch(s.get("aa")), epoch(s.get("ad")), _delay(s), int(bool(s.get("cf"))),
                   int(bool(s.get("cn")))] for s in stops],
        })

    n = len(running)
    total = sum(max(r["delay"], 0) for r in running)
    by = defaultdict(list)
    for r in running:
        by[r["carrier"]].append(max(r["delay"], 0))
    carriers = sorted(({"code": c, "name": names.get(c, c), "total": sum(v), "count": len(v),
                        "avg": round(sum(v) / len(v), 1)} for c, v in by.items()), key=lambda c: -c["total"])
    buckets = Counter(next(label for label, lo, hi in BUCKETS if lo <= max(r["delay"], 0) < hi) for r in running)
    top = sorted(running, key=lambda r: -r["delay"])[:top_n]
    for r in top:
        r["carrierName"] = names.get(r["carrier"], r["carrier"])

    ts = local_time(data_ts or api_ts) if (data_ts or api_ts) else now.isoformat(timespec="seconds")
    summary = {
        "ts": ts,
        "epoch": epoch(ts),
        "fetchedAt": now.isoformat(timespec="seconds"),
        "total": total,
        "running": n,
        "delayed": sum(r["delay"] >= DELAYED_MIN for r in running),
        "avg": round(total / n, 1) if n else 0,
        "ghosts": ghosts,
        "finishedUnconfirmed": finished,
        "buckets": [{"label": label, "count": buckets[label]} for label, _, _ in BUCKETS],
        "carriers": carriers,
        "top": top,
        "day": {k: stats.get(k) for k in ("totalTrains", "inProgress", "completed", "notStarted",
                                          "cancelled", "partialCancelled")},
        "limits": {k.removeprefix("X-RateLimit-"): int(v) for k, v in limits.items()},
    }
    map_data = {"ts": ts, "epoch": epoch(ts), "carriers": {c["code"]: c["name"] for c in carriers},
                "stationNames": {}, "trains": map_trains}
    used = {str(s[0]) for tr in map_trains for s in tr["s"]}
    map_data["stationNames"] = {k: v for k, v in station_names.items() if k in used}
    return summary, map_data
