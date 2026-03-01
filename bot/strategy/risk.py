"""Risk engine with circuit breaker and liquidation checks."""

from __future__ import annotations

from dataclasses import dataclass

from bot.config import BotConfig
from bot.models import Position


@dataclass
class RiskState:
    daily_pnl_usd: float = 0.0
    drawdown_usd: float = 0.0
    consecutive_errors: int = 0
    circuit_breaker: bool = False
    reason: str = ""


class RiskEngine:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg
        self.state = RiskState()

    def liquidation_buffer_pct(self, pos: Position) -> float:
        if not pos.liquidation_price or pos.liquidation_price <= 0:
            return 999.0
        if pos.side.value == "buy":
            return (pos.mark_price - pos.liquidation_price) / pos.mark_price * 100
        return (pos.liquidation_price - pos.mark_price) / pos.mark_price * 100

    def validate_positions(self, positions: list[Position]) -> tuple[bool, str]:
        if len(positions) > self.cfg.risk.max_open_positions * 2:
            return False, "max positions exceeded"
        total_notional = sum(p.notional for p in positions)
        if total_notional > self.cfg.risk.max_total_notional_usd:
            return False, "max total notional exceeded"
        for pos in positions:
            if pos.notional > self.cfg.risk.max_notional_per_symbol_usd:
                return False, f"max per-symbol notional exceeded {pos.symbol}"
            if self.liquidation_buffer_pct(pos) < self.cfg.risk.min_liq_buffer_pct:
                return False, f"liquidation buffer breach {pos.symbol}"
            if not pos.isolated:
                return False, f"non-isolated position detected {pos.symbol}"
        return True, "ok"

    def on_error(self, message: str) -> None:
        self.state.consecutive_errors += 1
        if self.state.consecutive_errors >= self.cfg.risk.max_consecutive_errors:
            self.trip_circuit_breaker(f"too many errors: {message}")

    def reset_errors(self) -> None:
        self.state.consecutive_errors = 0

    def apply_pnl(self, pnl_delta: float) -> None:
        self.state.daily_pnl_usd += pnl_delta
        self.state.drawdown_usd = min(self.state.drawdown_usd, self.state.daily_pnl_usd)
        if abs(self.state.drawdown_usd) >= self.cfg.risk.max_drawdown_usd:
            self.trip_circuit_breaker("max drawdown breached")
        if -self.state.daily_pnl_usd >= self.cfg.risk.max_daily_loss_usd:
            self.trip_circuit_breaker("max daily loss breached")

    def trip_circuit_breaker(self, reason: str) -> None:
        self.state.circuit_breaker = True
        self.state.reason = reason
