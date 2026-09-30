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


def build(demo=False, today=None):
    spots_cfg, rules, shops = load("spots.json"), load("rules.json"), load("bait_shops.json")["shops"]
    today = today or datetime.now(LOCAL).date()
    target = today + timedelta(days=1)
    results = []
    for spot in spots_cfg["spots"]:
        rows = F.demo_spot(spot) if demo else F.fetch_spot(spot)
        ext = A.tide_extremes(rows)
        best = A.best_window(rows, ext, target)
        day_w, night_w = A.split_windows(rows, ext, target)
        species = A.species_for(spot, target)
        outlook = [(target + timedelta(days=i), A.best_window(rows, ext, target + timedelta(days=i)))
                   for i in range(4)]
        res = {"spot": spot, "rows": rows, "extremes": ext, "best": best, "night": night_w if night_w is not best else None, "outlook": outlook,
               "species": species, "legal": A.legal_notes(species, rules, target)}
        if best:
            arrive = best["start"] - timedelta(minutes=ARRIVE_BEFORE_WINDOW)
            res["departures"] = A.departures(spots_cfg["origins"], spot, arrive, BAIT_STOP_MIN)
            res["shops"] = A.shops_open(shops, arrive - timedelta(minutes=45))
        results.append(res)
    results.sort(key=lambda r: r["best"]["score"] if r["best"] else -1, reverse=True)
    return {"generated": datetime.now(LOCAL).replace(tzinfo=None), "today": today, "target": target, "results": results,
            "rules": rules, "demo": demo}


def chat_ids():
    """One Telegram channel per language: TELEGRAM_CHAT_ID_NL, _EN, _FR, _TR.
    TELEGRAM_CHAT_ID (no suffix) is treated as the Dutch channel."""
    ids = {L: os.environ.get(f"TELEGRAM_CHAT_ID_{L.upper()}") for L in LANGS}
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
    report = build(demo=demo)
    site_url = os.environ.get("SITE_URL", "")
    out = ROOT / "site"
    for L in LANGS:
        d = out if L == "nl" else out / L
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(R.page(report, L), encoding="utf-8")
        (d / "bulletin.txt").write_text(R.telegram(report, L, site_url), encoding="utf-8")
    print(R.telegram(report, "nl", site_url))
    if "--no-send" in sys.argv or demo:
        return
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("TELEGRAM_BOT_TOKEN not set; skipping send.")
        return
    for L, chat in chat_ids().items():
        try:
            print(f"Telegram {L}:", send_telegram(chat, R.telegram(report, L, site_url)))
        except Exception as e:  # one failing channel must not stop the others
            print(f"Telegram {L} failed: {e}")


if __name__ == "__main__":
    main()
