"""Execution coordinator for dual-leg entries/exits."""

from __future__ import annotations

import asyncio

from bot.config import BotConfig
from bot.exchanges.base import PerpExchange
from bot.models import ExchangeName, OrderRequest, OrderResult, Side, TradeIntent


class ExecutionEngine:
    def __init__(self, cfg: BotConfig, bybit: PerpExchange, kucoin: PerpExchange):
        self.cfg = cfg
        self.bybit = bybit
        self.kucoin = kucoin

    def _adapter(self, ex: ExchangeName) -> PerpExchange:
        return self.bybit if ex == ExchangeName.BYBIT else self.kucoin

    def _symbol_for(self, coin: str, ex: ExchangeName) -> str:
        return f"{coin}USDT" if ex == ExchangeName.BYBIT else f"{coin}USDTM"

    async def open_pair(self, intent: TradeIntent, qty_bybit: float, qty_kucoin: float, bid_ask: dict[str, tuple[float, float]]) -> tuple[OrderResult, OrderResult]:
        mode = self.cfg.strategy.entry_mode
        first_ex, second_ex = (intent.long_exchange, intent.short_exchange)
        long_side, short_side = Side.BUY, Side.SELL

        async def place_leg(ex: ExchangeName, side: Side, qty: float) -> OrderResult:
            symbol = self._symbol_for(intent.symbol, ex)
            bid, ask = bid_ask[symbol]
            order = self._build_order(symbol, side, qty, mode, bid, ask)
            return await self._adapter(ex).place_order(order)

        if self.cfg.strategy.sequential_entry:
            first_side = long_side if first_ex == intent.long_exchange else short_side
            first_qty = qty_bybit if first_ex == ExchangeName.BYBIT else qty_kucoin
            r1 = await place_leg(first_ex, first_side, first_qty)
            if not r1.success:
                return r1, OrderResult(False, None, 0.0, None, "first leg failed")
            try:
                second_side = long_side if second_ex == intent.long_exchange else short_side
                second_qty = qty_bybit if second_ex == ExchangeName.BYBIT else qty_kucoin
                r2 = await asyncio.wait_for(
                    place_leg(second_ex, second_side, second_qty),
                    timeout=self.cfg.strategy.max_leg_gap_ms / 1000,
                )
                if not r2.success:
                    await self.close_pair(intent, qty_bybit, qty_kucoin, bid_ask)
                return r1, r2
            except TimeoutError:
                await self.close_pair(intent, qty_bybit, qty_kucoin, bid_ask)
                return r1, OrderResult(False, None, 0.0, None, "second leg timeout")

        # Simultaneous mode
        r1, r2 = await asyncio.gather(
            place_leg(intent.long_exchange, long_side, qty_bybit if intent.long_exchange == ExchangeName.BYBIT else qty_kucoin),
            place_leg(intent.short_exchange, short_side, qty_bybit if intent.short_exchange == ExchangeName.BYBIT else qty_kucoin),
        )
        return r1, r2

    async def close_pair(self, intent: TradeIntent, qty_bybit: float, qty_kucoin: float, bid_ask: dict[str, tuple[float, float]]) -> None:
        close_long = TradeIntent(intent.symbol, intent.short_exchange, intent.long_exchange, intent.funding_diff_bps, 0)
        _ = close_long
        bybit_symbol = self._symbol_for(intent.symbol, ExchangeName.BYBIT)
        kucoin_symbol = self._symbol_for(intent.symbol, ExchangeName.KUCOIN)
        b_bid, b_ask = bid_ask[bybit_symbol]
        k_bid, k_ask = bid_ask[kucoin_symbol]
        await asyncio.gather(
            self.bybit.place_order(self._build_order(bybit_symbol, Side.SELL, qty_bybit, "ioc", b_bid, b_ask, reduce_only=True)),
            self.kucoin.place_order(self._build_order(kucoin_symbol, Side.BUY, qty_kucoin, "ioc", k_bid, k_ask, reduce_only=True)),
        )

    def _build_order(self, symbol: str, side: Side, qty: float, mode: str, bid: float, ask: float, reduce_only: bool = False) -> OrderRequest:
        if mode == "maker_hybrid":
            px = bid if side == Side.BUY else ask
            return OrderRequest(symbol=symbol, side=side, qty=qty, mode="limit", post_only=True, reduce_only=reduce_only, price=px)
        if mode == "ioc":
            px = ask if side == Side.BUY else bid
            return OrderRequest(symbol=symbol, side=side, qty=qty, mode="ioc", post_only=False, reduce_only=reduce_only, price=px)
        return OrderRequest(symbol=symbol, side=side, qty=qty, mode="market", reduce_only=reduce_only)
