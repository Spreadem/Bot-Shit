"""Data models shared across modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ExchangeName(str, Enum):
    BYBIT = "bybit"
    KUCOIN = "kucoin"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class SymbolInfo:
    symbol: str
    exchange: ExchangeName
    min_qty: float
    qty_step: float
    tick_size: float
    turnover_24h: float = 0.0


@dataclass(slots=True)
class FundingSnapshot:
    symbol: str
    exchange: ExchangeName
    funding_rate: float
    next_funding_time: datetime | None
    mark_price: float
    index_price: float
    bid: float
    ask: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class Position:
    symbol: str
    exchange: ExchangeName
    side: Side
    qty: float
    entry_price: float
    mark_price: float
    liquidation_price: float | None
    maintenance_margin: float | None
    isolated: bool = True

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.mark_price


@dataclass(slots=True)
class TradeIntent:
    symbol: str
    long_exchange: ExchangeName
    short_exchange: ExchangeName
    funding_diff_bps: float
    expected_edge_bps: float


@dataclass(slots=True)
class OrderRequest:
    symbol: str
    side: Side
    qty: float
    mode: str
    post_only: bool = False
    reduce_only: bool = False
    price: float | None = None


@dataclass(slots=True)
class OrderResult:
    success: bool
    order_id: str | None
    filled_qty: float
    avg_price: float | None
    error: str | None = None


@dataclass(slots=True)
class HealthStatus:
    exchange: ExchangeName
    api_ok: bool
    latency_ms: float
    last_error: str | None = None
