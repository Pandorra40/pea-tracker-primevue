"""
Backend FastAPI - PEA Tracker
Remplace la logique Streamlit/yfinance
Lancer avec : uvicorn backend_main:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
from functools import lru_cache
import time

app = FastAPI(title="PEA Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En prod : remplacer par l'URL de votre frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

# Portefeuille de référence
PORTEFEUILLE = {
    'AI.PA':  {'nom': 'Air Liquide',      'qte': 2, 'pru': 161.64, 'div': 3.20, 'secteur': 'Industrie'},
    'GTT.PA': {'nom': 'GTT',              'qte': 2, 'pru': 175.50, 'div': 7.30, 'secteur': 'Énergie'},
    'PUB.PA': {'nom': 'Publicis',         'qte': 4, 'pru':  86.60, 'div': 3.40, 'secteur': 'Communication'},
    'SU.PA':  {'nom': 'Schneider',        'qte': 1, 'pru': 234.28, 'div': 3.80, 'secteur': 'Industrie'},
    'SOP.PA': {'nom': 'Sopra Steria',     'qte': 2, 'pru': 155.12, 'div': 4.65, 'secteur': 'Tech'},
    'DIM.PA': {'nom': 'Sartorius Stedim', 'qte': 1, 'pru': 175.00, 'div': 0.69, 'secteur': 'Santé'},
}

_cache = {"data": None, "ts": 0}
CACHE_TTL = 3600  # 1 heure

def fetch_data():
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < CACHE_TTL:
        return _cache["data"]

    tickers = list(PORTEFEUILLE.keys())
    df = yf.download(tickers + ['^FCHI'], period="1y")['Close']
    last_prices = df[tickers].iloc[-1].to_dict()

    fund_data = {}
    for t in tickers:
        try:
            inf = yf.Ticker(t).info
            fund_data[t] = {
                'target': inf.get('targetMeanPrice', 0) or 0,
                'payout': (inf.get('payoutRatio', 0) or 0) * 100,
            }
        except Exception:
            fund_data[t] = {'target': 0, 'payout': 0}

    # Série temporelle normalisée base 100
    total_achat = sum(v['qte'] * v['pru'] for v in PORTEFEUILLE.values())
    weights = {t: (PORTEFEUILLE[t]['qte'] * PORTEFEUILLE[t]['pru']) / total_achat for t in tickers}

    pct = df[tickers].pct_change().dropna()
    port_idx = (pct @ pd.Series(weights)).add(1).cumprod().mul(100)
    cac_idx  = df['^FCHI'].pct_change().dropna().add(1).cumprod().mul(100)

    dates = port_idx.index.strftime('%Y-%m-%d').tolist()
    chart = [
        {"date": d, "portefeuille": round(float(p), 2), "cac40": round(float(c), 2)}
        for d, p, c in zip(dates, port_idx.values, cac_idx.reindex(port_idx.index).values)
    ]

    _cache["data"] = {
        "last_prices": last_prices,
        "fund_data": fund_data,
        "chart": chart,
    }
    _cache["ts"] = now
    return _cache["data"]


@app.get("/api/portfolio")
def get_portfolio():
    raw = fetch_data()
    last_prices = raw["last_prices"]
    fund_data   = raw["fund_data"]

    total_achat  = sum(v['qte'] * v['pru'] for v in PORTEFEUILLE.values())
    total_actuel = sum(PORTEFEUILLE[t]['qte'] * last_prices[t] for t in PORTEFEUILLE)
    total_div    = sum(v['qte'] * v['div'] for v in PORTEFEUILLE.values())

    total_target = sum(
        fund_data[t]['target'] * PORTEFEUILLE[t]['qte']
        for t in PORTEFEUILLE if fund_data[t]['target'] > 0
    )
    val_pour_upside = sum(
        last_prices[t] * PORTEFEUILLE[t]['qte']
        for t in PORTEFEUILLE if fund_data[t]['target'] > 0
    )
    upside = ((total_target / val_pour_upside) - 1) * 100 if val_pour_upside else 0

    positions = []
    for t, v in PORTEFEUILLE.items():
        cours = last_prices[t]
        target = fund_data[t]['target']
        div5 = v['div'] * 5
        positions.append({
            "ticker":    t,
            "nom":       v['nom'],
            "secteur":   v['secteur'],
            "qte":       v['qte'],
            "cours":     round(float(cours), 2),
            "pru":       v['pru'],
            "pmv":       round((cours - v['pru']) * v['qte'], 2),
            "target":    round(float(target), 2) if target else None,
            "potentiel": round(((target / cours) - 1) * 100, 1) if target else None,
            "div5":      round(div5 * v['qte'], 2),
            "pru_net":   round(v['pru'] - div5, 2),
            "yoc":       round((v['div'] / v['pru']) * 100, 2),
        })

    return {
        "resume": {
            "total_achat":    round(total_achat, 2),
            "total_actuel":   round(total_actuel, 2),
            "diff_globale":   round(total_actuel - total_achat, 2),
            "perf_pct":       round(((total_actuel / total_achat) - 1) * 100, 2),
            "div_5ans":       round(total_div * 5, 2),
            "upside_target":  round(upside, 1),
        },
        "positions": positions,
        "chart": raw["chart"],
    }


@app.post("/api/refresh")
def refresh():
    _cache["ts"] = 0
    return {"status": "cache cleared"}
