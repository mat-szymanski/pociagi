"""Buduje static/data/segments.json: przebieg torów między kolejnymi stacjami postoju.

Dla każdej pary kolejnych stacji z rozkładu PLK (oraz z bieżących danych mapy) szuka najkrótszej
drogi w grafie torów (A*), upraszcza ją i zapisuje jako zakodowaną polilinię (format Google,
precyzja 5). Klucz "a_b" to kierunek od stacji a do b (łącznice bywają jednokierunkowe).
Mapa rysuje trasę i przesuwa pociąg wzdłuż tych linii; dla par bez wyniku zostaje prosta.

Źródło torów: geo.osm z https://github.com/JanKemnitz/PolishTrainsGTFS (sieć pasażerska do
wyznaczania przebiegu, migrowana z PLRailMap, licencja CC0-1.0), czyli ten sam plik co stations.json.
Obsługiwany jest też eksport Overpass API w JSON (`out skel qt`) - wtedy wynik jest na licencji ODbL.

Użycie:
  python tools/build_segments.py <geo.osm> [--days 31]
Pary stacji: pełny rozkład z API PLK na --days dni (klucz z .env) + static/data/trains.json.
Ponowne uruchomienie dopisuje tylko brakujące pary (np. po zmianie rozkładu).
"""
import argparse
import heapq
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import plk  # noqa: E402

OUT = ROOT / "static" / "data" / "segments.json"
STATIONS = ROOT / "static" / "data" / "stations.json"
SNAP_M = 600  # stacja może leżeć do tylu metrów od toru
SNAP_K = 25  # tylu najbliższych węzłów toru bierzemy jako start/cel
MAX_DETOUR = 3.0  # odrzucamy drogę dłuższą niż 3x odległość w linii prostej (+5 km)
SIMPLIFY_M = 15  # tolerancja upraszczania linii


def dist_m(lat1, lon1, lat2, lon2):
    """Odległość w metrach (przybliżenie równoodległościowe - wystarczy na skalę Polski)."""
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000 * math.hypot(x, y)


class Graph:
    def __init__(self, files):
        coords, ways = {}, []  # ways: (lista węzłów, czy jednokierunkowa)
        for f in files:
            if str(f).endswith(".osm"):
                root = ET.parse(f).getroot()
                for n in root.iter("node"):
                    coords[n.get("id")] = (float(n.get("lat")), float(n.get("lon")))
                for w in root.iter("way"):
                    tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
                    if tags.get("railway") in ("rail", "light_rail", "narrow_gauge"):
                        ways.append(([nd.get("ref") for nd in w.findall("nd")], tags.get("oneway") == "yes"))
            else:
                for el in json.loads(Path(f).read_text(encoding="utf-8"))["elements"]:
                    if el["type"] == "node":
                        coords[el["id"]] = (el["lat"], el["lon"])
                    elif el["type"] == "way":
                        ways.append((el["nodes"], False))
        ids = list(coords)
        self.index = {nid: i for i, nid in enumerate(ids)}
        self.lat = [coords[n][0] for n in ids]
        self.lon = [coords[n][1] for n in ids]
        self.adj = [[] for _ in ids]
        seen = set()
        for nodes, oneway in ways:  # kafle Overpass zachodzą na siebie - te same drogi bywają kilka razy
            for a, b in zip(nodes, nodes[1:]):
                if a not in self.index or b not in self.index:
                    continue
                i, j = self.index[a], self.index[b]
                d = dist_m(self.lat[i], self.lon[i], self.lat[j], self.lon[j])
                for x, y in ((i, j),) if oneway else ((i, j), (j, i)):
                    if (x, y) not in seen:
                        seen.add((x, y))
                        self.adj[x].append((y, d))
        self.cells = defaultdict(list)  # siatka ~1 km do szukania najbliższych węzłów
        for i in range(len(ids)):
            if self.adj[i]:
                self.cells[(int(self.lat[i] * 100), int(self.lon[i] * 66))].append(i)
        print(f"graf: {sum(1 for a in self.adj if a)} węzłów torów, {len(seen)} krawędzi skierowanych", flush=True)

    def near(self, lat, lon):
        ci, cj = int(lat * 100), int(lon * 66)
        found = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for i in self.cells.get((ci + di, cj + dj), ()):
                    d = dist_m(lat, lon, self.lat[i], self.lon[i])
                    if d <= SNAP_M:
                        found.append((d, i))
        return sorted(found)[:SNAP_K]

    def route(self, a, b):
        """Najkrótsza droga po torach między stacjami a i b (lat, lon) albo None."""
        starts, goals = self.near(*a), {i: d for d, i in self.near(*b)}
        if not starts or not goals:
            return None
        straight = dist_m(*a, *b)
        limit = MAX_DETOUR * straight + 5000
        h = lambda i: max(0.0, dist_m(self.lat[i], self.lon[i], *b) - SNAP_M)
        best, prev, heap = {}, {}, []
        for d, i in starts:  # dojście od stacji do toru liczone podwójnie - wolimy bliższy tor
            best[i] = 2 * d
            prev[i] = None
            heapq.heappush(heap, (2 * d + h(i), 2 * d, i))
        while heap:
            f, g, i = heapq.heappop(heap)
            if f > limit:  # kolejka jest uporządkowana wg f - dalej będzie tylko gorzej
                return None
            if g > best.get(i, math.inf):
                continue
            if i in goals:
                path = []
                while i is not None:
                    path.append((self.lat[i], self.lon[i]))
                    i = prev[i]
                return [a] + path[::-1] + [b]
            for j, d in self.adj[i]:
                ng = g + d + (2 * goals[j] if j in goals else 0)
                if ng < best.get(j, math.inf):
                    best[j] = ng
                    prev[j] = i
                    heapq.heappush(heap, (ng + h(j), ng, j))
        return None


def simplify(pts, tol_m=SIMPLIFY_M):
    """Douglas-Peucker na współrzędnych przeliczonych lokalnie na metry."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(pts[0][0])
    xy = [(math.radians(p[1]) * math.cos(lat0) * 6371000, math.radians(p[0]) * 6371000) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        s, e = stack.pop()
        (x1, y1), (x2, y2) = xy[s], xy[e]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        idx, dmax = None, tol_m
        for k in range(s + 1, e):
            d = abs(dy * (xy[k][0] - x1) - dx * (xy[k][1] - y1)) / norm
            if d > dmax:
                idx, dmax = k, d
        if idx is not None:
            keep[idx] = True
            stack += [(s, idx), (idx, e)]
    return [p for p, k in zip(pts, keep) if k]


def encode(pts):
    """Zakodowana polilinia (algorytm Google, precyzja 5)."""
    out, plat, plon = [], 0, 0
    for lat, lon in pts:
        ilat, ilon = round(lat * 1e5), round(lon * 1e5)
        for v in (ilat - plat, ilon - plon):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1F)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ilat, ilon
    return "".join(out)


def station_pairs(days):
    pairs = set()
    key = plk.load_key()
    start = plk.warsaw_now().date()
    status, body, _ = plk.get(f"/api/v1/schedules/shortened?dateFrom={start}&dateTo={start + timedelta(days=days - 1)}"
                              f"&dictionaries=false", key)
    if status != 200:
        raise SystemExit(f"schedules: HTTP {status} {body}")
    for r in body.get("rt", []):
        ids = [s["id"] for s in r.get("st", [])]
        pairs.update(zip(ids, ids[1:]))
    current = ROOT / "static" / "data" / "trains.json"
    if current.exists():  # objazdy i zmiany z bieżących danych wykonania
        for t in json.loads(current.read_text(encoding="utf-8"))["trains"]:
            ids = [s[0] for s in t["s"]]
            pairs.update(zip(ids, ids[1:]))
    return {(a, b) for a, b in pairs if a != b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rails", nargs="+")
    ap.add_argument("--days", type=int, default=31)
    args = ap.parse_args()

    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    segments = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    pairs = station_pairs(args.days)
    todo = [(a, b) for a, b in sorted(pairs)
            if f"{a}_{b}" not in segments and str(a) in stations and str(b) in stations]
    print(f"par stacji: {len(pairs)}, do policzenia: {len(todo)}", flush=True)

    graph = Graph(args.rails)
    found = failed = 0
    t0 = time.time()
    for n, (a, b) in enumerate(todo, 1):
        pa, pb = stations[str(a)][:2], stations[str(b)][:2]
        path = graph.route(tuple(pa), tuple(pb))
        if path:
            segments[f"{a}_{b}"] = encode(simplify(path))
            found += 1
        else:
            failed += 1
        if n % 250 == 0:
            print(f"  {n}/{len(todo)}  znalezione {found}, bez drogi {failed}  ({time.time() - t0:.0f} s)", flush=True)
    OUT.write_text(json.dumps(segments, separators=(",", ":")), encoding="utf-8")
    print(f"gotowe: {found} nowych odcinków, {failed} bez drogi (zostaje prosta), razem {len(segments)} "
          f"-> {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
