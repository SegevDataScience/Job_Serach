#!/usr/bin/env python3
"""
geo.py — the commuting zone (his rule, 2026-11-08).

A job is out if every place it names is:
  - north of Herzliya (Kfar Saba, Ra'anana, Netanya, Haifa...), or
  - Be'er Sheva, or
  - more than 55 km from both Jerusalem and Shoresh.
A job that names at least one place inside the zone stays ("Haifa; Tel Aviv"
stays for Tel Aviv). A location with no recognisable place returns None and the
older city whitelist in find_jobs decides.

Coordinates are city centres (±1-2 km), enough for a 55 km radius.
"""

from __future__ import annotations

import math
import re

ANCHORS = {"ירושלים": (31.778, 35.235), "שורש": (31.797, 35.065)}
MAX_KM = 55.0
NORTH_LIMIT_LAT = 32.170  # Herzliya's latitude; anything further north is out
EXCLUDED = {"באר שבע"}

# (Hebrew name, lat, lon, patterns). Patterns: lowercase English/Hebrew spellings seen in postings.
PLACES: list[tuple[str, float, float, list[str]]] = [
    ("ירושלים", 31.778, 35.235, ["jerusalem", "ירושלים"]),
    ("מבשרת ציון", 31.802, 35.150, ["mevaseret", "מבשרת"]),
    ("מעלה אדומים", 31.777, 35.298, ["maale adumim", "ma'ale adumim", "מעלה אדומים"]),
    ("גבעת זאב", 31.861, 35.169, ["givat zeev", "גבעת זאב"]),
    ("בית שמש", 31.747, 34.988, ["beit shemesh", "bet shemesh", "בית שמש"]),
    ("מודיעין", 31.898, 35.010, ["modiin", "modi'in", "modi’in", "מודיעין"]),
    ("שוהם", 31.999, 34.946, ["shoham", "שוהם"]),
    ("לוד", 31.951, 34.895, ["lod", "לוד"]),
    ("רמלה", 31.929, 34.866, ["ramla", "רמלה"]),
    ("איירפורט סיטי", 31.995, 34.900, ["airport city", "ben gurion airport", "איירפורט", "קרית שדה התעופה", "נמל תעופה בן גוריון", "נמל תעופה בן-גוריון"]),
    ("רחובות", 31.894, 34.811, ["rehovot", "רחובות"]),
    ("נס ציונה", 31.930, 34.798, ["ness ziona", "nes ziona", "נס ציונה"]),
    ("ראשון לציון", 31.964, 34.804, ["rishon", "ראשון לציון"]),
    ("יבנה", 31.878, 34.739, ["yavne", "יבנה"]),
    ("גדרה", 31.814, 34.778, ["gedera", "גדרה"]),
    ("אשדוד", 31.804, 34.655, ["ashdod", "אשדוד"]),
    ("אשקלון", 31.669, 34.571, ["ashkelon", "אשקלון"]),
    ("קריית גת", 31.610, 34.764, ["kiryat gat", "qiryat gat", "קריית גת", "קרית גת"]),
    ("קריית מלאכי", 31.731, 34.746, ["kiryat malachi", "קריית מלאכי", "קרית מלאכי"]),
    ("חולון", 32.011, 34.774, ["holon", "חולון"]),
    ("בת ים", 32.017, 34.745, ["bat yam", "bat-yam", "בת ים"]),
    ("אזור", 32.024, 34.806, ["azor"]),
    ("תל אביב", 32.085, 34.782, ["tel aviv", "tel-aviv", "tlv", "jaffa", "תל אביב", "תל-אביב", "יפו"]),
    ("רמת גן", 32.068, 34.824, ["ramat gan", "ramat-gan", "רמת גן", "רמת-גן"]),
    ("גבעתיים", 32.071, 34.810, ["givatayim", "giv'atayim", "גבעתיים"]),
    ("בני ברק", 32.084, 34.834, ["bnei brak", "bnei-brak", "בני ברק"]),
    ("פתח תקווה", 32.087, 34.887, ["petah tikva", "petach tikva", "petah-tikva", "petach-tikva", "petah tiqva", "פתח תקווה", "פתח תקוה"]),
    ("קריית אונו", 32.064, 34.855, ["kiryat ono", "kiryat-ono", "קרית אונו", "קריית אונו"]),
    ("אור יהודה", 32.031, 34.853, ["or yehuda", "אור יהודה"]),
    ("יהוד", 32.033, 34.890, ["yehud", "יהוד"]),
    ("גבעת שמואל", 32.077, 34.851, ["givat shmuel", "גבעת שמואל"]),
    ("ראש העין", 32.096, 34.957, ["rosh haayin", "rosh ha'ayin", "ראש העין"]),
    ("אלעד", 32.052, 34.951, ["elad", "אלעד"]),
    ("רמת השרון", 32.146, 34.839, ["ramat hasharon", "רמת השרון"]),
    ("הוד השרון", 32.150, 34.888, ["hod hasharon", "הוד השרון"]),
    ("הרצליה", 32.166, 34.844, ["herzliya", "herzliyya", "הרצליה"]),
    # outside the zone (named so a posting that lists only these is dropped)
    ("כפר סבא", 32.175, 34.907, ["kfar saba", "kefar sava", "כפר סבא"]),
    ("רעננה", 32.184, 34.871, ["raanana", "ra'anana", "רעננה"]),
    ("נתניה", 32.329, 34.857, ["netanya", "נתניה"]),
    ("חדרה", 32.437, 34.919, ["hadera", "חדרה"]),
    ("קיסריה", 32.500, 34.900, ["caesarea", "קיסריה"]),
    ("חיפה", 32.794, 34.990, ["haifa", "חיפה"]),
    ("יקנעם", 32.659, 35.105, ["yokneam", "יקנעם", "יוקנעם"]),
    ("באר שבע", 31.252, 34.791, ["beer sheva", "be'er sheva", "beersheba", "באר שבע"]),
    ("מודיעין עילית", 31.932, 35.043, ["modiin ilit", "modiin illit", "modi'in illit", "מודיעין עילית"]),
]
# Region words some boards use instead of a city.
REGIONS_IN = ["גוש דן", "ירושלים והסביבה", 'ירושלים יו"ש', "jerusalem district", "jerusalem area", "השפלה", "shfela", "tel aviv district"]
REGIONS_OUT = ["השרון", "sharon", "צפון", "north", "חיפה והקריות", "קריות", "דרום", "south", "גליל", "עמק"]

_LETTERS = "a-zא-ת"


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def in_zone(name: str) -> bool:
    for place, lat, lon, _ in PLACES:
        if place == name:
            if place in EXCLUDED or place == "מודיעין עילית" or lat > NORTH_LIMIT_LAT:
                return False
            return min(_km((lat, lon), anchor) for anchor in ANCHORS.values()) <= MAX_KM
    return False


def places_in(text: str) -> list[str]:
    # "Herzliya, Tel Aviv District" names Herzliya, not Tel Aviv.
    low = re.sub(r"(tel aviv|jerusalem|center|central|haifa|northern|southern) district", " ", (text or "").lower())
    found = []
    # Longer names first, so "מודיעין עילית" is not also read as "מודיעין".
    for place, _, _, patterns in sorted(PLACES, key=lambda p: -max(len(x) for x in p[3])):
        hit = False
        for p in patterns:  # every spelling is consumed ("Modiin Ilit (מודיעין עילית)" names one place, once)
            prefix = "[בלמוה]?" if p[:1] >= "א" else ""
            rx = rf"(?<![{_LETTERS}]){prefix}{re.escape(p)}(?![{_LETTERS}])"
            if re.search(rx, low):
                hit = True
                low = re.sub(rx, " ", low)
        if hit:
            found.append(place)
    return found


def zone_verdict(location: str) -> bool | None:
    """True: some named place is inside the zone. False: places are named and all are
    outside. None: nothing recognisable (the city whitelist decides)."""
    places = places_in(location)
    if any(in_zone(p) for p in places):
        return True
    low = (location or "").lower()
    if any(r in low for r in REGIONS_IN):
        return True
    if places:
        return False
    if any(re.search(rf"(?<![{_LETTERS}]){re.escape(r)}(?![{_LETTERS}])", low) for r in REGIONS_OUT):
        return False
    return None


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    for place, lat, lon, _ in PLACES:
        d = min(_km((lat, lon), a) for a in ANCHORS.values())
        print(f"{place:14} {d:5.1f} km  {'IN' if in_zone(place) else 'out'}")
