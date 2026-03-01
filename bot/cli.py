"""Typer CLI for funding arbitrage bot."""

from __future__ import annotations

import asyncio
from collections import defaultdict

import typer

from bot.config import BotConfig
from bot.dashboard import render_health, render_positions, render_spreads
from bot.data.marketdata import discover_common_symbols, get_snapshots_for_symbol
from bot.execution.executor import ExecutionEngine
from bot.exchanges.bybit import BybitExchange
from bot.exchanges.kucoin import KucoinExchange
from bot.storage.db import DB
from bot.strategy.funding_arb import FundingArbStrategy
from bot.strategy.hedge import compute_notional_drift_pct
from bot.strategy.risk import RiskEngine

app = typer.Typer(help="Market-neutral funding rate arbitrage bot")


def _build(cfg: BotConfig) -> tuple[BybitExchange, KucoinExchange, FundingArbStrategy, RiskEngine, DB, ExecutionEngine]:
    bybit = BybitExchange(cfg.bybit_api_key, cfg.bybit_api_secret)
    kucoin = KucoinExchange(cfg.kucoin_api_key, cfg.kucoin_api_secret, cfg.kucoin_api_passphrase)
    strat = FundingArbStrategy(cfg)
    risk = RiskEngine(cfg)
    db = DB(cfg.db_path)
    exe = ExecutionEngine(cfg, bybit, kucoin)
    return bybit, kucoin, strat, risk, db, exe


@app.command()
def doctor(config: str | None = typer.Option(None, help="Path to JSON config override")) -> None:
    """Validate keys/connectivity and show top symbols."""

    async def _run() -> None:
        cfg = BotConfig.from_file(config)
        bybit, kucoin, _, _, _, _ = _build(cfg)
        try:
            hb, hk = await asyncio.gather(bybit.ping(), kucoin.ping())
            print(f"Bybit API: {hb.api_ok} latency={hb.latency_ms:.1f}ms err={hb.last_error}")
            print(f"KuCoin API: {hk.api_ok} latency={hk.latency_ms:.1f}ms err={hk.last_error}")
            symbols = await discover_common_symbols(bybit, kucoin, cfg.strategy.top_n_coins, cfg.default_symbols)
            print("Top common symbols:", ", ".join(symbols))
        finally:
            await bybit.close()
            await kucoin.close()

    asyncio.run(_run())


async def _fetch_positions(bybit: BybitExchange, kucoin: KucoinExchange):
    p1, p2 = await asyncio.gather(bybit.get_positions(), kucoin.get_positions())
    return p1 + p2


@app.command()
def positions(config: str | None = typer.Option(None)) -> None:
    """Show open positions and liquidation buffers."""

    async def _run() -> None:
        cfg = BotConfig.from_file(config)
        bybit, kucoin, _, risk, _, _ = _build(cfg)
        try:
            pos = await _fetch_positions(bybit, kucoin)
            buffers = {f"{p.exchange.value}:{p.symbol}": risk.liquidation_buffer_pct(p) for p in pos}
            render_positions(pos, buffers)
        finally:
            await bybit.close()
            await kucoin.close()

    asyncio.run(_run())


@app.command("close-all")
def close_all(config: str | None = typer.Option(None)) -> None:
    """Emergency cancel all + flatten (TODO: reduce-only close logic per symbol)."""

    async def _run() -> None:
        cfg = BotConfig.from_file(config)
        bybit, kucoin, _, _, _, _ = _build(cfg)
        try:
            positions = await _fetch_positions(bybit, kucoin)
            symbols_bybit = [p.symbol for p in positions if p.exchange.value == "bybit"]
            symbols_kucoin = [p.symbol for p in positions if p.exchange.value == "kucoin"]
            await asyncio.gather(bybit.cancel_all_orders(symbols_bybit), kucoin.cancel_all_orders(symbols_kucoin))
            print("Cancelled open orders. Manual flatten recommended if adapter endpoint differs.")
        finally:
            await bybit.close()
            await kucoin.close()

    asyncio.run(_run())


@app.command()
def run(
    live: bool = typer.Option(False, "--live", help="Run live tiny-size mode."),
    paper: bool = typer.Option(False, "--paper", help="Paper simulate fills."),
    config: str | None = typer.Option(None),
) -> None:
    """Run strategy loop."""

    if live and paper:
        raise typer.BadParameter("Choose one of --live or --paper")

    async def _run() -> None:
        cfg = BotConfig.from_file(config)
        bybit, kucoin, strat, risk, db, exe = _build(cfg)
        if cfg.hard_kill_switch:
            print("Hard kill switch enabled. Exiting.")
            return
        try:
            symbols = await discover_common_symbols(bybit, kucoin, cfg.strategy.top_n_coins, cfg.default_symbols)
            active: set[str] = set()
            while True:
                hb, hk = await asyncio.gather(bybit.ping(), kucoin.ping())
                render_health(
                    [("bybit", hb.api_ok, hb.latency_ms, hb.last_error), ("kucoin", hk.api_ok, hk.latency_ms, hk.last_error)],
                    risk.state,
                )
                if not hb.api_ok or not hk.api_ok:
                    risk.on_error("api failure")
                    if risk.state.circuit_breaker:
                        break
                    await asyncio.sleep(cfg.poll_interval_sec)
                    continue

                intents = []
                bid_ask: dict[str, tuple[float, float]] = {}
                for coin in symbols:
                    b, k = await get_snapshots_for_symbol(bybit, kucoin, coin)
                    db.save_funding(b)
                    db.save_funding(k)
                    bid_ask[b.symbol] = (b.bid, b.ask)
                    bid_ask[k.symbol] = (k.bid, k.ask)
                    intent = strat.make_intent(b, k)
                    if intent:
                        intents.append(intent)
                intents = sorted(intents, key=lambda i: i.expected_edge_bps, reverse=True)[: cfg.risk.max_open_positions]
                render_spreads(intents)

                positions = await _fetch_positions(bybit, kucoin)
                ok, reason = risk.validate_positions(positions)
                if not ok:
                    risk.trip_circuit_breaker(reason)
                    break

                grouped = defaultdict(list)
                for p in positions:
                    key = p.symbol.replace("USDTM", "").replace("USDT", "")
                    grouped[key].append(p)
                for coin, plist in grouped.items():
                    if len(plist) == 2:
                        drift = compute_notional_drift_pct(plist[0], plist[1])
                        if drift > cfg.risk.max_notional_drift_pct:
                            risk.trip_circuit_breaker(f"notional drift {coin} {drift:.2f}%")
                            break

                if risk.state.circuit_breaker:
                    break

                for intent in intents:
                    if intent.symbol in active:
                        if strat.should_exit(intent.funding_diff_bps):
                            active.remove(intent.symbol)
                        continue
                    notional = min(
                        cfg.strategy.capital_usd * cfg.strategy.leverage * cfg.strategy.allocation_per_symbol,
                        cfg.risk.max_notional_per_symbol_usd,
                        cfg.live_tiny_notional_usd if live else cfg.risk.max_notional_per_symbol_usd,
                    )
                    bybit_px = sum(bid_ask[f"{intent.symbol}USDT"]) / 2
                    kucoin_px = sum(bid_ask[f"{intent.symbol}USDTM"]) / 2
                    qty_b = round(notional / bybit_px, 6)
                    qty_k = round(notional / kucoin_px, 0)
                    if paper:
                        print(f"[PAPER] Open {intent.symbol}: long {intent.long_exchange.value}, short {intent.short_exchange.value}")
                        active.add(intent.symbol)
                        continue
                    r1, r2 = await exe.open_pair(intent, qty_b, qty_k, bid_ask)
                    if r1.success and r2.success:
                        active.add(intent.symbol)
                        db.save_trade(intent.symbol, intent.long_exchange.value, "buy", qty_b if intent.long_exchange.value == "bybit" else qty_k, r1.avg_price or 0.0, "entry")
                        db.save_trade(intent.symbol, intent.short_exchange.value, "sell", qty_b if intent.short_exchange.value == "bybit" else qty_k, r2.avg_price or 0.0, "entry")
                    else:
                        risk.on_error(f"entry failed {intent.symbol} {r1.error} {r2.error}")

                await asyncio.sleep(cfg.poll_interval_sec)

            await asyncio.gather(bybit.cancel_all_orders(), kucoin.cancel_all_orders())
            print(f"Circuit breaker active: {risk.state.reason}")
        finally:
            db.close()
            await bybit.close()
            await kucoin.close()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
