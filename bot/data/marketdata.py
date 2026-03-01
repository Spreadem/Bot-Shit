"""Market data polling/discovery utilities."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from bot.exchanges.base import PerpExchange
from bot.models import FundingSnapshot


def normalize_symbol(sym: str) -> str:
    return sym.replace("USDT", "").replace("M", "")


async def discover_common_symbols(
    bybit: PerpExchange,
    kucoin: PerpExchange,
    top_n: int,
    fallback: Iterable[str],
) -> list[str]:
    b, k = await asyncio.gather(bybit.get_top_usdt_perps(top_n * 2), kucoin.get_top_usdt_perps(top_n * 2))
    b_map = {normalize_symbol(s.symbol): s.symbol for s in b}
    k_map = {normalize_symbol(s.symbol): s.symbol for s in k}
    inter = [coin for coin in b_map if coin in k_map]
    if not inter:
        inter = [coin for coin in fallback if coin in b_map and coin in k_map]
    return inter[:top_n]


async def get_snapshots_for_symbol(bybit: PerpExchange, kucoin: PerpExchange, coin: str) -> tuple[FundingSnapshot, FundingSnapshot]:
    bybit_symbol = f"{coin}USDT"
    kucoin_symbol = f"{coin}USDTM"
    return await asyncio.gather(
        bybit.get_funding_snapshot(bybit_symbol),
        kucoin.get_funding_snapshot(kucoin_symbol),
    )
