"""Tests de btc_swing.py (hors ligne, réseau simulé).

Lancer :  python3 -m unittest discover -s tests -v
"""
import io
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import btc_swing as bs  # noqa: E402

# Exemple de référence de Wilder (StockCharts, « RSI ») : RSI(14) attendu.
WILDER_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                 45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64]
WILDER_RSI = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97]


def candles_from_closes(closes, spread=0.01, step=86400, t0=1_700_000_000):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(dict(t=t0 + i * step, o=o, h=max(o, c) * (1 + spread),
                        l=min(o, c) * (1 - spread), c=c, v=1.0))
        prev = c
    return out


def to_weekly(daily):
    """Agrège des bougies jour en bougies semaine (7 j)."""
    out = []
    for i in range(0, len(daily) - 6, 7):
        wk = daily[i:i + 7]
        out.append(dict(t=wk[0]["t"], o=wk[0]["o"], h=max(x["h"] for x in wk),
                        l=min(x["l"] for x in wk), c=wk[-1]["c"], v=sum(x["v"] for x in wk)))
    return out


def trend(start, pct_per_bar, n, wiggle=0.0):
    """Série géométrique avec une petite oscillation pour créer des pivots."""
    import math
    return [start * (1 + pct_per_bar) ** i * (1 + wiggle * math.sin(i / 3)) for i in range(n)]


class TestIndicators(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(bs.sma([1, 2, 3, 4, 5], 3), [None, None, 2, 3, 4])

    def test_ema_seed_and_recursion(self):
        e = bs.ema([1, 2, 3, 4, 5], 3)
        self.assertEqual(e[:2], [None, None])
        self.assertAlmostEqual(e[2], 2.0)        # amorçage = SMA
        self.assertAlmostEqual(e[3], 3.0)        # 4*0.5 + 2*0.5
        self.assertAlmostEqual(e[4], 4.0)

    def test_ema_constant(self):
        self.assertTrue(all(abs(x - 7) < 1e-12 for x in bs.ema([7] * 50, 10)[9:]))

    def test_rsi_wilder_reference(self):
        r = bs.rsi(WILDER_CLOSES, 14)
        self.assertTrue(all(x is None for x in r[:14]))
        for got, exp in zip(r[14:], WILDER_RSI):
            # les valeurs publiées sont calculées avec des moyennes arrondies à 2 déc.
            self.assertAlmostEqual(got, exp, delta=0.1)

    def test_rsi_bounds(self):
        self.assertEqual(bs.rsi(list(range(1, 40)))[-1], 100.0)
        self.assertLess(bs.rsi(list(range(40, 1, -1)))[-1], 1.0)

    def test_macd_zero_on_flat_and_sign_on_trend(self):
        line, sig, hist = bs.macd([100.0] * 60)
        self.assertAlmostEqual(line[-1], 0)
        self.assertAlmostEqual(hist[-1], 0)
        line, _, _ = bs.macd(trend(100, 0.01, 100))
        self.assertGreater(line[-1], 0)
        self.assertIsNone(sig[32])               # 26 + 9 - 2 = 33e point
        self.assertIsNotNone(sig[33])

    def test_atr_uses_true_range_with_gaps(self):
        c = [dict(h=10, l=9, c=9.5), dict(h=12, l=11.5, c=12)]   # gap haussier
        c = c + [dict(h=12, l=11.5, c=12)] * 20
        a = bs.atr(c, 3)
        self.assertAlmostEqual(max(x for x in a if x is not None) >= 1.0, True)

    def test_bollinger_flat(self):
        up, mid, lo = bs.bollinger([50.0] * 30)
        self.assertEqual((up[-1], mid[-1], lo[-1]), (50.0, 50.0, 50.0))

    def test_pivots_and_cluster(self):
        closes = [100, 101, 102, 103, 104, 110, 104, 103, 102, 101, 100,
                  95, 96, 97, 98, 99, 110.5, 99, 98, 97, 96, 95]
        highs, lows = bs.pivots(candles_from_closes(closes, spread=0), 3, 3)
        self.assertIn(110, highs)
        self.assertIn(110.5, highs)
        zones = bs.cluster([h for h in highs if h > 105])
        self.assertEqual(len(zones), 1)          # 110 et 110.5 fusionnés
        self.assertEqual(zones[0][1], 2)


class TestFetch(unittest.TestCase):
    def test_binance_parsing_drops_unclosed_candle(self):
        now_ms = int(time.time() * 1000)
        rows = [[now_ms - 2 * 86_400_000, "1", "3", "0.5", "2", "10", now_ms - 86_400_001],
                [now_ms - 86_400_000, "2", "4", "1.5", "3", "11", now_ms + 5_000]]
        with mock.patch.object(bs, "_get_json", return_value=rows):
            out = bs.fetch_binance("1d", 2)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["c"], 2.0)
        self.assertEqual(out[0]["t"], (now_ms - 2 * 86_400_000) // 1000)

    def test_kraken_parsing_drops_unclosed_candle(self):
        now = int(time.time())
        rows = [[now - 3 * 86400, "1", "3", "0.5", "2", "1.9", "10", 5],
                [now - 2 * 86400, "2", "4", "1.5", "3", "2.9", "11", 5],
                [now - 3600, "3", "5", "2.5", "4", "3.9", "12", 5]]
        payload = {"error": [], "result": {"XXBTZUSD": rows, "last": now}}
        with mock.patch.object(bs, "_get_json", return_value=payload):
            out = bs.fetch_kraken("1d", 10)
        self.assertEqual([x["c"] for x in out], [2.0, 3.0])
        self.assertEqual(out[0]["v"], 10.0)

    def test_kraken_error(self):
        with mock.patch.object(bs, "_get_json", return_value={"error": ["EGeneral"]}):
            with self.assertRaises(RuntimeError):
                bs.fetch_kraken("1d", 10)

    def test_fallback_to_kraken(self):
        with mock.patch.object(bs, "fetch_binance", side_effect=OSError("451")), \
             mock.patch.object(bs, "fetch_kraken", return_value=["ok"]):
            data, src = bs.fetch("1d", 10)
        self.assertEqual((data, src), (["ok"], "kraken"))

    def test_all_sources_fail(self):
        with mock.patch.object(bs, "fetch_binance", side_effect=OSError("a")), \
             mock.patch.object(bs, "fetch_kraken", side_effect=OSError("b")):
            with self.assertRaises(bs.DataError):
                bs.fetch("1d", 10)


class TestAnalyse(unittest.TestCase):
    def test_strong_uptrend_is_bullish(self):
        daily = candles_from_closes(trend(10000, 0.004, 1000, wiggle=0.02))
        weekly = to_weekly(daily)
        a = bs.analyse(daily, weekly)
        self.assertGreaterEqual(a["score"], 2, a["notes"])
        self.assertIn("ACHAT", a["verdict"])

    def test_strong_downtrend_is_bearish(self):
        daily = candles_from_closes(trend(150000, -0.003, 1000, wiggle=0.02))
        weekly = to_weekly(daily)
        a = bs.analyse(daily, weekly)
        self.assertLessEqual(a["score"], -2, a["notes"])

    def test_plan_is_coherent(self):
        for seed in range(30):
            a = bs.analyse(bs.demo_candles(400, 1, seed), bs.demo_candles(200, 7, seed + 100))
            p, price = a["plan"], a["price"]
            self.assertLess(p["stop"], p["entry"])
            self.assertGreater(p["t1"], p["entry"])
            self.assertGreaterEqual(p["t2"], p["t1"])
            self.assertLessEqual(p["entry"], price * 1.0001, f"seed {seed}: entrée > prix")
            self.assertTrue(all(z[0] > price for z in a["res"]))
            self.assertTrue(all(z[0] < price for z in a["sup"]))

    def test_short_history_does_not_crash(self):
        daily = candles_from_closes(trend(50000, 0.001, 60, wiggle=0.02))
        weekly = candles_from_closes(trend(50000, 0.001, 10, wiggle=0.02), step=7 * 86400)
        a = bs.analyse(daily, weekly)
        buf = io.StringIO()
        with redirect_stdout(buf):
            bs.report(a, "test")
        self.assertIn("n/d", buf.getvalue())


class TestCli(unittest.TestCase):
    def test_demo_end_to_end(self):
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(sys, "argv", ["btc_swing.py", "--demo"]):
            bs.main()
        out = buf.getvalue()
        for s in ("Prix actuel", "SCORE", "Stop", "Objectif2"):
            self.assertIn(s, out)

    def test_watch_survives_network_error(self):
        calls = {"n": 0}

        def fake_run(demo):
            calls["n"] += 1
            if calls["n"] == 1:
                raise bs.DataError("réseau coupé")
            raise KeyboardInterrupt  # arrête la boucle au 2e passage

        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch.object(bs, "run", side_effect=fake_run), \
             mock.patch.object(bs.time, "sleep"), \
             mock.patch.object(sys, "argv", ["btc_swing.py", "--watch", "1"]):
            bs.main()
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
