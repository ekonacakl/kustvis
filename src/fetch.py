"""Fetch weather and marine forecasts from Open-Meteo (free, no API key).

Returns one dict per spot with hourly series in local time (Europe/Brussels).
Use demo=True to generate realistic synthetic data for offline testing.
"""
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

TZ = "Europe/Brussels"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

WEATHER_VARS = "temperature_2m,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,cloud_cover,is_day"
MARINE_VARS = "wave_height,wave_period,sea_level_height_msl,sea_surface_temperature,ocean_current_velocity"


def _get(url, params):
    q = urllib.parse.urlencode(params)
    with urllib.request.urlopen(f"{url}?{q}", timeout=30) as r:
        return json.load(r)


def fetch_spot(spot, days=5):
    common = {"latitude": spot["lat"], "longitude": spot["lon"],
              "timezone": TZ, "forecast_days": days, "past_days": 1}
    w = _get(WEATHER_URL, {**common, "hourly": WEATHER_VARS})
    m = _get(MARINE_URL, {**common, "hourly": MARINE_VARS})
    return merge(w["hourly"], m["hourly"])


def merge(wh, mh):
    """Join weather and marine hourly arrays on timestamp."""
    idx = {t: i for i, t in enumerate(mh["time"])}
    rows = []
    for i, t in enumerate(wh["time"]):
        row = {"time": datetime.fromisoformat(t)}
        for k, v in wh.items():
            if k != "time":
                row[k] = v[i]
        j = idx.get(t)
        for k, v in mh.items():
            if k != "time":
                row[k] = v[j] if j is not None else None
        rows.append(row)
    return rows


def demo_spot(spot, days=5, start=None):
    """Synthetic but plausible North Sea data: semi-diurnal tide, spring/neap cycle,
    a passing low-pressure system, variable wind and waves."""
    start = (start or datetime.now()).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
    phase = (spot["lon"] - 2.7) * 0.6  # tide arrives slightly later going east
    rows = []
    for h in range((days + 1) * 24):
        t = start + timedelta(hours=h)
        hrs = h + phase
        spring = 1.9 + 0.35 * math.cos(2 * math.pi * hrs / (14.77 * 24))
        sea = spring * math.cos(2 * math.pi * hrs / 12.42)
        pressure = 1014 - 9 * math.exp(-((h - 50) / 14) ** 2) + 2 * math.sin(h / 30)
        wind = 14 + 10 * math.exp(-((h - 52) / 10) ** 2) + 4 * math.sin(h / 5)
        rows.append({
            "time": t,
            "temperature_2m": 15 + 4 * math.sin(2 * math.pi * (t.hour - 9) / 24),
            "pressure_msl": round(pressure, 1),
            "wind_speed_10m": round(wind, 1),
            "wind_direction_10m": 225 + 40 * math.sin(h / 20),
            "wind_gusts_10m": round(wind * 1.5, 1),
            "precipitation": 0.4 if 44 < h < 56 else 0.0,
            "cloud_cover": 60,
            "is_day": 1 if 7 <= t.hour < 19 else 0,
            "wave_height": round(0.6 + wind / 30, 2),
            "wave_period": 5.5,
            "sea_level_height_msl": round(sea, 2),
            "sea_surface_temperature": 16.5,
            "ocean_current_velocity": round(abs(math.sin(2 * math.pi * hrs / 12.42)) * 2.5 * spring / 1.9, 2),
        })
    return rows
