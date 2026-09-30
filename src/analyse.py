"""Turn raw hourly data into fishing advice: tides, condition score, legal status,
departure times and open bait shops.

The score is a transparent heuristic, not a scientific model. Every factor is
listed with its contribution so users (and you) can see why a day scores well.
"""
import math
from datetime import datetime, timedelta, date

SEASON_SUMMER = range(4, 12)   # April..November: summer species active
BASS_SEASON = (date(2000, 4, 25), date(2000, 11, 15))  # typical inshore bass window


# ---------- tides ----------

def tide_extremes(rows):
    """High and low water from the hourly sea-level curve, refined with a
    parabola through the 3 points around each turning point."""
    out = []
    for i in range(1, len(rows) - 1):
        a, b, c = (rows[i - 1]["sea_level_height_msl"], rows[i]["sea_level_height_msl"],
                   rows[i + 1]["sea_level_height_msl"])
        if None in (a, b, c):
            continue
        kind = "HW" if b > a and b >= c else "LW" if b < a and b <= c else None
        if not kind:
            continue
        denom = a - 2 * b + c
        off = 0.5 * (a - c) / denom if denom else 0.0
        t = rows[i]["time"] + timedelta(minutes=round(off * 60))
        h = b - 0.25 * (a - c) * off
        out.append({"kind": kind, "time": t, "height": round(h, 2)})
    return out


def tidal_range(extremes, day):
    """Largest HW-LW difference on a day: proxy for spring (big) vs neap (small)."""
    ex = [e for e in extremes if e["time"].date() == day]
    hw = [e["height"] for e in ex if e["kind"] == "HW"]
    lw = [e["height"] for e in ex if e["kind"] == "LW"]
    if not hw or not lw:
        return None
    return round(max(hw) - min(lw), 2)


# ---------- conditions score ----------

def _at(rows, t):
    return min(rows, key=lambda r: abs((r["time"] - t).total_seconds()))


def pressure_trend(rows, t, hours=6):
    now, before = _at(rows, t), _at(rows, t - timedelta(hours=hours))
    return round(now["pressure_msl"] - before["pressure_msl"], 1)


def score_window(rows, hw, trange):
    """Score the fishing window from HW-2h to HW+1h (0..10)."""
    t = hw["time"]
    window = [r for r in rows if t - timedelta(hours=2) <= r["time"] <= t + timedelta(hours=1)]
    if not window:
        return None
    wave = max(r["wave_height"] or 0 for r in window)
    wind = max(r["wind_speed_10m"] for r in window)
    gust = max(r["wind_gusts_10m"] for r in window)
    dp = pressure_trend(rows, t)
    dark = sum(1 for r in window if not r["is_day"]) / len(window)

    f = []  # (text key, params, points): rendered in the reader's language later
    if wave < 0.3:   f.append(("f_flat", {}, 0.5))
    elif wave < 1.5: f.append(("f_surf", {}, 2.5))
    elif wave < 2.2: f.append(("f_big", {}, 1.0))
    else:            f.append(("f_toohigh", {}, -2.0))
    if wind < 20:    f.append(("f_calm", {}, 2.0))
    elif wind < 32:  f.append(("f_breeze", {}, 1.0))
    else:            f.append(("f_strong", {}, -1.5))
    # Current / tidal range: "geen stroming, geen vis"
    if trange is not None:
        if trange > 4.3:   f.append(("f_spring", {}, 2.0))
        elif trange > 3.6: f.append(("f_mean", {}, 1.2))
        else:              f.append(("f_neap", {}, 0.4))
    # Pressure: stable or slowly falling is usually better than a sharp rise.
    dps = f"{dp:+}"
    if -3 <= dp <= 1:  f.append(("f_p_stable", {"dp": dps}, 1.5))
    elif dp < -3:      f.append(("f_p_fall", {"dp": dps}, 0.8))
    else:              f.append(("f_p_rise", {"dp": dps}, 0.3))
    if dark >= 0.5:    f.append(("f_dark", {}, 1.0))

    total = max(0.0, min(10.0, sum(p for _, _, p in f)))
    unsafe = wave >= 2.5 or gust >= 60
    return {"score": round(total, 1), "factors": f, "wave": wave, "wind": wind,
            "gust": gust, "dp": dp, "unsafe": unsafe,
            "start": t - timedelta(hours=2), "end": t + timedelta(hours=1)}


def best_window(rows, extremes, day):
    trange = tidal_range(extremes, day)
    cands = []
    for e in extremes:
        if e["kind"] == "HW" and e["time"].date() == day:
            c = score_window(rows, e, trange)
            if c:
                c["hw"], c["range"] = e, trange
                cands.append(c)
    return max(cands, key=lambda c: c["score"]) if cands else None


# ---------- species & rules ----------

def species_for(spot, day):
    season = "summer" if day.month in SEASON_SUMMER else "winter"
    sp = list(spot["species"][season])
    d = date(2000, day.month, day.day)
    if "zeebaars" in sp and not (BASS_SEASON[0] <= d <= BASS_SEASON[1]):
        sp.remove("zeebaars")
    return sp


def legal_notes(species, rules, day):
    """Structured notes (key, params) rendered per language later."""
    notes = []
    # Closed-season warnings apply even if the species is not a target this time of year.
    for s, r in rules["species"].items():
        if day.month in r.get("no_retention_months", []):
            notes.append(("l_closed", {"sp": s}))
    for s in species:
        r = rules["species"].get(s, {})
        if day.month in r.get("no_retention_months", []):
            continue
        if "min_size_cm" in r:
            notes.append(("l_size", {"sp": s, "min": r["min_size_cm"], "bag": r.get("bag_limit_per_day", "?")}))
        if r.get("recfishing_registration"):
            notes.append(("l_rec", {"sp": s}))
    return notes


# ---------- travel ----------

def haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def drive_minutes(origin, spot):
    """Rough estimate without traffic: road distance ~1.25x straight line,
    average 95 km/h (mostly motorway), +10 min parking/walking.
    Replace with OpenRouteService in v2."""
    km = haversine_km(origin["lat"], origin["lon"], spot["lat"], spot["lon"]) * 1.25
    return round(km / 95 * 60 + 10), round(km)


def departures(origins, spot, arrive_by, bait_stop_min=0):
    out = []
    for o in origins:
        mins, km = drive_minutes(o, spot)
        leave = arrive_by - timedelta(minutes=mins + bait_stop_min)
        out.append({"from": o["name"], "km": km, "minutes": mins, "leave": leave})
    return out


# ---------- bait shops ----------

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def shops_open(shops, when):
    """Shops open at `when` (a datetime). Ignores shops without a name."""
    res = []
    for s in shops:
        if not s.get("name"):
            continue
        hrs = s["hours"].get(DAYS[when.weekday()])
        if not hrs:
            continue
        o, c = hrs.split("-")
        oh = when.replace(hour=int(o[:2]), minute=int(o[3:]))
        ch = when.replace(hour=int(c[:2]), minute=int(c[3:]))
        if oh <= when <= ch:
            res.append(s)
    return res
