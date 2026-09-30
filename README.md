# Kustvis – daily shore-fishing bulletin for the Belgian coast

Every evening this project fetches tomorrow's tide, waves, wind and pressure for six
spots (Nieuwpoort, Raversijde, Oostende ×2, Blankenberge, Zeebrugge), scores the best
fishing window around high water, works out when to leave from Brussels / Leuven /
Antwerpen / Gent / Brugge, adds the 2026 legal rules, then:

- posts a short bulletin to a Telegram channel per language, and
- publishes a web page (GitHub Pages) with tide charts, all spots and the rules.

Languages: Dutch/Flemish (default), English, French and Turkish. The web page has a
language switcher (`/`, `/en/`, `/fr/`, `/tr/`). Telegram channels can't show different
languages to different readers, so there is one channel per language; set up only the
ones you want and the others are skipped.

Cost: €0. GitHub Actions and GitHub Pages are free for public repos; Open-Meteo needs no key.

## Project layout

```
config/spots.json       spots, coordinates, species per season, tips, departure cities
config/rules.json       2026 rules (bass 42 cm, 3/day, no retention Feb–Mar, RecFishing)
config/bait_shops.json  fill in by hand: fresh-bait shops and opening hours
src/fetch.py            Open-Meteo weather + marine data (and --demo synthetic data)
src/analyse.py          tides, score, species, legal notes, departure times, open shops
src/render.py           Telegram message + web page
src/main.py             runs everything
.github/workflows/daily.yml   runs every evening, deploys the page
```

No external Python packages are needed.

## Try it locally

```
python src/main.py --demo      # synthetic data, opens nothing, writes site/index.html
python src/main.py --no-send   # real data, builds the page, doesn't post to Telegram
```

## Setup (about 20 minutes)

1. **Telegram bot.** In Telegram, open @BotFather, send `/newbot`, choose a name.
   Copy the token it gives you.
2. **Telegram channels.** Create one channel per language you want (e.g. "Kustvis België",
   "Kustvis Belgium EN", "Kustvis Belgique FR", "Kustvis Belçika TR"), and add the same bot
   to each as an administrator with permission to post. The chat ID for a public channel is
   `@yourchannelname`. For a private channel, post one message, forward it to
   @userinfobot or open `https://api.telegram.org/bot<TOKEN>/getUpdates` to read the `-100…` ID.
3. **GitHub repo.** Create a new public repository, upload this folder's contents
   (keep the `.github` folder).
4. **Secrets.** Repo → Settings → Secrets and variables → Actions:
   - Secrets: `TELEGRAM_BOT_TOKEN`, and one chat ID per channel:
     `TELEGRAM_CHAT_ID_NL`, `TELEGRAM_CHAT_ID_EN`, `TELEGRAM_CHAT_ID_FR`, `TELEGRAM_CHAT_ID_TR`
   - Variables: `SITE_URL` = `https://<your-username>.github.io/<repo-name>/`
5. **Pages.** Repo → Settings → Pages → Source: **GitHub Actions**.
6. **First run.** Repo → Actions → *Daily bulletin* → **Run workflow**. Check the
   channel and the page. After that it runs by itself every evening.

## What is honest to tell users

- Tides come from a model (Open-Meteo, ~8 km grid). Good on an open coast like ours,
  but not a nautical tide table. v2 should switch to the official Vlaamse Hydrografie
  predictions or Meetnet Vlaamse Banken (free account + API).
- The score is a transparent heuristic (waves, wind, tidal range, pressure trend, light).
  Every factor is shown on the page under "Waarom deze score". Tune the weights in
  `analyse.py → score_window` as you learn what works.
- Drive times are estimates without traffic.
- Rules must be re-checked each January; spot coordinates should be verified on site.

## Roadmap

- v1.1: fill `bait_shops.json`; verify spot coordinates; add bass protection zones.
- v2: official tide data (Meetnet Vlaamse Banken API); real drive times with traffic
  (OpenRouteService, free key); interactive bot commands (`/morgen`, `/oostende`)
  via a Cloudflare Worker webhook, where each user picks their own language
  with `/taal` and gets private messages instead of a channel.
- v3: user catch reports to calibrate the score per spot.
