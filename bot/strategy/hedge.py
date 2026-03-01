"""Drift monitoring and rebalance helpers."""

from __future__ import annotations

from bot.models import Position


def compute_notional_drift_pct(long_pos: Position, short_pos: Position) -> float:
    if long_pos.notional == 0 and short_pos.notional == 0:
        return 0.0
    avg = (long_pos.notional + short_pos.notional) / 2
    return abs(long_pos.notional - short_pos.notional) / avg * 100
