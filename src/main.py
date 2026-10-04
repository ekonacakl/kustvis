"""Daily run: fetch data, analyse, build the web page, send the Telegram bulletin.

Usage:
  python src/main.py            # live data, sends Telegram if secrets are set
  python src/main.py --demo     # synthetic data, no network needed
  python src/main.py --no-send  # build page only
Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SITE_URL (optional)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("Europe/Brussels")

sys.path.insert(0, str(Path(__file__).parent))
import analyse as A
import fetch as F
import render as R
from i18n import LANGS

ROOT = Path(__file__).resolve().parent.parent
BAIT_STOP_MIN = 20       # extra time for picking up fresh bait
ARRIVE_BEFORE_WINDOW = 15  # minutes to set up before the window starts


def load(name):
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def build(region, cfg, demo=False, today=None):
    """Build the report for one region (be = Belgian coast, nld = Dutch coast)."""
    rules, shops = load("rules.json"), load("bait_shops.json")["shops"]
    shops = [s for s in shops if s.get("region", "be") == region["id"]]
    today = today or datetime.now(LOCAL).date()
    target = today + timedelta(days=1)
    results, skipped = [], []
    for spot in cfg["spots"]:
        if spot.get("region", "be") != region["id"]:
            continue
        spot = {"sea_bearing": region["sea_bearing"], "tide_scale": region["tide_scale"], **spot}
        try:
            rows = F.demo_spot(spot) if demo else F.fetch_spot(spot)
        except Exception as e:  # one spot failing must not stop the bulletin
            print(f"SKIP {spot['id']}: no data ({e})", flush=True)
            skipped.append(spot)
            continue
        ext = A.tide_extremes(rows)
        best = A.best_window(rows, ext, target, spot)
        day_w, night_w = A.split_windows(rows, ext, target, spot)
        species = A.species_for(spot, target)
        outlook = [(target + timedelta(days=i), A.best_window(rows, ext, target + timedelta(days=i), spot))
                   for i in range(4)]
        res = {"spot": spot, "rows": rows, "extremes": ext, "best": best,
               "night": night_w if night_w is not best else None, "outlook": outlook,
               "species": species, "legal": A.legal_notes(species, rules, target)}
        if best:
            res["fit"] = A.species_fit(best, spot, species)
            res["tips"] = A.gear_tips(best, rows, species, res["night"], spot)
            arrive = best["start"] - timedelta(minutes=ARRIVE_BEFORE_WINDOW)
            res["departures"] = A.departures(region["origins"], spot, arrive, BAIT_STOP_MIN)
            res["shops"] = A.shops_open(shops, arrive - timedelta(minutes=45))
        results.append(res)
    if not results:
        raise RuntimeError(f"no data for any spot in region {region['id']}")
    # Ties in the general score are broken by the best species fit at the spot.
    results.sort(key=lambda r: (r["best"]["score"], max(r.get("fit", {}).values(), default=0)) if r["best"] else (-1, 0),
                 reverse=True)
    return {"generated": datetime.now(LOCAL).replace(tzinfo=None), "today": today, "target": target,
            "results": results, "rules": rules, "demo": demo, "skipped": skipped,
            "region": region, "regions": cfg["regions"], "picks": A.picks(results)}


def chat_ids(region):
    """One Telegram channel per region and language.
    Belgium:     TELEGRAM_CHAT_ID_NL, _EN, _FR, _TR
    Netherlands: TELEGRAM_CHAT_ID_NLD_NL, _NLD_EN, _NLD_FR, _NLD_TR
    Channels that are not configured are skipped."""
    mid = "" if region["id"] == "be" else region["id"].upper() + "_"
    ids = {L: os.environ.get(f"TELEGRAM_CHAT_ID_{mid}{L.upper()}") for L in LANGS}
    if region["id"] == "be":
        ids["nl"] = ids["nl"] or os.environ.get("TELEGRAM_CHAT_ID")
    return {L: c for L, c in ids.items() if c}


def send_telegram(chat, text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=30) as r:
        return r.status


def main():
    demo = "--demo" in sys.argv
    send = "--no-send" not in sys.argv and not demo
    cfg = load("spots.json")
    site_url = os.environ.get("SITE_URL", "")
    out = ROOT / "site"
    built = 0
    for region in cfg["regions"]:
        try:
            report = build(region, cfg, demo=demo)
        except Exception as e:  # one region failing must not stop the other
            print(f"REGION {region['id']} FAILED: {e}", flush=True)
            continue
        built += 1
        for L in LANGS:
            d = out / region["path"] / ("" if L == "nl" else L)
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(R.page(report, L), encoding="utf-8")
            (d / "bulletin.txt").write_text(R.telegram(report, L, site_url), encoding="utf-8")
        print(R.telegram(report, "nl", site_url), "\n", flush=True)
        if not send:
            continue
        if not os.environ.get("TELEGRAM_BOT_TOKEN"):
            print("TELEGRAM_BOT_TOKEN not set; skipping send.")
            continue
        for L, chat in chat_ids(region).items():
            try:
                print(f"Telegram {region['id']}/{L}:", send_telegram(chat, R.telegram(report, L, site_url)))
            except Exception as e:  # one failing channel must not stop the others
                print(f"Telegram {region['id']}/{L} failed: {e}")
    if not built:
        raise SystemExit("No data for any region: Open-Meteo unreachable. Nothing sent.")


if __name__ == "__main__":
    main()
