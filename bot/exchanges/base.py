"""Common exchange interface."""

from __future__ import annotations

import abc
from typing import Sequence

from bot.models import FundingSnapshot, HealthStatus, OrderRequest, OrderResult, Position, SymbolInfo


class PerpExchange(abc.ABC):
    name: str

    @abc.abstractmethod
    async def ping(self) -> HealthStatus:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_top_usdt_perps(self, top_n: int) -> list[SymbolInfo]:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_funding_snapshot(self, symbol: str) -> FundingSnapshot:
        raise NotImplementedError

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]:
        raise NotImplementedError

    @abc.abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResult:
        raise NotImplementedError

    @abc.abstractmethod
    async def cancel_all_orders(self, symbols: Sequence[str] | None = None) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def set_leverage_isolated(self, symbol: str, leverage: int) -> None:
        raise NotImplementedError
