# -*- coding: utf-8 -*-
"""
Aggiorna data.json per la Console di Accumulazione BTC.
Fonti: CoinGecko (prezzo), bitcoin-data.com/BGeometrics (metriche on-chain),
Blockchain.com (hash rate per le hash ribbons).
Eseguito 3 volte al giorno da GitHub Actions.
"""
import urllib.request, json, sys, statistics
from datetime import datetime, timezone, timedelta

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (console-accumulo)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

dati = {"aggiornato": datetime.now(timezone.utc).isoformat(timespec="seconds")}
errori = []

# --- prezzo (CoinGecko) ---
try:
    p = get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
    dati["price"] = float(p["bitcoin"]["usd"])
except Exception as e:
    errori.append(f"prezzo: {e}")

# --- metriche on-chain (bitcoin-data.com) ---
mappa = {"mvrvZ": ("mvrv-zscore", "mvrvZscore"),
         "puell": ("puell-multiple", "puellMultiple"),
         "sopr": ("sopr", "sopr"),
         "reserveRisk": ("reserve-risk", "reserveRisk"),
         "sthMvrv": ("sth-mvrv", "sthMvrv"),
         "lthMvrv": ("lth-mvrv", "lthMvrv")}
for chiave, (endpoint, campo) in mappa.items():
    try:
        d = get(f"https://bitcoin-data.com/v1/{endpoint}/last")
        dati[chiave] = float(d[campo])
    except Exception as e:
        errori.append(f"{chiave}: {e}")

# --- gap STH-MVRV / LTH-MVRV: dato reale, differenza assoluta ---
if "sthMvrv" in dati and "lthMvrv" in dati:
    dati["sthLthGap"] = round(abs(dati["lthMvrv"] - dati["sthMvrv"]), 4)

# --- SOPR <= 1 sostenuto da 3+ settimane (medie settimanali, non il dato grezzo) ---
try:
    start = (datetime.now(timezone.utc) - timedelta(days=23)).strftime("%Y-%m-%d")
    storico_sopr = get(f"https://bitcoin-data.com/v1/sopr?start={start}")
    vals_sopr = [row["sopr"] for row in storico_sopr][-21:]
    settimane = [vals_sopr[i:i + 7] for i in range(0, len(vals_sopr), 7)]
    medie = [sum(w) / len(w) for w in settimane if w]
    dati["soprSustained"] = bool(len(medie) >= 3 and all(m <= 1.0 for m in medie[-3:]))
except Exception as e:
    errori.append(f"soprSustained: {e}")

# --- zVWAP: ancorato al massimo di ciclo, anchor auto-rilevato (no valori a mano) ---
try:
    ath = get("https://bitcoin-data.com/v1/ath-stats/last")
    ath_date = ath["athDate"]  # "YYYY-MM-DD"
    prezzo_attuale = float(ath["priceUsd"])

    mc = get("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
              "?vs_currency=usd&days=365&interval=daily")
    righe = [(p, v) for (ts, p), (_, v) in zip(mc["prices"], mc["total_volumes"])
             if datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d") >= ath_date]
    if len(righe) < 5:  # fallback se l'anchor supera la finestra gratuita di 365gg CoinGecko
        righe = list(zip((p for _, p in mc["prices"]), (v for _, v in mc["total_volumes"])))

    vwap = sum(p * v for p, v in righe) / sum(v for _, v in righe)
    stdev = statistics.pstdev([p for p, _ in righe])
    dati["zvwap"] = round((prezzo_attuale - vwap) / stdev, 4) if stdev else 0.0
except Exception as e:
    errori.append(f"zvwap: {e}")

# --- hash ribbons (Blockchain.com, SMA 30/60 giorni) ---
try:
    d = get("https://api.blockchain.info/charts/hash-rate?timespan=90days&format=json&sampled=false")
    vals = [pt["y"] for pt in d["values"]]  # già in TH/s
    if len(vals) >= 60:
        sma30 = sum(vals[-30:]) / 30
        sma60 = sum(vals[-60:]) / 60
        dati["hashRibbonCapitulation"] = bool(sma30 < sma60)
        dati["hashRibbonCrossover"] = bool(sma30 > sma60)
    else:
        raise ValueError(f"solo {len(vals)} punti hash rate")

    # --- costo di produzione minerario: stesso hashrate, nessuna chiamata API in più ---
    EFFICIENZA_JTH = 16.0   # J/TH medio flotta di rete — stima metà 2026, facoltativo rivedere ogni 6-12 mesi
    PREZZO_KWH = 0.055      # $/kWh medio ponderato mining industriale globale
    BLOCK_REWARD = 3.125    # BTC/blocco dal halving 20/04/2024 (prossimo halving: 2028)
    hashrate_ths = vals[-1]
    potenza_watt = hashrate_ths * EFFICIENZA_JTH
    costo_giorno = (potenza_watt / 1000) * 24 * PREZZO_KWH
    dati["minerCost"] = round(costo_giorno / (BLOCK_REWARD * 144))
except Exception as e:
    errori.append(f"hashRibbons/minerCost: {e}")

# --- salvataggio: non sovrascrivere se troppi errori ---
if errori:
    print("AVVISI:", "; ".join(errori))
if len(errori) >= 3:
    print("Troppe fonti in errore: data.json NON aggiornato per non degradare i dati.")
    sys.exit(1)

with open("data.json", "w") as f:
    json.dump(dati, f, indent=2)
print("data.json aggiornato:", json.dumps(dati, indent=2))
