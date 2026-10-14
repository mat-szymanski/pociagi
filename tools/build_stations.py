"""Buduje static/data/stations.json (ID stacji PLK -> [szer., dł., nazwa]) z pliku geo.osm.

Źródło: https://github.com/JanKemnitz/PolishTrainsGTFS/blob/kw/data/geo.osm (licencja CC0-1.0),
tag `ref` = ID stacji w API PKP PLK.
Użycie: python tools/build_stations.py <geo.osm>
"""
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "static" / "data" / "stations.json"


def main(src):
    stations = {}
    for node in ET.parse(src).getroot().iter("node"):
        tags = {t.get("k"): t.get("v") for t in node.findall("tag")}
        if tags.get("railway") in ("station", "halt") and tags.get("ref", "").isdigit():
            stations[tags["ref"]] = [round(float(node.get("lat")), 5), round(float(node.get("lon")), 5),
                                     tags.get("name", "")]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(stations, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(stations)} stacji -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
