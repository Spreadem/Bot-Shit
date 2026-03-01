"""Rich console dashboard rendering."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from bot.models import Position, TradeIntent
from bot.strategy.risk import RiskState

console = Console()


def render_spreads(intents: list[TradeIntent]) -> None:
    t = Table(title="Top Funding Spreads")
    t.add_column("Symbol")
    t.add_column("Long")
    t.add_column("Short")
    t.add_column("Diff (bps)")
    t.add_column("Expected Edge")
    for i in intents:
        t.add_row(i.symbol, i.long_exchange.value, i.short_exchange.value, f"{i.funding_diff_bps:.2f}", f"{i.expected_edge_bps:.2f}")
    console.print(t)


def render_positions(positions: list[Position], liq_buffers: dict[str, float]) -> None:
    t = Table(title="Current Positions")
    t.add_column("Exchange")
    t.add_column("Symbol")
    t.add_column("Side")
    t.add_column("Qty")
    t.add_column("Entry")
    t.add_column("Mark")
    t.add_column("Liq")
    t.add_column("Liq Buffer %")
    for p in positions:
        key = f"{p.exchange.value}:{p.symbol}"
        t.add_row(
            p.exchange.value,
            p.symbol,
            p.side.value,
            f"{p.qty:.6f}",
            f"{p.entry_price:.4f}",
            f"{p.mark_price:.4f}",
            f"{(p.liquidation_price or 0):.4f}",
            f"{liq_buffers.get(key, 0.0):.2f}",
        )
    console.print(t)


def render_health(health_rows: list[tuple[str, bool, float, str | None]], risk: RiskState) -> None:
    t = Table(title="Health")
    t.add_column("Exchange")
    t.add_column("API")
    t.add_column("Latency ms")
    t.add_column("Last Error")
    for ex, ok, lat, err in health_rows:
        t.add_row(ex, "ok" if ok else "down", f"{lat:.1f}", err or "-")
    console.print(t)
    console.print(
        f"[bold]Risk[/bold]: daily_pnl={risk.daily_pnl_usd:.2f} drawdown={risk.drawdown_usd:.2f} "
        f"errors={risk.consecutive_errors} cb={risk.circuit_breaker} reason={risk.reason}"
    )
