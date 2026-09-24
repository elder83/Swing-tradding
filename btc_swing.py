#!/usr/bin/env python3
"""Analyse swing trading du Bitcoin (unités de temps : jour et semaine).

Récupère les bougies en direct (Binance, repli sur Kraken), calcule les
indicateurs classiques et produit un signal ACHAT / VENTE / ATTENTE avec
niveaux d'entrée, stop et objectifs basés sur l'ATR.

Usage :
    python3 btc_swing.py --hebdo      # swing hebdo (à lancer le lundi matin)
    python3 btc_swing.py              # analyse jour (timing plus fin)
    python3 btc_swing.py --watch 4    # relance toutes les 4 heures
    python3 btc_swing.py --demo       # données synthétiques (test hors ligne)

Aucune dépendance externe : Python 3.8+ suffit.
Ceci n'est pas un conseil en investissement.
"""
import argparse
import json
import math
import random
import time
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Données
# --------------------------------------------------------------------------

class DataError(RuntimeError):
    """Aucune source de données n'a répondu."""


INTERVAL_S = {"1d": 86400, "1w": 7 * 86400}


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "btc-swing/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def fetch_binance(interval, limit):
    url = ("https://api.binance.com/api/v3/klines?symbol=BTCUSDT"
           f"&interval={interval}&limit={limit}")
    now_ms = time.time() * 1000
    # r[6] = heure de clôture : on écarte la bougie en cours (non clôturée)
    return [dict(t=int(r[0]) // 1000, o=float(r[1]), h=float(r[2]),
                 l=float(r[3]), c=float(r[4]), v=float(r[5]))
            for r in _get_json(url) if int(r[6]) < now_ms]


def fetch_kraken(interval, limit):
    minutes = {"1d": 1440, "1w": 10080}[interval]
    data = _get_json(f"https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval={minutes}")
    if data.get("error"):
        raise RuntimeError(data["error"])
    rows = next(v for k, v in data["result"].items() if k != "last")
    now = time.time()
    return [dict(t=int(r[0]), o=float(r[1]), h=float(r[2]), l=float(r[3]),
                 c=float(r[4]), v=float(r[6]))
            for r in rows if int(r[0]) + INTERVAL_S[interval] <= now][-limit:]


def fetch(interval, limit):
    errors = []
    for name in ("binance", "kraken"):
        try:
            return globals()[f"fetch_{name}"](interval, limit), name
        except Exception as e:  # noqa: BLE001 - on essaie la source suivante
            errors.append(f"{name}: {e}")
    raise DataError("Impossible de récupérer les données :\n  " + "\n  ".join(errors))


def eur_rate():
    """Taux USD -> EUR déduit des paires BTC/EUR et BTC/USD de Kraken (None si indisponible)."""
    try:
        res = _get_json("https://api.kraken.com/0/public/Ticker?pair=XBTEUR,XBTUSD")["result"]
        eur = next(float(v["c"][0]) for k, v in res.items() if k.endswith("EUR"))
        usd = next(float(v["c"][0]) for k, v in res.items() if k.endswith("USD"))
        return eur / usd
    except Exception:  # noqa: BLE001 - l'affichage en euros est un bonus
        return None


def weeks_from_daily(daily):
    """Semaines lundi -> dimanche (UTC), seulement les semaines complètes."""
    groups = {}
    for x in daily:
        monday = x["t"] - datetime.fromtimestamp(x["t"], timezone.utc).weekday() * 86400
        groups.setdefault(monday - monday % 86400, []).append(x)
    return [dict(t=k, o=v[0]["o"], h=max(i["h"] for i in v), l=min(i["l"] for i in v),
                 c=v[-1]["c"], v=sum(i["v"] for i in v))
            for k, v in sorted(groups.items()) if len(v) == 7]


def demo_candles(n, step_days, seed):
    """Marche aléatoire réaliste pour tester le script sans réseau."""
    rnd = random.Random(seed)
    price, out, t0 = 60000.0, [], int(time.time()) - n * step_days * 86400
    for i in range(n):
        o = price
        price *= math.exp(rnd.gauss(0.0015 * step_days, 0.03 * math.sqrt(step_days)))
        h, l = max(o, price) * (1 + abs(rnd.gauss(0, 0.01))), min(o, price) * (1 - abs(rnd.gauss(0, 0.01)))
        out.append(dict(t=t0 + i * step_days * 86400, o=o, h=h, l=l, c=price, v=rnd.uniform(1e4, 5e4)))
    return out

# --------------------------------------------------------------------------
# Indicateurs
# --------------------------------------------------------------------------

def sma(xs, n):
    return [None if i < n - 1 else sum(xs[i - n + 1:i + 1]) / n for i in range(len(xs))]


def ema(xs, n):
    k, out, prev = 2 / (n + 1), [], None
    for i, x in enumerate(xs):
        if i < n - 1:
            out.append(None)
            continue
        prev = sum(xs[:n]) / n if prev is None else x * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(xs, n=14):
    out, gain, loss = [None] * len(xs), 0.0, 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        g, l_ = max(d, 0), max(-d, 0)
        if i <= n:
            gain += g / n
            loss += l_ / n
            if i < n:
                continue
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l_) / n
        out[i] = 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
    return out


def macd(xs, fast=12, slow=26, sig=9):
    f, s = ema(xs, fast), ema(xs, slow)
    line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
    valid = [x for x in line if x is not None]
    sig_valid = ema(valid, sig)
    signal = [None] * (len(line) - len(valid)) + sig_valid
    hist = [a - b if a is not None and b is not None else None for a, b in zip(line, signal)]
    return line, signal, hist


def atr(c, n=14):
    trs = [c[0]["h"] - c[0]["l"]] + [
        max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - c[i - 1]["c"]), abs(c[i]["l"] - c[i - 1]["c"]))
        for i in range(1, len(c))]
    return ema(trs, n)


def bollinger(xs, n=20, k=2):
    mid = sma(xs, n)
    up, lo = [], []
    for i, m in enumerate(mid):
        if m is None:
            up.append(None)
            lo.append(None)
            continue
        sd = math.sqrt(sum((x - m) ** 2 for x in xs[i - n + 1:i + 1]) / n)
        up.append(m + k * sd)
        lo.append(m - k * sd)
    return up, mid, lo


def pivots(c, left=5, right=5, lookback=180):
    """Sommets et creux de swing -> résistances / supports."""
    c = c[-lookback:]
    highs, lows = [], []
    for i in range(left, len(c) - right):
        before, after = c[i - left:i], c[i + 1:i + right + 1]
        # strict à gauche, large à droite : un sommet égal n'est compté qu'une fois
        if c[i]["h"] > max(x["h"] for x in before) and c[i]["h"] >= max(x["h"] for x in after):
            highs.append(c[i]["h"])
        if c[i]["l"] < min(x["l"] for x in before) and c[i]["l"] <= min(x["l"] for x in after):
            lows.append(c[i]["l"])
    return highs, lows


def cluster(levels, tol=0.015):
    """Regroupe les niveaux proches (±1,5 %) pour obtenir des zones."""
    zones = []
    for lv in sorted(levels):
        if zones and abs(lv - zones[-1][-1]) / lv < tol:
            zones[-1].append(lv)
        else:
            zones.append([lv])
    return [(sum(z) / len(z), len(z)) for z in zones]

# --------------------------------------------------------------------------
# Analyse
# --------------------------------------------------------------------------

def last(xs, back=0):
    return xs[-1 - back]


def analyse(daily, weekly):
    dc = [x["c"] for x in daily]
    wc = [x["c"] for x in weekly]
    price = dc[-1]

    d = dict(ema20=ema(dc, 20), ema50=ema(dc, 50), ema200=ema(dc, 200), rsi=rsi(dc),
             atr=atr(daily))
    d["macd"], d["macd_sig"], d["macd_hist"] = macd(dc)
    d["bb_up"], d["bb_mid"], d["bb_lo"] = bollinger(dc)
    w = dict(sma20=sma(wc, 20), sma50=sma(wc, 50), ema21=ema(wc, 21), rsi=rsi(wc))
    w["macd"], w["macd_sig"], w["macd_hist"] = macd(wc)

    score, notes = 0, []

    def add(pts, txt):
        nonlocal score
        score += pts
        notes.append(f"{pts:+d}  {txt}")

    # --- Tendance de fond (hebdo) : elle décide du sens privilégié
    bull = last(w["sma50"]) is None or price > last(w["sma50"])
    if last(w["sma50"]) and price > last(w["sma50"]):
        add(2, "Prix au-dessus de la MM50 hebdo (tendance de fond haussière)")
    elif last(w["sma50"]):
        add(-2, "Prix sous la MM50 hebdo (tendance de fond baissière)")
    if last(w["ema21"]) and price > last(w["ema21"]):
        add(1, "Prix au-dessus de l'EMA21 hebdo (bull market support band)")
    elif last(w["ema21"]):
        add(-1, "Prix sous l'EMA21 hebdo")
    if last(w["macd_hist"]) is not None:
        add(1 if last(w["macd_hist"]) > 0 else -1,
            f"MACD hebdo {'positif' if last(w['macd_hist']) > 0 else 'négatif'} (histogramme)")

    # --- Tendance intermédiaire (jour)
    if last(d["ema50"]) and last(d["ema200"]):
        if last(d["ema50"]) > last(d["ema200"]):
            add(1, "EMA50 > EMA200 jour (golden cross en place)")
        else:
            add(-1, "EMA50 < EMA200 jour (death cross en place)")
        add(1 if price > last(d["ema200"]) else -1,
            f"Prix {'au-dessus de' if price > last(d['ema200']) else 'sous'} l'EMA200 jour")

    # --- Momentum / timing (jour)
    h, hp = last(d["macd_hist"]), last(d["macd_hist"], 1)
    if h is not None and hp is not None:
        if h > 0 and hp <= 0:
            add(2, "Croisement haussier du MACD jour (signal d'entrée)")
        elif h < 0 and hp >= 0:
            add(-2, "Croisement baissier du MACD jour (signal de sortie)")
        else:
            add(1 if h > hp else -1, f"Momentum MACD jour {'en hausse' if h > hp else 'en baisse'}")

    r = last(d["rsi"])
    # Les signaux contrariants valent moins quand ils vont contre la tendance de fond
    if r >= 75:
        add(-2 if not bull else -1, f"RSI jour {r:.0f} : fort surachat, risque de correction")
    elif r >= 65:
        add(-1, f"RSI jour {r:.0f} : zone haute, ne pas courir après le prix")
    elif r <= 30:
        add(2 if bull else 1, f"RSI jour {r:.0f} : survente, rebond "
            + ("probable" if bull else "technique possible (contre-tendance)"))
    elif r <= 40 and bull:
        add(1, f"RSI jour {r:.0f} : zone basse dans une tendance haussière, bon point d'accumulation")

    if last(d["bb_up"]) and price > last(d["bb_up"]):
        add(-1, "Clôture au-dessus de la bande de Bollinger haute (extension)")
    elif last(d["bb_lo"]) and price < last(d["bb_lo"]):
        add(1, "Clôture sous la bande de Bollinger basse (excès baissier)")

    # --- Supports / résistances
    # pivots jour (6 mois) + pivots hebdo (2 ans) pour voir les niveaux plus anciens
    highs, lows = pivots(daily)
    w_highs, w_lows = pivots(weekly, 2, 2, 104)
    zones = cluster(highs + lows + w_highs + w_lows)
    res = sorted([z for z in zones if z[0] > price * 1.005], key=lambda z: z[0])[:3]
    sup = sorted([z for z in zones if z[0] < price * 0.995], key=lambda z: -z[0])[:3]

    a = last(d["atr"])
    stretch = (price - last(d["ema20"])) / a if last(d["ema20"]) else 0
    if score >= 4 and stretch > 2:
        verdict = (f"ACHAT SUR REPLI (tendance haussière mais prix étiré à {stretch:.1f} ATR "
                   "au-dessus de l'EMA20 : ne pas acheter au plus haut)")
    elif score >= 4:
        verdict = "ACHAT (tendance + momentum alignés)"
    elif score >= 2:
        verdict = "ACHAT SUR REPLI (attendre un retour vers un support / l'EMA20)"
    elif score <= -4:
        verdict = "VENTE / RESTER HORS DU MARCHÉ"
    elif score <= -2:
        verdict = "ALLÉGER / PRUDENCE"
    else:
        verdict = "ATTENTE (signaux contradictoires)"

    pullback = max(last(d["ema20"]) or 0, sup[0][0] if sup else price - a)
    entry = price if score >= 4 and stretch <= 2 else min(price, pullback)
    plan = dict(entry=entry, stop=entry - 2 * a, t1=entry + 2 * a, t2=entry + 4 * a)
    if res:
        plan["t1"] = min(plan["t1"], res[0][0]) if res[0][0] > entry else plan["t1"]

    return dict(price=price, score=score, verdict=verdict, notes=notes, res=res, sup=sup,
                plan=plan, atr=a, stretch=stretch, d=d, w=w, rsi_w=last(w["rsi"]),
                date=datetime.fromtimestamp(daily[-1]["t"], timezone.utc))


def analyse_weekly(weekly, price=None):
    """Swing hebdo : la tendance hebdo décide, les niveaux hebdo donnent entrées et sorties.

    Règle de fond (testée sur 2015-2026) : on n'est acheteur que si la semaine clôture
    au-dessus de la MM50 hebdo ; sous la bande EMA21/MM20 hebdo, on sort.
    """
    c = [x["c"] for x in weekly]
    close = c[-1]
    price = price or close
    ema21, sma20, sma50 = last(ema(c, 21)), last(sma(c, 20)), last(sma(c, 50))
    r = last(rsi(c))
    hist = macd(c)[2]
    a = last(atr(weekly))
    band_lo, band_hi = min(ema21, sma20), max(ema21, sma20)

    highs, lows = pivots(weekly, 2, 2, 156)
    zones = cluster(highs + lows)
    res = sorted([z for z in zones if z[0] > price * 1.01], key=lambda z: z[0])[:3]
    sup = sorted([z for z in zones if z[0] < price * 0.99], key=lambda z: -z[0])[:3]

    above50 = sma50 is not None and close > sma50
    if close < band_lo:
        regime, action = "BAISSIER", "HORS DU MARCHÉ : garder la part trading en USDC"
    elif not above50:
        regime, action = "NEUTRE", "PRUDENCE : pas de nouvel achat tant que la MM50 hebdo n'est pas reprise"
    elif r is not None and r >= 70:
        regime, action = "HAUSSIER (surchauffe)", "ALLÉGER : prendre une partie des gains"
    else:
        regime, action = "HAUSSIER", "ACHETEUR : acheter les replis, conserver les positions"

    zone_buy = max([z[0] for z in sup] + [sma50 or 0, band_hi])
    zone_buy = min(zone_buy, price)
    plan = dict(buy=zone_buy, t1=res[0][0] if res else price + a,
                t2=res[1][0] if len(res) > 1 else price + 2 * a,
                reduce=sma50, exit=band_lo)
    return dict(close=close, price=price, ema21=ema21, sma20=sma20, sma50=sma50, rsi=r,
                hist=last(hist), hist_prev=last(hist, 1), atr=a, res=res, sup=sup,
                regime=regime, action=action, plan=plan,
                date=datetime.fromtimestamp(weekly[-1]["t"] + 6 * 86400, timezone.utc))


def report_weekly(a, source, rate=None):
    def m(x):
        if x is None:
            return "n/d"
        usd = f"{x:,.0f} $".replace(",", " ")
        return usd + (f"  ({x * rate:,.0f} €)".replace(",", " ") if rate else "")

    momentum = "en hausse" if a["hist"] > a["hist_prev"] else "en baisse"
    lines = [
        "=" * 64,
        f" BITCOIN – Swing HEBDO ({source}, semaine close le {a['date']:%Y-%m-%d})",
        "=" * 64,
        f" Prix actuel            {m(a['price'])}",
        f" Clôture hebdo          {m(a['close'])}",
        f" Mouvement moyen/semaine {m(a['atr'])}  ({a['atr'] / a['close'] * 100:.0f} %)",
        "",
        f" Bande EMA21/MM20 hebdo {m(min(a['ema21'], a['sma20']))} – {m(max(a['ema21'], a['sma20']))}",
        f" MM50 hebdo             {m(a['sma50'])}",
        f" RSI hebdo              {a['rsi']:.0f}",
        f" MACD hebdo             {'positif' if a['hist'] > 0 else 'négatif'}, {momentum}",
        "",
        " Résistances : " + ", ".join(m(z[0]) for z in a["res"]),
        " Supports    : " + ", ".join(m(z[0]) for z in a["sup"]),
        "",
        f" TENDANCE : {a['regime']}",
        f" ACTION   : {a['action']}",
        "",
        " Ordres à placer pour la semaine :",
        f"   Achat sur repli vers   {m(a['plan']['buy'])}",
        f"   Vente partielle vers   {m(a['plan']['t1'])}",
        f"   Vente partielle vers   {m(a['plan']['t2'])}",
        f"   Clôture hebdo sous     {m(a['plan']['reduce'])}  → alléger de moitié",
        f"   Clôture hebdo sous     {m(a['plan']['exit'])}  → tout repasser en USDC",
        "",
        " Décider uniquement sur la clôture du dimanche soir (lundi 2 h, heure de Paris).",
        " Pas un conseil en investissement.",
        "=" * 64,
    ]
    print("\n".join(lines))


def fmt(x):
    if x is None:
        return "       n/d  "
    return f"{x:>10,.0f} $".replace(",", " ")


def report(a, source):
    d, w, p = a["d"], a["w"], a["price"]
    pct = lambda x: f"{(p / x - 1) * 100:+.1f} %" if x else "n/d"  # noqa: E731
    lines = [
        "=" * 64,
        f" BITCOIN – Analyse swing ({source}, bougie du {a['date']:%Y-%m-%d})",
        "=" * 64,
        f" Prix actuel          {fmt(p)}",
        f" ATR 14 j (volatilité){fmt(a['atr'])}  ({a['atr'] / p * 100:.1f} %/jour)",
        "",
        " Moyennes mobiles            niveau       écart",
        f"  EMA20  jour         {fmt(last(d['ema20']))}   {pct(last(d['ema20']))}",
        f"  EMA50  jour         {fmt(last(d['ema50']))}   {pct(last(d['ema50']))}",
        f"  EMA200 jour         {fmt(last(d['ema200']))}   {pct(last(d['ema200']))}",
        f"  EMA21  hebdo        {fmt(last(w['ema21']))}   {pct(last(w['ema21']))}",
        f"  MM50   hebdo        {fmt(last(w['sma50']))}   {pct(last(w['sma50']))}",
        "",
        f" RSI14 jour {last(d['rsi']):.1f}   |   RSI14 hebdo "
        + (f"{a['rsi_w']:.1f}" if a["rsi_w"] is not None else "n/d"),
        "",
        " Résistances : " + ", ".join(f"{z[0]:,.0f} ({z[1]}x)".replace(",", " ") for z in a["res"]),
        " Supports    : " + ", ".join(f"{z[0]:,.0f} ({z[1]}x)".replace(",", " ") for z in a["sup"]),
        "",
        " Détail du score :",
        *["   " + n for n in a["notes"]],
        "",
        f" SCORE {a['score']:+d}  →  {a['verdict']}",
        "",
        (" Plan indicatif (long) :" if a["score"] >= 2 else
         " Pas d'achat conseillé. Plan à activer seulement si le score repasse ≥ +2 :"),
        f"   Entrée   {fmt(a['plan']['entry'])}",
        f"   Stop     {fmt(a['plan']['stop'])}   (2 × ATR)",
        f"   Objectif1{fmt(a['plan']['t1'])}   (prendre 50 %, stop au point mort)",
        f"   Objectif2{fmt(a['plan']['t2'])}   (4 × ATR)",
        "",
        " Taille de position : risquer 1–2 % du capital entre entrée et stop.",
        " Pas un conseil en investissement.",
        "=" * 64,
    ]
    print("\n".join(lines))


def run(demo, hebdo=False):
    if hebdo:
        if demo:
            daily, src, price, rate = demo_candles(800, 1, 3), "démo", None, None
        else:
            daily, src = fetch("1d", 1000)
            price, rate = daily[-1]["c"], eur_rate()
        report_weekly(analyse_weekly(weeks_from_daily(daily), price), src, rate)
        return
    if demo:
        daily, weekly, src = demo_candles(400, 1, 1), demo_candles(200, 7, 2), "démo"
    else:
        daily, src = fetch("1d", 400)
        weekly, _ = fetch("1w", 200)
    report(analyse(daily, weekly), src)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", type=float, metavar="HEURES", help="relancer l'analyse toutes les N heures")
    ap.add_argument("--hebdo", action="store_true", help="swing sur l'unité de temps semaine")
    ap.add_argument("--demo", action="store_true", help="données synthétiques (hors ligne)")
    args = ap.parse_args()
    while True:
        try:
            run(args.demo, args.hebdo)
        except DataError as e:
            if not args.watch:
                raise SystemExit(str(e))
            print(f"[{datetime.now():%Y-%m-%d %H:%M}] {e}\nNouvel essai dans {args.watch} h.")
        except KeyboardInterrupt:
            break
        if not args.watch:
            break
        try:
            time.sleep(args.watch * 3600)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
