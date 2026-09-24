# Swing trading Bitcoin

`btc_swing.py` analyse le BTC sur les unités de temps **jour** et **semaine**
à partir de données en direct (Binance, repli sur Kraken) et affiche :

- EMA 20/50/200 jour, EMA21 et MM50 hebdo, RSI, MACD, Bollinger, ATR
- supports / résistances détectés automatiquement (sommets et creux de swing)
- un score de -10 à +10 et un verdict : ACHAT, ACHAT SUR REPLI, ATTENTE, ALLÉGER, VENTE
- un plan indicatif : entrée, stop (2×ATR), objectifs (2×ATR / 4×ATR)

## Utilisation

```bash
python3 btc_swing.py --hebdo    # swing HEBDO : à lancer le lundi matin, trades de 1 à plusieurs semaines
python3 btc_swing.py            # analyse ponctuelle
python3 btc_swing.py --watch 24 # relance toutes les 24 h (idéal : après la clôture journalière, 02:00 heure de Paris)
python3 btc_swing.py --demo     # test hors ligne avec données synthétiques
```

Aucune dépendance : Python 3.8+ suffit.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

20 tests hors ligne : indicateurs comparés à des valeurs de référence (RSI de Wilder),
lecture des réponses Binance/Kraken simulées, bascule d'une source à l'autre,
cohérence des signaux et du plan de trade, cas limites.

## Mode hebdo (`--hebdo`)

Semaines du lundi au dimanche (UTC), décision uniquement sur la clôture du dimanche soir.

- **Tendance** : clôture au-dessus de la MM50 hebdo = haussier (on achète les replis) ;
  entre la bande EMA21/MM20 hebdo et la MM50 = neutre (pas de nouvel achat) ;
  sous la bande = baissier (part trading en USDC).
- **Ordres de la semaine** : achat sur le support hebdo le plus proche, ventes partielles
  sur les résistances hebdo, allègement sous la MM50, sortie sous la bande.
- Prix affichés en dollars et en euros.

Test historique de la règle de tendance seule (clôtures hebdo Kraken, frais 0,25 %) :

| Depuis | MM50 hebdo | Bande EMA21/MM20 | Achat-conservation |
|---|---|---|---|
| 2018 | ×9,0 (perte max 55 %) | ×8,0 (64 %) | ×5,7 (77 %) |
| 2021 | ×3,7 (50 %) | ×3,4 (47 %) | ×2,3 (76 %) |
| 2024 | ×2,2 (25 %) | ×2,0 (22 %) | ×1,8 (51 %) |

Les performances passées ne préjugent pas des performances futures.

## Logique du score (mode jour)

1. **Tendance de fond (hebdo)** : on n'achète en priorité que si le prix est au-dessus de la MM50 et de l'EMA21 hebdo.
2. **Tendance intermédiaire (jour)** : position par rapport à l'EMA200, golden/death cross EMA50/200.
3. **Timing** : croisements du MACD jour, RSI (survente < 30, surachat > 70), excès de Bollinger.

## Règles de gestion

- Risquer 1 à 2 % du capital par trade (distance entrée → stop).
- Prendre 50 % à l'objectif 1, remonter le stop au prix d'entrée, laisser courir le reste.
- Agir sur les **clôtures** journalières/hebdomadaires, pas sur les mèches.

> Outil pédagogique, pas un conseil en investissement.
