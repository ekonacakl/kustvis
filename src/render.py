"""Render the Telegram bulletin (HTML parse mode) and the static web page,
in any language from i18n.LANGS."""
from html import escape


def E(v):
    return escape(str(v), quote=False)


def A(v):
    return escape(str(v), quote=True)

from i18n import LANGS, LANG_NAMES, T, sp, text

BAIT_MIN = 20


def rkey(rep, key, L):
    """Region-specific text if it exists (e.g. general_nld), else the default."""
    x = T[L]
    return x.get(f"{key}_{rep['region']['id']}", x[key])


def root_prefix(rep, L):
    depth = (1 if rep["region"]["path"] else 0) + (0 if L == "nl" else 1)
    return "../" * depth or "./"


def href(root, region, L):
    return (root + region["path"] + ("" if L == "nl" else f"{L}/")) or "./"


def hm(t):
    return t.strftime("%H:%M")


def dag(d, L):
    x = T[L]
    return x["date"].format(day=x["days"][d.weekday()], d=d.day, m=x["months"][d.month - 1])


def part(t, L):
    """Day-part word for a time, so 04:50 reads as 'night', not ambiguous."""
    h = t.hour
    i = 0 if h < 6 else 1 if h < 12 else 2 if h < 18 else 3 if h < 23 else 0
    return T[L]["part"][i]


def verdict(score, unsafe, L):
    x = T[L]
    if unsafe:       return x["v_unsafe"]
    if score >= 7.5: return x["v_very_good"]
    if score >= 6:   return x["v_good"]
    if score >= 4:   return x["v_fair"]
    return x["v_poor"]


def note(n, L):
    key, params = n
    p = dict(params)
    if "sp" in p:
        p["sp"] = sp(p["sp"], L)
    return T[L][key].format(**p)


def species_list(r, L):
    return ", ".join(sp(s, L) for s in r["species"])


def short_name(spot, L):
    return text(spot["name"], L).split(" –")[0]


def compass(deg, L):
    return "" if deg is None else T[L]["compass"][int((deg + 22.5) // 45) % 8]


def num(v, fmt="{:.1f}"):
    return "–" if v is None else fmt.format(v)


def sc(v):
    """6.0 -> '6', 6.5 -> '6.5'"""
    return f"{v:g}"


def factor(k, p, L):
    x, p = T[L], dict(p)
    if "rel" in p:
        p["rel"] = f", {x['rel'][p['rel']]}" if p["rel"] else ""
    return x[k].format(**p)


def tip(tp, L):
    return T[L][tp[1]].format(**tp[2])


def maps_url(spot):
    return f"https://www.google.com/maps/dir/?api=1&destination={spot['lat']},{spot['lon']}"


def missing_lines(rep, L):
    """Footnotes: which inputs were missing, and which spots returned no data."""
    x, out = T[L], []
    miss = []
    for r in rep["results"]:
        for w in (r.get("best"), r.get("night")):
            for k in (w or {}).get("missing", []):
                if x["var"][k] not in miss:
                    miss.append(x["var"][k])
        if not r.get("best") and x["var"]["sea_level_height_msl"] not in miss:
            miss.append(x["var"]["sea_level_height_msl"])
    if miss:
        out.append(x["missing_note"].format(list=", ".join(miss)))
    if rep.get("skipped"):
        out.append(x["skipped_note"].format(list="; ".join(text(s["name"], L) for s in rep["skipped"])))
    return out


def pick_lines(rep, L):
    """'Best for ...' lines, shared by the bulletin and the page."""
    x, out = T[L], []
    for kind, spc, r, v in rep.get("picks", []):
        spot = short_name(r["spot"], L) if kind != "species" else text(r["spot"]["name"], L)
        if kind == "species":
            out.append(("🎯", x["p_species"].format(sp=sp(spc, L).capitalize(), spot=spot, v=sc(v))))
        elif kind == "variety":
            out.append(("🐟", x["p_variety"].format(spot=text(r["spot"]["name"], L), v=v, list=species_list(r, L))))
        elif kind == "shelter":
            out.append(("🛡", x["p_shelter"].format(spot=text(r["spot"]["name"], L), v=v)))
        elif kind == "night":
            n = r["night"]
            out.append(("🌙", x["p_night"].format(spot=text(r["spot"]["name"], L), s=hm(n["start"]), e=hm(n["end"]), v=sc(v))))
    return out


def fit_list(r, L):
    return " · ".join(f"{sp(k, L)} {sc(v)}" for k, v in sorted(r.get("fit", {}).items(), key=lambda kv: -kv[1]))


# ---------------- Telegram ----------------

def telegram(rep, L="nl", site_url=""):
    x, t = T[L], rep["target"]
    lines = [x["tg_title"].format(date=dag(t, L), region=text(rep["region"]["name"], L))]
    if rep["demo"]:
        lines.append(f"<i>({x['test_data']})</i>")
    pl = pick_lines(rep, L)
    if pl:
        lines.append("")
        lines.append(f"<b>{x['picks']}</b>")
        lines.extend(f"{icon} {E(t_)}" for icon, t_ in pl)
    for i, r in enumerate([r for r in rep["results"] if r["best"]][:3]):
        b, s = r["best"], r["spot"]
        lines.append("")
        lines.append(f"<b>{E(text(s['name'], L))}</b>: {sc(b['score'])}/10 · {verdict(b['score'], b['unsafe'], L)}")
        lines.append(x["tg_window"].format(hw=hm(b["hw"]["time"]), s=hm(b["start"]), e=hm(b["end"]),
                                           part=part(b["start"], L)))
        lines.append(x["tg_cond"].format(w=num(b["wind"], "{:.0f}"), dir=compass(b["wdir"], L), wave=num(b["wave"]),
                                         c=num(b["cloud"], "{:.0f}"), dp=f"{b['dp']:+}"))
        n = r.get("night")
        if n:
            lines.append(x["tg_night"].format(hw=hm(n["hw"]["time"]), s=hm(n["start"]), e=hm(n["end"]),
                                              part=part(n["start"], L), sc=sc(n["score"])))
        if r.get("fit"):
            lines.append(f"🐟 {fit_list(r, L)}")
        elif r["species"]:
            lines.append(f"🐟 {species_list(r, L)}")
        if i == 0:
            for tp in r.get("tips", []):
                if tp[1] != "t_sole_night":
                    who = "🎒" if tp[0] == "all" else f"🎒 {sp(tp[0], L).capitalize()}:"
                    lines.append(f"{who} {E(tip(tp, L))}")
        lines.append(f'<a href="{maps_url(s)}">{x["tg_route"]}</a>')
        if i == 0 and r.get("departures"):
            dep = " · ".join(f"{text(d['from'], L)} {hm(d['leave'])}" for d in r["departures"])
            lines.append(x["tg_leave"].format(n=BAIT_MIN, list=dep))
            if r.get("shops"):
                lines.append(x["tg_shops"].format(list=", ".join(E(s_["name"]) for s_ in r["shops"])))
    if rep["today"].weekday() == 3:  # Thursday: weekend outlook
        lines.append("")
        lines.append(x["tg_weekend"])
        for r in rep["results"][:3]:
            we = [(d, b) for d, b in r["outlook"] if d.weekday() in (5, 6) and b]
            if we:
                parts = [f"{x['days_short'][d.weekday()]} {sc(b['score'])}" for d, b in we]
                lines.append(f"· {E(short_name(r['spot'], L))}: " + ", ".join(parts))
    closed = []
    for r in rep["results"]:
        for n in r["legal"]:
            if n[0] == "l_closed" and note(n, L) not in closed:
                closed.append(note(n, L))
    lines.append("")
    lines.extend(closed)
    lines.append(x["tg_recfishing"])
    if site_url:
        url = href(site_url.rstrip("/") + "/", rep["region"], L)
        lines.append(f'<a href="{url}">{x["tg_link"]}</a>')
    lines.append(f"<i>{x['tg_disclaimer']}</i>")
    for m in missing_lines(rep, L):
        lines.append(f"<i>ⓘ {E(m)}</i>")
    return "\n".join(lines)


# ---------------- Web page ----------------

def tide_svg(r, day, L, w=720, h=150, big=False):
    x = T[L]
    rows = [p for p in r["rows"] if p["time"].date() == day and p["sea_level_height_msl"] is not None]
    if len(rows) < 2:
        return ""
    lo, hi = -2.8, 2.8
    pad = 18 if big else 6
    X = lambda i: pad + i * (w - 2 * pad) / (len(rows) - 1)
    Y = lambda v: pad + (hi - v) * (h - 2 * pad) / (hi - lo)
    pts = " ".join(f"{X(i):.1f},{Y(p['sea_level_height_msl']):.1f}" for i, p in enumerate(rows))
    area = f"{X(0):.1f},{h} {pts} {X(len(rows) - 1):.1f},{h}"
    t0 = rows[0]["time"]
    tx = lambda t: pad + (t - t0).total_seconds() / 3600 * (w - 2 * pad) / (len(rows) - 1)
    parts = [f'<svg viewBox="0 0 {w} {h}" class="tide" role="img" aria-label="{A(x["tide_aria"].format(date=dag(day, L)))}">']
    b = r["best"] if r["best"] and r["best"]["hw"]["time"].date() == day else None
    if b:
        x1, x2 = max(tx(b["start"]), 0), min(tx(b["end"]), w)
        parts.append(f'<rect x="{x1:.1f}" y="0" width="{x2 - x1:.1f}" height="{h}" class="win"/>')
    parts.append(f'<polygon points="{area}" class="water"/>')
    parts.append(f'<polyline points="{pts}" class="line"/>')
    if big:
        for hr in (0, 6, 12, 18):
            xx = pad + hr * (w - 2 * pad) / (len(rows) - 1)
            parts.append(f'<text x="{xx:.0f}" y="{h - 4}" class="ax">{hr:02d}:00</text>')
        for e in r["extremes"]:
            if e["time"].date() == day:
                xx, yy = tx(e["time"]), Y(e["height"])
                dy = -8 if e["kind"] == "HW" else 18
                anchor = "start" if xx < 40 else "end" if xx > w - 40 else "middle"
                lab = x["hw"] if e["kind"] == "HW" else x["lw"]
                parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="3.5" class="pt"/>')
                parts.append(f'<text x="{xx:.1f}" y="{yy + dy:.1f}" class="lbl" text-anchor="{anchor}">{lab} {hm(e["time"])}</text>')
    parts.append("</svg>")
    return "".join(parts)


def score_bar(score, unsafe):
    cls = "bad" if unsafe or score < 4 else "mid" if score < 6 else "good"
    return f'<span class="score {cls}"><b>{score:g}</b><span>/10</span></span>'


def lang_switch(rep, L, root):
    items = []
    for code in LANGS:
        cur = ' aria-current="page"' if code == L else ""
        items.append(f'<a href="{href(root, rep["region"], code)}" lang="{code}" hreflang="{code}"{cur} title="{LANG_NAMES[code]}">{code.upper()}</a>')
    return f'<nav class="langs" aria-label="Language">{"".join(items)}</nav>'


def region_switch(rep, L, root):
    items = []
    for r in rep["regions"]:
        cur = ' aria-current="page"' if r["id"] == rep["region"]["id"] else ""
        items.append(f'<a href="{href(root, r, L)}"{cur}>{E(text(r["name"], L))}</a>')
    return f'<nav class="regions" aria-label="{A(T[L]["region_label"])}">{"".join(items)}</nav>'


def page(rep, L="nl"):
    x, t = T[L], rep["target"]
    prefix = root_prefix(rep, L)
    region = rep["region"]
    res = [r for r in rep["results"] if r["best"]]
    top = res[0] if res else None
    gen = rep["generated"]
    upd = x["updated"].format(date=dag(gen.date(), L), time=hm(gen)) + (f" · {x['test_data']}" if rep["demo"] else "")
    title = f"Kustvis {text(region['name'], L)} – {dag(t, L)}"
    out = [f"""<!doctype html><html lang="{L}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title>
{''.join(f'<link rel="alternate" hreflang="{c}" href="{href(prefix, region, c)}">' for c in LANGS)}
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;700&family=Barlow:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body><main>
<header class="top"><span class="brand">Kustvis</span>{lang_switch(rep, L, prefix)}</header>
{region_switch(rep, L, prefix)}
<p class="upd">{E(upd)}</p>"""]
    if top:
        b, s = top["best"], top["spot"]
        why = x["why"].format(verdict=verdict(b["score"], b["unsafe"], L), hw=hm(b["hw"]["time"]),
                              w=num(b["wind"], "{:.0f}"), dir=compass(b["wdir"], L), wave=num(b["wave"]))
        out.append(f"""<section class="hero">
<p class="when">{E(x['tomorrow'].format(date=dag(t, L)))}</p>
<h1>{E(text(s['name'], L))}<br><span class="win-t">{hm(b['start'])}–{hm(b['end'])}</span></h1>
<p class="why">{E(why)} {score_bar(b['score'], b['unsafe'])}</p>
{tide_svg(top, t, L, big=True)}
<p class="legend"><span class="sw"></span>{E(x['legend'])}</p>""")
        if top.get("departures"):
            out.append(f'<table class="dep"><caption>{E(x["dep_caption"].format(n=BAIT_MIN))}</caption>'
                       f'<thead><tr><th>{x["th_from"]}</th><th>{x["th_dist"]}</th><th>{x["th_time"]}</th><th>{x["th_leave"]}</th></tr></thead><tbody>')
            for d in top["departures"]:
                out.append(f"<tr><td>{E(text(d['from'], L))}</td><td>{d['km']} {x['km']}</td><td>{d['minutes']} {x['min']}</td><td><b>{hm(d['leave'])}</b></td></tr>")
            out.append(f'</tbody></table><p class="note">{E(x["dep_note"])}</p>')
        out.append("</section>")

    targets = [k for k in ("zeebaars", "tong") if any(k in r["species"] for r in res)]
    chips = "".join(f'<button type="button" data-t="{k}" aria-pressed="{"true" if k == "all" else "false"}">{E(lab)}</button>'
                    for k, lab in [("all", x["all"])] + [(k, sp(k, L).capitalize()) for k in targets])
    pl = pick_lines(rep, L)
    if pl:
        out.append(f'<section class="picks"><h2>{E(x["picks"])}</h2><ul>'
                   + "".join(f"<li><span aria-hidden=\"true\">{icon}</span> {E(t_)}</li>" for icon, t_ in pl)
                   + f'</ul><p class="note">{E(x["fit_note"])}</p></section>')
    out.append(f'<section><h2>{E(x["all_spots"])}</h2>'
               + (f'<div class="target" role="group" aria-label="{A(x["target"])}"><span>{E(x["target"])}</span>{chips}</div>' if targets else "")
               + '<ol class="spots">')
    for r in res:
        b, s = r["best"], r["spot"]
        factors = "".join(f"<li><span>{E(factor(k, p, L))}</span><span>{pt:+.1f}</span></li>" for k, p, pt in b["factors"])
        outlook = "".join(
            f'<li><span>{x["days_short"][d.weekday()]}</span>{score_bar(o["score"], o["unsafe"]) if o else "–"}</li>'
            for d, o in r["outlook"])
        legal = "".join(f"<li>{E(note(n, L))}</li>" for n in r["legal"])
        tips = "".join(f'<li data-sp="{tp[0]}">{"" if tp[0] == "all" else "<b>" + E(sp(tp[0], L).capitalize()) + ":</b> "}{E(tip(tp, L))}</li>'
                       for tp in r.get("tips", []))
        meta = x["meta"].format(hw=hm(b["hw"]["time"]), s=hm(b["start"]), e=hm(b["end"]), r=b["range"] or "?")
        fits = " ".join(f'data-fit-{k}="{v}"' for k, v in r.get("fit", {}).items())
        fitchips = "".join(f'<span class="fit" data-sp="{k}">{E(sp(k, L))} <b>{sc(v)}</b></span>'
                           for k, v in sorted(r.get("fit", {}).items(), key=lambda kv: -kv[1]))
        out.append(f"""<li class="spot" {fits}><div class="head"><h3>{E(text(s['name'], L))}</h3>{score_bar(b['score'], b['unsafe'])}</div>
<p class="meta">{E(meta)}</p>
{f'<p class="meta">🌙 {E(x["night_meta"].format(hw=hm(r["night"]["hw"]["time"]), s=hm(r["night"]["start"]), e=hm(r["night"]["end"]), sc=sc(r["night"]["score"])))}</p>' if r.get("night") else ''}
{tide_svg(r, t, L, h=70)}
<p class="fits"><b>{x['fit'] if fitchips else x['fish']}:</b> {fitchips or E(species_list(r, L) or x['no_fish'])}</p>
<p class="tip">{E(text(s['tips'], L))}</p>
{f'<div class="gear"><h4>{E(x["gear"])}</h4><ul>{tips}</ul></div>' if tips else ''}
<p><a class="btn" href="{maps_url(s)}" target="_blank" rel="noopener">{E(x['route'])}</a></p>
<details><summary>{E(x['why_score'])}</summary><ul class="factors">{factors}</ul></details>
{f'<ul class="legal">{legal}</ul>' if legal else ''}
<ul class="outlook" aria-label="{A(x['coming_days'])}">{outlook}</ul></li>""")
    out.append("</ol></section>")

    rules = rep["rules"]
    zb = rules["species"]["zeebaars"]
    gen_rules = "".join(f"<li>{E(g)}</li>" for g in rkey(rep, "general", L))
    months = "".join(f'<span class="{"x" if i + 1 in zb["no_retention_months"] else ""}">{m}</span>'
                     for i, m in enumerate(x["months"]))
    link = f'<a href="{region["rules_url"]}">{region["rules_site"]}</a>'
    out.append(f"""<section class="rules"><h2>{E(x['rules_title'].format(y=rules['year']))}</h2>
<div class="rule-bass"><h3>{E(sp('zeebaars', L).capitalize())}</h3>
<p>{x['bass_line'].format(min=zb['min_size_cm'], bag=zb['bag_limit_per_day'])}</p>
<div class="months">{months}</div>
<p class="note">{E(x['months_note'])} {E(rkey(rep, 'bass_extra', L))}</p></div>
<ul>{gen_rules}</ul>
<p class="note">{x['source'].format(link=link)}</p></section>
<footer><p>{E(x['footer'])}</p><p>{E(x['gear_note'])}</p>{"".join(f"<p>ⓘ {E(m)}</p>" for m in missing_lines(rep, L))}</footer>
</main><script>{JS}</script></body></html>""")
    return "\n".join(out)


JS = """
(function(){var b=document.querySelectorAll('.target button');if(!b.length)return;
var ol=document.querySelector('.spots'),li=[].slice.call(ol.children);
li.forEach(function(e,i){e.setAttribute('data-i',i)});
function set(t){document.body.setAttribute('data-target',t);
for(var i=0;i<b.length;i++)b[i].setAttribute('aria-pressed',b[i].getAttribute('data-t')===t?'true':'false');
li.slice().sort(function(p,q){if(t==='all')return p.getAttribute('data-i')-q.getAttribute('data-i');
var d=(parseFloat(q.getAttribute('data-fit-'+t))||-1)-(parseFloat(p.getAttribute('data-fit-'+t))||-1);
return d||p.getAttribute('data-i')-q.getAttribute('data-i')}).forEach(function(e){ol.appendChild(e)});
try{localStorage.setItem('kustvis-target',t)}catch(e){}}
for(var i=0;i<b.length;i++)b[i].addEventListener('click',function(){set(this.getAttribute('data-t'))});
var s='all';try{s=localStorage.getItem('kustvis-target')||'all'}catch(e){}
if(!document.querySelector('.target button[data-t="'+s+'"]'))s='all';set(s);})();
"""

CSS = """
:root{--sea:#1F3A44;--foam:#EEF2F0;--paper:#FFFFFF;--sand:#C9B98F;--buoy:#F2C230;--kelp:#3F6B47;--rust:#A4452C;--ink:#172a31;--muted:#5b6d72;--line:#d5ddda}
@media (prefers-color-scheme:dark){:root{--foam:#0f1d22;--paper:#15272e;--ink:#e6eeeb;--muted:#9fb1b4;--line:#28414a;--sea:#7fb3c2}}
*{box-sizing:border-box}
body{margin:0;background:var(--foam);color:var(--ink);font:400 17px/1.55 Barlow,system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:20px 16px 48px}
h1,h2,h3,.brand,.score b,.win-t{font-family:'Barlow Condensed',sans-serif;font-weight:700;letter-spacing:.005em}
.top{display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:2px solid var(--sea);padding-bottom:8px}
.brand{font-size:26px;color:var(--sea)}
.upd{color:var(--muted);font-size:14px;margin:8px 0 0}
.langs{display:flex;gap:2px}
.langs a{font:600 14px Barlow,sans-serif;text-decoration:none;color:var(--muted);padding:4px 8px;border-radius:3px}
.langs a:hover{color:var(--sea)}
.langs a[aria-current]{background:var(--sea);color:var(--foam)}
.langs a:focus-visible{outline:3px solid var(--buoy);outline-offset:1px}
.hero{padding:28px 0 8px}
.when{margin:0;color:var(--muted);font-weight:500}
h1{font-size:clamp(34px,7vw,56px);line-height:1.02;margin:6px 0 12px;color:var(--ink)}
.win-t{display:inline-block;background:var(--buoy);color:#172a31;padding:0 10px;margin-top:6px}
.why{margin:0 0 14px;max-width:62ch}
.tide{width:100%;height:auto;display:block;background:var(--paper);border:1px solid var(--line)}
.tide .water{fill:var(--sea);opacity:.14}
.tide .line{fill:none;stroke:var(--sea);stroke-width:2.2}
.tide .win{fill:var(--buoy);opacity:.45}
.tide .pt{fill:var(--sea)}
.tide .lbl{font:600 13px Barlow,sans-serif;fill:var(--ink)}
.tide .ax{font:12px Barlow,sans-serif;fill:var(--muted)}
.legend{font-size:14px;color:var(--muted);margin:6px 0 18px}
.sw{display:inline-block;width:14px;height:10px;background:var(--buoy);margin-right:6px;vertical-align:middle}
.score{display:inline-flex;align-items:baseline;gap:1px;padding:1px 8px;border-radius:3px;color:#fff;white-space:nowrap}
.score b{font-size:20px}.score span{font-size:13px;opacity:.85}
.score.good{background:var(--kelp)}.score.mid{background:#8a7a3c}.score.bad{background:var(--rust)}
table.dep{width:100%;border-collapse:collapse;background:var(--paper);border:1px solid var(--line);font-size:16px}
.dep caption{text-align:left;font-weight:600;padding:0 0 6px}
.dep th,.dep td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
.dep th{font-weight:500;color:var(--muted);font-size:14px}
.note{font-size:14px;color:var(--muted)}
h2{font-size:30px;margin:36px 0 10px;color:var(--sea)}
.spots{list-style:none;padding:0;margin:0;counter-reset:s}
.spot{background:var(--paper);border-left:4px solid var(--sea);padding:14px 16px;margin:0 0 14px}
.spot .head{display:flex;justify-content:space-between;gap:12px;align-items:center}
.spot h3{font-size:23px;margin:0}
.spot p{margin:6px 0}
.meta{color:var(--muted);font-size:15px}
.tip{font-size:15px}
details{margin:6px 0}summary{cursor:pointer;font-weight:500;color:var(--sea)}
.factors{list-style:none;padding:0;margin:6px 0;font-size:15px}
.factors li{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:2px 0}
.legal{padding-left:0;list-style:none;font-size:15px;margin:6px 0}
.outlook{display:flex;gap:10px;list-style:none;padding:8px 0 0;margin:8px 0 0;border-top:1px solid var(--line);flex-wrap:wrap}
.outlook li{display:flex;align-items:center;gap:6px;font-size:14px;color:var(--muted)}
.outlook .score b{font-size:15px}
.rules ul{padding-left:18px}
.rule-bass{background:var(--paper);padding:14px 16px;border:1px solid var(--line)}
.rule-bass h3{margin:0 0 4px;font-size:22px}
.months{display:grid;grid-template-columns:repeat(12,1fr);gap:3px;margin:8px 0}
.months span{text-align:center;font-size:13px;padding:5px 0;background:var(--kelp);color:#fff}
.months span.x{background:var(--rust)}
footer{margin-top:36px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
a{color:var(--sea)}
a:focus-visible,summary:focus-visible{outline:3px solid var(--buoy);outline-offset:2px}
@media (max-width:520px){.dep th:nth-child(2),.dep td:nth-child(2){display:none}.months span{font-size:11px}}
.target{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 14px}
.target span{font-weight:500;color:var(--muted);font-size:15px}
.target button{font:600 15px Barlow,sans-serif;padding:6px 14px;border:2px solid var(--sea);background:transparent;color:var(--sea);border-radius:999px;cursor:pointer}
.target button[aria-pressed=true]{background:var(--sea);color:var(--foam)}
.target button:focus-visible,.btn:focus-visible{outline:3px solid var(--buoy);outline-offset:2px}
.gear{background:var(--foam);padding:8px 12px;margin:8px 0}
.gear h4{margin:0 0 4px;font:600 15px Barlow,sans-serif}
.gear ul{margin:0;padding-left:18px;font-size:15px}
body[data-target=zeebaars] .gear li[data-sp=tong],body[data-target=tong] .gear li[data-sp=zeebaars]{display:none}
.btn{display:inline-block;font-weight:600;font-size:15px;text-decoration:none;background:var(--sea);color:var(--foam);padding:8px 14px;border-radius:4px}
.regions{display:flex;gap:4px;margin:10px 0 0}
.regions a{font:600 15px Barlow,sans-serif;text-decoration:none;color:var(--sea);padding:5px 12px;border:2px solid var(--sea);border-radius:4px}
.regions a[aria-current]{background:var(--sea);color:var(--foam)}
.regions a:focus-visible{outline:3px solid var(--buoy);outline-offset:2px}
.picks ul{list-style:none;padding:0;margin:0 0 8px;background:var(--paper);border:1px solid var(--line)}
.picks li{padding:9px 12px;border-bottom:1px solid var(--line);font-weight:500}
.picks li:last-child{border-bottom:0}
.fits{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.fit{background:var(--foam);border:1px solid var(--line);border-radius:3px;padding:1px 8px;font-size:15px}
body[data-target=zeebaars] .fit[data-sp=zeebaars],body[data-target=tong] .fit[data-sp=tong]{border-color:var(--sea);background:var(--buoy);color:#172a31}
"""
