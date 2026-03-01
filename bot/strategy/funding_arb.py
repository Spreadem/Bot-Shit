"""Funding spread signal generation and entry/exit decisions."""

from __future__ import annotations

from bot.config import BotConfig
from bot.models import ExchangeName, FundingSnapshot, TradeIntent


class FundingArbStrategy:
    def __init__(self, cfg: BotConfig):
        self.cfg = cfg

    def make_intent(self, bybit: FundingSnapshot, kucoin: FundingSnapshot) -> TradeIntent | None:
        diff = bybit.funding_rate - kucoin.funding_rate
        spread_bps = abs(diff) * 10_000
        mid_b = (bybit.bid + bybit.ask) / 2
        mid_k = (kucoin.bid + kucoin.ask) / 2
        spread_cost_bps = ((bybit.ask - bybit.bid) / mid_b + (kucoin.ask - kucoin.bid) / mid_k) * 5_000
        expected_fees = self.cfg.strategy.taker_fee_bps + self.cfg.strategy.slippage_buffer_bps
        edge = spread_bps - spread_cost_bps - expected_fees
        if spread_bps < self.cfg.strategy.min_funding_diff_bps:
            return None
        if spread_cost_bps > self.cfg.strategy.max_entry_spread_bps:
            return None
        if edge <= 0:
            return None
        if diff > 0:
            return TradeIntent(bybit.symbol.replace("USDT", ""), ExchangeName.KUCOIN, ExchangeName.BYBIT, spread_bps, edge)
        return TradeIntent(bybit.symbol.replace("USDT", ""), ExchangeName.BYBIT, ExchangeName.KUCOIN, spread_bps, edge)

    def should_exit(self, funding_diff_bps: float) -> bool:
        return funding_diff_bps < self.cfg.strategy.exit_diff_bps
