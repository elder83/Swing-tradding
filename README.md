# Swing trading Bitcoin

`btc_swing.py` analyse le BTC sur les unités de temps **jour** et **semaine**
à partir de données en direct (Binance, repli sur Kraken) et affiche :

- EMA 20/50/200 jour, EMA21 et MM50 hebdo, RSI, MACD, Bollinger, ATR
- supports / résistances détectés automatiquement (sommets et creux de swing)
- un score de -10 à +10 et un verdict : ACHAT, ACHAT SUR REPLI, ATTENTE, ALLÉGER, VENTE
- un plan indicatif : entrée, stop (2×ATR), objectifs (2×ATR / 4×ATR)

## Utilisation

```bash
python3 btc_swing.py            # analyse ponctuelle
python3 btc_swing.py --watch 24 # relance toutes les 24 h (idéal : après la clôture journalière, 02:00 heure de Paris)
python3 btc_swing.py --demo     # test hors ligne avec données synthétiques
```

Aucune dépendance : Python 3.8+ suffit.

## Logique du score

1. **Tendance de fond (hebdo)** : on n'achète en priorité que si le prix est au-dessus de la MM50 et de l'EMA21 hebdo.
2. **Tendance intermédiaire (jour)** : position par rapport à l'EMA200, golden/death cross EMA50/200.
3. **Timing** : croisements du MACD jour, RSI (survente < 30, surachat > 70), excès de Bollinger.

## Règles de gestion

- Risquer 1 à 2 % du capital par trade (distance entrée → stop).
- Prendre 50 % à l'objectif 1, remonter le stop au prix d'entrée, laisser courir le reste.
- Agir sur les **clôtures** journalières/hebdomadaires, pas sur les mèches.

> Outil pédagogique, pas un conseil en investissement.
