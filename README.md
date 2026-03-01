# Funding Rate Arbitrage Bot (Bybit + KuCoin USDT Perps)

Python 3.11+ asyncio bot for market-neutral funding spread capture across **Bybit linear USDT perpetuals** and **KuCoin Futures USDT perpetuals**.

## Features

- Direct exchange APIs only (no aggregators).
- Top-N dynamic symbol discovery + static fallback universe.
- Delta-neutral spread logic:
  - Long lower/negative funding exchange.
  - Short higher/positive funding exchange.
- Default `ENTRY_MODE=maker_hybrid` with sequential dual-leg safety.
- Isolated margin checks + liquidation buffer checks.
- Circuit breaker with hard kill switch.
- SQLite persistence for funding, trades, PnL, liq buffers.
- Rich terminal dashboard.
- CLI:
  - `python -m bot doctor`
  - `python -m bot run --live`
  - `python -m bot run --paper`
  - `python -m bot positions`
  - `python -m bot close-all`

## Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

1. Copy env file and fill credentials:

```bash
cp .env.example .env
```

2. Optional: copy `config.example.json` and customize strategy/risk parameters.

## Run

Doctor checks:

```bash
python -m bot doctor --config config.example.json
```

Paper run:

```bash
python -m bot run --paper --config config.example.json
```

Live tiny-size run:

```bash
python -m bot run --live --config config.example.json
```

## Safety defaults

- Live mode is tiny notional by default (`live_tiny_notional_usd=100`).
- Leverage defaults to `2x`, enforced range `[2,10]`.
- Circuit breaker closes order flow and cancels open orders.
- Hard kill switch can be set in config/env.

## Notes on exchange specifics

Exchange endpoints sometimes differ by account type and region. Adapter TODOs are intentionally left where account-specific behavior may vary (e.g., margin/leverage mode toggles). Core flow remains runnable and structured.

## Disclaimer

This software is for educational purposes; live trading carries substantial financial risk.
