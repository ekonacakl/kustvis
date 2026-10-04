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
    levels = [r["sea_level_height_msl"] for r in rows if r.get("sea_level_height_msl") is not None]
    mid = sum(levels) / len(levels) if levels else 0.0
    out = []
    for i in range(1, len(rows) - 1):
        a, b, c = (rows[i - 1]["sea_level_height_msl"], rows[i]["sea_level_height_msl"],
                   rows[i + 1]["sea_level_height_msl"])
        if None in (a, b, c):
            continue
        kind = "HW" if b > a and b >= c else "LW" if b < a and b <= c else None
        # Ignore small wiggles on the wrong side of mean level (e.g. the double
        # low water at Hoek van Holland), which are not real high or low waters.
        if not kind or (kind == "HW" and b < mid) or (kind == "LW" and b > mid):
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
    ok = [r for r in rows if r.get("pressure_msl") is not None]
    if not ok:
        return 0.0
    now, before = _at(ok, t), _at(ok, t - timedelta(hours=hours))
    return round(now["pressure_msl"] - before["pressure_msl"], 1)


SEA_BEARING = 320  # the Belgian coast faces roughly north-west
USED_VARS = ["sea_level_height_msl", "wave_height", "wind_speed_10m", "wind_direction_10m",
             "cloud_cover", "pressure_msl", "is_day"]
WEIGHTS = {"wave": 2.5, "tide": 2.5, "wind": 2.0, "cloud": 1.0, "pressure": 1.0, "light": 1.0}


def _vals(window, key):
    return [r[key] for r in window if r.get(key) is not None]


def _mean_dir(degs):
    x = sum(math.cos(math.radians(d)) for d in degs)
    y = sum(math.sin(math.radians(d)) for d in degs)
    return math.degrees(math.atan2(y, x)) % 360


def half(x):
    """Round to the nearest 0.5 so scores read as 6, 6.5, 7 instead of 6.2."""
    return round(x * 2) / 2


def score_window(rows, hw, trange, spot=None):
    """Score the fishing window from 0 to 10 (steps of 0.5). The window is
    HW-2h..HW+1h, or HW..HW+3h (the ebb) at river mouths and outflows.

    Six parts, each worth a fixed share: waves 2.5, tide 2.5, wind 2, cloud 1,
    pressure 1, light 1. Spot type matters: an open beach wants some surf, a pier
    or harbour wall is more forgiving. A missing input counts as neutral (half
    its share) and is reported in c["missing"]."""
    t = hw["time"]
    before, after = (0, 3) if (spot or {}).get("mouth") else (2, 1)
    start, end = t - timedelta(hours=before), t + timedelta(hours=after)
    window = [r for r in rows if start <= r["time"] <= end]
    if not window:
        return None
    lo, hi = (spot or {}).get("tide_scale", (2.8, 4.6))
    tide_v = None
    kind = (spot or {}).get("type", "beach")
    bearing = (spot or {}).get("sea_bearing", SEA_BEARING)
    missing = [k for k in USED_VARS if not _vals(window, k)]
    f = []  # (text key, params, points)

    def add(part, key, value, **params):
        f.append((key, params, round(WEIGHTS[part] * value, 1)))

    # --- waves
    wv = _vals(window, "wave_height")
    wave = max(wv) if wv else None
    if wave is None:
        add("wave", "f_nodata_wave", 0.5)
    elif kind == "beach":
        if wave < 0.3:   add("wave", "f_flat", 0.3)
        elif wave < 0.5: add("wave", "f_light_surf", 0.7)
        elif wave < 1.4: add("wave", "f_surf", 1.0)
        elif wave < 2.0: add("wave", "f_big", 0.5)
        else:            add("wave", "f_toohigh", 0.0)
    else:  # pier / harbour wall: deeper water, less dependent on surf
        if wave < 0.3:   add("wave", "f_flat", 0.6)
        elif wave < 1.2: add("wave", "f_surf", 1.0)
        elif wave < 1.8: add("wave", "f_big", 0.6)
        else:            add("wave", "f_toohigh", 0.1)

    # --- tide: "geen stroming, geen vis"
    if trange is None:
        add("tide", "f_nodata_tide", 0.5)
    else:
        tide_v = (trange - lo) / (hi - lo)   # 0 = neap, 1 = spring, for this region
        key = "f_spring" if tide_v > 0.83 else "f_mean" if tide_v > 0.44 else "f_neap"
        add("tide", key, max(0.2, min(1.0, tide_v)), r=f"{trange:.1f}")

    # --- wind: speed, and direction relative to the coast
    ws = _vals(window, "wind_speed_10m")
    wind = max(ws) if ws else None
    gust = max(_vals(window, "wind_gusts_10m") or [0])
    wd = _vals(window, "wind_direction_10m")
    wdir = _mean_dir(wd) if wd else None
    if wind is None:
        add("wind", "f_nodata_wind", 0.5)
    else:
        v = 1.0 if wind < 12 else 0.85 if wind < 20 else 0.6 if wind < 28 else 0.3 if wind < 38 else 0.0
        key = "f_calm" if wind < 20 else "f_breeze" if wind < 32 else "f_strong"
        rel = None
        if wdir is not None:
            diff = abs((wdir - bearing + 180) % 360 - 180)
            rel = "onshore" if diff < 60 else "offshore" if diff > 120 else "cross"
            if rel == "onshore" and wind >= 25:
                v -= 0.25 if kind == "beach" else 0.35   # casting into the wind, exposed walls
            elif rel == "offshore" and 8 <= wind < 30:
                v += 0.1                                  # wind in the back: easy casting
        add("wind", key, max(0.0, min(1.0, v)), w=round(wind), rel=rel)

    # --- cloud cover and light
    il = _vals(window, "is_day")
    dark = sum(1 for d in il if d == 0) / len(il) if il else None
    cc = _vals(window, "cloud_cover")
    cloud = sum(cc) / len(cc) if cc else None
    if cloud is None:
        add("cloud", "f_nodata_cloud", 0.5)
    elif dark is not None and dark >= 0.9:
        add("cloud", "f_cloud_night", 0.7, c=round(cloud))
    elif cloud >= 70: add("cloud", "f_overcast", 1.0, c=round(cloud))
    elif cloud >= 30: add("cloud", "f_partly", 0.6, c=round(cloud))
    else:             add("cloud", "f_sunny", 0.3, c=round(cloud))

    if dark is None:      add("light", "f_nodata_light", 0.5)
    elif dark >= 0.9:     add("light", "f_dark", 0.8)
    elif dark > 0.1:      add("light", "f_twilight", 1.0)
    else:                 add("light", "f_daylight", 0.4)

    # --- pressure trend: stable or slowly falling beats a sharp rise
    dp = pressure_trend(rows, t)
    dps = f"{dp:+}"
    if "pressure_msl" in missing: add("pressure", "f_nodata_pressure", 0.5)
    elif -3 <= dp <= 1:           add("pressure", "f_p_stable", 1.0, dp=dps)
    elif dp < -3:                 add("pressure", "f_p_fall", 0.6, dp=dps)
    else:                         add("pressure", "f_p_rise", 0.3, dp=dps)

    total = max(0.0, min(10.0, sum(p for _, _, p in f)))
    unsafe = (wave or 0) >= 2.5 or gust >= 60
    return {"score": half(total), "factors": f, "wave": wave, "wind": wind, "wdir": wdir,
            "gust": gust, "dp": dp, "cloud": cloud, "dark": dark, "unsafe": unsafe,
            "missing": missing, "tide_v": tide_v, "start": start, "end": end}


def day_windows(rows, extremes, day, spot=None):
    """Score every high-water window of the day and tag it as daylight or not."""
    trange = tidal_range(extremes, day)
    out = []
    for e in extremes:
        if e["kind"] == "HW" and e["time"].date() == day:
            c = score_window(rows, e, trange, spot)
            if c:
                c["hw"], c["range"] = e, trange
                c["daylight"] = c["dark"] is None or c["dark"] < 0.5
                out.append(c)
    return out


def split_windows(rows, extremes, day, spot=None):
    """(daytime, night): the best daylight window and the best night window.
    Most people fish in daylight, so daytime is the main recommendation;
    the night window is shown as an alternative."""
    ws = day_windows(rows, extremes, day, spot)
    best = lambda xs: max(xs, key=lambda c: c["score"]) if xs else None
    return best([w for w in ws if w["daylight"]]), best([w for w in ws if not w["daylight"]])


def best_window(rows, extremes, day, spot=None):
    """Main recommendation: the daylight window, or the night one if there is none."""
    d, n = split_windows(rows, extremes, day, spot)
    return d or n


# ---------- per-species fit ----------
# Weather is nearly identical along a short coast, so the general score barely
# separates the spots. What does differ is the spot itself (beach, pier, harbour
# wall, river mouth) and what each species wants. Rules of thumb, tune freely.
#   wave: (ideal_low, ideal_high) in metres   light: "low" | "day" | None
#   spot: bonus per spot trait                current: how much the fish likes a strong tide
SPECIES_PREF = {
    "zeebaars": {"wave": (0.5, 1.4), "light": "low", "current": 1.5,
                 "spot": {"mouth": 1.5, "beach": 0.5, "pier": 0.5, "harbour_wall": 0.5}},
    "tong":     {"wave": (0.0, 0.6), "light": "low", "current": 0.0,
                 "spot": {"beach": 1.0, "mouth": 0.5, "pier": 0.0, "harbour_wall": -0.5}},
    "paling":   {"wave": (0.0, 0.7), "light": "low", "current": 0.5,
                 "spot": {"mouth": 1.5, "pier": 0.5, "harbour_wall": 0.5, "beach": -0.5}},
    "makreel":  {"wave": (0.0, 0.8), "light": "day", "current": 1.0,
                 "spot": {"harbour_wall": 1.5, "pier": 1.0, "mouth": 0.0, "beach": -1.0}},
    "wijting":  {"wave": (0.4, 1.5), "light": "low", "current": 1.0,
                 "spot": {"pier": 0.5, "beach": 0.5, "harbour_wall": 0.5, "mouth": 0.0}},
    "gul":      {"wave": (0.6, 1.8), "light": "low", "current": 1.5,
                 "spot": {"harbour_wall": 1.0, "pier": 0.5, "beach": 0.5, "mouth": 0.0}},
    "schar":    {"wave": (0.2, 1.0), "light": None, "current": 0.5,
                 "spot": {"beach": 1.0, "pier": 0.0, "harbour_wall": 0.0, "mouth": 0.0}},
}


def species_fit(win, spot, species):
    """0..10 (steps of 0.5) per species: how well this window at this spot suits it."""
    out = {}
    for sp in species:
        pref = SPECIES_PREF.get(sp)
        if not pref:
            continue
        v = 5.0
        wave = win.get("wave")
        if wave is not None:
            lo, hi = pref["wave"]
            if lo <= wave <= hi:  v += 2.0
            else:                 v -= min(3.0, 2.5 * (lo - wave if wave < lo else wave - hi))
        dark, cloud = win.get("dark"), win.get("cloud")
        if dark is not None and pref["light"]:
            low = dark > 0.1 or (cloud or 0) >= 70
            if pref["light"] == "low":  v += 1.5 if dark > 0.1 else 0.5 if low else -1.0
            else:                       v += 1.0 if dark < 0.1 else -2.0
        if win.get("tide_v") is not None:
            v += pref["current"] * (max(0.0, min(1.0, win["tide_v"])) - 0.4)
        v += pref["spot"].get(spot.get("type", "beach"), 0)
        if spot.get("mouth"):
            v += pref["spot"].get("mouth", 0)
        wind = win.get("wind")
        if wind is not None and wind >= 30:
            v -= 1.0 if spot.get("type") == "beach" else 2.0   # exposed walls are worse in a blow
        out[sp] = half(max(0.0, min(10.0, v)))
    return out


def picks(results):
    """'Best for ...' choices, so readers can choose even when general scores tie.
    Returns a list of (kind, species or None, result, value)."""
    ok = [r for r in results if r.get("best")]
    out = []
    seen = []
    for r in ok:
        for sp in r["species"]:
            if sp not in seen:
                seen.append(sp)
    for sp in seen:
        cands = [r for r in ok if sp in r.get("fit", {})]
        if cands:
            top = max(cands, key=lambda r: (r["fit"][sp], r["best"]["score"]))
            if top["fit"][sp] >= 5:          # a poor chance is not a recommendation
                out.append(("species", sp, top, top["fit"][sp]))
    out.sort(key=lambda p: -p[3])
    out = out[:4]
    if ok:
        var = max(ok, key=lambda r: (len(r["species"]), r["best"]["score"]))
        if len({len(r["species"]) for r in ok}) > 1:
            out.append(("variety", None, var, len(var["species"])))
        windy = max((r["best"]["wind"] or 0) for r in ok)
        if windy >= 25:
            shel = [r for r in ok if r["spot"].get("mouth") or r["spot"].get("type") == "pier"]
            if shel:
                out.append(("shelter", None, max(shel, key=lambda r: r["best"]["score"]), round(windy)))
        night = [r for r in ok if r.get("night")]
        if night:
            n = max(night, key=lambda r: r["night"]["score"])
            if n["night"]["score"] > n["best"]["score"]:
                out.append(("night", None, n, n["night"]["score"]))
    return out


# ---------- gear tips ----------

def gear_tips(win, rows, species, night=None, spot=None):
    """Rule-of-thumb tackle tips from waves, tide and light. Returns
    (target, text key, params); target is "all" or a species key."""
    tips = []
    wave, tv = win["wave"], win.get("tide_v")
    if wave is not None:
        w = f"{wave:.1f}"
        if wave >= 1.3 or (tv is not None and tv > 0.83):
            tips.append(("all", "t_lead_heavy", {"wave": w}))
        elif wave < 0.5 and (tv is None or tv <= 0.55):
            tips.append(("all", "t_lead_light", {"wave": w}))
        else:
            tips.append(("all", "t_lead_mid", {"wave": w}))
    # Water clarity is not measured; estimate it from the waves of the last 24 hours.
    prev = [r["wave_height"] for r in rows
            if win["start"] - timedelta(hours=24) <= r["time"] <= win["start"]
            and r.get("wave_height") is not None]
    clarity = None
    if prev:
        clarity = "clear" if max(prev) < 0.6 else "murky" if max(prev) > 1.0 else None
    if "zeebaars" in species:
        if (spot or {}).get("mouth"):
            tips.append(("zeebaars", "t_mouth", {}))
        if wave is not None:
            if wave < 0.4:   tips.append(("zeebaars", "t_bass_calm", {}))
            elif wave < 1.4: tips.append(("zeebaars", "t_bass_surf", {}))
            else:            tips.append(("zeebaars", "t_bass_rough", {}))
        if clarity:
            tips.append(("zeebaars", "t_clear" if clarity == "clear" else "t_murky", {}))
        # Spinning: lure type and weight follow wind, waves and light.
        wind, wdir = win.get("wind"), win.get("wdir")
        onshore = wdir is not None and abs((wdir - (spot or {}).get("sea_bearing", SEA_BEARING) + 180) % 360 - 180) < 60
        tips.append(("zeebaars", "t_spin_rod", {}))
        if wave is not None and wind is not None:
            low_light = (win.get("dark") or 0) > 0.1 or (win.get("cloud") or 0) >= 70
            if wind >= 25 and onshore:  tips.append(("zeebaars", "t_lure_spoon", {"w": round(wind)}))
            elif wave >= 1.4:           tips.append(("zeebaars", "t_lure_deep", {}))
            elif wave < 0.4 and wind < 15:
                tips.append(("zeebaars", "t_lure_surface" if low_light else "t_lure_minnow", {}))
            elif wind >= 18:            tips.append(("zeebaars", "t_lure_jig", {"w": round(wind)}))
            else:                       tips.append(("zeebaars", "t_lure_shad", {}))
    if "tong" in species:
        if wave is not None:
            tips.append(("tong", "t_sole_good" if wave < 0.8 else "t_sole_poor", {}))
        if win.get("daylight") and night:
            tips.append(("tong", "t_sole_night", {"s": night["start"].strftime("%H:%M"),
                                                 "e": night["end"].strftime("%H:%M")}))
    return tips


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
