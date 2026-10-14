"""Jednorazowa migawka opóźnień w konsoli. Użycie: python delay_now.py"""
from plk import DELAYED_MIN, load_key, snapshot


def main():
    s, _ = snapshot(load_key(), top_n=10)
    d = s["day"]
    print(f"Stan na: {s['ts']} | zapytania pozostałe: {s['limits'].get('Hourly-Remaining')}/h, "
          f"{s['limits'].get('Daily-Remaining')}/dobę")
    print(f"Doba: {d['totalTrains']} pociągów | w trasie {d['inProgress']} | zakończone {d['completed']} "
          f"| nie wyruszyły {d['notStarted']} | odwołane {d['cancelled']} (częściowo {d['partialCancelled']})")
    print(f"Pociągi w trasie z potwierdzoną pozycją: {s['running']} (odrzucone \"widma\": {s['ghosts']})")
    print(f"Opóźnione (>={DELAYED_MIN} min): {s['delayed']}")
    print(f"SUMA OPÓŹNIEŃ: {s['total']} min = {s['total'] / 60:.1f} h | średnio {s['avg']} min na pociąg")
    print("Rozkład [min]:", {b["label"]: b["count"] for b in s["buckets"]})
    print("\nWg przewoźnika (suma min / pociągi / średnio):")
    for c in s["carriers"]:
        print(f"  {c['code']:8} {c['total']:6}  {c['count']:4}  {c['avg']:5.1f}  {c['name']}")
    print("\nTop 10:")
    for r in s["top"]:
        print(f"  {r['delay']:4} min  {r['carrier']:5} {r['from']} → {r['to']} (ostatnio: {r['at']})")


if __name__ == "__main__":
    main()
